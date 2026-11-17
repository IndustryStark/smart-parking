def login(client):
    return client.post("/api/admin/login", json={"password": "secret123"})


def test_admin_api_requires_login(client):
    assert client.get("/api/admin/chips").status_code == 401
    assert client.post("/api/admin/chips", json={"uid": "AABBCCDD"}).status_code == 401
    assert client.post("/api/admin/login", json={"password": "nope"}).status_code == 401
    assert login(client).status_code == 200
    assert client.get("/api/admin/chips").status_code == 200


def test_mutations_need_json_body(client):
    login(client)
    r = client.post("/api/admin/chips", data="uid=AABBCCDD", content_type="application/x-www-form-urlencoded")
    assert r.status_code == 415


def test_pages_render(client):
    for path in ("/", "/entrance", "/admin", "/api/state"):
        assert client.get(path).status_code == 200


def test_register_chip_assign_employee_and_enter(client):
    login(client)
    emps = {e["name"]: e["id"] for e in client.get("/api/admin/employees").get_json()}
    # unknown chip is rejected at the entrance ...
    assert not client.post("/api/sim/scan", json={"uid": "0A0B0C0D"}).get_json()["ok"]
    # ... admin registers it for Lena, then it works
    r = client.post("/api/admin/chips", json={"uid": "0a:0b:0c:0d", "employee_id": emps["Lena"], "active": True})
    assert r.status_code == 201
    res = client.post("/api/sim/scan", json={"uid": "0A0B0C0D"}).get_json()
    assert res["ok"] and res["zone"] == "C"          # Sales -> zone C
    # reassigning the chip to an Engineering employee changes where the next car goes
    client.put("/api/admin/chips/0A0B0C0D", json={"employee_id": emps["Peter"]})
    client.post("/api/sim/spot", json={"spot_id": res["spot_id"], "occupied": True})
    client.post("/api/sim/spot", json={"spot_id": res["spot_id"], "occupied": False})
    assert client.post("/api/sim/scan", json={"uid": "0A0B0C0D"}).get_json()["zone"] == "A"


def test_invalid_input_and_duplicates_are_rejected(client):
    login(client)
    assert client.post("/api/admin/chips", json={"uid": "xyz"}).status_code == 400
    assert client.post("/api/admin/departments", json={"name": "  "}).status_code == 400
    assert client.post("/api/admin/departments", json={"name": "Sales"}).status_code == 409
    assert client.post("/api/admin/spots", json={"name": "Z1", "zone_id": 1, "gpio_pin": 99}).status_code == 400


def test_simulated_buttons_and_led_show_in_state(client):
    client.post("/api/sim/scan", json={"uid": "A1B2C3D4"})
    assert client.get("/api/state").get_json()["feedback"]["led"] == "green"
    client.post("/api/sim/help", json={})
    state = client.get("/api/state").get_json()
    assert state["entrance"]["help"] is True
    assert (state["feedback"]["led"], state["feedback"]["blink"]) == ("blue", True)
    client.post("/api/sim/repeat", json={})
    assert client.get("/api/state").get_json()["entrance"]["spot"] == "A1"


def test_led_button_pins_are_reserved(client):
    login(client)
    zone = client.get("/api/admin/zones").get_json()[0]["id"]
    for pin in (17, 18, 27, 22, 26, 12):
        r = client.post("/api/admin/spots", json={"name": f"X{pin}", "zone_id": zone, "gpio_pin": pin})
        assert r.status_code == 400, pin


def test_gpio_pin_conflicts_are_rejected(client):
    login(client)
    zone = client.get("/api/admin/zones").get_json()[0]["id"]
    new = lambda pin, **kw: client.post("/api/admin/spots", json={"name": f"P{pin}", "zone_id": zone, "gpio_pin": pin, **kw})
    assert new(5).status_code == 400            # demo spot A1 already uses GPIO5
    assert new(8).status_code == 400            # SPI chip-select of the RFID reader
    assert new(18).status_code == 400           # servo
    assert new(30).status_code == 400           # not a header GPIO
    assert new(4, trigger_pin=4).status_code == 400
    assert new(4).status_code == 201            # a free pin works
    spots = {s["name"]: s["id"] for s in client.get("/api/admin/spots").get_json()}
    assert client.put(f"/api/admin/spots/{spots['A1']}", json={"gpio_pin": 6}).status_code == 400   # A2's pin
    assert client.put(f"/api/admin/spots/{spots['A1']}", json={"gpio_pin": 5}).status_code == 200   # own pin is fine


def test_sensor_reconfigure_failure_is_reported_not_fatal(service):
    from smartparking.web import create_app
    def boom():
        raise RuntimeError("pin busy")
    c = create_app(service, on_spots_changed=boom, admin_password="secret123", secret="t").test_client()
    c.post("/api/admin/login", json={"password": "secret123"})
    zone = c.get("/api/admin/zones").get_json()[0]["id"]
    r = c.post("/api/admin/spots", json={"name": "Q1", "zone_id": zone, "gpio_pin": 4})
    assert r.status_code == 201 and "pin busy" in r.get_json()["warning"]


def test_new_department_gets_all_zones_ranked_and_can_be_reordered(client):
    login(client)
    dep = client.post("/api/admin/departments", json={"name": "HR"}).get_json()["id"]
    zones = client.get("/api/admin/zones").get_json()
    row = next(d for d in client.get("/api/admin/departments").get_json() if d["id"] == dep)
    assert sorted(row["zone_order"]) == sorted(z["id"] for z in zones)

    emp = client.post("/api/admin/employees", json={"name": "Eva", "department_id": dep}).get_json()["id"]
    client.post("/api/admin/chips", json={"uid": "ABCDEF01", "employee_id": emp})
    zid = {z["name"]: z["id"] for z in zones}
    r = client.put(f"/api/admin/departments/{dep}/zones", json={"zones": [zid["B"], zid["A"], zid["C"]]})
    assert r.status_code == 200
    assert client.post("/api/sim/scan", json={"uid": "ABCDEF01"}).get_json()["zone"] == "B"
    assert client.put(f"/api/admin/departments/{dep}/zones", json={"zones": [zid["B"]]}).status_code == 400


def test_new_spot_distance_is_computed_and_in_use_department_cannot_be_deleted(client):
    login(client)
    zone = client.get("/api/admin/zones").get_json()[0]["id"]
    sid = client.post("/api/admin/spots", json={"name": "Z9", "zone_id": zone, "x": 3, "y": 7}).get_json()["id"]
    spot = next(s for s in client.get("/api/admin/spots").get_json() if s["id"] == sid)
    assert round(spot["dist"], 2) == 5.0              # entrance is at (0,3): hypot(3,4)
    dep = client.get("/api/admin/departments").get_json()[0]["id"]
    assert client.delete(f"/api/admin/departments/{dep}").status_code == 409


def test_state_reflects_parking_flow_and_events_are_logged(client):
    login(client)
    res = client.post("/api/sim/scan", json={"uid": "A1B2C3D4"}).get_json()
    client.post("/api/sim/spot", json={"spot_id": res["spot_id"], "occupied": True})
    state = client.get("/api/state").get_json()
    assert state["counts"]["occupied"] == 1
    kinds = [e["kind"] for e in client.get("/api/admin/events").get_json()]
    assert kinds[:2] == ["PARKED", "RESERVED"]
