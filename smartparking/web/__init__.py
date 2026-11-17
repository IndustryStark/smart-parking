"""Flask app: public live map + entrance screen, password-protected admin panel, JSON API."""
import json
import os
import queue
import re
import secrets
import sqlite3
import time
from functools import wraps

from flask import Flask, Response, jsonify, render_template, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from .. import config
from ..db import distance_to_entrance
from ..service import normalize_uid

UID_RE = re.compile(r"^[0-9A-F]{8,20}$")
TABLES = ("departments", "zones", "employees", "chips", "spots")

LISTS = {
    "departments": "SELECT id, name FROM departments ORDER BY name",
    "zones": "SELECT id, name FROM zones ORDER BY name",
    "employees": "SELECT id, name, department_id, fixed_spot_id FROM employees ORDER BY name",
    "chips": "SELECT uid, employee_id, active, created FROM chips ORDER BY created DESC, uid",
    "spots": "SELECT id, name, zone_id, x, y, dist, sensor_kind, gpio_pin, trigger_pin, state "
             "FROM spots ORDER BY name",
}
COLUMNS = {  # editable columns per table
    "departments": ["name"],
    "zones": ["name"],
    "employees": ["name", "department_id", "fixed_spot_id"],
    "chips": ["uid", "employee_id", "active"],
    "spots": ["name", "zone_id", "x", "y", "sensor_kind", "gpio_pin", "trigger_pin"],
}
PK = {"chips": "uid"}
REQUIRED = {"departments": ["name"], "zones": ["name"], "employees": ["name", "department_id"],
            "chips": ["uid"], "spots": ["name", "zone_id"]}
NULLABLE_INT = {"employee_id", "fixed_spot_id", "gpio_pin", "trigger_pin"}
INT = {"department_id", "zone_id"}
FLOAT = {"x", "y"}


def _clean(table, data, creating):
    """Validate and convert incoming JSON for one table. Raises ValueError with a user-facing message."""
    out = {}
    for col in COLUMNS[table]:
        if col not in data:
            if creating and col in REQUIRED[table]:
                raise ValueError(f"{col} is required")
            continue
        v = data[col]
        if col == "name":
            v = str(v or "").strip()
            if not v or len(v) > 60:
                raise ValueError("name must be 1-60 characters")
        elif col == "uid":
            v = normalize_uid(v)
            if not UID_RE.match(v):
                raise ValueError("chip UID must be 8-20 hex characters (for example A1B2C3D4)")
        elif col == "active":
            v = 1 if v in (True, 1, "1", "true") else 0
        elif col == "sensor_kind":
            if v not in ("ir", "ultrasonic"):
                raise ValueError("sensor_kind must be 'ir' or 'ultrasonic'")
        elif col in NULLABLE_INT:
            v = None if v in (None, "") else int(v)
            if col.endswith("_pin") and v is not None and not 2 <= v <= 27:
                raise ValueError("GPIO pin must be a BCM number between 2 and 27")
        elif col in INT:
            v = int(v)
        elif col in FLOAT:
            v = float(v)
        out[col] = v
    return out


