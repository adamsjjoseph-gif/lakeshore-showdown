"""Unit tests for the contest math (leaderboards, store goal, payouts). Run: python3 -m unittest discover tests"""
import os, sys, unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import calc  # noqa: E402

# Sep 26 (Sat) - Sep 30 (Wed) 2026; appointments count Sep 26 - Sep 29. One store (Chrysler Muskegon), $3,000.
CFG = {"start_date": "2026-09-26", "end_date": "2026-09-30", "appt_start": "2026-09-26", "appt_end": "2026-09-29",
       "weight_new": 1, "weight_used": 1, "weight_appt": 1, "points_new": 2, "points_per_1k": 1, "points_per_appt": 0.5,
       "heavy_hitter": 4000, "closed_sundays": True, "bounty_days": 1, "prizes": calc.DEFAULT_PRIZES}
STORES = [
    {"id": 1, "name": "Chrysler Muskegon", "short": "CJDR Muskegon", "color": "#e11d48", "new_target": 70, "used_target": 140000,
     "appt_target": 60, "contribution": 3000},
]
NAMES = ["Monty", "Nathan", "Adrian", "Sierra", "Jacob", "Raheem"]
DAYS = ["2026-09-26", "2026-09-27", "2026-09-28", "2026-09-29", "2026-09-30"]
AFTER = date(2026, 10, 2)
POOL_C = 300000


def roster():
    return [{"id": i, "store_id": 1, "name": n, "active": 1} for i, n in enumerate(NAMES, start=1)]


def deal(sp, d, kind, units=1, gross=0, store=1):
    return {"id": None, "sp_id": sp, "store_id": store, "date": d, "kind": kind, "units": units, "gross": gross}


def total_cents(res):
    return sum(round(l["amount"] * 100) for l in res["payouts"]["lines"])


class TestMoney(unittest.TestCase):
    def test_split_cents_exact(self):
        for total, n in ((90000, 7), (100000, 6), (25000, 3), (1, 2), (5000, 1)):
            parts = calc.split_cents(total, n)
            self.assertEqual(sum(parts), total)
            self.assertLessEqual(max(parts) - min(parts), 1)

    def test_prize_table_totals_exactly_3000(self):
        p = calc.DEFAULT_PRIZES
        self.assertNotIn("team", p)
        self.assertNotIn("mvp", p)
        self.assertEqual(p["points"][:2], [900, 275])
        self.assertEqual((sum(p["new"]), sum(p["used"]), sum(p["appt"]), p["hot_shot"]), (575, 575, 425, 50))
        for v in p["points"] + p["new"] + p["used"] + p["appt"] + [p["hot_shot"]]:
            self.assertEqual(v % 25, 0)                                    # clean $25 multiples
        periods = calc.contest_periods("2026-09-26", "2026-09-30", 1)
        self.assertEqual(len(periods), 5)                               # 5 Daily Hot Shot days
        b = calc.prize_budget(p, len(periods))
        self.assertEqual(b, {"points": 117500, "new": 57500, "used": 57500, "appt": 42500, "hot_shot": 25000, "total": 300000})
        self.assertEqual(b["total"], calc.POOL_TOTAL * 100)
        self.assertEqual(calc.POOL_TOTAL, 3000)

    def test_ended_contest_pays_out_exactly_the_pool(self):
        ppl = roster()
        deals = []
        for sp in range(1, 7):
            for d in DAYS:
                deals.append(deal(sp, d, "new", 1 + (sp % 3) * 0.5))
                deals.append(deal(sp, d, "used", 1, 1000 + sp * 37))
                deals.append(deal(sp, d, "appt", 1 + sp % 4))
        res = calc.compute(CFG, STORES, ppl, deals, AFTER)
        self.assertEqual(res["status"], "ended")
        self.assertTrue(res["payouts"]["budget_ok"])
        self.assertEqual(res["payouts"]["pool"], 3000)
        self.assertEqual(total_cents(res), POOL_C)
        self.assertEqual(res["payouts"]["upcoming"], 0)
        self.assertEqual(len([l for l in res["payouts"]["lines"] if l["cat"] == "hot_shot"]), 5)
        self.assertEqual(len([l for l in res["payouts"]["lines"] if l["cat"] == "points"]), 2)
        self.assertFalse([l for l in res["payouts"]["lines"] if l["cat"] in ("team", "mvp")])

    def test_unclaimed_prizes_roll_into_showdown_champion_first(self):
        ppl = roster()
        # only one rep sells, only new cars, only on day 1 -> lots unclaimed
        deals = [deal(2, "2026-09-26", "new", 2)]
        res = calc.compute(CFG, STORES, ppl, deals, AFTER)
        self.assertEqual(total_cents(res), POOL_C)        # still exactly the pool
        self.assertGreater(res["payouts"]["rollover"], 0)
        champ = [l for l in res["payouts"]["lines"] if l["cat"] == "points"]
        # rep 2 is the only one with points, so they get 1st + 2nd Champion prizes + everything unclaimed
        self.assertEqual([l["person_id"] for l in champ], [2])
        self.assertEqual(round(champ[0]["amount"] * 100), 90000 + 27500 + round(res["payouts"]["rollover"] * 100))
        self.assertFalse([l for l in res["payouts"]["lines"] if l["status"] == "unclaimed"])


