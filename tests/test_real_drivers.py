"""Exercise the real-hardware drivers against stand-in gpiozero / mfrc522 modules, so their logic
(debounce, polling, UID formatting, servo sequence) is tested without a Pi."""
import sys
import time
import types

import pytest


class FakeDigital:
    instances = {}

    def __init__(self, pin, pull_up=True):
        self.pin, self.is_active, self.closed = pin, False, False
        FakeDigital.instances[pin] = self

    def close(self):
        self.closed = True


class FakeDistance:
    instances = {}

    def __init__(self, echo, trigger, max_distance):
        self.echo, self.trigger, self.distance, self.closed = echo, trigger, 1.0, False
        FakeDistance.instances[echo] = self

    def close(self):
        self.closed = True


class FakeServo:
    last = None

    def __init__(self, pin, **kw):
        self.pin, self.kw, self.angle_history, self.detached = pin, kw, [], 0
        FakeServo.last = self

    @property
    def angle(self):
        return self.angle_history[-1] if self.angle_history else None

    @angle.setter
    def angle(self, value):
        self.angle_history.append(value)

    def detach(self):
        self.detached += 1

    def close(self):
        pass


class FakeLED:
    instances = {}

    def __init__(self, pin):
        self.pin, self.state = pin, "off"
        FakeLED.instances[pin] = self

    def on(self):
        self.state = "on"

    def off(self):
        self.state = "off"

    def blink(self, on_time=1, off_time=1):
        self.state = "blink"

    def close(self):
        self.state = "closed"


class FakeButton:
    last = None

    def __init__(self, pin, pull_up=True, bounce_time=None):
        self.pin, self.pull_up, self.bounce_time = pin, pull_up, bounce_time
        self.when_pressed = None
        FakeButton.last = self

    def close(self):
        pass


@pytest.fixture
def fake_gpiozero(monkeypatch):
    FakeDigital.instances, FakeDistance.instances, FakeLED.instances = {}, {}, {}
    mod = types.ModuleType("gpiozero")
    mod.DigitalInputDevice, mod.DistanceSensor, mod.AngularServo = FakeDigital, FakeDistance, FakeServo
    mod.LED, mod.Button = FakeLED, FakeButton
    monkeypatch.setitem(sys.modules, "gpiozero", mod)


