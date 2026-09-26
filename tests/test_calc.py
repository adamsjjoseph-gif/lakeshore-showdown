"""Unit tests for the contest math (leaderboards, store battle, payouts). Run: python3 -m unittest discover tests"""
import os, sys, unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import calc  # noqa: E402

# Sep 26 (Sat) - Sep 30 (Wed) 2026; appointments count Sep 26 - Sep 29
CFG = {"start_date": "2026-09-26", "end_date": "2026-09-30", "appt_start": "2026-09-26", "appt_end": "2026-09-29",
       "weight_new": 1, "weight_used": 1, "weight_appt": 1, "points_new": 2, "points_per_1k": 1, "points_per_appt": 0.5,
       "heavy_hitter": 4000, "qualifier_units": 1, "closed_sundays": True, "bounty_days": 1, "prizes": calc.DEFAULT_PRIZES}
STORES = [
    {"id": 1, "name": "Big Store", "short": "BIG", "color": "#f00", "new_target": 100, "used_target": 200000, "appt_target": 100, "contribution": 3500},
    {"id": 2, "name": "Small Store", "short": "SML", "color": "#0f0", "new_target": 40, "used_target": 80000, "appt_target": 40, "contribution": 3500},
    {"id": 3, "name": "Mid Store", "short": "MID", "color": "#00f", "new_target": 60, "used_target": 120000, "appt_target": 60, "contribution": 3500},
]
DAYS = ["2026-09-26", "2026-09-27", "2026-09-28", "2026-09-29", "2026-09-30"]
AFTER = date(2026, 10, 2)


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
        for total, n in ((250000, 7), (100000, 6), (25000, 3), (1, 2), (15000, 1)):
            parts = calc.split_cents(total, n)
            self.assertEqual(sum(parts), total)
            self.assertLessEqual(max(parts) - min(parts), 1)

    def test_prize_table_totals_exactly_10500(self):
        p = calc.DEFAULT_PRIZES
        self.assertEqual(p["team"][:2], [2500, 1000])
        self.assertEqual(sum(p["team"]), 3500)
        self.assertEqual((sum(p["new"]), sum(p["used"]), sum(p["appt"])), (2000, 2000, 1500))
        self.assertEqual((p["mvp"], p["hot_shot"]), (250, 150))
        periods = calc.contest_periods("2026-09-26", "2026-09-30", 1)
        self.assertEqual(len(periods), 5)                               # 5 Daily Hot Shot days
        b = calc.prize_budget(p, 3, len(periods))
        self.assertEqual(b, {"team": 350000, "new": 200000, "used": 200000, "appt": 150000, "mvp": 75000,
                             "hot_shot": 75000, "total": 1050000})
        self.assertEqual(b["total"], calc.POOL_TOTAL * 100)
        self.assertEqual(calc.POOL_TOTAL, 3 * 3500)

    def test_ended_contest_pays_out_exactly_the_pool(self):
        ppl = roster()
        deals = []
        for sp in range(1, 22):
            for d in DAYS:
                deals.append(deal(sp, d, "new", 1 + (sp % 3) * 0.5))
                deals.append(deal(sp, d, "used", 1, 1000 + sp * 37))
                deals.append(deal(sp, d, "appt", 1 + sp % 4))
        res = calc.compute(CFG, STORES, ppl, deals, AFTER)
        self.assertEqual(res["status"], "ended")
        self.assertTrue(res["payouts"]["budget_ok"])
        self.assertEqual(total_cents(res), 1050000)
        self.assertEqual(res["payouts"]["upcoming"], 0)
        self.assertEqual(len([l for l in res["payouts"]["lines"] if l["cat"] == "hot_shot"]), 5)

    def test_unclaimed_prizes_roll_into_first_place_team_pot(self):
        ppl = roster()
        # only one rep sells, only new cars, only on day 1 -> lots unclaimed
        deals = [deal(8, "2026-09-26", "new", 2)]
        res = calc.compute(CFG, STORES, ppl, deals, AFTER)
        self.assertEqual(total_cents(res), 1050000)        # still exactly the pool
        self.assertGreater(res["payouts"]["rollover"], 0)
        team = [l for l in res["payouts"]["lines"] if l["cat"] == "team" and l["person_id"] == 8]
        # rep 8 is the only qualifier anywhere, so they get 1st + 2nd team pots + everything unclaimed
        self.assertEqual(round(team[0]["amount"] * 100), 250000 + 100000 + round(res["payouts"]["rollover"] * 100))
        self.assertFalse([l for l in res["payouts"]["lines"] if l["status"] == "unclaimed"])


