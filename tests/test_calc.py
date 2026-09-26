"""Unit tests for the contest math (leaderboards, store battle, payouts). Run: python3 -m unittest discover tests"""
import os, sys, unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import calc  # noqa: E402

CFG = {"start_date": "2026-10-01", "end_date": "2026-10-31", "weight_new": 50, "points_new": 2, "points_per_1k": 1,
       "heavy_hitter": 4000, "qualifier_units": 1, "closed_sundays": True, "prizes": calc.DEFAULT_PRIZES}
STORES = [
    {"id": 1, "name": "Big Store", "short": "BIG", "color": "#f00", "new_target": 100, "used_target": 200000, "contribution": 3500},
    {"id": 2, "name": "Small Store", "short": "SML", "color": "#0f0", "new_target": 40, "used_target": 80000, "contribution": 3500},
    {"id": 3, "name": "Mid Store", "short": "MID", "color": "#00f", "new_target": 60, "used_target": 120000, "contribution": 3500},
]


def roster():
    ppl, i = [], 1
    for sid in (1, 2, 3):
        for n in range(7):
            ppl.append({"id": i, "store_id": sid, "name": f"S{sid}-P{n + 1}", "active": 1})
            i += 1
    return ppl


def deal(sp, d, kind, units=1, gross=0, store=None):
    return {"id": None, "sp_id": sp, "store_id": store, "date": d, "kind": kind, "units": units, "gross": gross}


def total_cents(res):
    return sum(round(l["amount"] * 100) for l in res["payouts"]["lines"])


class TestMoney(unittest.TestCase):
    def test_split_cents_exact(self):
        for total, n in ((300000, 7), (150000, 6), (25000, 3), (1, 2), (12500, 1)):
            parts = calc.split_cents(total, n)
            self.assertEqual(sum(parts), total)
            self.assertLessEqual(max(parts) - min(parts), 1)

    def test_default_budget_is_exactly_10500_for_october(self):
        periods = calc.contest_periods("2026-10-01", "2026-10-31")
        self.assertEqual([p["days"] for p in periods], [7, 7, 7, 7, 3])
        b = calc.prize_budget(calc.DEFAULT_PRIZES, 3, len(periods))
        self.assertEqual(b, {"team": 450000, "new": 200000, "used": 200000, "mvp": 75000, "bounties": 125000, "total": 1050000})

    def test_ended_contest_pays_out_exactly_the_pool(self):
        ppl = roster()
        deals = []
        for sp in range(1, 22):  # everyone sells something in every week
            for d in ("2026-10-02", "2026-10-09", "2026-10-16", "2026-10-23", "2026-10-30"):
                deals.append(deal(sp, d, "new", 1 + (sp % 3) * 0.5))
                deals.append(deal(sp, d, "used", 1, 1000 + sp * 37))
        res = calc.compute(CFG, STORES, ppl, deals, date(2026, 11, 3))
        self.assertEqual(res["status"], "ended")
        self.assertTrue(res["payouts"]["budget_ok"])
        self.assertEqual(total_cents(res), 1050000)
        self.assertEqual(res["payouts"]["upcoming"], 0)

    def test_unclaimed_prizes_roll_into_first_place_team_pot(self):
        ppl = roster()
        # only one rep sells, only new cars, only in week 1 -> lots unclaimed
        deals = [deal(8, "2026-10-02", "new", 2)]
        res = calc.compute(CFG, STORES, ppl, deals, date(2026, 11, 3))
        self.assertEqual(total_cents(res), 1050000)        # still exactly the pool
        self.assertGreater(res["payouts"]["rollover"], 0)
        # rep 8 (Small Store) is the only qualifier on the winning team, so they get the whole 1st-place team pot
        team = [l for l in res["payouts"]["lines"] if l["cat"] == "team" and l["person_id"] == 8]
        # ...plus the 2nd/3rd-place pots, because the other stores have no qualified reps
        self.assertEqual(round(team[0]["amount"] * 100), 300000 + 150000 + round(res["payouts"]["rollover"] * 100))
        self.assertFalse([l for l in res["payouts"]["lines"] if l["status"] == "unclaimed"])


