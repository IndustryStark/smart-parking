"""What the entrance LED shows.

  blue          = hold your chip to the reader (idle, spots available)
  green         = go (spot assigned, barrier open)
  red           = lot full (idle, no free spot)
  blinking red  = chip refused
  blinking blue = help requested
"""
import threading
import time


class Feedback:
    def __init__(self, led=None, go_s=5.0, deny_s=3.0):
        self.led = led
        self.go_s, self.deny_s = go_s, deny_s
        self.on_change = None                 # set by the service: pushes a screen update
        self._free = None                     # free spots, None until known
        self._until = 0.0                     # a temporary colour (green / blinking) holds until then
        self._timer = None
        self._lock = threading.RLock()

    def _show(self, color, blink=False, hold_s=0.0):
        with self._lock:
            if self._timer:
                self._timer.cancel()
            if self.led:
                self.led.show(color, blink)
            if hold_s > 0:
                self._until = time.monotonic() + hold_s
                self._timer = threading.Timer(hold_s, self._idle)
                self._timer.daemon = True
                self._timer.start()

    def _idle(self):
        with self._lock:
            if time.monotonic() < self._until or not self.led:
                return
            self.led.show("red" if self._free == 0 else "blue")
        if self.on_change:        # tell the screens the LED changed on its own (timer ran out)
            self.on_change()

    def start(self):
        self._idle()

    def set_free_count(self, n):
        """Called whenever the lot changes: an idle LED turns red when the lot is full, blue otherwise."""
        with self._lock:
            self._free = n
            self._idle()

    # ---- events from the service ----------------------------------------------------------------
    def granted(self, mode="reserved", led=True):
        """Green while the barrier is open. 'parked' (already inside) and repeats do not open it."""
        if led and mode != "parked":
            self._show("green", hold_s=self.go_s)

    def denied(self):
        self._show("red", blink=True, hold_s=self.deny_s)

    def help_requested(self):
        self._show("blue", blink=True, hold_s=self.deny_s)

    def status(self):
        return {"led": getattr(self.led, "color", None), "blink": bool(getattr(self.led, "blinking", False))}
