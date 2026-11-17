"""Central settings. Everything hardware-related lives here so wiring changes are one-line edits."""
import os

DB_PATH = os.environ.get("PARKING_DB", "parking.db")

# Allocation
RESERVATION_TIMEOUT_S = int(os.environ.get("PARKING_RESERVATION_S", "180"))  # spot held for an arriving car
ENTRANCE_MESSAGE_S = 15  # how long the entrance screen shows an assignment

# Barrier (servo, signal on a PWM-capable pin; power from an EXTERNAL 5 V supply, common ground!)
SERVO_PIN = 18
SERVO_OPEN_ANGLE = 90
SERVO_CLOSED_ANGLE = 0
BARRIER_OPEN_S = 5

# Spot sensors
SENSOR_POLL_S = 0.1
SENSOR_DEBOUNCE_S = 1.0          # a reading must be stable this long before it counts
ULTRASONIC_THRESHOLD_M = 0.30    # closer than this = car present
ULTRASONIC_MAX_M = 1.5

# RGB status LED at the entrance: blue = hold your chip, green = go, red = lot full / chip refused.
# Each colour channel through its own ~330 ohm resistor (common-cathode LED: common leg to GND).
LED_PINS = {"red": 22, "green": 23, "blue": 24}
LED_DENY_S = 3.0                 # how long a refusal / help request blinks

# Two push buttons to GND (internal pull-up, no resistor needed)
REPEAT_BUTTON_PIN = 27           # button 1: show the assigned place again
HELP_BUTTON_PIN = 17             # button 2: call for help

# Where the entrance sits on the lot map (same grid units as spot x/y)
ENTRANCE_POS = (0.0, 3.0)

# Admin login. Set PARKING_ADMIN_PASSWORD in production; the default is for demos only.
ADMIN_PASSWORD = os.environ.get("PARKING_ADMIN_PASSWORD")
DEFAULT_ADMIN_PASSWORD = "admin"
