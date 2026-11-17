"""Entrance barrier (servo) and a mock twin."""
import threading
import time


class ServoBarrier:
    """Servo on a PWM pin. Power the servo from an external 5 V supply and join its GND to the Pi's GND."""

    def __init__(self, pin=18, open_s=5, open_angle=90, closed_angle=0):
        from gpiozero import AngularServo  # Pi only
        self.open_s, self.open_angle, self.closed_angle = open_s, open_angle, closed_angle
        self._servo = AngularServo(pin, initial_angle=closed_angle, min_angle=0, max_angle=180,
                                   min_pulse_width=0.0005, max_pulse_width=0.0025)
        self._lock = threading.Lock()
        self.state = "closed"
        time.sleep(0.5)
        self._servo.detach()  # stop holding torque / jitter

    def _move(self, angle):
        self._servo.angle = angle
        time.sleep(0.6)
        self._servo.detach()

    def open_for(self, seconds=None):
        with self._lock:
            self.state = "open"
            self._move(self.open_angle)
            time.sleep(self.open_s if seconds is None else seconds)
            self._move(self.closed_angle)
            self.state = "closed"

    def close(self):
        self._servo.close()


class MockBarrier:
    def __init__(self, open_s=5):
        self.open_s = open_s
        self.state = "closed"
        self.open_count = 0
        self._lock = threading.Lock()

    def open_for(self, seconds=None):
        with self._lock:
            self.state = "open"
            self.open_count += 1
            time.sleep(self.open_s if seconds is None else seconds)
            self.state = "closed"

    def close(self):
        pass
