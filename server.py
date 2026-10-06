#!/usr/bin/env python3
"""
Lakeshore Showdown — dealership sales-contest (spiff) server.

Single file, Python standard library only (http.server + sqlite3). No build step.
Run:  python3 server.py         (then open http://localhost:8080)
Env:  PORT, DB_PATH, ADMIN_PIN, VIEW_PIN, STORE_PIN_1..N, SECRET_KEY, SEED_DEMO, TZ_NAME
"""
import base64, csv, hashlib, hmac, io, json, os, re, secrets, sqlite3, sys, tempfile, threading, time
from datetime import date, datetime, timedelta
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import calc
import demo

BASE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(BASE, "static")
DB_PATH = os.environ.get("DB_PATH", os.path.join(BASE, "data", "spiff.db"))
# TOGR battle board: own JSON file on the same persistent disk as the contest database
TOGR_FILE = os.path.join(os.path.dirname(DB_PATH), "togr_board.json")
TOGR_USER = "togr"
TOGR_PASS_SHA256 = "4a5930c92ce6b4e972b15f7d1387d42baea23b7a0f88f36a8e25714112517dd0"  # SHA-256 of the manager password
TOGR_LOCK = threading.Lock()
PORT = int(os.environ.get("PORT", "8080"))
PBKDF2_ITERS = 100_000
COOKIE = "spiff_session"

DEFAULT_SETTINGS = {
    "contest_name": "Lakeshore Showdown",
    "tagline": "7 closers · 5 days · $3,000 on the line",
    "start_date": "2026-09-26",
    "end_date": "2026-09-30",
    "appt_start": calc.DEFAULT_APPT_WINDOW[0],   # appointments only count on these dates (inclusive)
    "appt_end": calc.DEFAULT_APPT_WINDOW[1],
    "timezone": os.environ.get("TZ_NAME", "America/Detroit"),
    "closed_sundays": True,
    "weight_new": 1,          # store goal: relative weights of new units / used gross / appointments vs target
    "weight_used": 1,         # (1 / 1 / 1 = equal thirds)
    "weight_appt": 1,
    "points_new": 2,
    "points_per_1k": 1,
    "points_per_appt": 0.5,   # Showdown Points per appointment (inside the appointment window)
    "heavy_hitter": 4000,
    "hat_trick_units": 3,
    "streak_days": 3,
    "bounty_days": 1,         # Daily Hot Shot period length (1 = every day)
    "prizes": calc.DEFAULT_PRIZES,
    "demo_today": None,
    "view_pin_required": False,
}

DEFAULT_STORES = [
    # name, short, color, new target (units), used gross target ($), contribution ($), appointment target (window)
    ("Chrysler Muskegon", "CJDR Muskegon", "#e11d48", 70, 140000, 3000, 60),
]
STORE_NAME = DEFAULT_STORES[0][0]
DEFAULT_ROSTER = ["Monty", "Nathan", "Adrian", "Sierra", "Caleb", "Raheem", "Justin"]
OLD_TAGLINES = ("3 stores · 1 month · $10,500 on the line", "3 stores · 5 days · $10,500 on the line",
                "6 closers · 5 days · $3,000 on the line")
ADDED_V4 = "Justin"
RENAME_V5 = ("Jacob", "Caleb")   # same rep row/id, so his entries carry over
SCHEMA_VERSION = 5
DEFAULT_PINS = {"admin": "9999", "stores": ["1111"], "view": ""}