class TestStoreGoal(unittest.TestCase):
    def test_store_goal_is_percent_of_target(self):
        ppl = roster()
        deals = [deal(1, "2026-09-28", "new", 35), deal(2, "2026-09-28", "used", 1, 70000), deal(3, "2026-09-28", "appt", 30)]
        res = calc.compute(CFG, STORES, ppl, deals, date(2026, 9, 29))
        self.assertEqual(len(res["stores"]), 1)
        s = res["stores"][0]
        self.assertEqual((s["name"], s["new_pct"], s["used_pct"], s["appt_pct"]), ("Chrysler Muskegon", 50, 50, 50))
        self.assertAlmostEqual(s["score"], 50.0)
        self.assertNotIn("team_prize", s)
        self.assertEqual(res["score_weights"], {"new": 33.33, "used": 33.33, "appt": 33.33})

    def test_appointments_outside_window_do_not_count(self):
        ppl = roster()
        deals = [deal(1, "2026-09-29", "appt", 4), deal(1, "2026-09-30", "appt", 9), deal(1, "2026-09-25", "appt", 9)]
        res = calc.compute(CFG, STORES, ppl, deals, AFTER)
        me = next(r for r in res["leaderboards"]["appt"] if r["id"] == 1)
        self.assertEqual(me["appts"], 4)
        self.assertEqual(res["stores"][0]["appts"], 4)
        # the window is a setting: widen it and Sep 30 counts too
        res = calc.compute({**CFG, "appt_end": "2026-09-30"}, STORES, ppl, deals, AFTER)
        self.assertEqual(next(r for r in res["leaderboards"]["appt"] if r["id"] == 1)["appts"], 13)
        self.assertEqual(res["appt_window"]["end"], "2026-09-30")

    def test_legacy_weight_setting_maps_to_equal_thirds(self):
        self.assertEqual([round(x, 6) for x in calc.score_weights({"weight_new": 50})], [round(1 / 3, 6)] * 3)
        wn, wu, wa = calc.score_weights({"weight_new": 2, "weight_used": 1, "weight_appt": 1})
        self.assertAlmostEqual(wn, 0.5)
        self.assertAlmostEqual(wu + wa, 0.5)