class TestStoreBattle(unittest.TestCase):
    def test_small_store_can_beat_big_store_on_percent_of_target(self):
        ppl = roster()
        deals = [deal(1, "2026-10-05", "new", 50), deal(1, "2026-10-05", "used", 1, 100000),   # BIG: 50% / 50%
                 deal(8, "2026-10-05", "new", 30), deal(8, "2026-10-05", "used", 1, 60000)]    # SMALL: 75% / 75%
        res = calc.compute(CFG, STORES, ppl, deals, date(2026, 10, 20))
        order = [s["short"] for s in res["stores"]]
        self.assertEqual(order[0], "SML")
        sml = res["stores"][0]
        self.assertAlmostEqual(sml["score"], 75.0)
        self.assertAlmostEqual(res["stores"][1]["score"], 50.0)

    def test_weighting_and_tiebreak_on_new_pct(self):
        ppl = roster()
        # BIG: 60% new, 40% used = 50 ; SML: 40% new, 60% used = 50 -> tie broken by higher new %
        deals = [deal(1, "2026-10-05", "new", 60), deal(1, "2026-10-05", "used", 1, 80000),
                 deal(8, "2026-10-05", "new", 16), deal(8, "2026-10-05", "used", 1, 48000)]
        res = calc.compute(CFG, STORES, ppl, deals, date(2026, 10, 20))
        self.assertEqual([s["short"] for s in res["stores"]][:2], ["BIG", "SML"])
        self.assertEqual(res["stores"][0]["score"], res["stores"][1]["score"])

    def test_team_pot_split_evenly_among_qualifiers_only(self):
        ppl = roster()
        deals = [deal(sp, "2026-10-03", "new", 5) for sp in range(8, 15)]         # all 7 small-store reps qualify
        deals += [deal(1, "2026-10-03", "new", 0.5)]                               # BIG rep with 0.5 unit: not qualified
        deals += [deal(2, "2026-10-03", "new", 10)]
        res = calc.compute(CFG, STORES, ppl, deals, date(2026, 11, 2))
        small = next(s for s in res["stores"] if s["short"] == "SML")
        self.assertEqual(small["rank"], 1)
        shares = [round(l["amount"] * 100) for l in res["payouts"]["lines"] if l["cat"] == "team" and l["store_id"] == 2]
        self.assertEqual(len(shares), 7)
        self.assertEqual(sum(shares), 300000 + round(res["payouts"]["rollover"] * 100))
        big_team = [l for l in res["payouts"]["lines"] if l["cat"] == "team" and l["store_id"] == 1]
        self.assertEqual([l["person_id"] for l in big_team], [2])  # only the qualified BIG rep gets 2nd-place money


class TestIndividuals(unittest.TestCase):
    def test_split_deals_count_half(self):
        ppl = roster()
        deals = [deal(1, "2026-10-02", "new", 0.5), deal(1, "2026-10-03", "new", 0.5), deal(1, "2026-10-04", "used", 0.5, 900)]
        res = calc.compute(CFG, STORES, ppl, deals, date(2026, 10, 10))
        me = next(r for r in res["leaderboards"]["new"] if r["id"] == 1)
        self.assertEqual(me["new"], 1.0)
        self.assertEqual(me["used_units"], 0.5)
        self.assertEqual(me["gross"], 900)

    def test_tiebreak_then_split(self):
        ppl = roster()
        deals = [deal(1, "2026-10-02", "new", 5), deal(1, "2026-10-02", "used", 1, 2000),   # 5 units, $2000
                 deal(8, "2026-10-02", "new", 5), deal(8, "2026-10-02", "used", 1, 3000),   # 5 units, $3000 -> wins tie-break
                 deal(15, "2026-10-02", "new", 3), deal(16, "2026-10-02", "new", 3)]        # exact tie for 3rd
        res = calc.compute(CFG, STORES, ppl, deals, date(2026, 11, 2))
        new_lines = {(l["person_id"], l["label"]): l["amount"] for l in res["payouts"]["lines"] if l["cat"] == "new"}
        self.assertEqual(new_lines[(8, "1st")], 1000)
        self.assertEqual(new_lines[(1, "2nd")], 600)
        self.assertEqual(new_lines[(15, "3rd")], 200)   # tied 3rd place splits the $400
        self.assertEqual(new_lines[(16, "3rd")], 200)
        ranks = {r["id"]: r["rank"] for r in res["leaderboards"]["new"]}
        self.assertEqual((ranks[8], ranks[1], ranks[15], ranks[16]), (1, 2, 3, 3))

    def test_tie_for_first_splits_first_and_second(self):
        ppl = roster()
        deals = [deal(1, "2026-10-02", "used", 1, 2500), deal(8, "2026-10-02", "used", 1, 2500), deal(15, "2026-10-02", "used", 1, 100)]
        res = calc.compute(CFG, STORES, ppl, deals, date(2026, 11, 2))
        used = {l["person_id"]: l for l in res["payouts"]["lines"] if l["cat"] == "used"}
        self.assertEqual(used[1]["amount"], 800)
        self.assertEqual(used[8]["amount"], 800)
        self.assertEqual(used[1]["label"], "T-1st/2nd")
        self.assertEqual(used[15]["amount"], 400)

    def test_unwind_removed_changes_results(self):
        ppl = roster()
        deals = [deal(1, "2026-10-02", "new", 3), deal(8, "2026-10-02", "new", 2)]
        r1 = calc.compute(CFG, STORES, ppl, deals, date(2026, 10, 9))
        self.assertEqual(r1["leaderboards"]["new"][0]["id"], 1)
        r2 = calc.compute(CFG, STORES, ppl, deals[1:], date(2026, 10, 9))   # unwind = entry deleted
        self.assertEqual(r2["leaderboards"]["new"][0]["id"], 8)

    def test_inactive_rep_counts_for_store_but_not_individual_prizes(self):
        ppl = roster()
        ppl[0]["active"] = 0
        deals = [deal(1, "2026-10-02", "new", 10), deal(2, "2026-10-02", "new", 1)]
        res = calc.compute(CFG, STORES, ppl, deals, date(2026, 11, 2))
        self.assertEqual(next(s for s in res["stores"] if s["id"] == 1)["new"], 11)
        self.assertNotIn(1, [r["id"] for r in res["leaderboards"]["new"]])
        self.assertNotIn(1, [l["person_id"] for l in res["payouts"]["lines"]])

    def test_deals_outside_contest_window_ignored(self):
        ppl = roster()
        deals = [deal(1, "2026-09-30", "new", 5), deal(1, "2026-11-01", "new", 5), deal(1, "2026-10-31", "new", 1)]
        res = calc.compute(CFG, STORES, ppl, deals, date(2026, 11, 2))
        self.assertEqual(res["leaderboards"]["new"][0]["new"], 1)


