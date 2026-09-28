"""Admin daily-control tests (single store, Chrysler Muskegon): entry/edit/delete on any contest day, and mid-contest setting changes
(targets, rosters, prizes, dates, names/colors, badge thresholds) recalculating the leaderboard immediately + audit log."""
import os, subprocess, sys, tempfile, time, unittest, urllib.request
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_api import Client, free_port, ROOT  # noqa: E402


class AdminControlTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.port = free_port()
        env = {**os.environ, "PORT": str(cls.port), "DB_PATH": os.path.join(cls.tmp, "a.db"), "SEED_DEMO": "0",
               "ADMIN_PIN": "8642", "STORE_PIN_1": "1357", "QUIET": "1"}
        env.pop("VIEW_PIN", None)
        cls.proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "server.py")], env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.base = f"http://127.0.0.1:{cls.port}"
        for _ in range(50):
            try:
                urllib.request.urlopen(cls.base + "/healthz")
                break
            except Exception:
                time.sleep(0.1)
        t = date.today()
        cls.start, cls.end = (t - timedelta(days=12)).isoformat(), (t + timedelta(days=18)).isoformat()
        cls.day1 = cls.start                                    # oldest contest day (a "past day")
        cls.yday = (t - timedelta(days=1)).isoformat()
        cls.admin = Client(cls.base)
        assert cls.admin.login("8642")[0] == 200
        assert cls.admin.req("PUT", "/api/admin/settings", {"start_date": cls.start, "end_date": cls.end})[0] == 200
        _, a = cls.admin.req("GET", "/api/admin")
        cls.reps = {sid: [p["id"] for p in a["people"] if p["store_id"] == sid] for sid in (1,)}

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(5)

    def state(self):
        return self.admin.req("GET", "/api/state")[1]["result"]

    def store(self, res, sid):
        return next(s for s in res["stores"] if s["id"] == sid)

    def audit(self):
        return self.admin.req("GET", "/api/admin")[1]["audit"]

    # ------------------------------------------------------------------ entry on any day
    def test_01_admin_grid_and_past_day_entry(self):
        st, r = self.admin.req("GET", f"/api/entry/all?date={self.day1}")
        self.assertEqual(st, 200)
        self.assertEqual([sec["store"]["name"] for sec in r["sections"]], ["Chrysler Muskegon"])
        self.assertEqual([g["name"] for g in r["sections"][0]["grid"]], ["Monty", "Nathan", "Adrian", "Sierra", "Jacob", "Raheem"])
        self.assertTrue(all(x["rows"] == 0 for x in r["day_status"]))
        # admin enters a past day
        st, _ = self.admin.req("POST", "/api/entry/1/grid", {"date": self.day1, "rows": [
            {"sp_id": self.reps[1][0], "new": 3, "used": [{"gross": 2500}]}, {"sp_id": self.reps[1][3], "new": 1.5, "used": [{"gross": 4100}]}]})
        self.assertEqual(st, 200)
        _, r = self.admin.req("GET", f"/api/entry/all?date={self.day1}")
        self.assertEqual({x["store_id"]: x["rows"] for x in r["day_status"]}, {1: 4})
        res = self.state()
        self.assertEqual(self.store(res, 1)["new"], 4.5)
        self.assertEqual(self.store(res, 1)["gross"], 6600)
        # the store manager can't use the admin all-stores view, but can use their own store
        m1 = Client(self.base)
        m1.login("1357")
        self.assertEqual(m1.req("GET", "/api/entry/all")[0], 403)
        self.assertEqual(m1.req("POST", "/api/entry/2/grid", {"date": self.yday, "rows": []})[0], 403)
        self.assertEqual(m1.req("GET", "/api/entry/1")[0], 200)

    def test_02_admin_edits_and_deletes_entries(self):
        m1 = Client(self.base)
        m1.login("1357")
        st, r = m1.req("POST", "/api/entry/1/deal", {"sp_id": self.reps[1][2], "date": self.yday, "kind": "used", "gross": 1800})
        self.assertEqual(st, 200)
        did = r["id"]
        # admin corrects the manager's entry, moving it to a past day and to another rep
        st, _ = self.admin.req("PUT", f"/api/deals/{did}", {"sp_id": self.reps[1][4], "date": self.day1, "kind": "used", "gross": 2200})
        self.assertEqual(st, 200)
        _, e = self.admin.req("GET", f"/api/entry/1?date={self.day1}")
        d = next(x for x in e["recent"] if x["id"] == did)
        self.assertEqual((d["store_id"], d["sp_id"], d["gross"], d["date"]), (1, self.reps[1][4], 2200, self.day1))
        # a rep that isn't on the roster is rejected
        self.assertEqual(m1.req("PUT", f"/api/deals/{did}", {"sp_id": 9999, "date": self.day1, "kind": "used", "gross": 1})[0], 400)
        before = self.store(self.state(), 1)["gross"]
        self.assertEqual(self.admin.req("DELETE", f"/api/deals/{did}")[0], 200)
        self.assertEqual(self.store(self.state(), 1)["gross"], before - 2200)
        acts = [a["action"] for a in self.audit()]
        for a in ("deal-add", "deal-edit", "deal-delete", "grid-save"):
            self.assertIn(a, acts)
        edit = next(a for a in self.audit() if a["action"] == "deal-edit")
        self.assertIn("->", edit["detail"])

    # ------------------------------------------------------------------ mid-contest settings
    def test_03_mid_contest_target_change_recalculates(self):
        self.admin.req("POST", "/api/entry/1/grid", {"date": self.yday, "rows": [{"sp_id": self.reps[1][1], "new": 5, "used": [{"gross": 3000}]}]})
        res = self.state()
        s1 = self.store(res, 1)
        base_new, base_gross = s1["new"], s1["gross"]
        self.assertAlmostEqual(s1["new_pct"], round(base_new / 70 * 100, 2))
        # halve store 1's new target and raise its used target, mid-contest
        st, _ = self.admin.req("PUT", "/api/admin/stores/1", {"name": "Chrysler Muskegon", "short": "CJDR Muskegon", "color": "#e11d48",
                                                              "new_target": 35, "used_target": 150000, "contribution": 3000})
        self.assertEqual(st, 200)
        s1b = self.store(self.state(), 1)
        self.assertAlmostEqual(s1b["new_pct"], round(base_new / 35 * 100, 2))
        self.assertAlmostEqual(s1b["used_pct"], round(base_gross / 150000 * 100, 2))
        self.assertAlmostEqual(s1b["score"], round((base_new / 35 + base_gross / 150000 + 0 / 60) / 3 * 100, 2), places=1)   # equal thirds
        self.assertEqual(s1b["new_target"], 35)
        # trend chart uses the new targets for the whole history (derived, not stored)
        t = self.state()["trend"]
        self.assertAlmostEqual(t["stores"]["1"][-1] if "1" in t["stores"] else t["stores"][1][-1], s1b["score"], places=1)
        log = next(a for a in self.audit() if a["action"] == "store-edit")
        self.assertIn("new_target: 70.0 -> 35.0", log["detail"])
        self.assertEqual(self.state()["payouts"]["pool"], 3000)

    def test_04_roster_rename_deactivate_keeps_history(self):
        rep = self.reps[1][0]  # has entries from test_01
        self.admin.req("PUT", f"/api/admin/people/{rep}", {"name": "Dana Demo"})
        res = self.state()
        self.assertIn("Dana Demo", [r["name"] for r in res["leaderboards"]["new"]])
        store_new = self.store(res, 1)["new"]
        self.admin.req("PUT", f"/api/admin/people/{rep}", {"active": False})
        res = self.state()
        self.assertNotIn(rep, [r["id"] for r in res["leaderboards"]["new"]])       # off individual boards
        self.assertEqual(self.store(res, 1)["new"], store_new)                      # history still counts for the store
        self.assertEqual(self.admin.req("DELETE", f"/api/admin/people/{rep}")[0], 400)  # can't delete a rep with entries
        _, e = self.admin.req("GET", f"/api/entry/1?date={self.day1}")
        self.assertIn(rep, [r["sp_id"] for r in e["grid"]])                           # still correctable on days they sold
        self.admin.req("PUT", f"/api/admin/people/{rep}", {"active": True})
        self.assertIn(rep, [r["id"] for r in self.state()["leaderboards"]["new"]])
        st, r = self.admin.req("POST", "/api/admin/people", {"store_id": 1, "name": "Mid-Month Hire"})
        self.assertEqual(st, 200)
        self.assertIn("Mid-Month Hire", [r["name"] for r in self.state()["leaderboards"]["new"]])

    def test_05_prizes_dates_names_badges_recalculate(self):
        res = self.state()
        top = res["leaderboards"]["new"][0]["id"]
        # prize amounts
        self.admin.req("PUT", "/api/admin/settings", {"prizes": {"new": [500, 50, 25], "hot_shot": 25, "appt": [300, 125, 0],
                                                                 "points": [800, 300, 75]}})
        res = self.state()
        line = next(l for l in res["payouts"]["lines"] if l["cat"] == "new" and l["person_id"] == top)
        self.assertEqual(line["amount"], 500)
        self.assertEqual(res["payouts"]["budget"]["new"], 575)
        self.assertEqual(res["payouts"]["budget"]["appt"], 425)
        self.assertEqual(res["payouts"]["budget"]["points"], 1175)
        self.assertEqual(res["payouts"]["budget"]["hot_shot"], 25 * len(res["periods"]))
        # dates + bounty length
        new_end = (date.fromisoformat(self.end) + timedelta(days=5)).isoformat()
        st, r = self.admin.req("PUT", "/api/admin/settings", {"end_date": new_end, "bounty_days": 10})
        self.assertEqual(st, 200)
        res = self.state()
        self.assertEqual(res["total_days"], (date.fromisoformat(new_end) - date.fromisoformat(self.start)).days + 1)
        self.assertTrue(all(p["days"] <= 10 for p in res["periods"]))
        self.assertEqual(res["periods"][0]["days"], 10)
        # store name / color
        self.admin.req("PUT", "/api/admin/stores/1", {"name": "Chrysler Muskegon CDJR", "short": "CJDR Muskegon", "color": "#0ea5e9",
                                                      "new_target": 70, "used_target": 140000, "contribution": 3000})
        s1 = self.store(self.state(), 1)
        self.assertEqual((s1["name"], s1["color"]), ("Chrysler Muskegon CDJR", "#0ea5e9"))
        # badge thresholds
        self.admin.req("POST", "/api/entry/1/grid", {"date": self.day1, "rows": [{"sp_id": self.reps[1][5], "new": 2, "used": []}]})
        badges = lambda: next(r for r in self.state()["leaderboards"]["new"] if r["id"] == self.reps[1][5])["badges"]
        self.assertNotIn("hat_trick", badges())
        self.admin.req("PUT", "/api/admin/settings", {"hat_trick_units": 2})
        self.assertIn("hat_trick", badges())
        self.assertIn("2+ new units", self.state()["badges"]["hat_trick"]["desc"])
        # bad values rejected
        self.assertEqual(self.admin.req("PUT", "/api/admin/settings", {"timezone": "Mars/Base"})[0], 400)
        self.assertEqual(self.admin.req("PUT", "/api/admin/settings", {"end_date": "2000-01-01"})[0], 400)
        details = " ".join(a["detail"] for a in self.audit() if a["action"] == "settings")
        for key in ("prizes", "end_date", "bounty_days", "hat_trick_units"):
            self.assertIn(key, details)

    def test_06_shrinking_dates_warns_and_keeps_entries(self):
        new_start = (date.fromisoformat(self.start) + timedelta(days=1)).isoformat()
        st, r = self.admin.req("PUT", "/api/admin/settings", {"start_date": new_start})
        self.assertEqual(st, 200)
        self.assertGreater(r["entries_outside_dates"], 0)   # day-1 entries now outside -> ignored, not deleted
        st, r = self.admin.req("PUT", "/api/admin/settings", {"start_date": self.start})
        self.assertEqual(r["entries_outside_dates"], 0)


if __name__ == "__main__":
    unittest.main()
