"""Admin daily-control tests: cross-store entry/edit/delete on any contest day, and mid-contest setting changes
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
               "ADMIN_PIN": "8642", "STORE_PIN_1": "1357", "STORE_PIN_2": "2468", "STORE_PIN_3": "3579", "QUIET": "1"}
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
        cls.reps = {sid: [p["id"] for p in a["people"] if p["store_id"] == sid] for sid in (1, 2, 3)}

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

    # ------------------------------------------------------------------ cross-store entry
    def test_01_all_stores_grid_and_past_day_entry(self):
        st, r = self.admin.req("GET", f"/api/entry/all?date={self.day1}")
        self.assertEqual(st, 200)
        self.assertEqual([sec["store"]["id"] for sec in r["sections"]], [1, 2, 3])
        self.assertEqual(sum(len(sec["grid"]) for sec in r["sections"]), 21)
        self.assertTrue(all(x["rows"] == 0 for x in r["day_status"]))
        # admin enters a past day for two different stores
        for sid, new, gross in ((2, 3, 2500), (3, 1.5, 4100)):
            st, _ = self.admin.req("POST", f"/api/entry/{sid}/grid", {"date": self.day1, "rows": [
                {"sp_id": self.reps[sid][0], "new": new, "used": [{"gross": gross}]}]})
            self.assertEqual(st, 200)
        _, r = self.admin.req("GET", f"/api/entry/all?date={self.day1}")
        status = {x["store_id"]: x["rows"] for x in r["day_status"]}
        self.assertEqual(status, {1: 0, 2: 2, 3: 2})
        res = self.state()
        self.assertEqual(self.store(res, 2)["new"], 3)
        self.assertEqual(self.store(res, 3)["gross"], 4100)
        # the manager of store 1 can't use the all-stores view or write to store 2
        m1 = Client(self.base)
        m1.login("1357")
        self.assertEqual(m1.req("GET", "/api/entry/all")[0], 403)
        self.assertEqual(m1.req("POST", "/api/entry/2/grid", {"date": self.yday, "rows": []})[0], 403)
        self.assertEqual(m1.req("GET", "/api/entry/1")[0], 200)

    def test_02_admin_edits_and_deletes_any_stores_entries(self):
        m1 = Client(self.base)
        m1.login("1357")
        st, r = m1.req("POST", "/api/entry/1/deal", {"sp_id": self.reps[1][2], "date": self.yday, "kind": "used", "gross": 1800})
        self.assertEqual(st, 200)
        did = r["id"]
        # admin corrects the manager's entry, moving it to a past day
        st, _ = self.admin.req("PUT", f"/api/deals/{did}", {"sp_id": self.reps[1][2], "date": self.day1, "kind": "used", "gross": 2200})
        self.assertEqual(st, 200)
        # admin re-assigns it to a rep at another store (wrong store picked by mistake)
        st, _ = self.admin.req("PUT", f"/api/deals/{did}", {"sp_id": self.reps[3][4], "date": self.day1, "kind": "used", "gross": 2200})
        self.assertEqual(st, 200)
        _, e = self.admin.req("GET", f"/api/entry/3?date={self.day1}")
        d = next(x for x in e["recent"] if x["id"] == did)
        self.assertEqual((d["store_id"], d["sp_id"], d["gross"], d["date"]), (3, self.reps[3][4], 2200, self.day1))
        # store 1's manager can no longer touch it; store managers can't re-assign across stores
        self.assertEqual(m1.req("DELETE", f"/api/deals/{did}")[0], 403)
        m3 = Client(self.base)
        m3.login("3579")
        self.assertEqual(m3.req("PUT", f"/api/deals/{did}", {"sp_id": self.reps[1][0], "date": self.day1, "kind": "used", "gross": 1})[0], 400)
        before = self.store(self.state(), 3)["gross"]
        self.assertEqual(self.admin.req("DELETE", f"/api/deals/{did}")[0], 200)
        self.assertEqual(self.store(self.state(), 3)["gross"], before - 2200)
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
        self.assertAlmostEqual(s1["new_pct"], round(5 / 70 * 100, 2))
        # halve store 1's new target and raise its used target, mid-contest
        st, _ = self.admin.req("PUT", "/api/admin/stores/1", {"name": "Chrysler Muskegon", "short": "CJDR Muskegon", "color": "#e11d48",
                                                              "new_target": 35, "used_target": 150000, "contribution": 3500})
        self.assertEqual(st, 200)
        s1b = self.store(self.state(), 1)
        self.assertAlmostEqual(s1b["new_pct"], round(5 / 35 * 100, 2))
        self.assertAlmostEqual(s1b["used_pct"], round(3000 / 150000 * 100, 2))
        self.assertAlmostEqual(s1b["score"], round((5 / 35 * 0.5 + 3000 / 150000 * 0.5) * 100, 2))
        self.assertEqual(s1b["new_target"], 35)
        # trend chart uses the new targets for the whole history (derived, not stored)
        t = self.state()["trend"]
        self.assertAlmostEqual(t["stores"]["1"][-1] if "1" in t["stores"] else t["stores"][1][-1], s1b["score"], places=1)
        log = next(a for a in self.audit() if a["action"] == "store-edit")
        self.assertIn("new_target: 70.0 -> 35.0", log["detail"])
        # the store battle ranking follows the new score
        order = [s["id"] for s in self.state()["stores"]]
        self.assertEqual(order[0], max(self.state()["stores"], key=lambda s: s["score"])["id"])

    def test_04_roster_rename_deactivate_keeps_history(self):
        rep = self.reps[2][0]  # has entries from test_01
        self.admin.req("PUT", f"/api/admin/people/{rep}", {"name": "Dana Demo"})
        res = self.state()
        self.assertIn("Dana Demo", [r["name"] for r in res["leaderboards"]["new"]])
        store_new = self.store(res, 2)["new"]
        self.admin.req("PUT", f"/api/admin/people/{rep}", {"active": False})
        res = self.state()
        self.assertNotIn(rep, [r["id"] for r in res["leaderboards"]["new"]])       # off individual boards
        self.assertEqual(self.store(res, 2)["new"], store_new)                      # history still counts for the store
        self.assertEqual(self.admin.req("DELETE", f"/api/admin/people/{rep}")[0], 400)  # can't delete a rep with entries
        _, e = self.admin.req("GET", f"/api/entry/2?date={self.day1}")
        self.assertIn(rep, [r["sp_id"] for r in e["grid"]])                           # still correctable on days they sold
        self.admin.req("PUT", f"/api/admin/people/{rep}", {"active": True})
        self.assertIn(rep, [r["id"] for r in self.state()["leaderboards"]["new"]])
        st, r = self.admin.req("POST", "/api/admin/people", {"store_id": 2, "name": "Mid-Month Hire"})
        self.assertEqual(st, 200)
        self.assertIn("Mid-Month Hire", [r["name"] for r in self.state()["leaderboards"]["new"]])

    def test_05_prizes_dates_names_badges_recalculate(self):
        res = self.state()
        top = res["leaderboards"]["new"][0]["id"]
        # prize amounts
        self.admin.req("PUT", "/api/admin/settings", {"prizes": {"new": [1500, 300, 200], "top_gun": 150, "big_fish": 100}})
        res = self.state()
        line = next(l for l in res["payouts"]["lines"] if l["cat"] == "new" and l["person_id"] == top)
        self.assertEqual(line["amount"], 1500)
        self.assertEqual(res["payouts"]["budget"]["new"], 2000)
        # dates + bounty length
        new_end = (date.fromisoformat(self.end) + timedelta(days=5)).isoformat()
        st, r = self.admin.req("PUT", "/api/admin/settings", {"end_date": new_end, "bounty_days": 10})
        self.assertEqual(st, 200)
        res = self.state()
        self.assertEqual(res["total_days"], (date.fromisoformat(new_end) - date.fromisoformat(self.start)).days + 1)
        self.assertTrue(all(p["days"] <= 10 for p in res["periods"]))
        self.assertEqual(res["periods"][0]["days"], 10)
        # store name / color
        self.admin.req("PUT", "/api/admin/stores/3", {"name": "GH Ford Lincoln", "short": "GH Ford", "color": "#0ea5e9",
                                                      "new_target": 65, "used_target": 130000, "contribution": 3500})
        s3 = self.store(self.state(), 3)
        self.assertEqual((s3["name"], s3["color"]), ("GH Ford Lincoln", "#0ea5e9"))
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
