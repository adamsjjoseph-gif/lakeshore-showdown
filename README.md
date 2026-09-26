# ⚡ Lakeshore Showdown: Sales Contest (Spiff) Website

A live leaderboard and daily sales entry site for a 3-store dealership contest:
**Chrysler Muskegon vs. Chrysler Grand Haven vs. Grand Haven Ford**, $10,500 prize pool, **Sat Sep 26 – Wed Sep 30, 2026** (ends 11:59:59 PM ET). Three categories: new units, used front gross, and **appointments** (appointments count Sat 9/26 – Tue 9/29).

- **Public leaderboard** (`/`): live countdown to the end, store battle, individual rankings (New Unit King, Used Gross Boss, Appointment Ace), Daily Hot Shot, projected payouts, trend charts. Works on phones and refreshes every minute.
- **Enter Sales** (`/enter`): each store manager enters the day's numbers (new units, appointments, used deals) for the whole store on one screen. Defaults to yesterday. Includes edit, delete and copy.
- **Admin** (`/admin`): rosters, targets (incl. appointment targets), contest dates, appointment window, prize amounts, score weights, PINs, CSV export, backup, demo data, reset to empty, and a persistent-disk check.
- **Rules**: `RULES.md`, printable one-pager `Spiff_Rules.pdf` (also served at `/Spiff_Rules.pdf` and `/rules`).

Tech: one Python file (`server.py`) using only the Python standard library, with SQLite for storage. There's no build step and nothing to `pip install`. It includes a Dockerfile, plus `render.yaml` and `fly.toml` for one-click-style deploys.

```
server.py        web server + API + auth (Python stdlib only)
calc.py          all contest math (store scores, rankings, bounties, payouts in exact cents)
demo.py          clearly fake demo data generator
static/          HTML/CSS/JS pages (leaderboard, entry, admin, login) + bundled font (Barlow Condensed, SIL OFL)
tests/           automated tests (math + full API)
tools/           screenshot script, UI smoke test, rules-PDF builder
RULES.md / Spiff_Rules.pdf   one-page rules sheet
```

## Demo PINs (change before launch!)

| Role | PIN | Can do |
|---|---|---|
| Admin | `9999` | everything: entry/corrections for any store and any contest day (All-stores grid), plus every setting |
| Chrysler Muskegon manager | `1111` | enter/edit that store's sales |
| Chrysler Grand Haven manager | `2222` | enter/edit that store's sales |
| Grand Haven Ford manager | `3333` | enter/edit that store's sales |
| Leaderboard | *(open)* | anyone with the link can view. Admin can require a view PIN |

There is one PIN pad for everyone. The site works out your role from the PIN, so every PIN must be different. PINs are stored as salted PBKDF2 hashes. After 8 wrong PINs from one address, logins lock for 10 minutes, and there's also a site-wide limit. **Use 6-digit PINs for managers and admin when you go live.**

---

## 1) Run it locally

You need Python 3.9 or newer (Mac/Linux have it; on Windows install from python.org).

```bash
cd spiff_site
python3 server.py              # open http://localhost:8080
PORT=8787 python3 server.py    # a different port
```

On the first run it creates `data/spiff.db` with the 3 stores, placeholder rosters ("Salesperson 1–7") and **fake demo data** (a yellow "DEMO MODE" banner shows on every page). Demo data is only auto-loaded when the contest hasn't started yet. To start empty instead, run `SEED_DEMO=0 python3 server.py`.

An existing database from the earlier Oct 1–31 version is migrated automatically on start (deals table rebuilt to allow appointment rows, `appt_target` column added, dates/prizes moved to the 5-day format once; entries, rosters, targets and PINs are kept).

Run the tests:

```bash
python3 -m unittest discover tests -v        # 37 tests: payout math ($10,500 total), appointments, Hot Shot, tie-breaks, splits, unwinds, API, PINs, CSV, reset, DB migration
```

