"""The live database was created by the Oct 1-31 version (deals CHECK allowed only new/used, no appt_target column,
weekly bounty prizes). Starting the new server on such a file must migrate it in place without losing anything."""
import json, os, sqlite3, subprocess, sys, tempfile, time, unittest, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_api import Client, free_port, ROOT  # noqa: E402

OLD_SCHEMA = """
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE stores (id INTEGER PRIMARY KEY, name TEXT NOT NULL, short TEXT, color TEXT,
  new_target REAL DEFAULT 0, used_target REAL DEFAULT 0, contribution REAL DEFAULT 0, pin_hash TEXT, sort INTEGER DEFAULT 0);
CREATE TABLE salespeople (id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id),
  name TEXT NOT NULL, active INTEGER DEFAULT 1, placeholder INTEGER DEFAULT 0, sort INTEGER DEFAULT 0);
CREATE TABLE deals (id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id),
  sp_id INTEGER NOT NULL REFERENCES salespeople(id), date TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('new','used')), units REAL NOT NULL, gross REAL DEFAULT 0,
  note TEXT DEFAULT '', demo INTEGER DEFAULT 0, entered_by TEXT, created_at TEXT, updated_at TEXT);
CREATE INDEX deals_store_date ON deals(store_id, date);
CREATE TABLE audit (id INTEGER PRIMARY KEY, ts TEXT, who TEXT, action TEXT, detail TEXT);
"""


class MigrationTest(unittest.TestCase):
    def test_old_database_is_migrated_in_place(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "old.db")
        con = sqlite3.connect(path)
        con.executescript(OLD_SCHEMA)
        for i, (n, nt, ut) in enumerate((("Chrysler Muskegon", 70, 140000), ("Chrysler Grand Haven", 55, 110000), ("Grand Haven Ford", 65, 130000))):
            con.execute("INSERT INTO stores(name,short,color,new_target,used_target,contribution,sort) VALUES(?,?,?,?,?,?,?)",
                        (n, n, "#123456", nt, ut, 3500, i))
            for k in range(1, 8):
                con.execute("INSERT INTO salespeople(store_id,name,placeholder,sort) VALUES(?,?,1,?)", (i + 1, f"Salesperson {k}", k))
        for k, v in {"start_date": "2026-10-01", "end_date": "2026-10-31", "weight_new": 50, "bounty_days": 7,
                     "tagline": "3 stores · 1 month · $10,500 on the line",
                     "prizes": {"team": [3000, 1500, 0], "new": [1000, 600, 400], "used": [1000, 600, 400], "mvp": 250,
                                "top_gun": 125, "big_fish": 125}}.items():
            con.execute("INSERT INTO settings VALUES(?,?)", (k, json.dumps(v)))
        con.execute("INSERT INTO deals(store_id,sp_id,date,kind,units,gross) VALUES(1,1,'2026-09-28','new',1,0)")
        con.commit()
        con.close()
        port = free_port()
        env = {**os.environ, "PORT": str(port), "DB_PATH": path, "SEED_DEMO": "1", "ADMIN_PIN": "8642", "QUIET": "1"}
        proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "server.py")], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            base = f"http://127.0.0.1:{port}"
            for _ in range(50):
                try:
                    urllib.request.urlopen(base + "/healthz")
                    break
                except Exception:
                    time.sleep(0.1)
            a = Client(base)
            self.assertEqual(a.login("8642")[0], 200)
            _, adm = a.req("GET", "/api/admin")
            s = adm["settings"]
            self.assertEqual((s["start_date"], s["end_date"], s["appt_start"], s["appt_end"]),
                             ("2026-09-26", "2026-09-30", "2026-09-26", "2026-09-29"))
            self.assertEqual(s["prizes"], {"points": [900, 275, 0], "new": [575, 0, 0], "used": [575, 0, 0],
                                           "appt": [425, 0, 0], "hot_shot": 50})
            self.assertEqual(s["tagline"], "6 closers · 5 days · $3,000 on the line")
            self.assertTrue(adm["budget_ok"])
            self.assertEqual(adm["budget"]["total"], 3000)
            self.assertEqual([x["name"] for x in adm["stores"]], ["Chrysler Muskegon"])
            self.assertEqual([x["appt_target"] for x in adm["stores"]], [60])
            self.assertEqual([x["new_target"] for x in adm["stores"]], [70])      # target untouched
            self.assertEqual(adm["deal_count"], 1)                                          # Muskegon rows kept
            self.assertEqual(adm["demo_count"], 0)                                          # no demo re-seed on an existing DB
            self.assertIn("migrate", [x["action"] for x in adm["audit"]])
            # the rebuilt table now accepts appointment rows
            st, r = a.req("POST", "/api/entry/1/deal", {"sp_id": 2, "date": "2026-09-26", "kind": "appt", "units": 2})
            self.assertEqual(st, 200, r)
        finally:
            proc.terminate()
            proc.wait(5)
        con = sqlite3.connect(path)
        sql = con.execute("SELECT sql FROM sqlite_master WHERE name='deals'").fetchone()[0]
        self.assertIn("'appt'", sql)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM deals").fetchone()[0], 2)
        con.close()


