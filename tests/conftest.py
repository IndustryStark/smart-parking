import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from smartparking.db import DB, seed_demo          # noqa: E402
from smartparking.drivers.barrier import MockBarrier        # noqa: E402
from smartparking.drivers.indicators import MockButton, MockLED  # noqa: E402
from smartparking.drivers.rfid import MockRFIDReader        # noqa: E402
from smartparking.feedback import Feedback                  # noqa: E402
from smartparking.drivers.sensors import MockSensorBank     # noqa: E402
from smartparking.service import ParkingService             # noqa: E402
from smartparking.web import create_app                     # noqa: E402


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def service(clock):
    db = DB(":memory:")
    seed_demo(db)
    return ParkingService(db, MockBarrier(open_s=0), clock=clock, reservation_timeout=180)


@pytest.fixture
def fb_service(clock):
    """Service with a mock LED. Short LED hold times so tests do not wait long."""
    db = DB(":memory:")
    seed_demo(db)
    fb = Feedback(MockLED(), go_s=0.08, deny_s=0.08)
    svc = ParkingService(db, MockBarrier(open_s=0), clock=clock, reservation_timeout=180, feedback=fb)
    fb.start()
    svc._notify()
    return svc


@pytest.fixture
def spot(service):
    """spot('A1') -> current row of that spot."""
    return lambda name: service.db.one("SELECT * FROM spots WHERE name=?", (name,))


@pytest.fixture
def client(fb_service):
    service = fb_service
    hw = {"reader": MockRFIDReader(service.handle_tag), "sensors": MockSensorBank(service.handle_spot_change),
          "repeat_button": MockButton(service.handle_repeat), "help_button": MockButton(service.handle_help)}
    app = create_app(service, hardware=hw, mock=True, admin_password="secret123", secret="test")
    return app.test_client()
