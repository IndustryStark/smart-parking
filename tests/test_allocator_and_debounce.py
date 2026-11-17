from smartparking.allocator import choose_spot
from smartparking.drivers.sensors import Debouncer


def spot(i, zone, dist):
    return {"id": i, "zone_id": zone, "dist": dist}


def test_prefers_closest_zone_over_closest_spot():
    free = [spot(1, zone=1, dist=9.0), spot(2, zone=2, dist=1.0)]
    assert choose_spot(free, {1: 1, 2: 2})["id"] == 1


def test_within_zone_nearest_to_entrance_wins():
    free = [spot(1, 1, 5.0), spot(2, 1, 3.0), spot(3, 1, 4.0)]
    assert choose_spot(free, {1: 1})["id"] == 2


def test_falls_back_to_next_zone_and_unranked_zones_come_last():
    free = [spot(1, zone=3, dist=1.0), spot(2, zone=2, dist=8.0)]
    assert choose_spot(free, {2: 2})["id"] == 2          # ranked zone beats unranked one
    assert choose_spot([free[0]], {2: 2})["id"] == 1     # unranked still usable when nothing else is free


def test_tie_break_is_stable_and_empty_returns_none():
    assert choose_spot([spot(5, 1, 2.0), spot(4, 1, 2.0)], {1: 1})["id"] == 4
    assert choose_spot([], {1: 1}) is None


def test_debouncer_ignores_blips_and_reports_stable_changes_once():
    d = Debouncer(required=3, initial=False)
    assert [d.update(s) for s in (True, False, True, True)] == [None, None, None, None]
    assert d.update(True) is True        # third consecutive True
    assert d.update(True) is None        # no repeat report
    assert [d.update(False) for _ in range(2)] == [None, None]
    assert d.update(False) is False