class TestStoreBattle(unittest.TestCase):
    def test_small_store_can_beat_big_store_on_percent_of_target(self):
        ppl = roster()
        deals = [deal(1, "2026-09-28", "new", 50), deal(1, "2026-09-28", "used", 1, 100000), deal(1, "2026-09-28", "appt", 50),  # 50/50/50
                 deal(8, "2026-09-28", "new", 30), deal(8, "2026-09-28", "used", 1, 60000), deal(8, "2026-09-28", "appt", 30)]    # 75/75/75
        res = calc.compute(CFG, STORES, ppl, deals, date(2026, 9, 29))
        order = [s["short"] for s in res["stores"]]
        self.assertEqual(order[0], "SML")
        self.assertAlmostEqual(res["stores"][0]["score"], 75.0)
        self.assertAlmostEqual(res["stores"][1]["score"], 50.0)

    def test_appointments_are_an_equal_third_of_the_store_score(self):
        ppl = roster()
        deals = [deal(1, "2026-09-26", "new", 30), deal(1, "2026-09-26", "used", 1, 40000), deal(1, "2026-09-26", "appt", 80)]
        res = calc.compute(CFG, STORES, ppl, deals, date(2026, 9, 29))
        big = next(s for s in res["stores"] if s["id"] == 1)
        self.assertEqual((big["new_pct"], big["used_pct"], big["appt_pct"], big["appts"]), (30, 20, 80, 80))
        self.assertAlmostEqual(big["score"], round((30 + 20 + 80) / 3, 2))
        self.assertEqual(res["score_weights"], {"new": 33.33, "used": 33.33, "appt": 33.33})

    def test_appointments_outside_window_do_not_count(self):
        ppl = roster()
        deals = [deal(1, "2026-09-29", "appt", 4), deal(1, "2026-09-30", "appt", 9), deal(1, "2026-09-25", "appt", 9)]
        res = calc.compute(CFG, STORES, ppl, deals, AFTER)
        me = next(r for r in res["leaderboards"]["appt"] if r["id"] == 1)
        self.assertEqual(me["appts"], 4)
        self.assertEqual(next(s for s in res["stores"] if s["id"] == 1)["appts"], 4)
        # the window is a setting: widen it and Sep 30 counts too
        res = calc.compute({**CFG, "appt_end": "2026-09-30"}, STORES, ppl, deals, AFTER)
        self.assertEqual(next(r for r in res["leaderboards"]["appt"] if r["id"] == 1)["appts"], 13)
        self.assertEqual(res["appt_window"]["end"], "2026-09-30")

    def test_legacy_weight_setting_maps_to_equal_thirds(self):
        self.assertEqual([round(x, 6) for x in calc.score_weights({"weight_new": 50})], [round(1 / 3, 6)] * 3)
        wn, wu, wa = calc.score_weights({"weight_new": 2, "weight_used": 1, "weight_appt": 1})
        self.assertAlmostEqual(wn, 0.5)
        self.assertAlmostEqual(wu + wa, 0.5)

    def test_weighting_and_tiebreak_on_new_pct(self):
        ppl = roster()
        # BIG: 60% new, 40% used, 0 appt = 33.3 ; SML: 40% new, 60% used = 33.3 -> tie broken by higher new %
        deals = [deal(1, "2026-09-28", "new", 60), deal(1, "2026-09-28", "used", 1, 80000),
                 deal(8, "2026-09-28", "new", 16), deal(8, "2026-09-28", "used", 1, 48000)]
        res = calc.compute(CFG, STORES, ppl, deals, date(2026, 9, 29))
        self.assertEqual([s["short"] for s in res["stores"]][:2], ["BIG", "SML"])
        self.assertEqual(res["stores"][0]["score"], res["stores"][1]["score"])

    def test_team_pot_split_evenly_among_qualifiers_only(self):
        ppl = roster()
        deals = [deal(sp, "2026-09-26", "new", 5) for sp in range(8, 15)]         # all 7 small-store reps qualify
        deals += [deal(1, "2026-09-26", "new", 0.5)]                               # BIG rep with 0.5 unit: not qualified
        deals += [deal(3, "2026-09-26", "appt", 5)]                                # appointments alone don't qualify
        deals += [deal(2, "2026-09-26", "new", 10)]
        res = calc.compute(CFG, STORES, ppl, deals, AFTER)
        small = next(s for s in res["stores"] if s["short"] == "SML")
        self.assertEqual(small["rank"], 1)
        shares = [round(l["amount"] * 100) for l in res["payouts"]["lines"] if l["cat"] == "team" and l["store_id"] == 2]
        self.assertEqual(len(shares), 7)
        self.assertEqual(sum(shares), 250000 + round(res["payouts"]["rollover"] * 100))
        big_team = [l for l in res["payouts"]["lines"] if l["cat"] == "team" and l["store_id"] == 1]
        self.assertEqual([l["person_id"] for l in big_team], [2])  # only the qualified BIG rep gets 2nd-place money
        self.assertEqual(round(big_team[0]["amount"] * 100), 100000)


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
                 deal(8, "2026-09-26", "new", 5), deal(8, "2026-09-26", "used", 1, 3000),   # wins New Unit King tie-break
                 deal(15, "2026-09-28", "appt", 7), deal(16, "2026-09-28", "appt", 6), deal(16, "2026-09-30", "appt", 5)]
        res = calc.compute(CFG, STORES, ppl, deals, AFTER)
        lines = {(l["cat"], l["person_id"]): l["amount"] for l in res["payouts"]["lines"] if l["cat"] in ("new", "used", "appt")}
        self.assertEqual(lines, {("new", 8): 2000, ("used", 8): 2000, ("appt", 15): 1500})
        ranks = {r["id"]: r["rank"] for r in res["leaderboards"]["new"]}
        self.assertEqual((ranks[8], ranks[1]), (1, 2))

    def test_tie_for_first_splits_the_prize(self):
        ppl = roster()
        deals = [deal(1, "2026-09-26", "appt", 4), deal(8, "2026-09-26", "appt", 4)]
        res = calc.compute(CFG, STORES, ppl, deals, AFTER)
        appt = {l["person_id"]: l for l in res["payouts"]["lines"] if l["cat"] == "appt"}
        self.assertEqual((appt[1]["amount"], appt[8]["amount"]), (750, 750))
        self.assertEqual(appt[1]["label"], "T-1st/2nd")

    def test_unwind_removed_changes_results(self):
        ppl = roster()
        deals = [deal(1, "2026-09-26", "new", 3), deal(8, "2026-09-26", "new", 2)]
        r1 = calc.compute(CFG, STORES, ppl, deals, date(2026, 9, 29))
        self.assertEqual(r1["leaderboards"]["new"][0]["id"], 1)
        r2 = calc.compute(CFG, STORES, ppl, deals[1:], date(2026, 9, 29))
        self.assertEqual(r2["leaderboards"]["new"][0]["id"], 8)

    def test_inactive_rep_counts_for_store_but_not_individual_prizes(self):
        ppl = roster()
        ppl[0]["active"] = 0
        deals = [deal(1, "2026-09-26", "new", 10), deal(1, "2026-09-26", "appt", 9), deal(2, "2026-09-26", "new", 1)]
        res = calc.compute(CFG, STORES, ppl, deals, AFTER)
        s1 = next(s for s in res["stores"] if s["id"] == 1)
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
                 deal(8, "2026-09-26", "used", 1, 2500), deal(8, "2026-09-26", "appt", 4),  # 2.5 + 2 = 4.5 pts -> wins Sat
                 deal(15, "2026-09-28", "new", 1), deal(15, "2026-09-28", "used", 1, 1000),  # Mon: 3 pts
                 deal(16, "2026-09-28", "appt", 6),                                      # Mon: 3 pts, fewer new units -> loses tie-break
                 deal(2, "2026-09-30", "appt", 20), deal(3, "2026-09-30", "new", 0.5)]   # Wed: appts don't count (outside window)
        res = calc.compute(CFG, STORES, ppl, deals, date(2026, 9, 30))
        p = {x["start"]: x for x in res["periods"]}
        self.assertEqual(len(res["periods"]), 5)
        self.assertEqual(p["2026-09-26"]["status"], "won")
        self.assertEqual(p["2026-09-26"]["hot_shot"]["ids"], [8])
        self.assertEqual(p["2026-09-26"]["hot_shot"]["points"], 4.5)
        self.assertIsNone(p["2026-09-27"]["hot_shot"])                  # closed Sunday: nobody -> rolls into team pot
        self.assertEqual(p["2026-09-28"]["hot_shot"]["ids"], [15])
        self.assertEqual(p["2026-09-30"]["status"], "live")
        self.assertEqual(p["2026-09-30"]["hot_shot"]["ids"], [3])
        hs = [l for l in res["payouts"]["lines"] if l["cat"] == "hot_shot"]
        self.assertEqual(sorted((l["person_id"], l["amount"], l["status"]) for l in hs),
                         [(3, 150, "leading"), (8, 150, "won"), (15, 150, "won")])
        self.assertIn({"cat": "hot_shot", "cents": 15000, "period": 2}, res["payouts"]["unclaimed"])

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
        self.assertEqual(res["payouts"]["upcoming"], 750)
        self.assertEqual(res["trend"]["dates"], [])
        self.assertEqual(res["payouts"]["lines"], [])          # nothing projected before kickoff
        self.assertEqual(res["payouts"]["up_for_grabs"], 10500)
        self.assertEqual(res["appt_window"]["status"], "upcoming")


if __name__ == "__main__":
    unittest.main()