V2_SCHEMA = OLD_SCHEMA.replace("pin_hash TEXT, sort INTEGER DEFAULT 0);", "pin_hash TEXT, sort INTEGER DEFAULT 0, appt_target REAL DEFAULT 0);") \
    .replace("CHECK (kind IN ('new','used'))", "CHECK (kind IN ('new','used','appt'))")


class SingleStoreMigrationTest(unittest.TestCase):
    """The live 3-store v2 database ($10,500, placeholder rosters) -> Chrysler Muskegon only, $3,000, real roster.
    Muskegon's entries and PIN are kept; the other two stores (and their entries/reps) are removed."""

    def test_v2_three_store_database_becomes_single_store(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "v2.db")
        con = sqlite3.connect(path)
        con.executescript(V2_SCHEMA)
        for i, (n, at) in enumerate((("Chrysler Muskegon", 60), ("Chrysler Grand Haven", 48), ("Grand Haven Ford", 56))):
            con.execute("INSERT INTO stores(name,short,color,new_target,used_target,contribution,sort,appt_target) VALUES(?,?,?,?,?,?,?,?)",
                        (n, n, "#123456", 70, 140000, 3500, i, at))
            for k in range(1, 8):
                con.execute("INSERT INTO salespeople(store_id,name,placeholder,sort) VALUES(?,?,1,?)", (i + 1, f"Salesperson {k}", k))
        for k, v in {"schema_version": 2, "tagline": "3 stores · 5 days · $10,500 on the line",
                     "prizes": {"team": [2500, 1000, 0], "new": [2000, 0, 0], "used": [2000, 0, 0], "appt": [1500, 0, 0],
                                "mvp": 250, "hot_shot": 150}}.items():
            con.execute("INSERT INTO settings VALUES(?,?)", (k, json.dumps(v)))
        # a real Muskegon entry on placeholder rep #7 (must be kept), plus entries at the stores being removed
        con.execute("INSERT INTO deals(store_id,sp_id,date,kind,units,gross) VALUES(1,7,'2026-09-26','new',2,0)")
        con.execute("INSERT INTO deals(store_id,sp_id,date,kind,units,gross) VALUES(2,8,'2026-09-26','new',1,0)")
        con.execute("INSERT INTO deals(store_id,sp_id,date,kind,units,gross) VALUES(3,15,'2026-09-26','used',1,2500)")
        con.commit()
        con.close()
        port = free_port()
        env = {**os.environ, "PORT": str(port), "DB_PATH": path, "SEED_DEMO": "1", "ADMIN_PIN": "8642", "QUIET": "1",
               "STORE_PIN_1": "1357", "STORE_PIN_2": "2468", "STORE_PIN_3": "3579"}
        proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "server.py")], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            base = f"http://127.0.0.1:{port}"
            for _ in range(50):
                try:
                    urllib.request.urlopen(base + "/healthz")
                    break
                except Exception:
                    time.sleep(0.1)
            a = Client(base)
            self.assertEqual(a.login("8642")[0], 200)
            _, adm = a.req("GET", "/api/admin")
            self.assertEqual([(x["id"], x["name"], x["contribution"]) for x in adm["stores"]], [(1, "Chrysler Muskegon", 3000)])
            self.assertEqual(adm["pool"], 3000)
            self.assertTrue(adm["budget_ok"])
            self.assertEqual(adm["settings"]["tagline"], "6 closers · 5 days · $3,000 on the line")
            active = [p["name"] for p in adm["people"] if p["active"]]
            self.assertEqual(active, ["Monty", "Nathan", "Adrian", "Sierra", "Jacob", "Raheem"])
            # placeholder #7 had a real entry: kept (inactive) so the entry still counts for the store goal
            p7 = next(p for p in adm["people"] if p["id"] == 7)
            self.assertEqual((p7["active"], p7["deal_rows"]), (0, 1))
            self.assertEqual(adm["deal_count"], 1)
            self.assertEqual(Client(base).login("1357")[1]["role"], "store")
            self.assertEqual(Client(base).login("2468")[0], 401)
            self.assertEqual(Client(base).login("3579")[0], 401)
            self.assertIn("single store", " ".join(x["detail"] for x in adm["audit"] if x["action"] == "migrate"))
        finally:
            proc.terminate()
            proc.wait(5)
        # restarting doesn't migrate again
        con = sqlite3.connect(path)
        self.assertEqual(json.loads(con.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0]), 3)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM stores").fetchone()[0], 1)
        con.close()


if __name__ == "__main__":
    unittest.main()