class TestIndividuals(unittest.TestCase):
    def test_split_deals_count_half(self):
        ppl = roster()
        deals = [deal(1, "2026-09-26", "new", 0.5), deal(1, "2026-09-28", "new", 0.5), deal(1, "2026-09-29", "used", 0.5, 900)]
        res = calc.compute(CFG, STORES, ppl, deals, AFTER)
        me = next(r for r in res["leaderboards"]["new"] if r["id"] == 1)
        self.assertEqual(me["new"], 1.0)
        self.assertEqual(me["used_units"], 0.5)
        self.assertEqual(me["gross"], 900)

    def test_single_winner_prizes(self):
        ppl = roster()
        deals = [deal(1, "2026-09-26", "new", 5), deal(1, "2026-09-26", "used", 1, 2000),
                 deal(2, "2026-09-26", "new", 5), deal(2, "2026-09-26", "used", 1, 3000),   # wins New Unit King tie-break
                 deal(5, "2026-09-28", "appt", 7), deal(6, "2026-09-28", "appt", 6), deal(6, "2026-09-30", "appt", 5)]
        res = calc.compute(CFG, STORES, ppl, deals, AFTER)
        lines = {(l["cat"], l["person_id"]): l["amount"] for l in res["payouts"]["lines"] if l["cat"] in ("new", "used", "appt")}
        self.assertEqual(lines, {("new", 2): 575, ("used", 2): 575, ("appt", 5): 425})
        ranks = {r["id"]: r["rank"] for r in res["leaderboards"]["new"]}
        self.assertEqual((ranks[2], ranks[1]), (1, 2))

    def test_showdown_champion_places_and_tiebreak(self):
        ppl = roster()
        deals = [deal(1, "2026-09-26", "new", 3),                                  # 6 pts
                 deal(2, "2026-09-26", "new", 2), deal(2, "2026-09-26", "used", 1, 2000),   # 6 pts, fewer new -> 2nd
                 deal(3, "2026-09-28", "new", 1)]                                  # 2 pts
        res = calc.compute(CFG, STORES, ppl, deals, date(2026, 9, 29))
        champ = {l["person_id"]: l for l in res["payouts"]["lines"] if l["cat"] == "points"}
        self.assertEqual(champ[1]["label"], "Showdown Champion 1st")
        self.assertEqual(champ[2]["label"], "Showdown Champion 2nd")
        self.assertEqual(round(champ[2]["amount"] * 100), 27500)
        self.assertNotIn(3, champ)
        self.assertEqual([r["id"] for r in res["leaderboards"]["points"][:3]], [1, 2, 3])

    def test_tie_for_first_splits_the_prize(self):
        ppl = roster()
        deals = [deal(1, "2026-09-26", "appt", 4), deal(4, "2026-09-26", "appt", 4)]
        res = calc.compute(CFG, STORES, ppl, deals, AFTER)
        appt = {l["person_id"]: l for l in res["payouts"]["lines"] if l["cat"] == "appt"}
        self.assertEqual((appt[1]["amount"], appt[4]["amount"]), (212.5, 212.5))
        self.assertEqual(appt[1]["label"], "T-1st/2nd")

    def test_unwind_removed_changes_results(self):
        ppl = roster()
        deals = [deal(1, "2026-09-26", "new", 3), deal(2, "2026-09-26", "new", 2)]
        r1 = calc.compute(CFG, STORES, ppl, deals, date(2026, 9, 29))
        self.assertEqual(r1["leaderboards"]["new"][0]["id"], 1)
        r2 = calc.compute(CFG, STORES, ppl, deals[1:], date(2026, 9, 29))
        self.assertEqual(r2["leaderboards"]["new"][0]["id"], 2)

    def test_inactive_rep_counts_for_store_but_not_individual_prizes(self):
        ppl = roster()
        ppl[0]["active"] = 0
        deals = [deal(1, "2026-09-26", "new", 10), deal(1, "2026-09-26", "appt", 9), deal(2, "2026-09-26", "new", 1)]
        res = calc.compute(CFG, STORES, ppl, deals, AFTER)
        s1 = res["stores"][0]
        self.assertEqual((s1["new"], s1["appts"]), (11, 9))
        self.assertNotIn(1, [r["id"] for r in res["leaderboards"]["new"]])
        self.assertNotIn(1, [l["person_id"] for l in res["payouts"]["lines"]])

    def test_deals_outside_contest_window_ignored(self):
        ppl = roster()
        deals = [deal(1, "2026-09-25", "new", 5), deal(1, "2026-10-01", "new", 5), deal(1, "2026-09-30", "new", 1)]
        res = calc.compute(CFG, STORES, ppl, deals, AFTER)
        self.assertEqual(res["leaderboards"]["new"][0]["new"], 1)


