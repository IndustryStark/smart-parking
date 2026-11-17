#!/usr/bin/env python3
"""Test one piece of hardware at a time, WITHOUT the web app. Run on the Pi (stop the service first:
sudo systemctl stop smartparking), from the project folder:

  python tools/hwtest.py rfid                      # hold a chip at the reader, UIDs are printed
  python tools/hwtest.py sensors                   # raw IR sensor states for the demo pins, Ctrl+C to stop
  python tools/hwtest.py sensors --pins 5,6,13     # your own pins (BCM)
  python tools/hwtest.py ultrasonic --echo 12 --trigger 7
  python tools/hwtest.py servo                     # open, wait, close the barrier once
  python tools/hwtest.py led                       # blue, green, red, blinking red
  python tools/hwtest.py buttons                   # press button 1 (show place again) and button 2 (help)
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEMO_PINS = "5,6,13,19,26,20,21,16"


def test_rfid(_):
    from smartparking.drivers.rfid import RFIDReader
    reader = RFIDReader(lambda uid: print("chip:", uid, flush=True))
    reader.start()
    print("Hold a chip at the reader. Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        reader.stop()


def test_sensors(args):
    from gpiozero import DigitalInputDevice
    pins = [int(p) for p in args.pins.split(",")]
    devs = {p: DigitalInputDevice(p, pull_up=True) for p in pins}
    last = {}
    print("Cover / uncover each sensor. 'car' = obstacle seen. Ctrl+C to stop.")
    try:
        while True:
            for p, d in devs.items():
                state = "car" if d.is_active else "empty"
                if last.get(p) != state:
                    last[p] = state
                    print(f"GPIO{p}: {state}", flush=True)
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass


def test_ultrasonic(args):
    from gpiozero import DistanceSensor
    sensor = DistanceSensor(echo=args.echo, trigger=args.trigger, max_distance=1.5)
    print("ECHO must go through a 1k/2k voltage divider. Ctrl+C to stop.")
    try:
        while True:
            print(f"{sensor.distance * 100:5.1f} cm", flush=True)
            time.sleep(0.3)
    except KeyboardInterrupt:
        pass


def test_servo(_):
    from smartparking import config
    from smartparking.drivers.barrier import ServoBarrier
    b = ServoBarrier(config.SERVO_PIN, config.BARRIER_OPEN_S, config.SERVO_OPEN_ANGLE, config.SERVO_CLOSED_ANGLE)
    print("Opening barrier...")
    b.open_for(2)
    print("Closed.")


def test_led(_):
    from smartparking import config
    from smartparking.drivers.indicators import StatusLED
    led = StatusLED(config.LED_PINS)
    for color, blink, label in (("blue", False, "hold your chip"), ("green", False, "go"),
                                ("red", False, "full"), ("red", True, "chip refused")):
        print(f"{color}{' (blinking)' if blink else ''}: {label}")
        led.show(color, blink)
        time.sleep(2)
    led.show("off")


def test_buttons(_):
    from smartparking import config
    from smartparking.drivers.indicators import PushButton
    b1 = PushButton(lambda: print("button 1 (show place again)", flush=True), config.REPEAT_BUTTON_PIN)
    b2 = PushButton(lambda: print("button 2 (help)", flush=True), config.HELP_BUTTON_PIN)
    b1.start()
    b2.start()
    print(f"Press button 1 (GPIO{config.REPEAT_BUTTON_PIN}) and button 2 (GPIO{config.HELP_BUTTON_PIN}). Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        b1.stop()
        b2.stop()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("rfid").set_defaults(fn=test_rfid)
    s = sub.add_parser("sensors")
    s.add_argument("--pins", default=DEMO_PINS)
    s.set_defaults(fn=test_sensors)
    u = sub.add_parser("ultrasonic")
    u.add_argument("--echo", type=int, required=True)
    u.add_argument("--trigger", type=int, required=True)
    u.set_defaults(fn=test_ultrasonic)
    sub.add_parser("servo").set_defaults(fn=test_servo)
    sub.add_parser("led").set_defaults(fn=test_led)
    sub.add_parser("buttons").set_defaults(fn=test_buttons)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
