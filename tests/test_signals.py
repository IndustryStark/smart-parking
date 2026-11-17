import time

from smartparking.db import DB, seed_demo
from smartparking.drivers.indicators import MockLED
from smartparking.feedback import Feedback
from smartparking.service import ParkingService

PETER, ANNA = "A1B2C3D4", "11223344"


def wait_for(cond, timeout=2.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def led(svc):
    return svc.feedback.led


def entrance(svc):
    return svc.snapshot()["entrance"]


def test_led_is_blue_when_idle(fb_service):
    assert (led(fb_service).color, led(fb_service).blinking) == ("blue", False)


def test_led_turns_green_on_grant_then_back_to_blue(fb_service):
    assert fb_service.handle_tag(PETER)["ok"]
    assert led(fb_service).color == "green"
    assert wait_for(lambda: led(fb_service).color == "blue")


def test_led_is_red_when_lot_is_full_and_back_to_blue_when_a_spot_frees(fb_service, spot):
    fb_service.db.x("UPDATE spots SET state='OCCUPIED'")
    fb_service._notify()
    assert led(fb_service).color == "red" and not led(fb_service).blinking
    fb_service.handle_spot_change(spot("A1")["id"], False)      # one car leaves
    assert led(fb_service).color == "blue"


def test_refused_chip_blinks_red_then_returns_to_idle(fb_service):
    assert not fb_service.handle_tag("DEADBEEF")["ok"]
    assert (led(fb_service).color, led(fb_service).blinking) == ("red", True)
    assert wait_for(lambda: led(fb_service).color == "blue" and not led(fb_service).blinking)


def test_full_lot_denial_ends_on_solid_red(fb_service):
    fb_service.db.x("UPDATE spots SET state='OCCUPIED'")
    fb_service._notify()
    assert not fb_service.handle_tag(PETER)["ok"]
    assert wait_for(lambda: (led(fb_service).color, led(fb_service).blinking) == ("red", False))


def test_green_is_not_overwritten_by_other_events_while_barrier_is_open(fb_service):
    fb_service.handle_tag(PETER)
    fb_service._notify()                                          # unrelated lot change during the green window
    assert led(fb_service).color == "green"


def test_screens_are_pushed_an_update_when_the_led_times_out(fb_service):
    q = fb_service.subscribe()
    fb_service.handle_tag(PETER)
    while not q.empty():
        q.get_nowait()
    assert wait_for(lambda: not q.empty())                        # LED fell back to blue by itself
    assert fb_service.snapshot()["feedback"]["led"] == "blue"


# ---- button 1: show place again ---------------------------------------------------------------------
def test_button1_shows_the_place_again_without_green_led(fb_service):
    fb_service.handle_tag(PETER)
    assert wait_for(lambda: led(fb_service).color == "blue")
    fb_service.entrance = {"ok": None, "message": "x", "ts": 0}   # screen has moved on
    fb_service.handle_repeat()
    e = entrance(fb_service)
    assert e["ok"] is True and e["spot"] == "A1" and "spot A1" in e["message"]
    assert led(fb_service).color == "blue"                        # the barrier is not opening again


def test_button1_without_recent_assignment_says_so(fb_service):
    fb_service.handle_repeat()
    e = entrance(fb_service)
    assert e["ok"] is None and "no recent assignment" in e["message"].lower()


def test_button1_forgets_a_spot_that_was_released(fb_service, clock):
    fb_service.handle_tag(PETER)
    clock.advance(200)
    fb_service.expire_reservations()                              # reservation lapsed
    fb_service.handle_repeat()
    assert "no recent assignment" in entrance(fb_service)["message"].lower()


def test_button1_shows_the_latest_persons_spot(fb_service):
    fb_service.handle_tag(PETER)
    fb_service.handle_tag(ANNA)
    fb_service.handle_repeat()
    e = entrance(fb_service)
    assert e["employee"] == "Anna" and e["spot"] == "A2"


def test_button1_after_parking_shows_where_the_car_is(fb_service, spot):
    fb_service.handle_tag(PETER)
    fb_service.handle_spot_change(spot("A1")["id"], True)
    fb_service.handle_repeat()
    assert "parked in A1" in entrance(fb_service)["message"]


# ---- button 2: help ------------------------------------------------------------------------------------
def test_button2_requests_help(fb_service):
    fb_service.handle_help()
    kinds = [e["kind"] for e in fb_service.db.q("SELECT kind FROM events")]
    assert "HELP" in kinds and "BUTTON" in kinds
    e = entrance(fb_service)
    assert e["help"] is True and e["ok"] is None and "Help requested" in e["message"]
    assert (led(fb_service).color, led(fb_service).blinking) == ("blue", True)
    assert wait_for(lambda: (led(fb_service).color, led(fb_service).blinking) == ("blue", False))


# ---- robustness ----------------------------------------------------------------------------------------
def test_broken_led_does_not_break_parking(clock):
    class BrokenLED:
        color, blinking = "off", False

        def show(self, color, blink=False):
            raise RuntimeError("gpio error")

    db = DB(":memory:")
    seed_demo(db)
    svc = ParkingService(db, None, clock=clock, feedback=Feedback(BrokenLED()))
    assert svc.handle_tag(PETER)["ok"]
    svc.handle_help()
    svc.handle_repeat()


def test_service_works_without_any_feedback_hardware(service):
    assert service.handle_tag(PETER)["ok"]
    service.handle_repeat()
    service.handle_help()
    assert service.snapshot()["feedback"] == {"led": None, "blink": False}


def test_snapshot_exposes_led(fb_service):
    fb_service.handle_tag(PETER)
    assert fb_service.snapshot()["feedback"] == {"led": "green", "blink": False}
