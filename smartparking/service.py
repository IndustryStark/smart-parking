"""Core service: reacts to chip scans and spot-sensor changes, owns the spot state machine.

Spot states:  FREE -> RESERVED (chip scanned, spot assigned) -> OCCUPIED (sensor sees the car) -> FREE
A spot can additionally carry `misparked=1` (car is not where it was assigned / car is unregistered).
"""
import queue
import re
import threading
import time

from .allocator import choose_spot


def normalize_uid(uid):
    return re.sub(r"[^0-9A-Fa-f]", "", str(uid)).upper()


class ParkingService:
    def __init__(self, db, barrier=None, clock=time.time, reservation_timeout=180, entrance_message_s=15,
                 feedback=None):
        self.db = db
        self.barrier = barrier
        self.feedback = feedback     # status LED, optional
        if feedback:
            feedback.on_change = self._push
        self.last_announcement = None  # what "repeat" says again
        self.clock = clock
        self.reservation_timeout = reservation_timeout
        self.entrance_message_s = entrance_message_s
        self.lock = threading.RLock()
        self._listeners = []
        self._stop = threading.Event()
        self.entrance = {"ok": None, "message": "Please scan your chip.", "ts": 0}
        self.learn_until = 0.0       # admin "scan new chip" mode
        self.learned_uid = None
        self.last_unknown = None     # last unregistered chip seen at the entrance

    # ---- plumbing -------------------------------------------------------------------------------
    def subscribe(self):
        q = queue.Queue()
        with self.lock:
            self._listeners.append(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            if q in self._listeners:
                self._listeners.remove(q)

    def _push(self):
        for q in list(self._listeners):
            q.put_nowait(1)

    def _notify(self):
        self._push()
        if self.feedback:   # keep an idle LED in step with the lot: red when full, blue otherwise
            free = self.db.one("SELECT COUNT(*) AS n FROM spots WHERE state='FREE'")["n"]
            self._fb("set_free_count", free)

    def _fb(self, name, *args, **kw):
        """Call the LED layer; a broken LED must never break parking."""
        if self.feedback:
            try:
                getattr(self.feedback, name)(*args, **kw)
            except Exception as exc:
                print("feedback error:", exc)

    def _log(self, kind, message, employee_id=None, spot_id=None):
        self.db.x("INSERT INTO events(ts,kind,message,employee_id,spot_id) VALUES(?,?,?,?,?)",
                  (self.clock(), kind, message, employee_id, spot_id))

    def start_background(self):
        """Expire stale reservations once per second."""
        def loop():
            while not self._stop.wait(1.0):
                try:
                    self.expire_reservations()
                except Exception as exc:
                    print("expiry error:", exc)
        threading.Thread(target=loop, name="expiry", daemon=True).start()

    def stop(self):
        self._stop.set()

    def _open_barrier(self):
        if self.barrier:
            threading.Thread(target=self.barrier.open_for, daemon=True).start()

    # ---- entrance -------------------------------------------------------------------------------
    def _deny(self, message, kind, uid=None, employee_id=None):
        self._log(kind, message + (f" ({uid})" if uid else ""), employee_id)
        self.entrance = {"ok": False, "message": message, "ts": self.clock()}
        self._fb("denied")
        self._notify()
        return {"ok": False, "message": message}

    def _grant(self, emp, spot, message, mode="reserved", announce=True, led=True):
        self.entrance = {"ok": True, "message": message, "employee": emp["name"],
                         "department": emp["department"], "spot_id": spot["id"],
                         "spot": spot["name"], "zone": spot["zone"], "ts": self.clock()}
        self.last_announcement = {"emp_id": emp["id"], "spot_id": spot["id"], "ts": self.clock()}
        if announce:
            self._fb("granted", mode, led)
        self._notify()
        return {"ok": True, "message": message, "spot": spot["name"], "zone": spot["zone"],
                "spot_id": spot["id"]}

    def start_learn(self, seconds=15):
        """Admin pressed 'scan new chip': the next scan is captured instead of triggering an entry."""
        with self.lock:
            self.learned_uid = None
            self.learn_until = self.clock() + seconds

    def handle_tag(self, uid):
        uid = normalize_uid(uid)
        with self.lock:
            if self.clock() < self.learn_until:
                self.learned_uid, self.learn_until = uid, 0.0
                self._log("LEARN", f"Chip {uid} captured for registration")
                self._notify()
                return {"ok": True, "learn": True, "uid": uid}

            chip = self.db.one("SELECT * FROM chips WHERE uid=?", (uid,))
            if not chip:
                self.last_unknown = uid
                return self._deny("Unknown chip. Please contact the front desk.", "UNKNOWN_TAG", uid)
            if not chip["active"]:
                return self._deny("This chip is disabled.", "DISABLED_TAG", uid, chip["employee_id"])
            if chip["employee_id"] is None:
                return self._deny("This chip is not assigned to an employee.", "UNASSIGNED_TAG", uid)

            emp = self.db.one(
                "SELECT e.*, d.name AS department FROM employees e "
                "JOIN departments d ON d.id=e.department_id WHERE e.id=?", (chip["employee_id"],))

            held = self.db.one(
                "SELECT s.*, z.name AS zone FROM spots s JOIN zones z ON z.id=s.zone_id "
                "WHERE s.employee_id=? AND s.state IN ('RESERVED','OCCUPIED')", (emp["id"],))
            if held:
                if held["state"] == "RESERVED":
                    self.db.x("UPDATE spots SET reserved_until=? WHERE id=?",
                              (self.clock() + self.reservation_timeout, held["id"]))
                    self._open_barrier()
                    return self._grant(emp, held, f"{emp['name']}, your spot {held['name']} "
                                                  f"(zone {held['zone']}) is still reserved.", mode="still")
                return self._grant(emp, held, f"{emp['name']}, you are already parked in {held['name']}.",
                                   mode="parked")

            free = self.db.q("SELECT s.*, z.name AS zone FROM spots s JOIN zones z ON z.id=s.zone_id "
                             "WHERE s.state='FREE'")
            spot = None
            if emp["fixed_spot_id"]:
                spot = next((s for s in free if s["id"] == emp["fixed_spot_id"]), None)
            if spot is None:
                ranks = {r["zone_id"]: r["rank"] for r in self.db.q(
                    "SELECT zone_id, rank FROM zone_pref WHERE department_id=?", (emp["department_id"],))}
                spot = choose_spot(free, ranks)
            if spot is None:
                return self._deny("The lot is full. Please wait or use street parking.",
                                  "LOT_FULL", employee_id=emp["id"])

            self.db.x("UPDATE spots SET state='RESERVED', employee_id=?, reserved_until=?, misparked=0 "
                      "WHERE id=?", (emp["id"], self.clock() + self.reservation_timeout, spot["id"]))
            self._log("RESERVED", f"{emp['name']} ({emp['department']}) -> {spot['name']} zone {spot['zone']}",
                      emp["id"], spot["id"])
            self._open_barrier()
            return self._grant(emp, spot, f"Welcome {emp['name']}. Please park in spot "
                                          f"{spot['name']} (zone {spot['zone']}).")

    # ---- buttons -------------------------------------------------------------------------------
    def repeat_last(self):
        """Say and show the last assignment again (only while that spot is still this person's)."""
        with self.lock:
            la = self.last_announcement
            spot = None
            if la and self.clock() - la["ts"] < 300:
                spot = self.db.one(
                    "SELECT s.*, z.name AS zone FROM spots s JOIN zones z ON z.id=s.zone_id "
                    "WHERE s.id=? AND s.employee_id=? AND s.state IN ('RESERVED','OCCUPIED')",
                    (la["spot_id"], la["emp_id"]))
            if not spot:
                self.entrance = {"ok": None, "ts": self.clock(),
                                 "message": "No recent assignment. Please hold your chip to the reader."}
                self._notify()
                return {"ok": False}
            emp = self.db.one("SELECT e.*, d.name AS department FROM employees e "
                              "JOIN departments d ON d.id=e.department_id WHERE e.id=?", (la["emp_id"],))
            mode = "reserved" if spot["state"] == "RESERVED" else "parked"
            msg = (f"Welcome {emp['name']}. Please park in spot {spot['name']} (zone {spot['zone']})."
                   if mode == "reserved" else f"{emp['name']}, you are parked in {spot['name']}.")
            return self._grant(emp, spot, msg, mode=mode, led=False)   # no green LED: the barrier is not opening

    def help_request(self, source):
        with self.lock:
            self._log("HELP", f"Help requested ({source})")
            self.entrance = {"ok": None, "help": True, "ts": self.clock(),
                             "message": "Help requested. Someone will be with you shortly."}
            self._fb("help_requested")
            self._notify()
            return {"ok": True}

    def handle_repeat(self):
        """Button 1: show the place again."""
        self._log("BUTTON", "Button 1 pressed (show place again)")
        return self.repeat_last()

    def handle_help(self):
        """Button 2: call for help."""
        self._log("BUTTON", "Button 2 pressed (help)")
        return self.help_request("button")

    # ---- spot sensors ---------------------------------------------------------------------------
    def handle_spot_change(self, spot_id, occupied):
        with self.lock:
            s = self.db.one("SELECT * FROM spots WHERE id=?", (spot_id,))
            if not s:
                return
            now = self.clock()
            if occupied:
                if s["state"] == "OCCUPIED":
                    return
                if s["state"] == "RESERVED":
                    self.db.x("UPDATE spots SET state='OCCUPIED', reserved_until=NULL, misparked=0 WHERE id=?",
                              (spot_id,))
                    self.db.x("INSERT INTO sessions(employee_id,spot_id,t_in) VALUES(?,?,?)",
                              (s["employee_id"], spot_id, now))
                    self._log("PARKED", f"Car detected in {s['name']}", s["employee_id"], spot_id)
                else:  # a car in a spot nobody reserved
                    pending = self.db.q("SELECT * FROM spots WHERE state='RESERVED' "
                                        "ORDER BY reserved_until ASC LIMIT 1")
                    emp_id = None
                    if pending:
                        # Assume the arriving driver is the one waiting the longest: they ignored their spot.
                        p = pending[0]
                        emp_id = p["employee_id"]
                        self.db.x("UPDATE spots SET state='FREE', employee_id=NULL, reserved_until=NULL "
                                  "WHERE id=?", (p["id"],))
                        self._log("MISPARKED", f"Car parked in {s['name']} instead of assigned {p['name']}",
                                  emp_id, spot_id)
                    else:
                        self._log("MISPARKED", f"Unregistered car detected in {s['name']}", None, spot_id)
                    self.db.x("UPDATE spots SET state='OCCUPIED', employee_id=?, reserved_until=NULL, "
                              "misparked=1 WHERE id=?", (emp_id, spot_id))
                    self.db.x("INSERT INTO sessions(employee_id,spot_id,t_in,misparked) VALUES(?,?,?,1)",
                              (emp_id, spot_id, now))
            else:
                if s["state"] != "OCCUPIED":
                    return  # a RESERVED spot still reads empty until the car arrives
                self.db.x("UPDATE sessions SET t_out=? WHERE spot_id=? AND t_out IS NULL", (now, spot_id))
                self.db.x("UPDATE spots SET state='FREE', employee_id=NULL, reserved_until=NULL, misparked=0 "
                          "WHERE id=?", (spot_id,))
                self._log("LEFT", f"Spot {s['name']} is free again", s["employee_id"], spot_id)
            self._notify()

    def expire_reservations(self):
        with self.lock:
            stale = self.db.q("SELECT * FROM spots WHERE state='RESERVED' AND reserved_until<=?",
                              (self.clock(),))
            for s in stale:
                self.db.x("UPDATE spots SET state='FREE', employee_id=NULL, reserved_until=NULL WHERE id=?",
                          (s["id"],))
                self._log("EXPIRED", f"Reservation for {s['name']} expired", s["employee_id"], s["id"])
            if stale:
                self._notify()
            return len(stale)

    # ---- read model for the UI ------------------------------------------------------------------
    def snapshot(self):
        with self.lock:
            spots = self.db.q(
                "SELECT s.id,s.name,s.zone_id,z.name AS zone,s.x,s.y,s.state,s.misparked,s.reserved_until,"
                "s.employee_id,e.name AS employee,d.name AS department "
                "FROM spots s JOIN zones z ON z.id=s.zone_id "
                "LEFT JOIN employees e ON e.id=s.employee_id "
                "LEFT JOIN departments d ON d.id=e.department_id ORDER BY z.name, s.name")
            counts = {"total": len(spots), "free": 0, "reserved": 0, "occupied": 0}
            for s in spots:
                counts[s["state"].lower()] += 1
            ex, ey = self.db.entrance()
            return {"spots": spots, "counts": counts, "entrance": dict(self.entrance),
                    "entrance_pos": {"x": ex, "y": ey}, "ts": self.clock(),
                    "entrance_ttl": self.entrance_message_s,
                    "barrier": getattr(self.barrier, "state", "closed"),
                    "feedback": self.feedback.status() if self.feedback else {"led": None, "blink": False}}
