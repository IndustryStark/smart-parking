"""Hardware factory: real GPIO drivers on a Raspberry Pi, mock twins everywhere else."""
import os
from collections import namedtuple

from .. import config
from .barrier import MockBarrier, ServoBarrier
from .indicators import MockButton, MockLED, PushButton, StatusLED
from .rfid import MockRFIDReader, RFIDReader
from .sensors import MockSensorBank, SensorBank

Hardware = namedtuple("Hardware", "reader sensors barrier led repeat_button help_button")


def on_raspberry_pi():
    try:
        with open("/proc/device-tree/model") as f:
            return "Raspberry Pi" in f.read()
    except OSError:
        return False


def want_mock(flag=None):
    """Mock if asked (--mock or PARKING_MOCK=1), otherwise whenever we are not on a Pi."""
    if flag is not None:
        return flag
    if os.environ.get("PARKING_MOCK"):
        return os.environ["PARKING_MOCK"] not in ("0", "false", "no")
    return not on_raspberry_pi()


def build_hardware(mock, on_tag, on_change, on_repeat, on_help):
    """Returns a Hardware tuple. Callbacks: on_tag(uid), on_change(spot_id, occupied), on_repeat(), on_help()."""
    if mock:
        return Hardware(MockRFIDReader(on_tag), MockSensorBank(on_change), MockBarrier(config.BARRIER_OPEN_S),
                        MockLED(), MockButton(on_repeat), MockButton(on_help))
    return Hardware(
        RFIDReader(on_tag),
        SensorBank(on_change, config.SENSOR_POLL_S, config.SENSOR_DEBOUNCE_S,
                   config.ULTRASONIC_THRESHOLD_M, config.ULTRASONIC_MAX_M),
        ServoBarrier(config.SERVO_PIN, config.BARRIER_OPEN_S, config.SERVO_OPEN_ANGLE, config.SERVO_CLOSED_ANGLE),
        StatusLED(config.LED_PINS),
        PushButton(on_repeat, config.REPEAT_BUTTON_PIN, config.BUTTONS_ACTIVE_HIGH),
        PushButton(on_help, config.HELP_BUTTON_PIN, config.BUTTONS_ACTIVE_HIGH))