Optional browser checks (need Node + `npm i playwright-core` + Chrome):
`node tools/ui_smoke.js http://localhost:8799` (run it against a throwaway server, because it edits data) and `node tools/screenshots.js http://localhost:8080`.

Rebuild the rules PDF after editing `RULES.md`: `python3 tools/build_rules_pdf.py http://localhost:8080`.

### Settings (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `8080` | web port |
| `DB_PATH` | `./data/spiff.db` | SQLite file. **It must be on persistent storage when hosted** |
| `ADMIN_PIN` | *(9999 on first run)* | if set, applied (hashed) at every start |
| `STORE_PIN_1`, `STORE_PIN_2`, `STORE_PIN_3` | *(1111/2222/3333 on first run)* | manager PINs in store order (Muskegon, GH Chrysler, GH Ford) |
| `VIEW_PIN` | *(not set = open)* | set it to require a PIN to view the leaderboard. An empty value makes the board open |
| `SECRET_KEY` | auto-generated & saved | signs login cookies |
| `SEED_DEMO` | `1` | `0` = don't load demo data on the very first start |
| `TZ_NAME` | `America/Detroit` | dealership time zone (used for "yesterday") |

PINs changed on the Admin page are saved in the database. PINs set with environment variables win again on every restart, so pick one approach.

---

## 2) Put it online (for a non-technical owner)

The site is a single small program that must keep **one file** (the database) safe. Every option below includes **persistent storage**. Without it, a restart would wipe your sales data.

### ⭐ Recommended: Render: about $7.25/month

Render's "Starter" web service is $7/month, plus a 1 GB disk at $0.25/month. HTTPS is included. (Render's free tier can't keep a disk, so don't use it.) Over October plus a week of setup, that's about **$10–15 total**, and you can delete the service after the contest.

**What you need:** an email address, a credit card, and about 30 minutes.

1. **Put the code on GitHub (free).**
   - Create an account at github.com, then click **New repository**. Name it `lakeshore-showdown`, choose **Private**, and click Create.
   - On the new repo page, click **"uploading an existing file"**. Drag in **everything inside** the `spiff_site` folder *except* the `data` folder, then click **Commit changes**.
2. **Create the site on Render.**
   - Sign up at render.com and choose **Sign in with GitHub**. Add a payment method under Billing.
   - Click **New +**, then **Blueprint**, and pick the `lakeshore-showdown` repo. Render reads `render.yaml` and sets up the web service and a 1 GB disk mounted at `/data` for you.
   - It will ask for **ADMIN_PIN, STORE_PIN_1, STORE_PIN_2, STORE_PIN_3**. Type four *different* 6-digit PINs, then click **Apply**.
   - Wait about 3–5 minutes for "Live". Your address looks like `https://lakeshore-showdown.onrender.com`.
3. **Set it up** (see the launch checklist below), then text the link to the sales teams.
4. *(Optional)* To use your own address, like `showdown.yourdealership.com`: in Render go to **Settings**, then **Custom Domains**, add the domain, and ask whoever manages your website/DNS to add the CNAME record Render shows you.

> No GitHub? On Render you can instead pick **New + → Web Service → Existing image** if someone publishes the Docker image for you. Either way, remember to add a **Disk** (mount path `/data`) and the env var `DB_PATH=/data/spiff.db`.

### Option B: Railway: about $5/month

Railway's Hobby plan is $5/month with $5 of usage included, which is enough for this app. Volumes cost $0.15/GB.
1. Put the code on GitHub (step 1 above). At railway.com, choose **New Project**, then **Deploy from GitHub repo**. Railway finds the Dockerfile.
2. In the service, go to **Settings**, then **Volumes**, and click **Add Volume** with mount path **`/data`**.
3. Under **Variables**, add `DB_PATH=/data/spiff.db`, `ADMIN_PIN`, `STORE_PIN_1..3`, and a long random `SECRET_KEY`.
4. Under **Settings**, then **Networking**, click **Generate Domain** to get your public link.

