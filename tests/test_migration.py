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
            self.assertEqual(s["tagline"], "7 closers · 5 days · $3,000 on the line")
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
            self.assertEqual(adm["settings"]["tagline"], "7 closers · 5 days · $3,000 on the line")
            active = [p["name"] for p in adm["people"] if p["active"]]
            self.assertEqual(active, ["Monty", "Nathan", "Adrian", "Sierra", "Caleb", "Raheem", "Justin"])
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
        self.assertEqual(json.loads(con.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0]), 5)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM stores").fetchone()[0], 1)
        con.close()


class AddJustinMigrationTest(unittest.TestCase):
    """The live v3 database (Muskegon only, 6 reps, real entries) -> v4: Justin is appended; nothing else changes."""

    def make_v3(self, extra_people=(), version=3, names=("Monty", "Nathan", "Adrian", "Sierra", "Jacob", "Raheem")):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "v3.db")
        con = sqlite3.connect(path)
        con.executescript(V2_SCHEMA)
        con.execute("INSERT INTO stores(name,short,color,new_target,used_target,contribution,sort,appt_target) "
                    "VALUES('Chrysler Muskegon','CJDR Muskegon','#e11d48',70,140000,3000,0,60)")
        for k, n in enumerate(names, start=1):
            con.execute("INSERT INTO salespeople(store_id,name,placeholder,sort) VALUES(1,?,0,?)", (n, k))
        for n, active in extra_people:
            con.execute("INSERT INTO salespeople(store_id,name,active,placeholder,sort) VALUES(1,?,?,0,99)", (n, active))
        prizes = {"points": [900, 275, 0], "new": [575, 0, 0], "used": [575, 0, 0], "appt": [425, 0, 0], "hot_shot": 50}
        for k, v in {"schema_version": version, "prizes": prizes}.items():
            con.execute("INSERT INTO settings VALUES(?,?)", (k, json.dumps(v)))
        con.execute("INSERT INTO deals(store_id,sp_id,date,kind,units,gross,entered_by) VALUES(1,6,'2026-09-26','used',1,4419,'admin')")
        con.execute("INSERT INTO deals(store_id,sp_id,date,kind,units,gross,entered_by) VALUES(1,3,'2026-09-28','used',1,4318,'admin')")
        con.commit()
        con.close()
        return path

    def start(self, path):
        port = free_port()
        env = {**os.environ, "PORT": str(port), "DB_PATH": path, "SEED_DEMO": "1", "ADMIN_PIN": "8642", "QUIET": "1"}
        proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "server.py")], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        base = f"http://127.0.0.1:{port}"
        for _ in range(50):
            try:
                urllib.request.urlopen(base + "/healthz")
                break
            except Exception:
                time.sleep(0.1)
        return proc, base

    def snapshot(self, path):
        con = sqlite3.connect(path)
        deals = con.execute("SELECT * FROM deals ORDER BY id").fetchall()
        people = con.execute("SELECT * FROM salespeople ORDER BY id").fetchall()
        stores = con.execute("SELECT * FROM stores ORDER BY id").fetchall()
        con.close()
        return deals, people, stores

    def test_v3_database_gets_justin_and_keeps_everything(self):
        path = self.make_v3()
        deals0, people0, stores0 = self.snapshot(path)
        for _ in range(2):          # second start must not add a second Justin
            proc, base = self.start(path)
            try:
                a = Client(base)
                self.assertEqual(a.login("8642")[0], 200)
                _, adm = a.req("GET", "/api/admin")
                self.assertEqual([p["name"] for p in adm["people"] if p["active"]],
                                 ["Monty", "Nathan", "Adrian", "Sierra", "Caleb", "Raheem", "Justin"])
                self.assertEqual(adm["settings"]["tagline"], "7 closers · 5 days · $3,000 on the line")
                self.assertEqual(adm["pool"], 3000)
                self.assertTrue(adm["budget_ok"])
                self.assertEqual(adm["settings"]["prizes"], {"points": [900, 275, 0], "new": [575, 0, 0], "used": [575, 0, 0],
                                                             "appt": [425, 0, 0], "hot_shot": 50})
                self.assertEqual(adm["deal_count"], 2)
                self.assertEqual(sum("added Justin" in x["detail"] for x in adm["audit"] if x["action"] == "migrate"), 1)
                _, st = Client(base).req("GET", "/api/state")
                self.assertIn("Justin", [x["name"] for x in st["result"]["leaderboards"]["points"]])
            finally:
                proc.terminate()
                proc.wait(5)
        deals1, people1, stores1 = self.snapshot(path)
        self.assertEqual(deals1, deals0)                      # every entry byte-for-byte unchanged
        self.assertEqual(stores1, stores0)                    # PIN hash / targets / contribution unchanged
        self.assertEqual(people1[:4] + people1[5:6], people0[:4] + people0[5:6])   # other existing reps unchanged
        self.assertEqual(people1[4], people0[4][:2] + ("Caleb",) + people0[4][3:])   # v5: Jacob renamed in place
        self.assertEqual(people1[6][1:], (1, "Justin", 1, 0, 7))
        self.assertEqual(len(people1), 7)

    def test_existing_justin_is_not_duplicated_and_custom_tagline_kept(self):
        path = self.make_v3(extra_people=[("justin", 0)])
        con = sqlite3.connect(path)
        con.execute("INSERT INTO settings VALUES('tagline', ?)", (json.dumps("Let's go Muskegon"),))
        con.commit()
        con.close()
        proc, base = self.start(path)
        try:
            a = Client(base)
            a.login("8642")
            _, adm = a.req("GET", "/api/admin")
            self.assertEqual([p["name"].lower() for p in adm["people"]].count("justin"), 1)
            self.assertTrue(next(p for p in adm["people"] if p["name"].lower() == "justin")["active"])
            self.assertEqual(adm["settings"]["tagline"], "Let's go Muskegon")
        finally:
            proc.terminate()
            proc.wait(5)


