PETER, ANNA, MARCO, LENA = "A1B2C3D4", "11223344", "55667788", "99AABBCC"


def test_engineering_employees_are_sent_to_their_closest_zone(service):
    r1, r2 = service.handle_tag(PETER), service.handle_tag(ANNA)
    assert (r1["ok"], r1["spot"], r1["zone"]) == (True, "A1", "A")
    assert r2["spot"] == "A2"                       # next-nearest in the same zone, never the same spot


def test_other_departments_get_their_own_zone(service):
    assert service.handle_tag(MARCO)["zone"] == "B"   # Production -> B
    assert service.handle_tag(LENA)["zone"] == "C"    # Sales -> C


def test_full_closest_zone_falls_back_to_next_ranked_zone(service):
    service.db.x("UPDATE spots SET state='OCCUPIED' WHERE zone_id=(SELECT id FROM zones WHERE name='A')")
    assert service.handle_tag(PETER)["zone"] == "C"   # Engineering ranking is A, C, B


def test_unknown_disabled_and_unassigned_chips_are_denied(service):
    assert not service.handle_tag("DEADBEEF")["ok"]
    assert service.last_unknown == "DEADBEEF"
    service.db.x("UPDATE chips SET active=0 WHERE uid=?", (PETER,))
    assert not service.handle_tag(PETER)["ok"]
    assert not service.handle_tag("CAFEBABE")["ok"]   # spare chip, no employee
    assert service.db.one("SELECT COUNT(*) AS n FROM spots WHERE state!='FREE'")["n"] == 0


def test_uid_formats_are_normalised(service):
    assert service.handle_tag("a1:b2:c3:d4")["ok"]


def test_fixed_spot_overrides_department_zone(service, spot):
    service.db.x("UPDATE employees SET fixed_spot_id=? WHERE name='Peter'", (spot("B3")["id"],))
    assert service.handle_tag(PETER)["spot"] == "B3"


def test_lot_full(service):
    service.db.x("UPDATE spots SET state='OCCUPIED'")
    r = service.handle_tag(PETER)
    assert not r["ok"] and "full" in r["message"].lower()


def test_scanning_twice_returns_same_spot(service):
    first = service.handle_tag(PETER)["spot"]
    assert service.handle_tag(PETER)["spot"] == first
    assert service.db.one("SELECT COUNT(*) AS n FROM spots WHERE state='RESERVED'")["n"] == 1


def test_park_then_leave_updates_state_and_sessions(service, spot, clock):
    service.handle_tag(PETER)
    a1 = spot("A1")["id"]
    service.handle_spot_change(a1, True)
    assert (spot("A1")["state"], spot("A1")["misparked"]) == ("OCCUPIED", 0)
    clock.advance(3600)
    service.handle_spot_change(a1, False)
    assert spot("A1")["state"] == "FREE" and spot("A1")["employee_id"] is None
    s = service.db.one("SELECT * FROM sessions")
    assert s["t_out"] - s["t_in"] == 3600


def test_reservation_expires(service, spot, clock):
    service.handle_tag(PETER)
    clock.advance(179)
    assert service.expire_reservations() == 0
    clock.advance(2)
    assert service.expire_reservations() == 1
    assert spot("A1")["state"] == "FREE"


def test_sensor_glitch_on_reserved_spot_is_ignored(service, spot):
    service.handle_tag(PETER)
    service.handle_spot_change(spot("A1")["id"], False)
    assert spot("A1")["state"] == "RESERVED"


def test_car_in_wrong_spot_is_flagged_and_reservation_moves(service, spot):
    service.handle_tag(PETER)                         # assigned A1
    service.handle_spot_change(spot("A3")["id"], True)  # parks in A3 instead
    a3 = spot("A3")
    assert (a3["state"], a3["misparked"]) == ("OCCUPIED", 1)
    assert a3["employee_id"] is not None              # still attributed to Peter
    assert spot("A1")["state"] == "FREE"              # old reservation released
    kinds = [e["kind"] for e in service.db.q("SELECT kind FROM events")]
    assert "MISPARKED" in kinds


def test_unregistered_car_is_flagged(service, spot):
    service.handle_spot_change(spot("B2")["id"], True)
    b2 = spot("B2")
    assert (b2["state"], b2["misparked"], b2["employee_id"]) == ("OCCUPIED", 1, None)


def test_learn_mode_captures_chip_without_triggering_entry(service):
    service.start_learn(15)
    r = service.handle_tag("CAFEBABE")
    assert r.get("learn") and service.learned_uid == "CAFEBABE"
    assert service.db.one("SELECT COUNT(*) AS n FROM spots WHERE state!='FREE'")["n"] == 0
    assert service.handle_tag(PETER)["ok"]            # learn mode ended after one capture


def test_snapshot_counts_and_listeners_are_notified(service):
    q = service.subscribe()
    service.handle_tag(PETER)
    assert not q.empty()
    snap = service.snapshot()
    assert snap["counts"] == {"total": 8, "free": 7, "reserved": 1, "occupied": 0}
    assert snap["entrance"]["spot"] == "A1"
