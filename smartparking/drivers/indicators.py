"""Entrance signals: RGB status LED and push buttons, with mock twins."""
import threading


class StatusLED:
    """RGB LED on three GPIO pins (red, green, blue). show('green') lights one colour,
    show('red', blink=True) blinks it. Each colour channel needs its own ~330 ohm resistor."""

    def __init__(self, pins):
        from gpiozero import LED  # Pi only
        self._leds = {color: LED(pin) for color, pin in pins.items()}
        self._lock = threading.Lock()
        self.color, self.blinking = "off", False

    def show(self, color, blink=False):
        with self._lock:
            for c, led in self._leds.items():
                if c != color:
                    led.off()                      # off() also stops a running blink
            led = self._leds.get(color)
            if led:
                led.blink(on_time=0.25, off_time=0.25) if blink else led.on()
            self.color, self.blinking = color, bool(blink and led)

    def close(self):
        for led in self._leds.values():
            led.close()


class MockLED:
    def __init__(self):
        self.color, self.blinking = "off", False
        self.history = []

    def show(self, color, blink=False):
        self.color, self.blinking = color, bool(blink)
        self.history.append((color, bool(blink)))

    def close(self):
        pass


class PushButton:
    """Push button. active_high=True: the pin goes HIGH when pressed (module with its own VCC, internal pull-down).
    active_high=False: the pin goes LOW when pressed (button to GND, internal pull-up). Calls on_press() once per press."""

    def __init__(self, on_press, pin, active_high=False):
        self.on_press, self.pin, self.active_high = on_press, pin, active_high

    def start(self):
        from gpiozero import Button  # Pi only
        self._button = Button(self.pin, pull_up=not self.active_high, bounce_time=0.05)
        self._button.when_pressed = self._fire

    def stop(self):
        if getattr(self, "_button", None):
            self._button.close()

    def _fire(self):
        try:
            self.on_press()
        except Exception as exc:  # a handler error must not kill the GPIO callback thread
            print("button handler error:", exc)


class MockButton:
    def __init__(self, on_press):
        self.on_press = on_press

    def start(self):
        pass

    def stop(self):
        pass

    def press(self):
        """Simulate a press."""
        return self.on_press()
