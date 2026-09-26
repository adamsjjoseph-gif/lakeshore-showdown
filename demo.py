"""Clearly-fake demo data so the leaderboard looks alive in screenshots. Wipe it from Admin > Data before launch."""
import random
from datetime import timedelta
from calc import to_date

# per-store "temperature" so the demo standings are interesting
STORE_FLAVOR = {0: (0.31, 0.25, 2300), 1: (0.26, 0.2, 2150), 2: (0.3, 0.23, 2250)}


def generate(stores, people, start, demo_today, closed_sundays=True, seed=2026):
    rng = random.Random(seed)
    start, demo_today = to_date(start), to_date(demo_today)
    deals = []
    order = {s["id"]: i for i, s in enumerate(stores)}
    skill = {p["id"]: rng.uniform(0.55, 1.45) for p in people}
    day = start
    while day < demo_today:
        if closed_sundays and day.weekday() == 6:
            day += timedelta(days=1)
            continue
        sat = 1.35 if day.weekday() == 5 else 1.0
        for p in people:
            if not p.get("active", 1):
                continue
            pn, pu, avg = STORE_FLAVOR.get(order.get(p["store_id"], 0) % 3)
            k = skill[p["id"]] * sat
            # new units
            if rng.random() < pn * k:
                units = 1.0
                if rng.random() < 0.15:
                    units = 0.5
                elif rng.random() < 0.12:
                    units = 2.0
                if rng.random() < 0.03:
                    units = 3.0
                deals.append({"sp_id": p["id"], "store_id": p["store_id"], "date": day.isoformat(),
                              "kind": "new", "units": units, "gross": 0})
            # used deals, each with its own gross
            if rng.random() < pu * k:
                n = 2 if rng.random() < 0.12 else 1
                for _ in range(n):
                    split = rng.random() < 0.12
                    g = rng.gauss(avg, 1100)
                    if rng.random() < 0.05:
                        g = rng.uniform(4200, 6400)
                    g = round(max(-600, g) / 5) * 5
                    if split:
                        g = round(g / 2)
                    deals.append({"sp_id": p["id"], "store_id": p["store_id"], "date": day.isoformat(),
                                  "kind": "used", "units": 0.5 if split else 1.0, "gross": g})
        day += timedelta(days=1)
    return deals