def wait_for(cond, timeout=2.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_sensor_bank_debounces_ir_and_ultrasonic(fake_gpiozero):
    from smartparking.drivers.sensors import SensorBank
    events = []
    bank = SensorBank(lambda sid, occ: events.append((sid, occ)), poll_s=0.005, debounce_s=0.03, threshold_m=0.3)
    bank.configure([
        {"id": 1, "gpio_pin": 5, "trigger_pin": None, "sensor_kind": "ir"},
        {"id": 2, "gpio_pin": 24, "trigger_pin": 23, "sensor_kind": "ultrasonic"},
        {"id": 3, "gpio_pin": None, "trigger_pin": None, "sensor_kind": "ir"},   # no sensor wired: skipped
    ])
    try:
        FakeDigital.instances[5].is_active = True          # IR sees a car
        FakeDistance.instances[24].distance = 0.12         # ultrasonic: car at 12 cm
        assert wait_for(lambda: {(1, True), (2, True)} <= set(events))
        FakeDigital.instances[5].is_active = False
        FakeDistance.instances[24].distance = 1.2
        assert wait_for(lambda: {(1, False), (2, False)} <= set(events))
        assert [e for e in events if e[0] == 3] == []
    finally:
        bank.stop()


def test_sensor_bank_ignores_short_blips(fake_gpiozero):
    from smartparking.drivers.sensors import SensorBank
    events = []
    bank = SensorBank(lambda sid, occ: events.append((sid, occ)), poll_s=0.005, debounce_s=0.2)
    bank.configure([{"id": 1, "gpio_pin": 5, "trigger_pin": None, "sensor_kind": "ir"}])
    try:
        FakeDigital.instances[5].is_active = True
        time.sleep(0.04)                                    # far shorter than the debounce time
        FakeDigital.instances[5].is_active = False
        time.sleep(0.3)
        assert events == []
    finally:
        bank.stop()


def test_sensor_bank_reconfigure_closes_old_devices(fake_gpiozero):
    from smartparking.drivers.sensors import SensorBank
    bank = SensorBank(lambda *a: None, poll_s=0.01, debounce_s=0.02)
    bank.configure([{"id": 1, "gpio_pin": 5, "trigger_pin": None, "sensor_kind": "ir"}])
    old = FakeDigital.instances[5]
    bank.configure([{"id": 1, "gpio_pin": 6, "trigger_pin": None, "sensor_kind": "ir"}])
    try:
        assert old.closed and 6 in FakeDigital.instances
    finally:
        bank.stop()


def test_servo_barrier_opens_then_closes(fake_gpiozero, monkeypatch):
    from smartparking.drivers import barrier
    monkeypatch.setattr(barrier.time, "sleep", lambda s: None)
    b = barrier.ServoBarrier(pin=18, open_s=0, open_angle=90, closed_angle=0)
    b.open_for()
    assert FakeServo.last.angle_history == [90, 0]
    assert FakeServo.last.detached >= 3 and b.state == "closed"


def test_rfid_reader_formats_uid_and_blocks_immediate_repeats(monkeypatch):
    class FakeMFRC522:
        PICC_REQIDL, MI_OK = 0x26, 0

        def MFRC522_Request(self, mode):
            return (self.MI_OK, 16)

        def MFRC522_Anticoll(self):
            return (self.MI_OK, [0xA1, 0xB2, 0xC3, 0xD4, 0x00])   # 4 UID bytes + checksum

    mod = types.ModuleType("mfrc522")
    mod.MFRC522 = FakeMFRC522
    monkeypatch.setitem(sys.modules, "mfrc522", mod)
    from smartparking.drivers.rfid import RFIDReader
    seen = []
    r = RFIDReader(seen.append, poll_s=0.01, repeat_block_s=5)
    r.start()
    try:
        assert wait_for(lambda: seen)
        time.sleep(0.1)
        assert seen == ["A1B2C3D4"]                           # held chip is reported once, not every poll
    finally:
        r.stop()


def test_rfid_handler_error_does_not_kill_reader(monkeypatch):
    class FakeMFRC522:
        PICC_REQIDL, MI_OK = 0x26, 0
        n = 0

        def MFRC522_Request(self, mode):
            return (self.MI_OK, 16)

        def MFRC522_Anticoll(self):
            FakeMFRC522.n += 1
            return (self.MI_OK, [FakeMFRC522.n, 0, 0, 0, 0])

    mod = types.ModuleType("mfrc522")
    mod.MFRC522 = FakeMFRC522
    monkeypatch.setitem(sys.modules, "mfrc522", mod)
    from smartparking.drivers.rfid import RFIDReader
    calls = []

    def handler(uid):
        calls.append(uid)
        raise RuntimeError("boom")

    r = RFIDReader(handler, poll_s=0.01, repeat_block_s=0)
    r.start()
    try:
        assert wait_for(lambda: len(calls) >= 3)               # still polling after exceptions
    finally:
        r.stop()


# ---- status LED and push buttons ------------------------------------------------------------
def test_status_led_lights_one_colour_and_can_blink(fake_gpiozero):
    from smartparking.drivers.indicators import StatusLED
    led = StatusLED({"red": 22, "green": 23, "blue": 24})
    state = lambda: {c: FakeLED.instances[p].state for c, p in (("red", 22), ("green", 23), ("blue", 24))}
    led.show("green")
    assert state() == {"red": "off", "green": "on", "blue": "off"} and led.color == "green"
    led.show("red", blink=True)
    assert state() == {"red": "blink", "green": "off", "blue": "off"} and led.blinking
    led.show("blue")
    assert state() == {"red": "off", "green": "off", "blue": "on"} and not led.blinking
    led.show("off")
    assert set(state().values()) == {"off"}


def test_push_button_calls_handler_once_per_press(fake_gpiozero):
    from smartparking.drivers.indicators import PushButton
    presses = []
    b = PushButton(lambda: presses.append(1), pin=27)
    b.start()
    gz = FakeButton.last
    assert gz.pin == 27 and gz.pull_up is True and gz.bounce_time == 0.05
    gz.when_pressed()
    gz.when_pressed()
    assert presses == [1, 1]


def test_two_buttons_use_their_own_pins(fake_gpiozero):
    from smartparking.drivers.indicators import PushButton
    from smartparking import config
    pins = []
    for pin in (config.REPEAT_BUTTON_PIN, config.HELP_BUTTON_PIN):
        PushButton(lambda: None, pin).start()
        pins.append(FakeButton.last.pin)
    assert pins == [27, 17]


def test_button_handler_error_does_not_escape_the_gpio_callback(fake_gpiozero):
    from smartparking.drivers.indicators import PushButton

    def boom():
        raise RuntimeError("handler failed")

    b = PushButton(boom, pin=27)
    b.start()
    FakeButton.last.when_pressed()          # must not raise into gpiozero's thread