# --------------------------------------------------------------------------------------------- db
class DB:
    def __init__(self, path):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")

    def q(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        r = self.q(sql, args)
        return r[0] if r else None

    def x(self, sql, args=()):
        with self.lock:
            return self.conn.execute(sql, args).lastrowid

    def tx(self):
        return _Tx(self)


class _Tx:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        self.db.lock.acquire()
        self.db.conn.execute("BEGIN IMMEDIATE")
        return self.db

    def __exit__(self, et, ev, tb):
        try:
            self.db.conn.execute("ROLLBACK" if et else "COMMIT")
        finally:
            self.db.lock.release()


# kind: 'new' (units), 'used' (units + gross) or 'appt' (units = number of appointments that day)
DEALS_COLS = """
  id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id),
  sp_id INTEGER NOT NULL REFERENCES salespeople(id), date TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('new','used','appt')), units REAL NOT NULL, gross REAL DEFAULT 0,
  note TEXT DEFAULT '', demo INTEGER DEFAULT 0, entered_by TEXT, created_at TEXT, updated_at TEXT"""
DEALS_FIELDS = "id,store_id,sp_id,date,kind,units,gross,note,demo,entered_by,created_at,updated_at"

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS stores (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, short TEXT, color TEXT,
  new_target REAL DEFAULT 0, used_target REAL DEFAULT 0, contribution REAL DEFAULT 0,
  pin_hash TEXT, sort INTEGER DEFAULT 0, appt_target REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS salespeople (
  id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id),
  name TEXT NOT NULL, active INTEGER DEFAULT 1, placeholder INTEGER DEFAULT 0, sort INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS deals (%s);
CREATE INDEX IF NOT EXISTS deals_store_date ON deals(store_id, date);
CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, ts TEXT, who TEXT, action TEXT, detail TEXT);
""" % DEALS_COLS

db = None


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def get_settings():
    out = json.loads(json.dumps(DEFAULT_SETTINGS))
    for r in db.q("SELECT key, value FROM settings"):
        try:
            out[r["key"]] = json.loads(r["value"])
        except Exception:
            pass
    out["prizes"] = {**calc.DEFAULT_PRIZES, **(out.get("prizes") or {})}
    for k in calc.LEGACY_PRIZE_KEYS:
        out["prizes"].pop(k, None)
    return out


def set_setting(k, v):
    db.x("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
         (k, json.dumps(v)))


def audit(who, action, detail=""):
    db.x("INSERT INTO audit(ts,who,action,detail) VALUES(?,?,?,?)", (now_iso(), who, action, str(detail)[:500]))


def hash_pin(pin):
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, PBKDF2_ITERS)
    return f"pbkdf2${PBKDF2_ITERS}${salt.hex()}${dk.hex()}"


def check_pin(pin, h):
    if not h or not pin:
        return False
    try:
        _, it, salt, dk = h.split("$")
        got = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), int(it))
        return hmac.compare_digest(got.hex(), dk)
    except Exception:
        return False


def today_local():
    s = get_settings()
    if s.get("demo_today"):
        return calc.to_date(s["demo_today"])
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(s.get("timezone") or "America/Detroit")).date()
    except Exception:
        return date.today()


def contest_end_ts(s):
    """Epoch milliseconds of the last second of the contest (end date 11:59:59 PM in the dealership time zone)."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(s.get("timezone") or "America/Detroit")
        e = calc.to_date(s["end_date"])
        dt = datetime(e.year, e.month, e.day, 23, 59, 59, tzinfo=tz)
        return int(dt.timestamp() * 1000), dt.tzname()
    except Exception:
        e = calc.to_date(s["end_date"])
        return int(datetime(e.year, e.month, e.day, 23, 59, 59).timestamp() * 1000), ""


def default_entry_date():
    """Yesterday — or Saturday when yesterday was a (closed) Sunday. Clamped to the contest window."""
    s = get_settings()
    t = today_local()
    d = t - timedelta(days=1)
    if s.get("closed_sundays") and d.weekday() == 6:
        d -= timedelta(days=1)
    start, end = calc.to_date(s["start_date"]), calc.to_date(s["end_date"])
    return max(start, min(d, end))


def migrate_schema():
    """Bring an existing database up to date (safe to run on every start)."""
    cols = {r["name"] for r in db.q("PRAGMA table_info(stores)")}
    if "appt_target" not in cols:
        db.x("ALTER TABLE stores ADD COLUMN appt_target REAL DEFAULT 0")
    sql = (db.one("SELECT sql FROM sqlite_master WHERE type='table' AND name='deals'") or {}).get("sql") or ""
    if "'appt'" not in sql:
        # SQLite can't alter a CHECK constraint: rebuild the deals table with 'appt' allowed, keeping every row + id
        with db.tx():
            db.conn.execute(f"CREATE TABLE deals_v2 ({DEALS_COLS})")
            db.conn.execute(f"INSERT INTO deals_v2 ({DEALS_FIELDS}) SELECT {DEALS_FIELDS} FROM deals")
            db.conn.execute("DROP TABLE deals")
            db.conn.execute("ALTER TABLE deals_v2 RENAME TO deals")
            db.conn.execute("CREATE INDEX IF NOT EXISTS deals_store_date ON deals(store_id, date)")


def migrate_settings(first_run):
    """One-time upgrades of an existing database:
    v1 -> v2: Oct 1-31 month -> Sep 26-30 five-day format with appointments.
    v2 -> v3: 3 stores / $10,500 -> Chrysler Muskegon only / $3,000 with the real roster.
    v3 -> v4: add Justin to the roster (insert only; existing reps, entries, PINs, targets and prizes untouched).
    v4 -> v5: rename Jacob -> Caleb in place (same id, entries carry over), only if the name is still Jacob."""
    ver = get_settings().get("schema_version") or 1
    if ver >= SCHEMA_VERSION:
        return
    if not first_run and ver < 3:
        migrate_single_store()
    elif not first_run:
        if ver < 4:
            migrate_add_justin()
        if ver < 5:
            migrate_rename_jacob()
    if not first_run and ver < 2:
        cur = get_settings()
        new = {k: DEFAULT_SETTINGS[k] for k in ("start_date", "end_date", "appt_start", "appt_end", "weight_new",
                                                  "weight_used", "weight_appt", "points_per_appt", "bounty_days")}
        new["prizes"] = dict(calc.DEFAULT_PRIZES)
        if cur.get("tagline") in OLD_TAGLINES:
            new["tagline"] = DEFAULT_SETTINGS["tagline"]
        for k, v in new.items():
            set_setting(k, v)
        for (name, *_rest, at), row in zip(DEFAULT_STORES, db.q("SELECT id, appt_target FROM stores ORDER BY sort,id")):
            if not row["appt_target"]:
                db.x("UPDATE stores SET appt_target=? WHERE id=?", (at, row["id"]))
        audit("system", "migrate", "5-day format: dates %s to %s, appointments %s to %s, new prize table, appointment targets"
              % (new["start_date"], new["end_date"], new["appt_start"], new["appt_end"]))
    set_setting("schema_version", SCHEMA_VERSION)


def migrate_single_store():
    """v3: keep only Chrysler Muskegon (its entries, PIN and targets are kept), set the $3,000 pool and prize table,
    and put the real roster (Monty, Nathan, Adrian, Sierra, Caleb, Raheem, Justin) in place of placeholder reps."""
    stores = db.q("SELECT id, name FROM stores ORDER BY sort,id")
    if not stores:
        return
    keep = next((x for x in stores if x["name"] == STORE_NAME), stores[0])
    removed = []
    with db.tx():
        c = db.conn
        for x in stores:
            if x["id"] == keep["id"]:
                continue
            n = c.execute("SELECT COUNT(*) FROM deals WHERE store_id=?", (x["id"],)).fetchone()[0]
            c.execute("DELETE FROM deals WHERE store_id=?", (x["id"],))
            c.execute("DELETE FROM deals WHERE sp_id IN (SELECT id FROM salespeople WHERE store_id=?)", (x["id"],))
            c.execute("DELETE FROM salespeople WHERE store_id=?", (x["id"],))
            c.execute("DELETE FROM stores WHERE id=?", (x["id"],))
            removed.append(f"{x['name']} ({n} entries)")
        c.execute("UPDATE stores SET name=?, contribution=?, sort=0 WHERE id=?", (STORE_NAME, DEFAULT_STORES[0][5], keep["id"]))
        # roster: fill in missing real names by renaming placeholder reps first, then adding; drop leftover placeholders
        people = [dict(r) for r in c.execute("SELECT id, name, placeholder FROM salespeople WHERE store_id=? ORDER BY sort,id",
                                            (keep["id"],)).fetchall()]
        have = {p["name"].strip().lower() for p in people if not p["placeholder"]}
        missing = [n for n in DEFAULT_ROSTER if n.lower() not in have]
        has_deals = lambda pid: c.execute("SELECT COUNT(*) FROM deals WHERE sp_id=?", (pid,)).fetchone()[0] > 0
        # only placeholders with NO entries get renamed (an entry on "Salesperson 3" belongs to an unknown person)
        placeholders = [p for p in people if p["placeholder"] and not has_deals(p["id"])]
        with_deals = [p for p in people if p["placeholder"] and has_deals(p["id"])]
        for p, name in zip(placeholders, missing):
            c.execute("UPDATE salespeople SET name=?, placeholder=0, active=1 WHERE id=?", (name, p["id"]))
        for name in missing[len(placeholders):]:
            c.execute("INSERT INTO salespeople(store_id,name,placeholder,sort) VALUES(?,?,0,?)", (keep["id"], name, 100))
        for p in placeholders[len(missing):]:
            c.execute("DELETE FROM salespeople WHERE id=?", (p["id"],))
        for p in with_deals:     # keep their entries (they count for the store goal) but drop them from individual prizes
            c.execute("UPDATE salespeople SET active=0 WHERE id=?", (p["id"],))
        order = {n.lower(): i for i, n in enumerate(DEFAULT_ROSTER, start=1)}
        for r in c.execute("SELECT id, name FROM salespeople WHERE store_id=?", (keep["id"],)).fetchall():
            c.execute("UPDATE salespeople SET sort=? WHERE id=?", (order.get(r[1].strip().lower(), 50 + r[0]), r[0]))
    set_setting("prizes", dict(calc.DEFAULT_PRIZES))
    if get_settings().get("tagline") in OLD_TAGLINES:
        set_setting("tagline", DEFAULT_SETTINGS["tagline"])
    db.x("DELETE FROM settings WHERE key='qualifier_units'")
    audit("system", "migrate", f"single store: kept {STORE_NAME}; removed " + (", ".join(removed) or "nothing")
          + f"; pool ${DEFAULT_STORES[0][5]:,}; new prize table; roster " + ", ".join(DEFAULT_ROSTER))


def migrate_add_justin():
    """v4: add Justin to Chrysler Muskegon (after the existing reps). Insert-only: no existing rep, entry, PIN,
    target or prize is changed. If a Justin already exists (e.g. added on the Admin page) he is just made active.
    The tagline is bumped to 7 closers only if it still reads the old default."""
    store = db.one("SELECT id FROM stores WHERE name=? ORDER BY sort,id", (STORE_NAME,)) or db.one("SELECT id FROM stores ORDER BY sort,id")
    if not store:
        return
    with db.tx():
        c = db.conn
        row = c.execute("SELECT id, active FROM salespeople WHERE store_id=? AND lower(trim(name))=?",
                        (store["id"], ADDED_V4.lower())).fetchone()
        if row:
            c.execute("UPDATE salespeople SET active=1 WHERE id=?", (row[0],))
            what = f"{ADDED_V4} already on roster (id {row[0]}), made active"
        else:
            mx = c.execute("SELECT COALESCE(MAX(sort),0) FROM salespeople WHERE store_id=? AND sort<50",
                           (store["id"],)).fetchone()[0]
            i = c.execute("INSERT INTO salespeople(store_id,name,active,placeholder,sort) VALUES(?,?,1,0,?)",
                          (store["id"], ADDED_V4, mx + 1)).lastrowid
            what = f"added {ADDED_V4} (id {i})"
    if get_settings().get("tagline") in OLD_TAGLINES:
        set_setting("tagline", DEFAULT_SETTINGS["tagline"])
    audit("system", "migrate", f"roster: {what}; entries, PINs, targets and prizes unchanged")


def migrate_rename_jacob():
    """v5: rename Jacob -> Caleb on the same salespeople row (id, active flag, sort and every entry stay as they are).
    Only a rep still named exactly Jacob is renamed; if the name was already changed, or a Caleb already exists,
    nothing is touched."""
    old, new = RENAME_V5
    store = db.one("SELECT id FROM stores WHERE name=? ORDER BY sort,id", (STORE_NAME,)) or db.one("SELECT id FROM stores ORDER BY sort,id")
    if not store:
        return
    with db.tx():
        c = db.conn
        rows = c.execute("SELECT id FROM salespeople WHERE store_id=? AND trim(name)=?", (store["id"], old)).fetchall()
        caleb = c.execute("SELECT id FROM salespeople WHERE store_id=? AND lower(trim(name))=?", (store["id"], new.lower())).fetchone()
        if len(rows) == 1 and not caleb:
            c.execute("UPDATE salespeople SET name=? WHERE id=?", (new, rows[0][0]))
            what = f"renamed {old} -> {new} (id {rows[0][0]}, entries kept)"
        else:
            what = f"{old} -> {new} rename skipped ({len(rows)} rep(s) named {old}, {new} {'exists' if caleb else 'absent'})"
    audit("system", "migrate", f"roster: {what}")


def init_db():
    global db
    db = DB(DB_PATH)
    db.conn.executescript(SCHEMA)
    migrate_schema()
    first_run = db.one("SELECT COUNT(*) n FROM stores")["n"] == 0
    migrate_settings(first_run)
    if first_run:
        for i, (name, short, color, nt, ut, contrib, at) in enumerate(DEFAULT_STORES):
            sid = db.x("INSERT INTO stores(name,short,color,new_target,used_target,contribution,sort,appt_target) "
                       "VALUES(?,?,?,?,?,?,?,?)", (name, short, color, nt, ut, contrib, i, at))
            for n, rep_name in enumerate(DEFAULT_ROSTER, start=1):
                db.x("INSERT INTO salespeople(store_id,name,placeholder,sort) VALUES(?,?,0,?)", (sid, rep_name, n))
        if not db.one("SELECT 1 FROM settings WHERE key='admin_pin_hash'"):
            set_setting("admin_pin_hash", hash_pin(DEFAULT_PINS["admin"]))
            for s, pin in zip(db.q("SELECT id FROM stores ORDER BY sort,id"), DEFAULT_PINS["stores"]):
                db.x("UPDATE stores SET pin_hash=? WHERE id=?", (hash_pin(pin), s["id"]))
        audit("system", "first-run", "seeded store, roster and demo PINs")
        # never put fake demo sales on a board whose contest has already started
        if os.environ.get("SEED_DEMO", "1") != "0" and today_local() < calc.to_date(get_settings()["start_date"]):
            load_demo("system")
    if not get_settings().get("secret_key") and not os.environ.get("SECRET_KEY"):
        set_setting("secret_key", secrets.token_hex(32))
    # environment-configured PINs override stored ones at startup (stored hashed)
    if os.environ.get("ADMIN_PIN"):
        set_setting("admin_pin_hash", hash_pin(os.environ["ADMIN_PIN"]))
    if "VIEW_PIN" in os.environ:
        vp = os.environ["VIEW_PIN"].strip()
        set_setting("view_pin_hash", hash_pin(vp) if vp else None)
        set_setting("view_pin_required", bool(vp))
    for i, s in enumerate(db.q("SELECT id FROM stores ORDER BY sort,id"), start=1):
        v = os.environ.get(f"STORE_PIN_{i}")
        if v:
            db.x("UPDATE stores SET pin_hash=? WHERE id=?", (hash_pin(v), s["id"]))


def load_demo(who):
    s = get_settings()
    start, end = calc.to_date(s["start_date"]), calc.to_date(s["end_date"])
    demo_today = min(end, start + timedelta(days=max(1, round(((end - start).days + 1) * 0.6)))).isoformat()
    stores = db.q("SELECT * FROM stores ORDER BY sort,id")
    people = db.q("SELECT * FROM salespeople ORDER BY store_id, sort, id")
    rows = demo.generate(stores, people, s["start_date"], demo_today, s.get("closed_sundays", True),
                         appt_window=calc.appt_window(s))
    with db.tx():
        db.conn.execute("DELETE FROM deals")
        for d in rows:
            db.conn.execute("INSERT INTO deals(store_id,sp_id,date,kind,units,gross,demo,entered_by,created_at) "
                            "VALUES(?,?,?,?,?,?,1,'demo',?)",
                            (d["store_id"], d["sp_id"], d["date"], d["kind"], d["units"], d["gross"], now_iso()))
    set_setting("demo_today", demo_today)
    audit(who, "load-demo", f"{len(rows)} fake deals, simulated today {demo_today}")


# ------------------------------------------------------------------------------------ sessions
def secret_key():
    return (os.environ.get("SECRET_KEY") or get_settings().get("secret_key") or "dev").encode()


def make_cookie(role, store_id=None, hours=24 * 30):
    payload = base64.urlsafe_b64encode(json.dumps(
        {"role": role, "store_id": store_id, "exp": int(time.time() + hours * 3600)}).encode()).decode()
    sig = hmac.new(secret_key(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def read_cookie(val):
    try:
        payload, sig = val.split(".")
        if not hmac.compare_digest(sig, hmac.new(secret_key(), payload.encode(), hashlib.sha256).hexdigest()):
            return None
        d = json.loads(base64.urlsafe_b64decode(payload))
        if d["exp"] < time.time():
            return None
        return d
    except Exception:
        return None


FAILS = {}  # ip -> [count, first_ts]
FAIL_LIMIT, FAIL_WINDOW = 8, 600


GLOBAL_FAILS = []  # timestamps of all failed logins (defends against IP-spoofing brute force)
GLOBAL_LIMIT = 60


def rate_limited(ip):
    now = time.time()
    GLOBAL_FAILS[:] = [t for t in GLOBAL_FAILS if now - t < FAIL_WINDOW]
    if len(GLOBAL_FAILS) >= GLOBAL_LIMIT:
        return True
    f = FAILS.get(ip)
    if f and time.time() - f[1] > FAIL_WINDOW:
        FAILS.pop(ip, None)
        return False
    return bool(f and f[0] >= FAIL_LIMIT)


def note_fail(ip):
    f = FAILS.setdefault(ip, [0, time.time()])
    f[0] += 1
    GLOBAL_FAILS.append(time.time())


def all_pin_hashes(exclude=None):
    """[(label, hash)] for uniqueness checks."""
    s = get_settings()
    out = [("admin", s.get("admin_pin_hash")), ("view", s.get("view_pin_hash"))]
    out += [(f"store:{r['id']}", r["pin_hash"]) for r in db.q("SELECT id, pin_hash FROM stores")]
    return [(k, h) for k, h in out if h and k != exclude]


# ------------------------------------------------------------------------------------ helpers
class ApiError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code, self.msg = code, msg


def num(v, name, lo=None, hi=None, step=None):
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ApiError(400, f"{name} must be a number")
    if f != f or (lo is not None and f < lo) or (hi is not None and f > hi):
        raise ApiError(400, f"{name} out of range")
    if step and abs(round(f / step) * step - f) > 1e-9:
        raise ApiError(400, f"{name} must be in steps of {step}")
    return f


def valid_date(v, s=None):
    try:
        d = date.fromisoformat(str(v))
    except Exception:
        raise ApiError(400, "Bad date")
    s = s or get_settings()
    if not (calc.to_date(s["start_date"]) <= d <= calc.to_date(s["end_date"])):
        raise ApiError(400, f"Date must be inside the contest ({s['start_date']} to {s['end_date']})")
    if d > today_local():
        raise ApiError(400, "Can't enter sales for a future date")
    return d.isoformat()


def contest_state():
    s = get_settings()
    stores = db.q("SELECT id,name,short,color,new_target,used_target,appt_target,contribution,sort FROM stores ORDER BY sort,id")
    people = db.q("SELECT id,store_id,name,active,placeholder FROM salespeople ORDER BY store_id, sort, id")
    deals = db.q("SELECT id,store_id,sp_id,date,kind,units,gross FROM deals")
    res = calc.compute(s, stores, people, deals, today_local())
    return s, stores, people, res


def public_settings(s):
    keys = ["contest_name", "tagline", "start_date", "end_date", "closed_sundays", "weight_new", "weight_used",
            "weight_appt", "points_new", "points_per_1k", "points_per_appt", "heavy_hitter",
            "hat_trick_units", "streak_days", "bounty_days", "prizes", "demo_today", "view_pin_required", "timezone",
            "appt_start", "appt_end"]
    out = {k: s.get(k) for k in keys}
    out["end_ts"], out["tz_abbr"] = contest_end_ts(s)
    return out


def grid_for(store_id, d):
    people = db.q("SELECT id,name,active,placeholder FROM salespeople WHERE store_id=? ORDER BY sort,id", (store_id,))
    deals = db.q("SELECT * FROM deals WHERE store_id=? AND date=? ORDER BY id", (store_id, d))
    rows = []
    for p in people:
        mine = [x for x in deals if x["sp_id"] == p["id"]]
        if not p["active"] and not mine:
            continue
        rows.append({"sp_id": p["id"], "store_id": store_id, "name": p["name"], "placeholder": p["placeholder"], "active": p["active"],
                     "new": sum(x["units"] for x in mine if x["kind"] == "new"),
                     "appt": int(sum(x["units"] for x in mine if x["kind"] == "appt")),
                     "used": [{"gross": x["gross"], "split": x["units"] < 1} for x in mine if x["kind"] == "used"]})
    return rows


def day_status(d):
    """Per store: how many entry rows exist for date d (lets the GM see which stores are done)."""
    counts = {r["store_id"]: r["n"] for r in db.q("SELECT store_id, COUNT(*) n FROM deals WHERE date=? GROUP BY store_id", (d,))}
    return [{"store_id": s["id"], "rows": counts.get(s["id"], 0)} for s in db.q("SELECT id FROM stores ORDER BY sort,id")]


def storage_info():
    """Where the database lives and whether that folder is a separately mounted (persistent) disk."""
    d = os.path.dirname(os.path.abspath(DB_PATH))
    mount = None
    try:
        best = ""
        with open("/proc/mounts") as f:
            for ln in f:
                parts = ln.split()
                if len(parts) >= 3 and (d == parts[1] or d.startswith(parts[1].rstrip("/") + "/")) and len(parts[1]) > len(best):
                    best = parts[1]
                    mount = {"mount_point": parts[1], "device": parts[0], "fs": parts[2]}
    except Exception:
        pass
    return {"db_path": os.path.abspath(DB_PATH), "db_dir": d, "db_dir_is_mount": os.path.ismount(d), "mount": mount}


def csv_text(header, rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue()


# ------------------------------------------------------------------------------------ handler
PAGES = {"/": "index.html", "/enter": "enter.html", "/admin": "admin.html", "/login": "login.html",
         "/rules": "rules.html", "/togr": "togr/index.html", "/battleboard": "togr/index.html"}
MIME = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
        ".svg": "image/svg+xml", ".png": "image/png", ".ttf": "font/ttf", ".ico": "image/x-icon",
        ".pdf": "application/pdf", ".json": "application/json", ".webmanifest": "application/manifest+json"}


class Handler(BaseHTTPRequestHandler):
    server_version = "Showdown/1.0"

    def log_message(self, fmt, *args):
        if os.environ.get("QUIET") != "1":
            sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    # -- plumbing
    def sess(self):
        raw = self.headers.get("Cookie", "")
        for part in raw.split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE:
                return read_cookie(v) or {}
        return {}

    def ip(self):
        return (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()

    def send(self, code, body, ctype="application/json", headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, default=str)
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        if ctype.startswith("application/json"):
            self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 1_000_000:
            raise ApiError(413, "Too large")
        if n and "application/json" not in (self.headers.get("Content-Type") or ""):
            raise ApiError(415, "JSON only")
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            raise ApiError(400, "Bad JSON")

    def who(self, s):
        return s.get("role", "anon") + (f":{s['store_id']}" if s.get("store_id") else "")

    def need_view(self, s):
        if get_settings().get("view_pin_required") and not s.get("role"):
            raise ApiError(401, "PIN required")

    def need_store(self, s, store_id):
        if s.get("role") == "admin":
            return
        if s.get("role") == "store" and int(s.get("store_id") or 0) == int(store_id):
            return
        raise ApiError(401 if not s.get("role") else 403, "Store manager PIN required")

    def need_admin(self, s):
        if s.get("role") != "admin":
            raise ApiError(401 if not s.get("role") else 403, "Admin PIN required")

    def static(self, path):
        if path == "/favicon.ico":
            path = "/favicon.svg"
        rel = PAGES.get(path) or path.lstrip("/")
        if rel == "Spiff_Rules.pdf":
            full = os.path.join(BASE, "Spiff_Rules.pdf")
        else:
            full = os.path.normpath(os.path.join(STATIC, rel))
            if not full.startswith(STATIC):
                return self.send(404, {"error": "not found"})
        if not os.path.isfile(full):
            return self.send(404, "Not found", "text/plain")
        with open(full, "rb") as f:
            data = f.read()
        ext = os.path.splitext(full)[1]
        cache = "no-cache" if ext in (".html", ".js", ".css") else "public, max-age=86400"
        self.send(200, data, MIME.get(ext, "application/octet-stream"), {"Cache-Control": cache})

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def do_PUT(self):
        self.route("PUT")

    def do_DELETE(self):
        self.route("DELETE")

    def route(self, method):
        u = urlparse(self.path)
        path, qs = u.path.rstrip("/") or "/", parse_qs(u.query)
        try:
            if path == "/healthz":
                db.one("SELECT 1 AS ok")
                return self.send(200, {"ok": True})
            if not path.startswith("/api/"):
                if method in ("GET", "HEAD"):
                    return self.static(path)
                raise ApiError(405, "Method not allowed")
            s = self.sess()
            for m, pat, fn in ROUTES:
                if m == method:
                    mt = re.fullmatch(pat, path)
                    if mt:
                        return fn(self, s, qs, *mt.groups())
            raise ApiError(404, "Unknown API route")
        except ApiError as e:
            self.send(e.code, {"error": e.msg})
        except Exception as e:  # pragma: no cover
            import traceback
            traceback.print_exc()
            self.send(500, {"error": "Server error: " + str(e)})

    # ------------------------------------------------------------------ auth routes
    def api_me(self, s, qs):
        st = get_settings()
        store = db.one("SELECT id,name,short,color FROM stores WHERE id=?", (s.get("store_id"),)) if s.get("store_id") else None
        self.send(200, {"role": s.get("role"), "store": store, "view_pin_required": bool(st.get("view_pin_required")),
                        "contest_name": st["contest_name"]})

    def api_login(self, s, qs):
        ip = self.ip()
        if rate_limited(ip):
            raise ApiError(429, "Too many wrong PINs. Wait 10 minutes and try again.")
        pin = str(self.body().get("pin", "")).strip()
        st = get_settings()
        role, store_id = None, None
        if check_pin(pin, st.get("admin_pin_hash")):
            role = "admin"
        else:
            for r in db.q("SELECT id, pin_hash FROM stores ORDER BY sort,id"):
                if check_pin(pin, r["pin_hash"]):
                    role, store_id = "store", r["id"]
                    break
            if not role and check_pin(pin, st.get("view_pin_hash")):
                role = "view"
        if not role:
            note_fail(ip)
            time.sleep(0.4)
            raise ApiError(401, "Wrong PIN")
        FAILS.pop(ip, None)
        hours = 12 if role == "admin" else 24 * 30
        secure = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
        audit(f"{role}" + (f":{store_id}" if store_id else ""), "login", ip)
        self.send(200, {"role": role, "store_id": store_id},
                  headers={"Set-Cookie": f"{COOKIE}={make_cookie(role, store_id, hours)}; Path=/; HttpOnly; "
                                         f"SameSite=Lax; Max-Age={hours * 3600}{secure}"})

    def api_logout(self, s, qs):
        self.send(200, {"ok": True}, headers={"Set-Cookie": f"{COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"})

    # ------------------------------------------------------------------ public board
    def api_state(self, s, qs):
        self.need_view(s)
        st, stores, people, res = contest_state()
        self.send(200, {"settings": public_settings(st), "stores": stores,
                        "people": [{k: p[k] for k in ("id", "store_id", "name", "active")} for p in people],
                        "result": res, "me": {"role": s.get("role"), "store_id": s.get("store_id")},
                        "demo": bool(st.get("demo_today")), "generated": now_iso()})

    # ------------------------------------------------------------------ entry
    def api_entry_get(self, s, qs, store_id):
        self.need_store(s, store_id)
        store = db.one("SELECT id,name,short,color FROM stores WHERE id=?", (store_id,))
        if not store:
            raise ApiError(404, "No such store")
        st = get_settings()
        d = (qs.get("date") or [default_entry_date().isoformat()])[0]
        recent = db.q("SELECT d.*, p.name sp_name FROM deals d JOIN salespeople p ON p.id=d.sp_id "
                      "WHERE d.store_id=? ORDER BY d.date DESC, d.id DESC LIMIT 60", (store_id,))
        people = db.q("SELECT id,store_id,name,active FROM salespeople WHERE store_id=? ORDER BY sort,id", (store_id,))
        is_admin = s.get("role") == "admin"
        stores = db.q("SELECT id,name,short,color FROM stores ORDER BY sort,id") if is_admin else [store]
        self.send(200, {"store": store, "stores": stores, "date": d, "default_date": default_entry_date().isoformat(),
                        "today": today_local().isoformat(), "start_date": st["start_date"], "end_date": st["end_date"],
                        "closed_sundays": st.get("closed_sundays"), "appt_start": st["appt_start"], "appt_end": st["appt_end"],
                        "sections": [{"store": store, "grid": grid_for(int(store_id), d)}],
                        "grid": grid_for(int(store_id), d), "day_status": day_status(d) if is_admin else None,
                        "people": people, "recent": recent, "demo": bool(st.get("demo_today"))})

    def api_entry_all(self, s, qs):
        """Admin only: every store's grid for one date on one screen."""
        self.need_admin(s)
        st = get_settings()
        d = (qs.get("date") or [default_entry_date().isoformat()])[0]
        stores = db.q("SELECT id,name,short,color FROM stores ORDER BY sort,id")
        recent = db.q("SELECT d.*, p.name sp_name FROM deals d JOIN salespeople p ON p.id=d.sp_id "
                      "ORDER BY d.date DESC, d.id DESC LIMIT 120")
        people = db.q("SELECT p.id,p.store_id,p.name,p.active FROM salespeople p JOIN stores s ON s.id=p.store_id "
                      "ORDER BY s.sort, s.id, p.sort, p.id")
        self.send(200, {"store": None, "stores": stores, "date": d, "default_date": default_entry_date().isoformat(),
                        "today": today_local().isoformat(), "start_date": st["start_date"], "end_date": st["end_date"],
                        "closed_sundays": st.get("closed_sundays"), "appt_start": st["appt_start"], "appt_end": st["appt_end"],
                        "sections": [{"store": x, "grid": grid_for(x["id"], d)} for x in stores],
                        "day_status": day_status(d), "people": people, "recent": recent,
                        "demo": bool(st.get("demo_today"))})

    def _check_sp(self, sp_id, store_id):
        p = db.one("SELECT * FROM salespeople WHERE id=?", (sp_id,))
        if not p or int(p["store_id"]) != int(store_id):
            raise ApiError(400, "Salesperson is not on this store's roster")
        return p

    def api_grid_save(self, s, qs, store_id):
        """Replace the day's numbers for each salesperson row sent (edit-in-place for the whole store)."""
        self.need_store(s, store_id)
        b = self.body()
        d = valid_date(b.get("date"))
        rows = b.get("rows") or []
        clean = []
        for r in rows:
            sp = int(r.get("sp_id") or 0)
            self._check_sp(sp, store_id)
            new = num(r.get("new") or 0, "New units", 0, 30, 0.5)
            used = []
            for u in r.get("used") or []:
                g = num(u.get("gross"), "Used gross", -25000, 100000)
                used.append((0.5 if u.get("split") else 1.0, round(g, 2)))
            if len(used) > 20:
                raise ApiError(400, "Too many used deals for one day")
            # appointments: whole number; a row sent without "appt" (older page) leaves that day's appointments alone
            appt = int(num(r.get("appt") or 0, "Appointments", 0, 200, 1)) if "appt" in r else None
            clean.append((sp, new, used, appt))
        n = 0
        names = {p["id"]: p["name"] for p in db.q("SELECT id,name FROM salespeople WHERE store_id=?", (store_id,))}
        sname = (db.one("SELECT short FROM stores WHERE id=?", (store_id,)) or {}).get("short", store_id)
        with db.tx():
            for sp, new, used, appt in clean:
                kinds = "('new','used','appt')" if appt is not None else "('new','used')"
                db.conn.execute(f"DELETE FROM deals WHERE store_id=? AND sp_id=? AND date=? AND kind IN {kinds}", (store_id, sp, d))
                if appt:
                    db.conn.execute("INSERT INTO deals(store_id,sp_id,date,kind,units,gross,entered_by,created_at) "
                                    "VALUES(?,?,?,'appt',?,0,?,?)", (store_id, sp, d, appt, self.who(s), now_iso()))
                    n += 1
                if new > 0:
                    db.conn.execute("INSERT INTO deals(store_id,sp_id,date,kind,units,gross,entered_by,created_at) "
                                    "VALUES(?,?,?,'new',?,0,?,?)", (store_id, sp, d, new, self.who(s), now_iso()))
                    n += 1
                for units, g in used:
                    db.conn.execute("INSERT INTO deals(store_id,sp_id,date,kind,units,gross,entered_by,created_at) "
                                    "VALUES(?,?,?,'used',?,?,?,?)", (store_id, sp, d, units, g, self.who(s), now_iso()))
                    n += 1
        detail = "; ".join(f"{names.get(sp, sp)}: {new:g} new, " + (", ".join(f"{'½ ' if u < 1 else ''}${g:,.0f}" for u, g in used) or "no used")
                           + (f", {appt} appt" if appt is not None else "") for sp, new, used, appt in clean)
        audit(self.who(s), "grid-save", f"{sname} {d}: {detail}")
        self.send(200, {"ok": True, "rows_saved": n, "grid": grid_for(int(store_id), d)})

    def _deal_fields(self, b, store_id):
        sp = int(b.get("sp_id") or 0)
        self._check_sp(sp, store_id)
        kind = b.get("kind")
        if kind not in ("new", "used", "appt"):
            raise ApiError(400, "kind must be new, used or appt")
        d = valid_date(b.get("date"))
        if kind == "new":
            units = num(b.get("units"), "Units", 0.5, 30, 0.5)
            gross = 0
        elif kind == "appt":
            units = num(b.get("units"), "Appointments", 1, 200, 1)
            gross = 0
        else:
            units = 0.5 if b.get("split") or float(b.get("units") or 1) == 0.5 else 1.0
            gross = round(num(b.get("gross"), "Used gross", -25000, 100000), 2)
        note = str(b.get("note") or "")[:200]
        return sp, d, kind, units, gross, note

    def api_deal_add(self, s, qs, store_id):
        self.need_store(s, store_id)
        sp, d, kind, units, gross, note = self._deal_fields(self.body(), store_id)
        i = db.x("INSERT INTO deals(store_id,sp_id,date,kind,units,gross,note,entered_by,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                 (store_id, sp, d, kind, units, gross, note, self.who(s), now_iso()))
        audit(self.who(s), "deal-add", f"#{i} {self._desc(sp, d, kind, units, gross)}")
        self.send(200, {"ok": True, "id": i})

    def _deal(self, s, deal_id):
        d = db.one("SELECT * FROM deals WHERE id=?", (deal_id,))
        if not d:
            raise ApiError(404, "No such entry")
        self.need_store(s, d["store_id"])
        return d

    def _desc(self, sp_id, d, kind, units, gross):
        p = db.one("SELECT p.name, s.short FROM salespeople p JOIN stores s ON s.id=p.store_id WHERE p.id=?", (sp_id,)) or {}
        return f"{p.get('short', '?')} / {p.get('name', sp_id)} {d} {kind} {units:g}" + (f" ${gross:,.0f}" if kind == "used" else "")

    def api_deal_edit(self, s, qs, deal_id):
        old = self._deal(s, deal_id)
        b = self.body()
        store_id = old["store_id"]
        if s.get("role") == "admin":  # admin may re-assign a deal to a rep at another store
            p = db.one("SELECT store_id FROM salespeople WHERE id=?", (int(b.get("sp_id") or 0),))
            if p:
                store_id = p["store_id"]
        sp, d, kind, units, gross, note = self._deal_fields(b, store_id)
        db.x("UPDATE deals SET store_id=?,sp_id=?,date=?,kind=?,units=?,gross=?,note=?,updated_at=?,entered_by=? WHERE id=?",
             (store_id, sp, d, kind, units, gross, note, now_iso(), self.who(s), deal_id))
        audit(self.who(s), "deal-edit", f"#{deal_id}: {self._desc(old['sp_id'], old['date'], old['kind'], old['units'], old['gross'])}"
                                        f" -> {self._desc(sp, d, kind, units, gross)}")
        self.send(200, {"ok": True})

    def api_deal_delete(self, s, qs, deal_id):
        old = self._deal(s, deal_id)
        db.x("DELETE FROM deals WHERE id=?", (deal_id,))
        audit(self.who(s), "deal-delete", f"#{deal_id} {self._desc(old['sp_id'], old['date'], old['kind'], old['units'], old['gross'])}")
        self.send(200, {"ok": True})

    # ------------------------------------------------------------------ admin
    def api_admin_get(self, s, qs):
        self.need_admin(s)
        st, stores, people, res = contest_state()
        full = db.q("SELECT id,name,short,color,new_target,used_target,appt_target,contribution,sort, pin_hash IS NOT NULL AS has_pin "
                    "FROM stores ORDER BY sort,id")
        counts = {r["sp_id"]: r["n"] for r in db.q("SELECT sp_id, COUNT(*) n FROM deals GROUP BY sp_id")}
        for p in people:
            p["deal_rows"] = counts.get(p["id"], 0)
        pub = public_settings(st)
        pub["has_view_pin"] = bool(st.get("view_pin_hash"))
        self.send(200, {"settings": pub, "stores": full, "people": people,
                        "budget": res["payouts"]["budget"], "pool": res["payouts"]["pool"],
                        "budget_ok": res["payouts"]["budget_ok"], "periods": len(res["periods"]),
                        "deal_count": db.one("SELECT COUNT(*) n FROM deals")["n"],
                        "demo_count": db.one("SELECT COUNT(*) n FROM deals WHERE demo=1")["n"],
                        "audit": db.q("SELECT * FROM audit ORDER BY id DESC LIMIT 40"),
                        "env_pins": {k: bool(os.environ.get(k)) for k in ("ADMIN_PIN", "VIEW_PIN")},
                        "storage": storage_info()})

    def api_admin_settings(self, s, qs):
        self.need_admin(s)
        b = self.body()
        cur = get_settings()
        out = {}
        for k in ("contest_name", "tagline", "timezone"):
            if k in b:
                out[k] = str(b[k])[:120]
        if "timezone" in out:
            try:
                from zoneinfo import ZoneInfo
                ZoneInfo(out["timezone"])
            except Exception:
                raise ApiError(400, "Unknown time zone (use e.g. America/Detroit)")
        for k in ("start_date", "end_date"):
            if k in b:
                try:
                    out[k] = date.fromisoformat(b[k]).isoformat()
                except Exception:
                    raise ApiError(400, f"Bad {k}")
        sd = calc.to_date(out.get("start_date", cur["start_date"]))
        ed = calc.to_date(out.get("end_date", cur["end_date"]))
        if ed < sd or (ed - sd).days > 366:
            raise ApiError(400, "End date must be after start date (max 1 year)")
        if "closed_sundays" in b:
            out["closed_sundays"] = bool(b["closed_sundays"])
        for k in ("appt_start", "appt_end"):
            if k in b:
                try:
                    out[k] = date.fromisoformat(b[k]).isoformat()
                except Exception:
                    raise ApiError(400, f"Bad {k}")
        if calc.to_date(out.get("appt_end", cur["appt_end"])) < calc.to_date(out.get("appt_start", cur["appt_start"])):
            raise ApiError(400, "Appointment window: last day must be on or after the first day")
        for k, lo, hi in (("weight_new", 0, 100), ("weight_used", 0, 100), ("weight_appt", 0, 100),
                          ("points_new", 0, 100), ("points_per_1k", 0, 100), ("points_per_appt", 0, 100),
                          ("heavy_hitter", 0, 100000), ("hat_trick_units", 0.5, 50),
                          ("streak_days", 2, 60), ("bounty_days", 1, 366)):
            if k in b:
                out[k] = num(b[k], k, lo, hi)
        if "prizes" in b:
            p = b["prizes"]
            pr = {}
            for k in ("points", "new", "used", "appt"):
                arr = p.get(k, cur["prizes"][k])
                if not isinstance(arr, list) or len(arr) > 10:
                    raise ApiError(400, f"prizes.{k} must be a list")
                pr[k] = [num(x, f"{k} prize", 0, 100000) for x in arr]
            for k in ("hot_shot",):
                pr[k] = num(p.get(k, cur["prizes"][k]), f"{k} prize", 0, 100000)
            out["prizes"] = pr
        wts = [out.get(k, cur.get(k)) for k in ("weight_new", "weight_used", "weight_appt")]
        if all(w is not None for w in wts) and sum(float(w) for w in wts) <= 0:
            raise ApiError(400, "At least one store-score weight must be above 0")
        changes = []
        for k, v in out.items():
            if cur.get(k) != v:
                changes.append(f"{k}: {json.dumps(cur.get(k))} -> {json.dumps(v)}")
            set_setting(k, v)
        if changes:
            audit(self.who(s), "settings", "; ".join(changes))
        outside = db.one("SELECT COUNT(*) n FROM deals WHERE date < ? OR date > ?",
                         (get_settings()["start_date"], get_settings()["end_date"]))["n"]
        self.send(200, {"ok": True, "changes": changes, "entries_outside_dates": outside})

    def api_admin_store(self, s, qs, store_id):
        self.need_admin(s)
        b = self.body()
        if not db.one("SELECT 1 FROM stores WHERE id=?", (store_id,)):
            raise ApiError(404, "No such store")
        name = str(b.get("name") or "").strip()[:60]
        if not name:
            raise ApiError(400, "Store name required")
        color = str(b.get("color") or "#2563eb")
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise ApiError(400, "Color must look like #1e40af")
        old = db.one("SELECT name, short, color, new_target, used_target, appt_target, contribution FROM stores WHERE id=?", (store_id,))
        new = {"name": name, "short": str(b.get("short") or name)[:30], "color": color,
               "new_target": num(b.get("new_target"), "New target", 0, 10000),
               "used_target": num(b.get("used_target"), "Used gross target", 0, 1e8),
               "appt_target": num(b.get("appt_target", old["appt_target"]), "Appointment target", 0, 100000),
               "contribution": num(b.get("contribution"), "Contribution", 0, 1e6)}
        db.x("UPDATE stores SET name=?, short=?, color=?, new_target=?, used_target=?, appt_target=?, contribution=? WHERE id=?",
             (new["name"], new["short"], new["color"], new["new_target"], new["used_target"], new["appt_target"],
              new["contribution"], store_id))
        changes = [f"{k}: {old[k]} -> {v}" for k, v in new.items() if old[k] != v]
        if changes:
            audit(self.who(s), "store-edit", f"{old['name']}: " + "; ".join(changes))
        self.send(200, {"ok": True})

    def api_admin_person_add(self, s, qs):
        self.need_admin(s)
        b = self.body()
        sid = int(b.get("store_id") or 0)
        if not db.one("SELECT 1 FROM stores WHERE id=?", (sid,)):
            raise ApiError(400, "No such store")
        name = str(b.get("name") or "").strip()[:60]
        if not name:
            raise ApiError(400, "Name required")
        mx = db.one("SELECT COALESCE(MAX(sort),0) m FROM salespeople WHERE store_id=?", (sid,))["m"]
        i = db.x("INSERT INTO salespeople(store_id,name,sort) VALUES(?,?,?)", (sid, name, mx + 1))
        audit(self.who(s), "rep-add", f"{i} {name} store {sid}")
        self.send(200, {"ok": True, "id": i})

    def api_admin_person_edit(self, s, qs, pid):
        self.need_admin(s)
        b = self.body()
        p = db.one("SELECT * FROM salespeople WHERE id=?", (pid,))
        if not p:
            raise ApiError(404, "No such salesperson")
        name = str(b.get("name", p["name"])).strip()[:60] or p["name"]
        active = 1 if b.get("active", p["active"]) else 0
        placeholder = p["placeholder"] if name == p["name"] else 0
        db.x("UPDATE salespeople SET name=?, active=?, placeholder=? WHERE id=?", (name, active, placeholder, pid))
        audit(self.who(s), "rep-edit", f"{pid} {p['name']} -> {name} active={active}")
        self.send(200, {"ok": True})

    def api_admin_person_delete(self, s, qs, pid):
        self.need_admin(s)
        n = db.one("SELECT COUNT(*) n FROM deals WHERE sp_id=?", (pid,))["n"]
        if n:
            raise ApiError(400, f"This salesperson has {n} entries. Mark them inactive instead (or delete their entries first).")
        db.x("DELETE FROM salespeople WHERE id=?", (pid,))
        audit(self.who(s), "rep-delete", pid)
        self.send(200, {"ok": True})

    def api_admin_pin(self, s, qs):
        self.need_admin(s)
        b = self.body()
        which, pin = b.get("which"), str(b.get("pin") or "").strip()
        if which == "view" and pin == "":
            set_setting("view_pin_hash", None)
            set_setting("view_pin_required", False)
            audit(self.who(s), "pin", "view PIN removed (leaderboard open)")
            return self.send(200, {"ok": True})
        if not re.fullmatch(r"\d{4,8}", pin):
            raise ApiError(400, "PIN must be 4-8 digits")
        label = "admin" if which == "admin" else "view" if which == "view" else f"store:{int(b.get('store_id') or 0)}"
        for other, h in all_pin_hashes(exclude=label):
            if check_pin(pin, h):
                raise ApiError(400, "That PIN is already used by another role — pick a different one")
        h = hash_pin(pin)
        if which == "admin":
            set_setting("admin_pin_hash", h)
        elif which == "view":
            set_setting("view_pin_hash", h)
            set_setting("view_pin_required", True)
        elif which == "store":
            sid = int(b.get("store_id") or 0)
            if not db.one("SELECT 1 FROM stores WHERE id=?", (sid,)):
                raise ApiError(400, "No such store")
            db.x("UPDATE stores SET pin_hash=? WHERE id=?", (h, sid))
        else:
            raise ApiError(400, "which must be admin, view or store")
        audit(self.who(s), "pin", f"{label} PIN changed")
        self.send(200, {"ok": True})

    def api_admin_reset(self, s, qs):
        self.need_admin(s)
        b = self.body()
        if b.get("confirm") != "RESET":
            raise ApiError(400, 'Type RESET to confirm')
        n = db.one("SELECT COUNT(*) n FROM deals")["n"]
        db.x("DELETE FROM deals")
        set_setting("demo_today", None)
        audit(self.who(s), "reset", f"deleted {n} entries; demo mode off")
        self.send(200, {"ok": True, "deleted": n})

    def api_admin_demo(self, s, qs):
        self.need_admin(s)
        load_demo(self.who(s))
        self.send(200, {"ok": True})

    def api_admin_export(self, s, qs, what):
        self.need_admin(s)
        st, stores, people, res = contest_state()
        sname = {x["id"]: x["name"] for x in stores}
        pname = {x["id"]: x["name"] for x in people}
        if what == "deals":
            rows = db.q("SELECT * FROM deals ORDER BY date, store_id, sp_id, id")
            text = csv_text(["id", "date", "store", "salesperson", "type", "units", "used_gross", "note", "entered_by",
                             "created_at", "updated_at", "demo"],
                            [[r["id"], r["date"], sname.get(r["store_id"]), pname.get(r["sp_id"]), r["kind"], r["units"],
                              r["gross"] if r["kind"] == "used" else "", r["note"], r["entered_by"], r["created_at"],
                              r["updated_at"] or "", r["demo"]] for r in rows])
        elif what == "standings":
            text = csv_text(["store", "new_units", "new_target", "new_pct", "used_units", "used_gross",
                             "used_target", "used_pct", "appointments", "appt_target", "appt_pct", "goal_score"],
                            [[x["name"], x["new"], x["new_target"], x["new_pct"], x["used_units"], x["gross"],
                              x["used_target"], x["used_pct"], x["appts"], x["appt_target"], x["appt_pct"], x["score"]]
                             for x in res["stores"]])
        elif what == "individuals":
            text = csv_text(["salesperson", "store", "new_units", "used_units", "used_gross", "appointments", "showdown_points",
                             "best_used_deal", "badges", "projected_payout"],
                            [[x["name"], sname.get(x["store_id"]), x["new"], x["used_units"], x["gross"], x["appts"], x["points"],
                              x["best_deal"], " ".join(x["badges"]), x["projected"]] for x in res["leaderboards"]["new"]])
        elif what == "payouts":
            text = csv_text(["category", "label", "salesperson", "store", "amount", "status"],
                            [[l["cat"], l["label"], pname.get(l["person_id"], ""), sname.get(l["store_id"], ""),
                              f"{l['amount']:.2f}", l["status"]] for l in res["payouts"]["lines"]])
        elif what == "roster":
            text = csv_text(["id", "store", "name", "active", "placeholder"],
                            [[p["id"], sname.get(p["store_id"]), p["name"], p["active"], p["placeholder"]] for p in people])
        else:
            raise ApiError(404, "Unknown export")
        fn = f"showdown_{what}_{date.today().isoformat()}.csv"
        self.send(200, text, "text/csv; charset=utf-8", {"Content-Disposition": f'attachment; filename="{fn}"'})

    def api_admin_backup(self, s, qs):
        self.need_admin(s)
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
            tmp = tf.name
        try:
            dst = sqlite3.connect(tmp)
            with db.lock:
                db.conn.backup(dst)
            dst.close()
            with open(tmp, "rb") as f:
                data = f.read()
        finally:
            os.unlink(tmp)
        self.send(200, data, "application/octet-stream",
                  {"Content-Disposition": f'attachment; filename="showdown_backup_{date.today().isoformat()}.db"'})

    # ------------------------------------------------------------------ TOGR battle board (separate from the spiff contest)
    def api_togr_get(self, s, qs):
        try:
            with open(TOGR_FILE, encoding="utf-8") as f:
                j = json.load(f)
        except FileNotFoundError:
            j = {}
        self.send(200, {"ok": True, "data": j.get("data"), "updated": j.get("updated")})

    def api_togr_save(self, s, qs):
        ip = self.ip()
        if rate_limited(ip):
            raise ApiError(429, "Too many wrong passwords. Wait 10 minutes and try again.")
        b = self.body()
        u = str(b.get("user", "")).strip().lower()
        p = str(b.get("pass", ""))
        ok = hmac.compare_digest(u, TOGR_USER) and hmac.compare_digest(hashlib.sha256(p.encode()).hexdigest(), TOGR_PASS_SHA256)
        if not ok:
            note_fail(ip)
            time.sleep(0.4)
            return self.send(401, {"ok": False, "error": "auth"})
        data = b.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("reps"), list):
            raise ApiError(400, "bad data")
        now = int(time.time())
        with TOGR_LOCK:
            os.makedirs(os.path.dirname(TOGR_FILE) or ".", exist_ok=True)
            if os.path.exists(TOGR_FILE):
                bdir = os.path.join(os.path.dirname(TOGR_FILE), "togr_backups")
                os.makedirs(bdir, exist_ok=True)
                try:
                    import shutil
                    shutil.copyfile(TOGR_FILE, os.path.join(bdir, "togr_" + datetime.now().strftime("%Y%m%d_%H") + ".json"))
                except Exception:
                    pass
            tmp = TOGR_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"updated": now, "data": data}, f)
            os.replace(tmp, TOGR_FILE)
        self.send(200, {"ok": True, "updated": now})


ROUTES = [
    ("GET", r"/api/me", Handler.api_me),
    ("POST", r"/api/login", Handler.api_login),
    ("POST", r"/api/logout", Handler.api_logout),
    ("GET", r"/api/state", Handler.api_state),
    ("GET", r"/api/entry/all", Handler.api_entry_all),
    ("GET", r"/api/entry/(\d+)", Handler.api_entry_get),
    ("POST", r"/api/entry/(\d+)/grid", Handler.api_grid_save),
    ("POST", r"/api/entry/(\d+)/deal", Handler.api_deal_add),
    ("PUT", r"/api/deals/(\d+)", Handler.api_deal_edit),
    ("DELETE", r"/api/deals/(\d+)", Handler.api_deal_delete),
    ("GET", r"/api/admin", Handler.api_admin_get),
    ("PUT", r"/api/admin/settings", Handler.api_admin_settings),
    ("PUT", r"/api/admin/stores/(\d+)", Handler.api_admin_store),
    ("POST", r"/api/admin/people", Handler.api_admin_person_add),
    ("PUT", r"/api/admin/people/(\d+)", Handler.api_admin_person_edit),
    ("DELETE", r"/api/admin/people/(\d+)", Handler.api_admin_person_delete),
    ("POST", r"/api/admin/pin", Handler.api_admin_pin),
    ("POST", r"/api/admin/reset", Handler.api_admin_reset),
    ("POST", r"/api/admin/demo", Handler.api_admin_demo),
    ("GET", r"/api/admin/export/(\w+)\.csv", Handler.api_admin_export),
    ("GET", r"/api/admin/backup\.db", Handler.api_admin_backup),
    ("GET", r"/api/togr/board", Handler.api_togr_get),
    ("POST", r"/api/togr/board", Handler.api_togr_save),
]


def main():
    init_db()
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    srv.daemon_threads = True
    print(f"Lakeshore Showdown running on http://localhost:{PORT}  (db: {DB_PATH})", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
