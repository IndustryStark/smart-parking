"""Spot selection. Pure function, no I/O, so it is trivial to unit-test."""

UNRANKED = 10 ** 6  # zones a department has no preference for are used last


def choose_spot(free_spots, zone_rank):
    """Pick the best free spot.

    free_spots: iterable of dicts with id, zone_id, dist (distance to the entrance).
    zone_rank:  {zone_id: rank}, rank 1 = closest zone for the employee's department.

    Order: department's zone rank, then distance to the entrance, then id (stable tie-break).
    """
    free_spots = list(free_spots)
    if not free_spots:
        return None
    return min(free_spots, key=lambda s: (zone_rank.get(s["zone_id"], UNRANKED), s["dist"], s["id"]))
