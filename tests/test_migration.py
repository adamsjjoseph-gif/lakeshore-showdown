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
            self.assertEqual(s["prizes"], {"team": [2500, 1000, 0], "new": [2000, 0, 0], "used": [2000, 0, 0],
                                           "appt": [1500, 0, 0], "mvp": 250, "hot_shot": 150})
            self.assertEqual(s["tagline"], "3 stores · 5 days · $10,500 on the line")
            self.assertTrue(adm["budget_ok"])
            self.assertEqual(adm["budget"]["total"], 10500)
            self.assertEqual([x["appt_target"] for x in adm["stores"]], [60, 48, 56])
            self.assertEqual([x["new_target"] for x in adm["stores"]], [70, 55, 65])      # targets untouched
            self.assertEqual(adm["deal_count"], 1)                                          # existing rows kept
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


if __name__ == "__main__":
    unittest.main()
