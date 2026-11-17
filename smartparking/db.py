"""SQLite storage: schema, thin helpers, demo seed data."""
import math
import sqlite3
import threading

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS departments(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS zones(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
-- rank 1 = closest zone for that department
CREATE TABLE IF NOT EXISTS zone_pref(
  department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
  zone_id INTEGER NOT NULL REFERENCES zones(id) ON DELETE CASCADE,
  rank INTEGER NOT NULL,
  PRIMARY KEY(department_id, zone_id));
CREATE TABLE IF NOT EXISTS employees(
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  department_id INTEGER NOT NULL REFERENCES departments(id),
  fixed_spot_id INTEGER REFERENCES spots(id) ON DELETE SET NULL);
CREATE TABLE IF NOT EXISTS chips(
  uid TEXT PRIMARY KEY,
  employee_id INTEGER REFERENCES employees(id) ON DELETE SET NULL,
  active INTEGER NOT NULL DEFAULT 1,
  created REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS spots(
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  zone_id INTEGER NOT NULL REFERENCES zones(id) ON DELETE CASCADE,
  x REAL NOT NULL DEFAULT 0,
  y REAL NOT NULL DEFAULT 0,
  dist REAL NOT NULL DEFAULT 0,          -- distance to entrance, computed from x/y
  sensor_kind TEXT NOT NULL DEFAULT 'ir', -- 'ir' (1 pin) or 'ultrasonic' (echo + trigger)
  gpio_pin INTEGER,                       -- IR output pin, or ultrasonic ECHO pin (BCM numbering)
  trigger_pin INTEGER,
  state TEXT NOT NULL DEFAULT 'FREE',     -- FREE | RESERVED | OCCUPIED
  employee_id INTEGER REFERENCES employees(id) ON DELETE SET NULL,
  reserved_until REAL,
  misparked INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS sessions(
  id INTEGER PRIMARY KEY,
  employee_id INTEGER, spot_id INTEGER,
  t_in REAL NOT NULL, t_out REAL,
  misparked INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY,
  ts REAL NOT NULL, kind TEXT NOT NULL, message TEXT NOT NULL,
  employee_id INTEGER, spot_id INTEGER);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
"""


class DB:
    """One shared connection guarded by a re-entrant lock (sensor, RFID and web threads all use it)."""

    def __init__(self, path=":memory:"):
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        with self.lock:
            self.conn.executescript(SCHEMA)

    def q(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def x(self, sql, args=()):
        """Execute a write and commit. Returns lastrowid."""
        with self.lock:
            try:
                cur = self.conn.execute(sql, args)
                self.conn.commit()
                return cur.lastrowid
            except Exception:
                self.conn.rollback()
                raise

    def get_setting(self, key, default=None):
        row = self.one("SELECT value FROM settings WHERE key=?", (key,))
        return row["value"] if row else default

    def set_setting(self, key, value):
        self.x("INSERT INTO settings(key,value) VALUES(?,?) "
               "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))

    def entrance(self):
        return (float(self.get_setting("entrance_x", config.ENTRANCE_POS[0])),
                float(self.get_setting("entrance_y", config.ENTRANCE_POS[1])))


def distance_to_entrance(db, x, y):
    ex, ey = db.entrance()
    return round(math.hypot(float(x) - ex, float(y) - ey), 3)


def seed_demo(db):
    """Fill an empty database with a small demo lot so the app is usable on first start."""
    if db.one("SELECT 1 AS n FROM departments LIMIT 1"):
        return False
    dep = {n: db.x("INSERT INTO departments(name) VALUES(?)", (n,))
           for n in ("Engineering", "Production", "Sales")}
    zone = {n: db.x("INSERT INTO zones(name) VALUES(?)", (n,)) for n in ("A", "B", "C")}
    # Closest zone first, per department. Engineering sits next to zone A, Production next to B.
    prefs = {"Engineering": ("A", "C", "B"), "Production": ("B", "C", "A"), "Sales": ("C", "A", "B")}
    for d, order in prefs.items():
        for rank, z in enumerate(order, start=1):
            db.x("INSERT INTO zone_pref VALUES(?,?,?)", (dep[d], zone[z], rank))
    layout = [("A1", "A", 2, 0, 5), ("A2", "A", 3, 0, 6), ("A3", "A", 4, 0, 13),
              ("B1", "B", 2, 6, 19), ("B2", "B", 3, 6, 24), ("B3", "B", 4, 6, 20),
              ("C1", "C", 7, 2, 21), ("C2", "C", 7, 4, 16)]
    for name, z, x, y, pin in layout:
        db.x("INSERT INTO spots(name,zone_id,x,y,dist,sensor_kind,gpio_pin) VALUES(?,?,?,?,?,?,?)",
             (name, zone[z], x, y, distance_to_entrance(db, x, y), "ir", pin))
    people = [("Peter", "Engineering", "A1B2C3D4"), ("Anna", "Engineering", "11223344"),
              ("Marco", "Production", "55667788"), ("Lena", "Sales", "99AABBCC"),
              ("Jonas", "Sales", "DDEEFF00")]
    for name, d, uid in people:
        eid = db.x("INSERT INTO employees(name,department_id) VALUES(?,?)", (name, dep[d]))
        db.x("INSERT INTO chips(uid,employee_id,active,created) VALUES(?,?,1,0)", (uid, eid))
    db.x("INSERT INTO chips(uid,employee_id,active,created) VALUES('CAFEBABE',NULL,1,0)")  # spare chip
    return True
