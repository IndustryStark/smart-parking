"""RFID reader at the entrance (MFRC522 over SPI) and a mock twin for development."""
import threading
import time


def format_uid(raw):
    """MFRC522_Anticoll returns 4 UID bytes + 1 checksum byte. Keep the 4 UID bytes as hex."""
    return "".join("%02X" % b for b in raw[:4])


class RFIDReader:
    """Polls the MFRC522 in a thread and calls on_tag(uid_hex). Same chip held in front of the
    reader is reported once per `repeat_block_s`."""

    def __init__(self, on_tag, poll_s=0.2, repeat_block_s=2.0):
        self.on_tag = on_tag
        self.poll_s = poll_s
        self.repeat_block_s = repeat_block_s
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        # Imported here so the app also runs on laptops without the Pi libraries installed.
        try:
            from mfrc522 import MFRC522  # pip install mfrc522
        except ImportError:
            import MFRC522 as _legacy    # class name used in the course guide
            MFRC522 = _legacy.MFRC522
        self._reader = MFRC522()
        self._thread = threading.Thread(target=self._loop, name="rfid", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _loop(self):
        r = self._reader
        last_uid, last_t = None, 0.0
        while not self._stop.is_set():
            status, _tag_type = r.MFRC522_Request(r.PICC_REQIDL)
            if status == r.MI_OK:
                status, raw = r.MFRC522_Anticoll()
                if status == r.MI_OK:
                    uid, now = format_uid(raw), time.monotonic()
                    if uid != last_uid or now - last_t > self.repeat_block_s:
                        last_uid, last_t = uid, now
                        try:
                            self.on_tag(uid)
                        except Exception as exc:  # never let a handler error kill the reader
                            print("RFID handler error:", exc)
            time.sleep(self.poll_s)


class MockRFIDReader:
    def __init__(self, on_tag):
        self.on_tag = on_tag

    def start(self):
        pass

    def stop(self):
        pass

    def scan(self, uid):
        """Simulate a chip held in front of the reader."""
        return self.on_tag(uid)