class RenameJacobMigrationTest(AddJustinMigrationTest):
    """The live v4 database (7 reps incl. Jacob) -> v5: Jacob becomes Caleb on the same row; nothing else changes."""
    V4 = ("Monty", "Nathan", "Adrian", "Sierra", "Jacob", "Raheem", "Justin")

    # reuse the parent helpers (make_v3/start/snapshot) but not its tests, which already run in the parent class
    def test_v3_database_gets_justin_and_keeps_everything(self):
        pass

    def test_existing_justin_is_not_duplicated_and_custom_tagline_kept(self):
        pass

    def test_v4_jacob_renamed_to_caleb_in_place(self):
        path = self.make_v3(version=4, names=self.V4)
        con = sqlite3.connect(path)       # give Jacob (id 5) an entry: it must carry over to Caleb
        con.execute("INSERT INTO deals(store_id,sp_id,date,kind,units,gross,entered_by) VALUES(1,5,'2026-09-27','new',2,0,'admin')")
        con.commit()
        con.close()
        deals0, people0, stores0 = self.snapshot(path)
        for _ in range(2):          # second start must not rename again or log again
            proc, base = self.start(path)
            try:
                a = Client(base)
                self.assertEqual(a.login("8642")[0], 200)
                _, adm = a.req("GET", "/api/admin")
                self.assertEqual([(p["id"], p["name"]) for p in adm["people"] if p["active"]],
                                 list(enumerate(["Monty", "Nathan", "Adrian", "Sierra", "Caleb", "Raheem", "Justin"], start=1)))
                self.assertEqual(adm["settings"]["tagline"], "7 closers · 5 days · $3,000 on the line")
                self.assertEqual(adm["pool"], 3000)
                self.assertEqual(adm["deal_count"], 3)
                self.assertEqual(sum("renamed Jacob -> Caleb" in x["detail"] for x in adm["audit"] if x["action"] == "migrate"), 1)
                self.assertFalse(any("added Justin" in x["detail"] for x in adm["audit"]))   # v4 step not re-run
                _, st = Client(base).req("GET", "/api/state")
                caleb = next(x for x in st["result"]["leaderboards"]["new"] if x["name"] == "Caleb")
                self.assertEqual(caleb["new"], 2)                                            # his entry carried over
                self.assertNotIn("Jacob", [x["name"] for x in st["people"]])
            finally:
                proc.terminate()
                proc.wait(5)
        deals1, people1, stores1 = self.snapshot(path)
        self.assertEqual(deals1, deals0)
        self.assertEqual(stores1, stores0)
        self.assertEqual(len(people1), 7)
        self.assertEqual(people1[4], (5, 1, "Caleb", 1, 0, 5))
        self.assertEqual([r for i, r in enumerate(people1) if i != 4], [r for i, r in enumerate(people0) if i != 4])

    def test_rename_skipped_if_name_already_changed(self):
        path = self.make_v3(version=4, names=("Monty", "Nathan", "Adrian", "Sierra", "Jake", "Raheem", "Justin"))
        _, people0, _ = self.snapshot(path)
        proc, base = self.start(path)
        try:
            a = Client(base)
            a.login("8642")
            _, adm = a.req("GET", "/api/admin")
            self.assertIn("Jake", [p["name"] for p in adm["people"]])
            self.assertNotIn("Caleb", [p["name"] for p in adm["people"]])
            self.assertIn("rename skipped", " ".join(x["detail"] for x in adm["audit"] if x["action"] == "migrate"))
        finally:
            proc.terminate()
            proc.wait(5)
        self.assertEqual(self.snapshot(path)[1], people0)

    def test_rename_skipped_if_caleb_already_exists(self):
        path = self.make_v3(version=4, names=self.V4, extra_people=[("Caleb", 1)])
        _, people0, _ = self.snapshot(path)
        proc, base = self.start(path)
        proc.terminate()
        proc.wait(5)
        self.assertEqual(self.snapshot(path)[1], people0)


if __name__ == "__main__":
    unittest.main()
