"""End-to-end API tests: starts a real server on a temp database. Run: python3 -m unittest discover tests"""
import csv, io, json, os, socket, subprocess, sys, tempfile, time, unittest, urllib.request, urllib.error
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Client:
    def __init__(self, base):
        self.base, self.cookie = base, None

    def req(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            r.add_header("Content-Type", "application/json")
        if self.cookie:
            r.add_header("Cookie", self.cookie)
        try:
            with urllib.request.urlopen(r) as resp:
                sc = resp.headers.get("Set-Cookie")
                if sc:
                    self.cookie = sc.split(";")[0]
                raw = resp.read()
                ctype = resp.headers.get("Content-Type", "")
                return resp.status, (json.loads(raw) if "json" in ctype else raw.decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def login(self, pin):
        return self.req("POST", "/api/login", {"pin": pin})


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.port = free_port()
        env = {**os.environ, "PORT": str(cls.port), "DB_PATH": os.path.join(cls.tmp, "t.db"), "SEED_DEMO": "0",
               "ADMIN_PIN": "8642", "STORE_PIN_1": "1357", "STORE_PIN_2": "2468", "STORE_PIN_3": "3579", "QUIET": "1"}
        env.pop("VIEW_PIN", None)
        cls.proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "server.py")], env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        cls.base = f"http://127.0.0.1:{cls.port}"
        for _ in range(50):
            try:
                urllib.request.urlopen(cls.base + "/api/me")
                break
            except Exception:
                time.sleep(0.1)
        # put "today" inside the contest so entries are allowed
        cls.today = date.today()
        cls.start = (cls.today - timedelta(days=10)).isoformat()
        cls.end = (cls.today + timedelta(days=20)).isoformat()
        cls.yday = (cls.today - timedelta(days=1)).isoformat()
        a = Client(cls.base)
        assert a.login("8642")[0] == 200
        _, cls.fresh = a.req("GET", "/api/admin")          # untouched first-run settings (defaults)
        st, _ = a.req("PUT", "/api/admin/settings", {"start_date": cls.start, "end_date": cls.end,
                                                     "appt_start": cls.start, "appt_end": cls.yday})
        assert st == 200, st

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(5)

    def admin(self):
        c = Client(self.base)
        self.assertEqual(c.login("8642")[0], 200)
        return c

    def store(self, n):
        c = Client(self.base)
        st, r = c.login({1: "1357", 2: "2468", 3: "3579"}[n])
        self.assertEqual(st, 200)
        self.assertEqual(r["role"], "store")
        return c

    def roster(self, store_id):
        st, r = self.admin().req("GET", "/api/admin")
        return [p["id"] for p in r["people"] if p["store_id"] == store_id]

    # ---------------------------------------------------------------- tests
    def test_01_public_board_open_and_entry_locked(self):
        c = Client(self.base)
        st, r = c.req("GET", "/api/state")
        self.assertEqual(st, 200)
        self.assertEqual(r["result"]["payouts"]["pool"], 10500)
        self.assertEqual(c.req("GET", "/api/entry/1")[0], 401)
        self.assertEqual(c.req("POST", "/api/entry/1/grid", {"date": self.yday, "rows": []})[0], 401)
        self.assertEqual(c.req("GET", "/api/admin")[0], 401)
        self.assertEqual(c.login("0000")[0], 401)

    def test_02_store_cannot_touch_other_store_or_admin(self):
        c = self.store(1)
        self.assertEqual(c.req("GET", "/api/entry/2")[0], 403)
        self.assertEqual(c.req("GET", "/api/admin")[0], 403)
        self.assertEqual(c.req("POST", "/api/admin/reset", {"confirm": "RESET"})[0], 403)

    def test_03_grid_entry_edit_and_leaderboard(self):
        c = self.store(1)
        ids = self.roster(1)
        st, r = c.req("GET", "/api/entry/1")
        self.assertEqual(st, 200)
        self.assertEqual(len(r["grid"]), 7)
        rows = [{"sp_id": ids[0], "new": 2, "used": [{"gross": 2500}, {"gross": 1200, "split": True}]},
                {"sp_id": ids[1], "new": 0.5, "used": []}]
        st, r = c.req("POST", "/api/entry/1/grid", {"date": self.yday, "rows": rows})
        self.assertEqual(st, 200, r)
        self.assertEqual(r["rows_saved"], 4)
        st, s = c.req("GET", "/api/state")
        store1 = next(x for x in s["result"]["stores"] if x["id"] == 1)
        self.assertEqual(store1["new"], 2.5)
        self.assertEqual(store1["used_units"], 1.5)
        self.assertEqual(store1["gross"], 3700)
        top = s["result"]["leaderboards"]["new"][0]
        self.assertEqual((top["id"], top["new"]), (ids[0], 2))
        # correction: re-save the day for rep 0 -> replaces, doesn't duplicate
        st, r = c.req("POST", "/api/entry/1/grid", {"date": self.yday, "rows": [{"sp_id": ids[0], "new": 1, "used": [{"gross": 2600}]}]})
        self.assertEqual(st, 200)
        g = {x["sp_id"]: x for x in r["grid"]}
        self.assertEqual(g[ids[0]]["new"], 1)
        self.assertEqual([u["gross"] for u in g[ids[0]]["used"]], [2600])
        self.assertEqual(g[ids[1]]["new"], 0.5)  # untouched row preserved

    def test_04_single_entry_add_edit_delete(self):
        c = self.store(2)
        ids = self.roster(2)
        st, r = c.req("POST", "/api/entry/2/deal", {"sp_id": ids[3], "date": self.yday, "kind": "used", "gross": 3100})
        self.assertEqual(st, 200)
        did = r["id"]
        st, _ = c.req("PUT", f"/api/deals/{did}", {"sp_id": ids[3], "date": self.yday, "kind": "used", "gross": 3300, "split": True})
        self.assertEqual(st, 200)
        _, e = c.req("GET", f"/api/entry/2?date={self.yday}")
        d = next(x for x in e["recent"] if x["id"] == did)
        self.assertEqual((d["gross"], d["units"]), (3300, 0.5))
        # another store can't edit or delete it
        self.assertEqual(self.store(3).req("DELETE", f"/api/deals/{did}")[0], 403)
        # unwind -> delete
        self.assertEqual(c.req("DELETE", f"/api/deals/{did}")[0], 200)
        _, e = c.req("GET", f"/api/entry/2?date={self.yday}")
        self.assertFalse([x for x in e["recent"] if x["id"] == did])

    def test_05_validation(self):
        c = self.store(3)
        ids = self.roster(3)
        other = self.roster(1)[0]
        bad = [
            {"date": self.yday, "rows": [{"sp_id": ids[0], "new": 0.3}]},                       # not a half step
            {"date": (self.today + timedelta(days=1)).isoformat(), "rows": [{"sp_id": ids[0], "new": 1}]},  # future
            {"date": "2020-01-01", "rows": [{"sp_id": ids[0], "new": 1}]},                      # outside contest
            {"date": self.yday, "rows": [{"sp_id": other, "new": 1}]},                          # other store's rep
            {"date": self.yday, "rows": [{"sp_id": ids[0], "new": 1, "used": [{"gross": "abc"}]}]},
        ]
        for b in bad:
            st, r = c.req("POST", "/api/entry/3/grid", b)
            self.assertEqual(st, 400, (b, r))

    def test_06_admin_roster_pins_export_reset(self):
        a = self.admin()
        st, r = a.req("POST", "/api/admin/people", {"store_id": 3, "name": "New Hire"})
        self.assertEqual(st, 200)
        pid = r["id"]
        self.assertEqual(a.req("PUT", f"/api/admin/people/{pid}", {"name": "Jane Closer"})[0], 200)
        self.assertEqual(a.req("PUT", f"/api/admin/people/{pid}", {"active": False})[0], 200)
        _, adm = a.req("GET", "/api/admin")
        p = next(x for x in adm["people"] if x["id"] == pid)
        self.assertEqual((p["name"], p["active"]), ("Jane Closer", 0))
        self.assertEqual(a.req("DELETE", f"/api/admin/people/{pid}")[0], 200)
        # PINs: must be unique and 4-8 digits; stored hashed
        self.assertEqual(a.req("POST", "/api/admin/pin", {"which": "store", "store_id": 3, "pin": "1357"})[0], 400)
        self.assertEqual(a.req("POST", "/api/admin/pin", {"which": "store", "store_id": 3, "pin": "12"})[0], 400)
        self.assertEqual(a.req("POST", "/api/admin/pin", {"which": "store", "store_id": 3, "pin": "3580"})[0], 200)
        self.assertEqual(Client(self.base).login("3579")[0], 401)
        self.assertEqual(Client(self.base).login("3580")[0], 200)
        import sqlite3
        con = sqlite3.connect(os.path.join(self.tmp, "t.db"))
        h = con.execute("SELECT pin_hash FROM stores WHERE id=3").fetchone()[0]
        self.assertTrue(h.startswith("pbkdf2$") and "3580" not in h)
        # CSV export
        st, text = a.req("GET", "/api/admin/export/deals.csv")
        self.assertEqual(st, 200)
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(rows[0][:4], ["id", "date", "store", "salesperson"])
        self.assertGreater(len(rows), 1)
        for what in ("standings", "individuals", "payouts", "roster"):
            self.assertEqual(a.req("GET", f"/api/admin/export/{what}.csv")[0], 200)
        # view PIN locks the board
        self.assertEqual(a.req("POST", "/api/admin/pin", {"which": "view", "pin": "5555"})[0], 200)
        self.assertEqual(Client(self.base).req("GET", "/api/state")[0], 401)
        v = Client(self.base)
        self.assertEqual(v.login("5555")[1]["role"], "view")
        self.assertEqual(v.req("GET", "/api/state")[0], 200)
        self.assertIn(v.req("GET", "/api/entry/1")[0], (401, 403))
        self.assertEqual(a.req("POST", "/api/admin/pin", {"which": "view", "pin": ""})[0], 200)
        self.assertEqual(Client(self.base).req("GET", "/api/state")[0], 200)
        # reset needs confirmation, then empties everything
        self.assertEqual(a.req("POST", "/api/admin/reset", {})[0], 400)
        st, r = a.req("POST", "/api/admin/reset", {"confirm": "RESET"})
        self.assertEqual(st, 200)
        _, adm = a.req("GET", "/api/admin")
        self.assertEqual(adm["deal_count"], 0)

    def test_07_budget_check_follows_settings(self):
        a = self.admin()
        _, adm = a.req("GET", "/api/admin")
        n = adm["periods"]
        # make the daily Hot Shot fill the rest of the pool exactly: 10500 - 3500 - 2000 - 2000 - 1500 - 750 = 750 over n days
        st, _ = a.req("PUT", "/api/admin/settings", {"prizes": {"hot_shot": 750 / n}})
        self.assertEqual(st, 200)
        _, adm = a.req("GET", "/api/admin")
        self.assertAlmostEqual(adm["budget"]["total"], 10500, places=0)
        self.assertEqual(adm["settings"]["prizes"]["appt"], [1500, 0, 0])
        # put it back to the real $150/day
        self.assertEqual(a.req("PUT", "/api/admin/settings", {"prizes": {"hot_shot": 150}})[0], 200)

    def test_00_fresh_defaults_are_the_5_day_contest(self):
        s = self.fresh["settings"]
        self.assertEqual((s["start_date"], s["end_date"]), ("2026-09-26", "2026-09-30"))
        self.assertEqual((s["appt_start"], s["appt_end"]), ("2026-09-26", "2026-09-29"))
        self.assertEqual(s["prizes"], {"team": [2500, 1000, 0], "new": [2000, 0, 0], "used": [2000, 0, 0],
                                       "appt": [1500, 0, 0], "mvp": 250, "hot_shot": 150})
        self.assertEqual(self.fresh["periods"], 5)
        self.assertTrue(self.fresh["budget_ok"])
        self.assertEqual(self.fresh["budget"]["total"], 10500)
        self.assertEqual(self.fresh["pool"], 10500)
        self.assertEqual([st["appt_target"] for st in self.fresh["stores"]], [60, 48, 56])
        self.assertEqual([(st["new_target"], st["used_target"]) for st in self.fresh["stores"]],
                         [(70, 140000), (55, 110000), (65, 130000)])
        self.assertIn("db_dir_is_mount", self.fresh["storage"])
        # countdown target: Sep 30 2026 11:59:59 PM Eastern (EDT = UTC-4) -> Oct 1 03:59:59 UTC
        _, st = Client(self.base).req("GET", "/api/state")
        self.assertIn("end_ts", st["settings"])

    def test_04b_appointments_entry_leaderboard_and_edit(self):
        c = self.store(2)
        ids = self.roster(2)
        rows = [{"sp_id": ids[0], "new": 1, "appt": 4, "used": []}, {"sp_id": ids[1], "new": 0, "appt": 2, "used": [{"gross": 1500}]}]
        st, r = c.req("POST", "/api/entry/2/grid", {"date": self.yday, "rows": rows})
        self.assertEqual(st, 200, r)
        g = {x["sp_id"]: x for x in r["grid"]}
        self.assertEqual((g[ids[0]]["appt"], g[ids[1]]["appt"]), (4, 2))
        _, s = c.req("GET", "/api/state")
        store2 = next(x for x in s["result"]["stores"] if x["id"] == 2)
        self.assertEqual(store2["appts"], 6)
        self.assertAlmostEqual(store2["appt_pct"], round(6 / 48 * 100, 2))
        top = s["result"]["leaderboards"]["appt"][0]
        self.assertEqual((top["id"], top["appts"]), (ids[0], 4))
        # a row saved without an "appt" key (older page) keeps that day's appointments
        st, r = c.req("POST", "/api/entry/2/grid", {"date": self.yday, "rows": [{"sp_id": ids[0], "new": 2, "used": []}]})
        self.assertEqual({x["sp_id"]: x for x in r["grid"]}[ids[0]]["appt"], 4)
        # appointments must be whole numbers
        self.assertEqual(c.req("POST", "/api/entry/2/grid", {"date": self.yday, "rows": [{"sp_id": ids[0], "appt": 1.5}]})[0], 400)
        self.assertEqual(c.req("POST", "/api/entry/2/grid", {"date": self.yday, "rows": [{"sp_id": ids[0], "appt": -1}]})[0], 400)
        # single entry + admin edit/delete of an appointment row
        st, r = c.req("POST", "/api/entry/2/deal", {"sp_id": ids[2], "date": self.yday, "kind": "appt", "units": 3})
        self.assertEqual(st, 200)
        did = r["id"]
        a = self.admin()
        self.assertEqual(a.req("PUT", f"/api/deals/{did}", {"sp_id": ids[2], "date": self.yday, "kind": "appt", "units": 5})[0], 200)
        _, s = a.req("GET", "/api/state")
        self.assertEqual(next(x for x in s["result"]["stores"] if x["id"] == 2)["appts"], 11)
        self.assertEqual(a.req("DELETE", f"/api/deals/{did}")[0], 200)
        # clearing appointments to 0 removes the row
        c.req("POST", "/api/entry/2/grid", {"date": self.yday, "rows": [{"sp_id": ids[0], "new": 2, "appt": 0, "used": []},
                                                                        {"sp_id": ids[1], "new": 0, "appt": 0, "used": []}]})
        _, s = a.req("GET", "/api/state")
        self.assertEqual(next(x for x in s["result"]["stores"] if x["id"] == 2)["appts"], 0)
        # appointment window + targets are admin settings
        self.assertEqual(a.req("PUT", "/api/admin/settings", {"appt_start": self.yday, "appt_end": self.start})[0], 400)
        st, _ = a.req("PUT", "/api/admin/stores/2", {"name": "Chrysler Grand Haven", "short": "CJDR Grand Haven", "color": "#f59e0b",
                                                     "new_target": 55, "used_target": 110000, "appt_target": 50, "contribution": 3500})
        self.assertEqual(st, 200)
        _, adm = a.req("GET", "/api/admin")
        self.assertEqual(next(x for x in adm["stores"] if x["id"] == 2)["appt_target"], 50)
        a.req("PUT", "/api/admin/stores/2", {"name": "Chrysler Grand Haven", "short": "CJDR Grand Haven", "color": "#f59e0b",
                                             "new_target": 55, "used_target": 110000, "appt_target": 48, "contribution": 3500})

    def test_08_rate_limit(self):
        c = Client(self.base)
        codes = [c.login("0001")[0] for _ in range(9)]
        self.assertIn(429, codes)


if __name__ == "__main__":
    unittest.main()
