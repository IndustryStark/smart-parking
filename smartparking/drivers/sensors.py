"""Per-spot occupancy sensors: IR obstacle modules (1 pin) or HC-SR04 ultrasonic (echo + trigger).

Raw readings are noisy, so every spot goes through a median filter (ultrasonic) and a Debouncer:
a new state only counts after it has been stable for `debounce_s`.
"""
import statistics
import threading
import time
from collections import deque


class Debouncer:
    """Report a state change only after `required` consecutive samples agree."""

    def __init__(self, required=10, initial=False):
        self.required = max(1, required)
        self.state = initial
        self._candidate = None
        self._count = 0

    def update(self, sample):
        """Feed one boolean sample. Returns the new state if it changed, else None."""
        sample = bool(sample)
        if sample == self.state:
            self._candidate, self._count = None, 0
            return None
        if sample == self._candidate:
            self._count += 1
        else:
            self._candidate, self._count = sample, 1
        if self._count >= self.required:
            self.state, self._candidate, self._count = sample, None, 0
            return sample
        return None


class SensorBank:
    """Real GPIO sensors. configure(spots) (re)builds devices from the spots table."""

    def __init__(self, on_change, poll_s=0.1, debounce_s=1.0, threshold_m=0.30, max_m=1.5):
        self.on_change = on_change
        self.poll_s, self.debounce_s = poll_s, debounce_s
        self.threshold_m, self.max_m = threshold_m, max_m
        self._entries = {}   # spot_id -> dict(device, kind, deb, window)
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None

    def configure(self, spots):
        from gpiozero import DigitalInputDevice, DistanceSensor  # Pi only
        with self._lock:
            for e in self._entries.values():
                e["device"].close()
            self._entries = {}
            for s in spots:
                if s.get("gpio_pin") is None:
                    continue
                if s.get("sensor_kind") == "ultrasonic" and s.get("trigger_pin") is not None:
                    dev = DistanceSensor(echo=s["gpio_pin"], trigger=s["trigger_pin"], max_distance=self.max_m)
                    kind = "ultrasonic"
                else:
                    dev = DigitalInputDevice(s["gpio_pin"], pull_up=True)  # IR modules pull LOW on obstacle
                    kind = "ir"
                self._entries[s["id"]] = dict(
                    device=dev, kind=kind, window=deque(maxlen=5),
                    deb=Debouncer(max(1, round(self.debounce_s / self.poll_s)), initial=False))
        if self._thread is None:
            self.start()

    def start(self):
        self._thread = threading.Thread(target=self._loop, name="spot-sensors", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        with self._lock:
            for e in self._entries.values():
                e["device"].close()
            self._entries = {}

    def _sample(self, e):
        if e["kind"] == "ir":
            return bool(e["device"].is_active)  # active = pin LOW = obstacle seen
        e["window"].append(e["device"].distance)  # metres
        return statistics.median(e["window"]) < self.threshold_m

    def _loop(self):
        while not self._stop.is_set():
            with self._lock:
                items = list(self._entries.items())
            for spot_id, e in items:
                try:
                    changed = e["deb"].update(self._sample(e))
                except Exception as exc:
                    print("sensor error on spot", spot_id, exc)
                    continue
                if changed is not None:
                    try:
                        self.on_change(spot_id, changed)
                    except Exception as exc:
                        print("sensor handler error:", exc)
            time.sleep(self.poll_s)


class MockSensorBank:
    def __init__(self, on_change):
        self.on_change = on_change

    def configure(self, spots):
        pass

    def start(self):
        pass

    def stop(self):
        pass

    def set(self, spot_id, occupied):
        """Simulate a car arriving at / leaving a spot."""
        return self.on_change(int(spot_id), bool(occupied))