class TestHotShotAndBadges(unittest.TestCase):
    def test_daily_hot_shot_uses_showdown_points_including_appointments(self):
        ppl = roster()
        deals = [deal(1, "2026-09-26", "new", 2),                                       # 4 pts
                 deal(4, "2026-09-26", "used", 1, 2500), deal(4, "2026-09-26", "appt", 4),  # 2.5 + 2 = 4.5 pts -> wins Sat
                 deal(5, "2026-09-28", "new", 1), deal(5, "2026-09-28", "used", 1, 1000),  # Mon: 3 pts
                 deal(6, "2026-09-28", "appt", 6),                                      # Mon: 3 pts, fewer new units -> loses tie-break
                 deal(2, "2026-09-30", "appt", 20), deal(3, "2026-09-30", "new", 0.5)]   # Wed: appts don't count (outside window)
        res = calc.compute(CFG, STORES, ppl, deals, date(2026, 9, 30))
        p = {x["start"]: x for x in res["periods"]}
        self.assertEqual(len(res["periods"]), 5)
        self.assertEqual(p["2026-09-26"]["status"], "won")
        self.assertEqual(p["2026-09-26"]["hot_shot"]["ids"], [4])
        self.assertEqual(p["2026-09-26"]["hot_shot"]["points"], 4.5)
        self.assertIsNone(p["2026-09-27"]["hot_shot"])                  # closed Sunday: nobody -> rolls into Champion 1st
        self.assertEqual(p["2026-09-28"]["hot_shot"]["ids"], [5])
        self.assertEqual(p["2026-09-30"]["status"], "live")
        self.assertEqual(p["2026-09-30"]["hot_shot"]["ids"], [3])
        hs = [l for l in res["payouts"]["lines"] if l["cat"] == "hot_shot"]
        self.assertEqual(sorted((l["person_id"], l["amount"], l["status"]) for l in hs),
                         [(3, 50, "leading"), (4, 50, "won"), (5, 50, "won")])
        self.assertIn({"cat": "hot_shot", "cents": 5000, "period": 2}, res["payouts"]["unclaimed"])

    def test_points_include_appointments(self):
        ppl = roster()
        deals = [deal(1, "2026-09-26", "new", 1), deal(1, "2026-09-26", "used", 1, 2000), deal(1, "2026-09-26", "appt", 3)]
        res = calc.compute(CFG, STORES, ppl, deals, AFTER)
        me = next(r for r in res["leaderboards"]["points"] if r["id"] == 1)
        self.assertEqual(me["points"], 2 + 2 + 1.5)

    def test_badges(self):
        ppl = roster()
        deals = [deal(1, "2026-09-26", "new", 3), deal(1, "2026-09-26", "used", 1, 4500),
                 deal(1, "2026-09-28", "new", 1), deal(1, "2026-09-29", "new", 1),
                 # Sat 9/26 -> Mon 9/28 keeps a streak alive when closed Sundays
                 deal(2, "2026-09-26", "new", 1), deal(2, "2026-09-28", "new", 1), deal(2, "2026-09-29", "new", 1),
                 deal(3, "2026-09-26", "appt", 5)]                               # appointments alone earn no deal badges
        res = calc.compute(CFG, STORES, ppl, deals, date(2026, 9, 30))
        b = {r["id"]: r["badges"] for r in res["leaderboards"]["new"]}
        self.assertEqual(set(b[1]), {"hat_trick", "heavy_hitter", "on_fire", "double_down", "opening_day"})
        self.assertIn("on_fire", b[2])
        self.assertEqual(b[3], [])
        streak = {r["id"]: r["streak"] for r in res["leaderboards"]["new"]}
        self.assertEqual(streak[2], 3)

    def test_before_contest_starts(self):
        res = calc.compute(CFG, STORES, roster(), [], date(2026, 9, 25))
        self.assertEqual(res["status"], "upcoming")
        self.assertEqual(res["days_left"], 5)
        self.assertEqual(res["payouts"]["upcoming"], 250)
        self.assertEqual(res["trend"]["dates"], [])
        self.assertEqual(res["payouts"]["lines"], [])          # nothing projected before kickoff
        self.assertEqual(res["payouts"]["up_for_grabs"], 3000)
        self.assertEqual(res["appt_window"]["status"], "upcoming")


if __name__ == "__main__":
    unittest.main()