### Option C: Fly.io: roughly $2–4/month (more technical)

This option uses a command-line tool. Install `flyctl`, then in this folder run:
```bash
fly launch --copy-config --no-deploy        # accept the app name or choose one
fly volumes create showdown_data --size 1   # persistent disk for the database
fly secrets set ADMIN_PIN=xxxxxx STORE_PIN_1=xxxxxx STORE_PIN_2=xxxxxx STORE_PIN_3=xxxxxx SECRET_KEY=$(openssl rand -hex 32)
fly deploy
```

### Option D: A cheap VPS (DigitalOcean, Hetzner, Lightsail): about $4–6/month

On an Ubuntu server with Docker installed:
```bash
docker build -t showdown .
docker run -d --name showdown --restart unless-stopped -p 80:8080 \
  -v showdown_data:/data -e ADMIN_PIN=xxxxxx -e STORE_PIN_1=xxxxxx -e STORE_PIN_2=xxxxxx -e STORE_PIN_3=xxxxxx \
  showdown
```
For HTTPS, put Caddy in front: `caddy reverse-proxy --from showdown.yourdomain.com --to localhost:8080`.

### Launch checklist (do this before kickoff)

1. Open `/admin` and log in with the admin PIN.
2. **Rosters:** rename "Salesperson 1–7" to real names at each store, and add or remove people.
3. **Stores:** set each store's **new-unit target**, **used-gross target** and **appointment target** — sized for the contest length (5 days; appointments 4 days). Check the colors and the $3,500 contributions.
4. **Contest & Prizes:** confirm the dates and prizes. The green bar must say **Prizes $10,500 = Pool $10,500**. If you change the contest length, the number of Daily Hot Shot days changes too, so adjust the Hot Shot amount until the bar turns green.
5. **PINs:** confirm the manager PINs, and decide whether the leaderboard is open or needs a view PIN.
6. **Data:** click **Reset to empty**. This deletes the demo sales and removes the yellow banner.
7. Print `Spiff_Rules.pdf` for the huddles, and send managers their PIN plus the `/enter` link.

---

## Admin daily routine (the GM, about 5 minutes each morning)

The admin PIN can do everything a store manager can, for **every store and every day of the contest**. It can also change any setting mid-contest.

1. **Enter yesterday for each store.** Go to **Enter Sales**. Admin opens on **All stores** and on yesterday (Saturday on Mondays). The store tabs show which stores already have entries for that day ("✓ 12 entries" or "nothing entered"). Type or fix each rep's new units and used deals, then press **Save day**. You can also click one store's tab to work on just that store.
2. **Review.** Check the leaderboard. Fix typos or remove unwinds under **Recent entries** (Edit / ✕), for any store and any past day. Use ◀ ▶ or the calendar to go back to an earlier day. Saving a day again replaces that day's numbers.
3. **Done.** Every entry, edit, delete and setting change is written to the **Activity log** on the Admin page, with old → new values.

Mid-contest changes (Admin page) take effect on the leaderboard immediately:
- store targets, contributions, names and colors
- roster adds and renames. Deactivating a rep keeps their history; their deals still count for the store.
- prize amounts, Daily Hot Shot amount and period length, appointment window
- contest dates. Entries outside new dates are kept but don't count, and you get a warning.
- store-score weights (new / used / appointments), points (incl. per appointment), badge thresholds, closed Sundays, and time zone

**Every leaderboard number and what controls it** (all admin-editable):

