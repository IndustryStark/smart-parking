# Smart Parking

Raspberry Pi parking assistant. An RFID chip per employee is read at the entrance, the system assigns a spot
in the parking zones closest to the employee's department, shows it on a display, opens the barrier, and
per-spot sensors keep a live map of the lot.

## Run

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python run.py --mock        # simulated hardware, works on any laptop
python run.py               # on the Pi: real GPIO (auto-detected)
```

| Page | URL |
|------|-----|
| Live map (and simulator in mock mode) | http://localhost:5000/ |
| Entrance display (open fullscreen on the Pi) | http://localhost:5000/entrance |
| Admin panel | http://localhost:5000/admin |

Admin password: set `PARKING_ADMIN_PASSWORD` before the first start. The demo default is `admin`.
First start with an empty database adds demo departments, zones, 8 spots and 5 employees with chips.

Kiosk on the Pi: `chromium-browser --kiosk http://localhost:5000/entrance`

## Deploy on the Raspberry Pi

Needs Raspberry Pi OS (Bookworm) with network access and SSH enabled (`sudo raspi-config` > Interface Options > SSH).
From your laptop, in this folder:

```bash
./deploy/upload.sh pi@raspberrypi.local --install --kiosk
```

That copies the project to `~/smartparking` on the Pi and runs `deploy/install.sh`, which:

1. installs the system packages (gpiozero, lgpio, spidev, RPi.GPIO shim) and creates a venv that sees them,
2. enables SPI and adds your user to the `gpio` and `spi` groups,
3. creates `/etc/smartparking.env` with a random admin password (printed once, change it there),
4. installs and starts the `smartparking` systemd service, which starts on every boot and restarts on failure,
5. with `--kiosk`: opens the entrance screen fullscreen in Chromium after login (enable desktop autologin with `raspi-config`).

Reboot once after the first install (SPI and group changes). Afterwards, open `http://<pi-address>:5000/admin`.

Update after code changes: run the same upload command again. The database in `data/` is never overwritten.

```bash
ssh pi@raspberrypi.local "journalctl -u smartparking -f"    # live logs
ssh pi@raspberrypi.local "sudo systemctl restart smartparking"
ssh pi@raspberrypi.local "sudo systemctl stop smartparking" # before running tools/hwtest.py
```

First start creates the demo lot (8 spots on the demo pins). Replace it in the admin panel, or reset with
`rm ~/smartparking/data/parking.db` and restart the service.

### Test the hardware first

Stop the service, then test each part on its own (`python tools/hwtest.py -h` for options):

```bash
cd ~/smartparking && source venv/bin/activate
python tools/hwtest.py rfid        # hold a chip at the reader
python tools/hwtest.py sensors     # cover each IR sensor, watch the state change
python tools/hwtest.py servo       # barrier opens and closes once
python tools/hwtest.py led         # blue, green, red, blinking red
python tools/hwtest.py buttons     # press button 1 and button 2
```

## LED and buttons

| LED | Meaning |
|-----|---------|
| Blue | Hold your chip to the reader (idle, spots available) |
| Green | Go: spot assigned, barrier open |
| Red | Lot full (idle) |
| Red, blinking | Chip refused |
| Blue, blinking | Help requested |

- **Button 1** (GPIO27): shows the assigned place again on the entrance screen. It refers to the last person who scanned a chip
  (within 5 minutes and while the spot is still theirs): the system cannot tell who presses.
- **Button 2** (GPIO17): calls for help. The request is logged in the admin panel, shown on the entrance screen and the LED blinks blue.
- In the simulator (`--mock`) the live map page has both buttons and shows the LED colour.

## Admin panel

- **Chips**: press "Scan new chip" and hold it at the reader (or type the UID), assign it to an employee,
  deactivate lost chips. "Use last unknown scan" takes the last rejected chip from the entrance.
- **Employees**: name, department, optional fixed spot.
- **Departments**: add departments and rank the zones from closest to farthest for each one.
- **Zones & spots**: define zones and spots, map position (x/y), sensor type and GPIO pins.
- **Log**: entries, parked/left, unknown chips, wrong-spot cars, expired reservations.

## How a spot is chosen

1. Chip UID -> employee -> department.
2. Fixed spot, if the employee has one and it is free.
3. Otherwise free spots sorted by the department's zone rank, then distance to the entrance.
4. Spot is `RESERVED` for 3 minutes (`PARKING_RESERVATION_S`), barrier opens.
5. Sensor sees the car -> `OCCUPIED`; car leaves -> `FREE`. A car in a spot nobody assigned is flagged as wrong-spot
   and the waiting reservation is released.

## Architecture

```
run.py
deploy/      upload.sh (laptop), install.sh + smartparking.service + kiosk.sh (Pi)
tools/       hwtest.py: test RFID, sensors, servo one by one
smartparking/
  drivers/   rfid.py, sensors.py, barrier.py   real GPIO drivers + mock twins (same interface)
  service.py chip scans + sensor events -> spot state machine, reservations, events
  allocator.py  pure spot-selection function
  db.py      SQLite schema + demo seed
  web/       Flask: pages, JSON API, live updates (SSE), admin CRUD
tests/       allocator, state machine, admin API (all run without hardware)
```

## Wiring (BCM numbering, 3.3 V logic only)

| Part | Pin |
|------|-----|
| MFRC522 RFID | SDA GPIO8 (CE0), SCK GPIO11, MOSI GPIO10, MISO GPIO9, RST GPIO25, **3.3 V**, GND. Enable SPI with `sudo raspi-config` |
| Servo barrier | Signal GPIO18; power from an **external 5 V supply**; its GND joined to the Pi GND |
| IR obstacle sensor per spot | OUT to the spot's GPIO (demo: 5, 6, 13, 19, 26, 20, 21, 16), VCC 3.3 V, GND |
| RGB LED (common cathode) | Red GPIO22, green GPIO23, blue GPIO24, each through a 330 ohm resistor; common leg to GND |
| Button 1 (show place again) | GPIO27 to GND (internal pull-up, no resistor needed) |
| Button 2 (help) | GPIO17 to GND (internal pull-up, no resistor needed) |
| Ultrasonic HC-SR04 (optional) | TRIG to `trigger_pin`; **ECHO is 5 V: use a 1k/2k voltage divider** to the GPIO pin |

Change a spot's pins in the admin panel; sensors are reconfigured immediately. The panel refuses pins 8, 9, 10, 11, 25
(RFID), 18 (servo), 22, 23, 24 (LED), 27 and 17 (buttons), pins outside 2-27, and a pin already used by another spot.

## Tests

```bash
python -m pytest
```

## Known limits

- The MFRC522 reads at about 3 cm: fine for a model lot, a real lot needs UHF RFID or plate recognition.
- The drivers in `drivers/*` are tested against stand-in gpiozero and mfrc522 modules (debounce, polling, UID format,
  servo sequence) but have not run on a real Pi. Use `tools/hwtest.py` on each part first, and check wiring with a multimeter.
- The web server is Flask's built-in threaded server: fine for a handful of displays on a local network, not for the internet.
- No login on the live map and entrance pages (they only show who parked where); only `/admin` needs the password.

## License

MIT, see [LICENSE](LICENSE). Built as a Raspberry Pi project for the course "Smart Building and Mobility".