def create_app(service, hardware=None, mock=False, admin_password=None, secret=None, on_spots_changed=None):
    app = Flask(__name__)
    app.config["SECRET_KEY"] = secret or os.environ.get("PARKING_SECRET") or secrets.token_hex(16)
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    db = service.db

    password = admin_password or config.ADMIN_PASSWORD
    if password:
        db.set_setting("admin_hash", generate_password_hash(password))
    elif not db.get_setting("admin_hash"):
        db.set_setting("admin_hash", generate_password_hash(config.DEFAULT_ADMIN_PASSWORD))
        print("WARNING: admin password is the default 'admin'. Set PARKING_ADMIN_PASSWORD.")

    def admin_required(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if not session.get("admin"):
                return jsonify(error="login required"), 401
            if request.method in ("POST", "PUT") and not request.is_json:
                return jsonify(error="JSON body required"), 415   # blocks cross-site form posts
            return fn(*a, **kw)
        return wrapper

    # ---- pages ----------------------------------------------------------------------------------
    @app.get("/")
    def index():
        return render_template("index.html", mock=mock)

    @app.get("/entrance")
    def entrance():
        return render_template("entrance.html", mock=mock)

    @app.get("/admin")
    def admin():
        return render_template("admin.html")

    # ---- public API -----------------------------------------------------------------------------
    @app.get("/api/state")
    def state():
        return jsonify(service.snapshot())

    @app.get("/api/stream")
    def stream():
        def gen():
            q = service.subscribe()
            try:
                yield f"data: {json.dumps(service.snapshot())}\n\n"
                while True:
                    try:
                        q.get(timeout=10)
                        while not q.empty():      # coalesce bursts into one update
                            q.get_nowait()
                        yield f"data: {json.dumps(service.snapshot())}\n\n"
                    except queue.Empty:
                        yield f"data: {json.dumps(service.snapshot())}\n\n"  # heartbeat doubles as refresh
            finally:
                service.unsubscribe(q)
        return Response(gen(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ---- simulator (mock hardware only) ---------------------------------------------------------
    if mock and hardware:
        @app.get("/api/sim/chips")
        def sim_chips():
            return jsonify(db.q("SELECT c.uid, c.active, e.name AS employee FROM chips c "
                                "LEFT JOIN employees e ON e.id=c.employee_id ORDER BY e.name, c.uid"))

        @app.post("/api/sim/scan")
        def sim_scan():
            return jsonify(hardware["reader"].scan((request.get_json(silent=True) or {}).get("uid", "")))

        @app.post("/api/sim/repeat")
        def sim_repeat():
            return jsonify(hardware["repeat_button"].press())

        @app.post("/api/sim/help")
        def sim_help():
            return jsonify(hardware["help_button"].press())

        @app.post("/api/sim/spot")
        def sim_spot():
            d = request.get_json(silent=True) or {}
            hardware["sensors"].set(d.get("spot_id"), d.get("occupied"))
            return jsonify(ok=True)

    # ---- admin: auth ----------------------------------------------------------------------------
    @app.get("/api/admin/me")
    def me():
        return jsonify(authenticated=bool(session.get("admin")))

    @app.post("/api/admin/login")
    def login():
        pw = (request.get_json(silent=True) or {}).get("password", "")
        if check_password_hash(db.get_setting("admin_hash"), pw):
            session["admin"] = True
            return jsonify(ok=True)
        time.sleep(0.5)  # slow down guessing
        return jsonify(error="wrong password"), 401

    @app.post("/api/admin/logout")
    def logout():
        session.clear()
        return jsonify(ok=True)

    @app.post("/api/admin/password")
    @admin_required
    def change_password():
        d = request.get_json()
        if not check_password_hash(db.get_setting("admin_hash"), d.get("old", "")):
            return jsonify(error="current password is wrong"), 400
        if len(d.get("new", "")) < 8:
            return jsonify(error="new password needs at least 8 characters"), 400
        db.set_setting("admin_hash", generate_password_hash(d["new"]))
        return jsonify(ok=True)

    # ---- admin: generic CRUD --------------------------------------------------------------------
    # SPI + RFID reset, servo, status LED, the two push buttons
    RESERVED_PINS = {8, 9, 10, 11, 25, config.SERVO_PIN, config.REPEAT_BUTTON_PIN, config.HELP_BUTTON_PIN,
                    *config.LED_PINS.values()}

    def check_pins(vals, spot_id=None):
        """Reject pin choices that would crash sensor setup: reserved, duplicated or shared pins."""
        pins = [vals[k] for k in ("gpio_pin", "trigger_pin") if vals.get(k) is not None]
        if len(pins) == 2 and pins[0] == pins[1]:
            raise ValueError("echo and trigger pins must differ")
        used = set()
        for r in db.q("SELECT id, gpio_pin, trigger_pin FROM spots"):
            if r["id"] != spot_id:
                used |= {r["gpio_pin"], r["trigger_pin"]}
        for p in pins:
            if p in RESERVED_PINS:
                raise ValueError(f"GPIO{p} is used by the RFID reader, servo, LED or buttons")
            if p in used:
                raise ValueError(f"GPIO{p} is already used by another spot")

    def spots_changed():
        """Reconfigure sensors. Returns a warning text instead of failing a request that already saved."""
        warning = None
        if on_spots_changed:
            try:
                on_spots_changed()
            except Exception as exc:
                warning = f"Saved, but the sensors could not be reconfigured: {exc}"
        service._notify()
        return warning

    @app.get("/api/admin/<table>")
    @admin_required
    def list_rows(table):
        if table not in TABLES:
            return jsonify(error="unknown table"), 404
        rows = db.q(LISTS[table])
        if table == "departments":
            for r in rows:
                r["zone_order"] = [p["zone_id"] for p in db.q(
                    "SELECT zone_id FROM zone_pref WHERE department_id=? ORDER BY rank", (r["id"],))]
        return jsonify(rows)

    @app.post("/api/admin/<table>")
    @admin_required
    def create_row(table):
        if table not in TABLES:
            return jsonify(error="unknown table"), 404
        try:
            warning = None
            vals = _clean(table, request.get_json() or {}, creating=True)
            if table == "spots":
                check_pins(vals)
            if table == "chips":
                vals["created"] = time.time()
            cols = ", ".join(vals)
            rid = db.x(f"INSERT INTO {table}({cols}) VALUES({', '.join('?' * len(vals))})", tuple(vals.values()))
            if table == "spots":
                _refresh_dist(rid)
                warning = spots_changed()
            if table == "zones":   # a new zone is appended to every department's ranking
                for d in db.q("SELECT id FROM departments"):
                    _append_zone_rank(d["id"], rid)
            if table == "departments":
                for i, z in enumerate(db.q("SELECT id FROM zones ORDER BY id"), start=1):
                    db.x("INSERT INTO zone_pref VALUES(?,?,?)", (rid, z["id"], i))
            return jsonify(ok=True, id=vals.get("uid", rid), warning=warning), 201
        except (ValueError, TypeError) as exc:
            return jsonify(error=str(exc)), 400
        except sqlite3.IntegrityError as exc:
            return jsonify(error=_integrity_message(exc)), 409

    @app.put("/api/admin/<table>/<key>")
    @admin_required
    def update_row(table, key):
        if table not in TABLES:
            return jsonify(error="unknown table"), 404
        pk = PK.get(table, "id")
        key = normalize_uid(key) if table == "chips" else key
        try:
            warning = None
            vals = _clean(table, request.get_json() or {}, creating=False)
            vals.pop("uid", None)
            if table == "spots":
                check_pins(vals, int(key))
            if vals:
                sets = ", ".join(f"{c}=?" for c in vals)
                db.x(f"UPDATE {table} SET {sets} WHERE {pk}=?", (*vals.values(), key))
            if table == "spots":
                _refresh_dist(key)
                warning = spots_changed()
            return jsonify(ok=True, warning=warning)
        except (ValueError, TypeError) as exc:
            return jsonify(error=str(exc)), 400
        except sqlite3.IntegrityError as exc:
            return jsonify(error=_integrity_message(exc)), 409

    @app.delete("/api/admin/<table>/<key>")
    @admin_required
    def delete_row(table, key):
        if table not in TABLES:
            return jsonify(error="unknown table"), 404
        pk = PK.get(table, "id")
        key = normalize_uid(key) if table == "chips" else key
        try:
            db.x(f"DELETE FROM {table} WHERE {pk}=?", (key,))
        except sqlite3.IntegrityError as exc:
            return jsonify(error=_integrity_message(exc)), 409
        if table == "spots":
            spots_changed()
        service._notify()
        return jsonify(ok=True)

    def _refresh_dist(spot_id):
        s = db.one("SELECT x, y FROM spots WHERE id=?", (spot_id,))
        if s:
            db.x("UPDATE spots SET dist=? WHERE id=?", (distance_to_entrance(db, s["x"], s["y"]), spot_id))

    def _append_zone_rank(dept_id, zone_id):
        last = db.one("SELECT COALESCE(MAX(rank),0) AS m FROM zone_pref WHERE department_id=?", (dept_id,))["m"]
        db.x("INSERT OR IGNORE INTO zone_pref VALUES(?,?,?)", (dept_id, zone_id, last + 1))

    def _integrity_message(exc):
        text = str(exc)
        if "UNIQUE" in text:
            return "That name or chip UID already exists."
        return "This item is still used by other records. Remove or reassign those first."

    # ---- admin: zone ranking per department -----------------------------------------------------
    @app.put("/api/admin/departments/<int:dept_id>/zones")
    @admin_required
    def set_zone_order(dept_id):
        order = (request.get_json() or {}).get("zones")
        valid = {z["id"] for z in db.q("SELECT id FROM zones")}
        if not isinstance(order, list) or set(order) != valid or len(order) != len(valid):
            return jsonify(error="send every zone id exactly once, closest first"), 400
        with db.lock:
            db.conn.execute("DELETE FROM zone_pref WHERE department_id=?", (dept_id,))
            for rank, zid in enumerate(order, start=1):
                db.conn.execute("INSERT INTO zone_pref VALUES(?,?,?)", (dept_id, zid, rank))
            db.conn.commit()
        return jsonify(ok=True)

    # ---- admin: chip registration helper, logs --------------------------------------------------
    @app.post("/api/admin/learn")
    @admin_required
    def learn_start():
        service.start_learn(15)
        return jsonify(ok=True, seconds=15)

    @app.get("/api/admin/learn")
    @admin_required
    def learn_status():
        return jsonify(active=service.clock() < service.learn_until, uid=service.learned_uid,
                       last_unknown=service.last_unknown)

    @app.get("/api/admin/events")
    @admin_required
    def events():
        limit = min(int(request.args.get("limit", 100)), 500)
        return jsonify(db.q(
            "SELECT ev.id, ev.ts, ev.kind, ev.message, e.name AS employee, s.name AS spot "
            "FROM events ev LEFT JOIN employees e ON e.id=ev.employee_id "
            "LEFT JOIN spots s ON s.id=ev.spot_id ORDER BY ev.id DESC LIMIT ?", (limit,)))

    return app