| Leaderboard item | Comes from | Where admin changes it |
|---|---|---|
| New units, used units, used gross, appointments (store + individual boards) | sales entries (appointments only inside the appointment window) | Enter Sales (any store, any contest day), Recent entries edit/delete, Contest & Prizes (appointment window) |
| Store score %, progress bars, store ranking, "leading store" | entries ÷ store targets × weights | Stores (targets), Contest & Prizes (weights) |
| Per-rep averages, roster count | entries ÷ active reps | Rosters (active/inactive) |
| Prize pool | sum of store contributions | Stores (contribution) |
| Team pot and per-rep share | team prizes, qualifier units, active reps | Contest & Prizes, Rosters |
| New Unit King / Used Gross Boss / Appointment Ace payouts | entries + prize amounts | Enter Sales, Contest & Prizes |
| Store MVP and points | entries × points per unit / per $1K / per appointment | Contest & Prizes |
| Daily Hot Shot (days, leaders, amount) | contest dates + Hot Shot period length + entries | Contest & Prizes |
| Countdown, days left, "Day X of Y", pace marker, time bar | contest end date (11:59:59 PM) + time zone | Contest & Prizes |
| Yesterday's highlights (Deal of the Day, Top Closer, Store of the Day, hot streak) | entries for the latest day | Enter Sales |
| Trend + daily charts | entries ÷ current targets (recomputed for the whole history) | Enter Sales, Stores |
| Badges | entries + thresholds (Hat Trick units, Heavy Hitter $, On Fire days, closed Sundays) | Contest & Prizes |
| Names, store names/colors, contest name, tagline | settings | Rosters, Stores, Contest & Prizes |

The only thing not edited on the Admin page is the printable `Spiff_Rules.pdf`. It's a document: edit `RULES.md` and run `tools/build_rules_pdf.py`. The **How To Win** section on the leaderboard always shows the live settings.

## 3) Backups & exporting data to CSV

- **Admin page → Data** has download buttons:
  - **All entries CSV**: every deal row (date, store, salesperson, new/used, units, gross, who entered it, when)
  - **Store standings CSV**, **Individuals CSV**, **Payouts CSV** (who gets paid what: hand this to payroll), **Roster CSV**
  - **Full database backup**: a copy of the SQLite file. Restore it by putting it back at `DB_PATH` while the app is stopped.
- Suggested routine: download **All entries CSV** + **Full database backup** every Monday, and keep them in a shared folder. At the end, save **Payouts CSV** after the final lock.
- Every change (logins, entries, edits, deletes, settings, resets) is written to the **Activity log** on the Admin page.

---

## How the contest math works (short)

- **Store score** = ⅓ × (new units ÷ new target) + ⅓ × (used gross ÷ used-gross target) + ⅓ × (appointments ÷ appointment target), shown as % of target with a pace marker. The weights can be changed in Admin.
- **Appointments** are entered per rep per day (whole numbers) and only count when dated inside the appointment window (default Sat 9/26 – Tue 9/29, admin-editable). They are stored as `kind='appt'` rows in the `deals` table (`units` = count).
- **Individual boards:** new units (splits count 0.5), used front gross and appointments, all stores together. One winner each ($2,000 / $2,000 / $1,500).
- **Daily Hot Shot:** $150 each contest day (5 days) to the rep with the most Showdown Points that day (2 per new unit + 1 per $1,000 used gross + 0.5 per appointment). Tie-break: new units, then used gross, then split. Closed Sunday's prize rolls into the 1st-place team pot.
- **Payouts** are computed in whole cents, so they always add up to exactly the pool. Tied people split the prize money for the places they hold. Prizes nobody qualifies for roll into the 1st-place store's team pot. Team pots are split evenly among reps with at least 1 counted unit.
- "Projected" payouts show what would pay out if the contest ended today. Past days' Hot Shots show as "won".
- Full rules: `RULES.md` / `Spiff_Rules.pdf`.

## Known limitations

- Designed for a single server instance (SQLite). That's plenty for 3 stores and ~21 reps, but don't run multiple copies at once.
- PIN login is deliberately simple (shared PINs, not individual accounts). The activity log records *which role* made a change, not which person.
- The site trusts what managers type. Numbers should be checked against the DMS before the final lock (the rules require it).
- There's no email, text or push notification. People open the link, and the leaderboard auto-refreshes every minute.
- Payout amounts are a calculator for payroll. Taxes and pay-plan rules are handled outside the app.