class TestBountiesAndBadges(unittest.TestCase):
    def test_weekly_bounties(self):
        ppl = roster()
        deals = [deal(1, "2026-10-02", "new", 2), deal(8, "2026-10-03", "new", 3),
                 deal(1, "2026-10-05", "used", 1, 4100), deal(15, "2026-10-06", "used", 0.5, 2000),
                 deal(15, "2026-10-08", "used", 1, 9000)]  # week 2 — must not count for week 1
        res = calc.compute(CFG, STORES, ppl, deals, date(2026, 10, 9))
        w1, w2 = res["periods"][0], res["periods"][1]
        self.assertEqual(w1["status"], "won")
        self.assertEqual(w1["top_gun"]["ids"], [8])
        self.assertEqual(w1["big_fish"]["ids"], [1])
        self.assertEqual(w1["big_fish"]["gross"], 4100)
        self.assertEqual(w2["status"], "live")
        self.assertEqual(w2["big_fish"]["ids"], [15])
        self.assertEqual(res["periods"][2]["status"], "upcoming")
        self.assertEqual(res["payouts"]["upcoming"], 750)  # weeks 3,4,5 x $250

    def test_badges(self):
        ppl = roster()
        deals = [deal(1, "2026-10-01", "new", 3), deal(1, "2026-10-01", "used", 1, 4500),
                 deal(1, "2026-10-02", "new", 1), deal(1, "2026-10-03", "new", 1),
                 # Sat Oct 3 -> Mon Oct 5 keeps a streak alive when closed Sundays
                 deal(2, "2026-10-02", "new", 1), deal(2, "2026-10-03", "new", 1), deal(2, "2026-10-05", "new", 1)]
        res = calc.compute(CFG, STORES, ppl, deals, date(2026, 10, 6))
        b = {r["id"]: r["badges"] for r in res["leaderboards"]["new"]}
        self.assertEqual(set(b[1]), {"hat_trick", "heavy_hitter", "on_fire", "double_down", "opening_day"})
        self.assertIn("on_fire", b[2])
        streak = {r["id"]: r["streak"] for r in res["leaderboards"]["new"]}
        self.assertEqual(streak[2], 3)

    def test_before_contest_starts(self):
        res = calc.compute(CFG, STORES, roster(), [], date(2026, 9, 25))
        self.assertEqual(res["status"], "upcoming")
        self.assertEqual(res["days_left"], 31)
        self.assertEqual(res["payouts"]["upcoming"], 1250)
        self.assertEqual(res["trend"]["dates"], [])
        self.assertEqual(res["payouts"]["lines"], [])          # nothing projected before kickoff
        self.assertEqual(res["payouts"]["up_for_grabs"], 10500)


if __name__ == "__main__":
    unittest.main()
