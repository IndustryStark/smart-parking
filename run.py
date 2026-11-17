#!/usr/bin/env python3
"""Start Smart Parking.

  python run.py            # real GPIO on a Raspberry Pi, mock hardware anywhere else
  python run.py --mock     # force mock hardware (simulator buttons appear in the web UI)
  python run.py --real     # force real GPIO
"""
import argparse

from smartparking import config
from smartparking.db import DB, seed_demo
from smartparking.drivers import build_hardware, want_mock
from smartparking.feedback import Feedback
from smartparking.service import ParkingService
from smartparking.web import create_app


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="use simulated hardware")
    ap.add_argument("--real", action="store_true", help="use real GPIO")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--db", default=config.DB_PATH)
    args = ap.parse_args()

    mock = want_mock(True if args.mock else False if args.real else None)
    db = DB(args.db)
    if seed_demo(db):
        print("Empty database: demo departments, zones, spots and employees were added.")

    # Hardware and service reference each other: build the service first, then wire callbacks.
    holder = {}
    hw = build_hardware(
        mock,
        on_tag=lambda uid: holder["service"].handle_tag(uid),
        on_change=lambda spot_id, occupied: holder["service"].handle_spot_change(spot_id, occupied),
        on_repeat=lambda: holder["service"].handle_repeat(),
        on_help=lambda: holder["service"].handle_help())
    feedback = Feedback(hw.led, go_s=config.BARRIER_OPEN_S, deny_s=config.LED_DENY_S)
    service = ParkingService(db, hw.barrier, reservation_timeout=config.RESERVATION_TIMEOUT_S,
                             entrance_message_s=config.ENTRANCE_MESSAGE_S, feedback=feedback)
    holder["service"] = service

    def reload_sensors():
        hw.sensors.configure(db.q("SELECT id, gpio_pin, trigger_pin, sensor_kind FROM spots"))

    app = create_app(service, hardware={"reader": hw.reader, "sensors": hw.sensors,
                                        "repeat_button": hw.repeat_button, "help_button": hw.help_button}, mock=mock, on_spots_changed=reload_sensors)

    reload_sensors()
    hw.reader.start()
    hw.repeat_button.start()
    hw.help_button.start()
    feedback.start()
    service._notify()          # light the LED for the current state
    service.start_background()
    print(f"Hardware: {'MOCK (simulator)' if mock else 'real GPIO'}")
    print(f"Live map:        http://localhost:{args.port}/")
    print(f"Entrance screen: http://localhost:{args.port}/entrance")
    print(f"Admin panel:     http://localhost:{args.port}/admin")
    try:
        app.run(host=args.host, port=args.port, threaded=True)
    finally:
        service.stop()
        for part in (hw.reader, hw.sensors, hw.repeat_button, hw.help_button):
            part.stop()
        hw.led.show("off")


if __name__ == "__main__":
    main()
