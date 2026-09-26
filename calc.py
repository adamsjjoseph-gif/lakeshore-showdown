"""
Contest math for the Lakeshore Showdown spiff.

Pure functions only (no database, no web) so the rules can be unit-tested.
All money is handled in integer CENTS internally so payouts always add up exactly.
"""
from collections import defaultdict
from datetime import date, timedelta

DEFAULT_PRIZES = {
    "team": [2500, 1000, 0],      # Store Battle: 1st / 2nd / 3rd place store (split among qualified reps)
    "new": [2000, 0, 0],          # New Unit King: top individual (all stores)
    "used": [2000, 0, 0],         # Used Gross Boss: top individual (all stores)
    "appt": [1500, 0, 0],         # Appointment Ace: top individual, appointments inside the appointment window
    "mvp": 250,                   # Store MVP: top Showdown Points at EACH store
    "hot_shot": 150,              # Daily Hot Shot: most Showdown Points that day (one prize per bounty period, default 1 day)
}
POOL_TOTAL = 10500                # 3 stores x $3,500
LEGACY_PRIZE_KEYS = ("top_gun", "big_fish")   # weekly bounties used before the 5-day format (ignored now)
DEFAULT_APPT_WINDOW = ("2026-09-26", "2026-09-29")

BADGES = {
    "hat_trick": {"icon": "🎩", "name": "Hat Trick", "desc": "3+ new units in one day"},
    "heavy_hitter": {"icon": "💣", "name": "Heavy Hitter", "desc": "A single used deal at or above the Heavy Hitter gross"},
    "on_fire": {"icon": "🔥", "name": "On Fire", "desc": "A deal on 3 selling days in a row"},
    "double_down": {"icon": "⚡", "name": "Double Down", "desc": "New AND used deal on the same day"},
    "opening_day": {"icon": "🚀", "name": "Opening Day", "desc": "Delivered a deal on day 1"},
}


def to_date(v):
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def c(dollars):
    """dollars -> integer cents"""
    return int(round(float(dollars or 0) * 100))


def split_cents(total, n):
    """Split integer cents into n shares that add up exactly (first shares get the extra pennies)."""
    if n <= 0:
        return []
    base, rem = divmod(int(total), n)
    return [base + (1 if i < rem else 0) for i in range(n)]


def tie_groups(items, key):
    """Sort items by key (desc) and return a list of tie-groups (lists of items with identical keys)."""
    out = []
    for it in sorted(items, key=key, reverse=True):
        k = key(it)
        if out and out[-1][0] == k:
            out[-1][1].append(it)
        else:
            out.append((k, [it]))
    return [g for _, g in out]


def award_places(groups, prizes):
    """
    groups: ranked tie-groups of ids. prizes: cents per place (1st, 2nd, ...).
    Tied people share the prizes for the places they occupy (e.g. two tied for 1st split 1st+2nd).
    Returns (awards{id: cents}, lines[...], unclaimed_cents).
    """
    awards, lines, pos = {}, [], 0
    for g in groups:
        if pos >= len(prizes):
            break
        k = len(g)
        places = list(range(pos + 1, min(pos + k, len(prizes)) + 1))
        pot = sum(prizes[pos:pos + k])
        shares = split_cents(pot, k)
        for gid, s in zip(g, shares):
            awards[gid] = awards.get(gid, 0) + s
        lines.append({"places": places, "ids": list(g), "shares": shares, "pot": pot, "tied": k > 1})
        pos += k
    unclaimed = sum(prizes) - sum(awards.values())
    return awards, lines, unclaimed


def contest_periods(start, end, days=7):
    """Bounty weeks (default 7 days) starting on the contest start date; the last one may be shorter."""
    start, end = to_date(start), to_date(end)
    days = max(1, int(days or 7))
    out, i, s = [], 1, start
    while s <= end:
        e = min(s + timedelta(days=days - 1), end)
        out.append({"n": i, "start": s, "end": e, "days": (e - s).days + 1})
        i += 1
        s = e + timedelta(days=1)
    return out


def prize_budget(prizes, n_stores, n_periods):
    """Total CENTS the prize settings will pay out (must equal the pool)."""
    p = {**DEFAULT_PRIZES, **(prizes or {})}
    parts = {
        "team": sum(c(x) for x in p["team"]),
        "new": sum(c(x) for x in p["new"]),
        "used": sum(c(x) for x in p["used"]),
        "appt": sum(c(x) for x in p["appt"]),
        "mvp": c(p["mvp"]) * n_stores,
        "hot_shot": c(p["hot_shot"]) * n_periods,
    }
    parts["total"] = sum(parts.values())
    return parts


def score_weights(cfg):
    """Store-battle weights for (new units, used gross, appointments), normalised to add up to 1.
    Settings hold relative weights (default 1/1/1 = equal thirds). Older databases only had weight_new (a % with
    used = 100 - new); for those, appointments get the average of the other two, which is equal thirds for 50/50."""
    if cfg.get("weight_used") is None:           # legacy: weight_new is a %, used = 100 - new
        wn = float(cfg.get("weight_new", 50) or 0)
        wu = max(0.0, 100 - wn)
        wa = float(cfg["weight_appt"]) if cfg.get("weight_appt") is not None else (wn + wu) / 2
    else:
        wn = float(cfg.get("weight_new") or 0)
        wu = float(cfg.get("weight_used") or 0)
        wa = float(cfg.get("weight_appt") or 0)
    tot = wn + wu + wa
    if tot <= 0:
        return 1 / 3, 1 / 3, 1 / 3
    return wn / tot, wu / tot, wa / tot


def appt_window(cfg):
    a = cfg.get("appt_start") or DEFAULT_APPT_WINDOW[0]
    b = cfg.get("appt_end") or DEFAULT_APPT_WINDOW[1]
    return to_date(a), to_date(b)


def _place_label(places):
    names = {1: "1st", 2: "2nd", 3: "3rd"}
    lab = lambda n: names.get(n, f"{n}th")
    if len(places) == 1:
        return lab(places[0])
    return "T-" + "/".join(lab(p) for p in places)


def compute(cfg, stores, people, deals, today):
    """
    cfg: settings dict (start_date, end_date, prizes, weight_new, points_new, points_per_1k,
         heavy_hitter, qualifier_units, closed_sundays)
    stores: [{id, name, short, color, new_target, used_target, contribution}]
    people: [{id, store_id, name, active}]
    deals:  [{id, store_id, sp_id, date, kind ('new'|'used'), units, gross}]
    today:  the date the contest considers "today" (data normally runs through yesterday)
    """
    start, end, today = to_date(cfg["start_date"]), to_date(cfg["end_date"]), to_date(today)
    P = {**DEFAULT_PRIZES, **(cfg.get("prizes") or {})}
    w_new, w_used, w_appt = score_weights(cfg)
    a_start, a_end = appt_window(cfg)
    pts_new = float(cfg.get("points_new", 2))
    pts_k = float(cfg.get("points_per_1k", 1))
    pts_appt = float(cfg.get("points_per_appt", 0.5) or 0)
    heavy_c = c(cfg.get("heavy_hitter", 4000))
    qual_units = float(cfg.get("qualifier_units", 1))
    closed_sun = bool(cfg.get("closed_sundays", True))
    hat_units = float(cfg.get("hat_trick_units", 3) or 3)
    streak_need = int(cfg.get("streak_days", 3) or 3)
    bounty_days = int(cfg.get("bounty_days", 1) or 1)

    total_days = (end - start).days + 1
    if today < start:
        status, elapsed, days_left = "upcoming", 0, total_days
    elif today > end:
        status, elapsed, days_left = "ended", total_days, 0
    else:
        status, elapsed, days_left = "live", (today - start).days, (end - today).days + 1
    pace = elapsed / total_days if total_days else 0

    store_ids = [s["id"] for s in stores]
    pmap = {p["id"]: p for p in people}

    # ---- clean deals: in contest window, known salesperson ----
    # new/used rows go in ds; appointment rows ('appt', units = count) only count inside the appointment window
    ds, aps = [], []
    for d in deals:
        dd = to_date(d["date"])
        if d["sp_id"] not in pmap or not (start <= dd <= end):
            continue
        row = {**d, "date": dd, "units": float(d["units"] or 0), "gross_c": c(d.get("gross") or 0)
               if d["kind"] == "used" else 0, "store_id": pmap[d["sp_id"]]["store_id"]}
        if d["kind"] == "appt":
            if a_start <= dd <= a_end:
                aps.append(row)
        else:
            ds.append(row)

    # ---- individual stats ----
    ps = {}
    for p in people:
        ps[p["id"]] = {"id": p["id"], "name": p["name"], "store_id": p["store_id"], "active": bool(p.get("active", 1)),
                       "new": 0.0, "used_units": 0.0, "gross_c": 0, "best_deal_c": None, "days": set(), "appts": 0.0,
                       "new_by_day": defaultdict(float), "used_days": set()}
    for d in ds:
        s = ps[d["sp_id"]]
        s["days"].add(d["date"])
        if d["kind"] == "new":
            s["new"] += d["units"]
            s["new_by_day"][d["date"]] += d["units"]
        else:
            s["used_units"] += d["units"]
            s["gross_c"] += d["gross_c"]
            s["used_days"].add(d["date"])
            if s["best_deal_c"] is None or d["gross_c"] > s["best_deal_c"]:
                s["best_deal_c"] = d["gross_c"]
    for a in aps:
        ps[a["sp_id"]]["appts"] += a["units"]
    for s in ps.values():
        s["points"] = round(s["new"] * pts_new + (s["gross_c"] / 100000.0) * pts_k + s["appts"] * pts_appt, 2)
        s["badges"] = _badges(s, start, heavy_c, closed_sun, hat_units, streak_need)
        s["streak"] = _current_streak(s["days"], min(today - timedelta(days=1), end), closed_sun)

    active = [s for s in ps.values() if s["active"]]
    unclaimed_notes = []
    payout_lines = []   # {cat, label, person_id, store_id, cents, status}
    rollover = 0

    # nothing to project before the contest starts or before the first deal is entered
    projecting = status != "upcoming" and bool(ds or aps)

    def emit(cat, label, pid, sid, cents, st):
        if not projecting:
            return
        payout_lines.append({"cat": cat, "label": label, "person_id": pid, "store_id": sid, "cents": cents, "status": st})

    indiv_status = "final" if status == "ended" else "projected"

    # ---- individual leaderboards ----
    def ranked(items, key):
        out, rank, prev = [], 0, None
        for i, it in enumerate(sorted(items, key=key, reverse=True)):
            k = key(it)
            if k != prev:
                rank, prev = i + 1, k
            out.append((rank, it))
        return out

    new_key = lambda s: (s["new"], s["gross_c"])
    used_key = lambda s: (s["gross_c"], s["new"])
    appt_key = lambda s: (s["appts"], s["new"], s["gross_c"])
    for cat, key, metric, prizes in (("new", new_key, "new", P["new"]), ("used", used_key, "gross_c", P["used"]),
                                     ("appt", appt_key, "appts", P["appt"])):
        elig = [s for s in active if s[metric] > 0]
        groups = [[x["id"] for x in g] for g in tie_groups(elig, key)]
        awards, lines, unc = award_places(groups, [c(x) for x in prizes])
        for ln in lines:
            for pid, sh in zip(ln["ids"], ln["shares"]):
                if sh:
                    emit(cat, _place_label(ln["places"]), pid, ps[pid]["store_id"], sh, indiv_status)
        if unc:
            rollover += unc
            unclaimed_notes.append({"cat": cat, "cents": unc})

    # ---- store MVPs ----
    for sid in store_ids:
        elig = [s for s in active if s["store_id"] == sid and s["points"] > 0]
        groups = tie_groups(elig, lambda s: (s["points"], s["new"]))
        mvp_c = c(P["mvp"])
        if groups:
            for s, sh in zip(groups[0], split_cents(mvp_c, len(groups[0]))):
                emit("mvp", "Store MVP" + (" (tie)" if len(groups[0]) > 1 else ""), s["id"], sid, sh, indiv_status)
        elif mvp_c:
            rollover += mvp_c
            unclaimed_notes.append({"cat": "mvp", "cents": mvp_c, "store_id": sid})

    # ---- Daily Hot Shot (one prize per bounty period; default period = 1 day) ----
    # Winner = most Showdown Points earned in that period (new units + used gross + appointments in the window).
    # Tie-break: more new units that day, then more used gross, then the tied reps split the prize.
    periods = contest_periods(start, end, bounty_days)
    hs_c = c(P["hot_shot"])
    active_ids = {s["id"] for s in active}
    for per in periods:
        if today > per["end"]:
            pst = "won"
        elif today >= per["start"]:
            pst = "live"
        else:
            pst = "upcoming"
        per["status"] = pst
        tot = defaultdict(lambda: [0.0, 0.0, 0])   # points, new units, gross cents
        for d in ds:
            if per["start"] <= d["date"] <= per["end"] and d["sp_id"] in active_ids:
                t = tot[d["sp_id"]]
                if d["kind"] == "new":
                    t[0] += d["units"] * pts_new
                    t[1] += d["units"]
                else:
                    t[0] += d["gross_c"] / 100000.0 * pts_k
                    t[2] += d["gross_c"]
        for a in aps:
            if per["start"] <= a["date"] <= per["end"] and a["sp_id"] in active_ids:
                tot[a["sp_id"]][0] += a["units"] * pts_appt
        cand = [(pid, (round(v[0], 6), v[1], v[2])) for pid, v in tot.items() if round(v[0], 6) > 0]
        per["hot_shot"] = None
        if cand and pst != "upcoming":
            g = tie_groups(cand, lambda x: x[1])[0]
            per["hot_shot"] = {"ids": sorted(x[0] for x in g), "points": round(g[0][1][0], 2), "new": g[0][1][1],
                               "gross": g[0][1][2] / 100}
            day_lab = per["start"].strftime("%a %-m/%-d") if per["days"] == 1 else f"Period {per['n']}"
            for (pid, _), sh in zip(sorted(g), split_cents(hs_c, len(g))):
                emit("hot_shot", f"Daily Hot Shot {day_lab}" + (" (tie)" if len(g) > 1 else ""), pid, ps[pid]["store_id"], sh,
                     "won" if pst == "won" else "leading")
        elif pst == "won" and hs_c:
            rollover += hs_c
            unclaimed_notes.append({"cat": "hot_shot", "cents": hs_c, "period": per["n"]})

    # ---- store battle ----
    st = {}
    for s in stores:
        mem = [p for p in ps.values() if p["store_id"] == s["id"]]
        act = [p for p in mem if p["active"]]
        new = sum(p["new"] for p in mem)
        uu = sum(p["used_units"] for p in mem)
        g = sum(p["gross_c"] for p in mem)
        ap = sum(p["appts"] for p in mem)
        nt, ut = float(s.get("new_target") or 0), float(s.get("used_target") or 0)
        at = float(s.get("appt_target") or 0)
        new_pct = new / nt if nt > 0 else 0.0
        used_pct = (g / 100.0) / ut if ut > 0 else 0.0
        appt_pct = ap / at if at > 0 else 0.0
        score = (w_new * new_pct + w_used * used_pct + w_appt * appt_pct) * 100
        hc = len(act) or 1
        st[s["id"]] = {"id": s["id"], "name": s["name"], "short": s.get("short") or s["name"], "color": s.get("color"),
                       "new": new, "used_units": uu, "gross": g / 100, "new_target": nt, "used_target": ut,
                       "new_pct": round(new_pct * 100, 2), "used_pct": round(used_pct * 100, 2), "score": round(score, 2),
                       "appts": ap, "appt_target": at, "appt_pct": round(appt_pct * 100, 2), "appts_per_rep": round(ap / hc, 2),
                       "_score": score, "_new_pct": new_pct, "headcount": len(act),
                       "new_per_rep": round(new / hc, 2), "gross_per_rep": round(g / 100 / hc, 2),
                       "qualifiers": [p["id"] for p in act if p["new"] + p["used_units"] >= qual_units]}
    if not projecting:
        rollover, unclaimed_notes = 0, []
    team_prizes = [c(x) for x in P["team"]] if projecting else []
    if team_prizes:
        team_prizes[0] += rollover
    sgroups = tie_groups(list(st.values()), lambda s: (round(s["_score"], 9), round(s["_new_pct"], 9)))
    rank = 1
    for g in sgroups:
        for s in g:
            s["rank"] = rank
        rank += len(g)
    s_awards, s_lines, s_unc = award_places([[s["id"] for s in g] for g in sgroups], team_prizes)
    team_status = "final" if status == "ended" else "projected"
    # a store with no qualified reps can't use its team pot -> it moves to the best-ranked store that has qualifiers
    ranked_ids = [x["id"] for g in sgroups for x in g]
    receivers = [sid for sid in ranked_ids if st[sid]["qualifiers"]]
    orphan = sum(v for sid, v in s_awards.items() if v and not st[sid]["qualifiers"])
    if orphan and receivers:
        for sid in list(s_awards):
            if not st[sid]["qualifiers"]:
                s_awards[sid] = 0
        s_awards[receivers[0]] = s_awards.get(receivers[0], 0) + orphan
    for sid, s in st.items():
        pot = s_awards.get(sid, 0)
        s["team_prize"] = pot / 100
        q = sorted(s["qualifiers"], key=lambda pid: (-ps[pid]["points"], ps[pid]["name"]))
        s["per_rep_share"] = (pot / len(q) / 100) if q else 0
        if pot and q:
            for pid, sh in zip(q, split_cents(pot, len(q))):
                emit("team", f"Store Battle {_place_label([s['rank']])} ({s['short']})", pid, sid, sh, team_status)
        elif pot:
            emit("team", f"Store Battle — no qualified reps at {s['short']}", None, sid, pot, "unclaimed")

    # ---- totals ----
    pool_c = sum(c(s.get("contribution") or 0) for s in stores)
    budget = prize_budget(P, len(stores), len(periods))
    upcoming_c = sum(hs_c for per in periods if per["status"] == "upcoming")
    assigned_c = sum(l["cents"] for l in payout_lines)
    by_person = defaultdict(int)
    for l in payout_lines:
        if l["person_id"] is not None:
            by_person[l["person_id"]] += l["cents"]
    # live-week bounties with no leader yet are still "up for grabs"
    live_open_c = 0
    for per in periods:
        if per["status"] == "live" and not per["hot_shot"]:
            live_open_c += hs_c

    # ---- leaderboards for display ----
    def person_row(s, extra):
        return {"id": s["id"], "name": s["name"], "store_id": s["store_id"], "new": s["new"],
                "used_units": s["used_units"], "gross": s["gross_c"] / 100, "points": s["points"], "appts": s["appts"],
                "best_deal": (s["best_deal_c"] or 0) / 100, "badges": s["badges"], "streak": s["streak"],
                "projected": by_person.get(s["id"], 0) / 100, **extra}

    lb_new = [person_row(s, {"rank": r}) for r, s in ranked(active, new_key)]
    lb_used = [person_row(s, {"rank": r}) for r, s in ranked(active, used_key)]
    lb_points = [person_row(s, {"rank": r}) for r, s in ranked(active, lambda s: (s["points"], s["new"]))]
    lb_appt = [person_row(s, {"rank": r}) for r, s in ranked(active, appt_key)]

    # ---- trend: cumulative store score by day ----
    last_data_day = min(end, today - timedelta(days=1))
    trend = {"dates": [], "stores": {sid: [] for sid in store_ids}, "daily_new": {sid: [] for sid in store_ids},
             "daily_gross": {sid: [] for sid in store_ids}, "daily_appt": {sid: [] for sid in store_ids}, "pace": []}
    if last_data_day >= start:
        cum_new = defaultdict(float)
        cum_g = defaultdict(int)
        cum_a = defaultdict(float)
        by_day = defaultdict(list)
        for d in ds + aps:
            by_day[d["date"]].append(d)
        day = start
        while day <= last_data_day:
            dn, dg, da = defaultdict(float), defaultdict(int), defaultdict(float)
            for d in by_day.get(day, []):
                if d["kind"] == "new":
                    dn[d["store_id"]] += d["units"]
                elif d["kind"] == "appt":
                    da[d["store_id"]] += d["units"]
                else:
                    dg[d["store_id"]] += d["gross_c"]
            trend["dates"].append(day.isoformat())
            trend["pace"].append(round(((day - start).days + 1) / total_days * 100, 2))
            for sid in store_ids:
                cum_new[sid] += dn[sid]
                cum_g[sid] += dg[sid]
                cum_a[sid] += da[sid]
                s = st[sid]
                np_ = cum_new[sid] / s["new_target"] if s["new_target"] else 0
                up_ = cum_g[sid] / 100 / s["used_target"] if s["used_target"] else 0
                ap_ = cum_a[sid] / s["appt_target"] if s["appt_target"] else 0
                trend["stores"][sid].append(round((w_new * np_ + w_used * up_ + w_appt * ap_) * 100, 2))
                trend["daily_new"][sid].append(dn[sid])
                trend["daily_gross"][sid].append(dg[sid] / 100)
                trend["daily_appt"][sid].append(da[sid])
            day += timedelta(days=1)

    # ---- highlights ("yesterday" = latest day with data up to yesterday) ----
    highlights = {}
    days_with = sorted({d["date"] for d in ds + aps if d["date"] <= last_data_day})
    if days_with:
        hd = days_with[-1]
        dd = [d for d in ds if d["date"] == hd]
        highlights["day"] = hd.isoformat()
        used = [d for d in dd if d["kind"] == "used"]
        if used:
            b = max(used, key=lambda d: d["gross_c"])
            highlights["deal_of_day"] = {"person_id": b["sp_id"], "gross": b["gross_c"] / 100, "split": b["units"] < 1}
        nd = defaultdict(float)
        for d in dd:
            if d["kind"] == "new":
                nd[d["sp_id"]] += d["units"]
        if nd:
            top = max(nd.values())
            highlights["top_closer"] = {"person_ids": [k for k, v in nd.items() if v == top], "units": top}
        ad = defaultdict(float)
        for a in aps:
            if a["date"] == hd:
                ad[a["sp_id"]] += a["units"]
        if ad:
            top = max(ad.values())
            highlights["top_setter"] = {"person_ids": [k for k, v in ad.items() if v == top], "appts": top}
        if len(trend["dates"]) >= 1:
            i = trend["dates"].index(hd.isoformat())
            gains = {sid: trend["stores"][sid][i] - (trend["stores"][sid][i - 1] if i > 0 else 0) for sid in store_ids}
            best = max(gains, key=gains.get)
            highlights["store_of_day"] = {"store_id": best, "gain": round(gains[best], 2)}
        hot = sorted([s for s in active if s["streak"] >= streak_need], key=lambda s: -s["streak"])
        highlights["hot"] = [{"person_id": s["id"], "streak": s["streak"]} for s in hot[:5]]

    for s in st.values():
        s.pop("_score"), s.pop("_new_pct")

    per_out = []
    for per in periods:
        per_out.append({"n": per["n"], "start": per["start"].isoformat(), "end": per["end"].isoformat(),
                        "days": per["days"], "status": per["status"], "hot_shot": per["hot_shot"]})

    return {
        "status": status, "today": today.isoformat(), "total_days": total_days, "elapsed_days": elapsed,
        "days_left": days_left, "pace_pct": round(pace * 100, 2),
        "stores": sorted(st.values(), key=lambda s: s["rank"]),
        "leaderboards": {"new": lb_new, "used": lb_used, "points": lb_points, "appt": lb_appt},
        "periods": per_out,
        "payouts": {
            "lines": [{**l, "amount": l["cents"] / 100} for l in payout_lines],
            "by_person": {pid: v / 100 for pid, v in by_person.items()},
            "pool": pool_c / 100, "budget": {k: v / 100 for k, v in budget.items()},
            "budget_ok": budget["total"] == pool_c,
            "assigned": assigned_c / 100, "upcoming": upcoming_c / 100, "open_live": live_open_c / 100,
            "rollover": rollover / 100, "unclaimed": unclaimed_notes,
            "unassigned_check": (pool_c - assigned_c - upcoming_c - live_open_c) / 100,
            "up_for_grabs": (pool_c - assigned_c) / 100, "projecting": projecting,
        },
        "trend": trend,
        "highlights": highlights,
        "badges": _badge_defs(hat_units, heavy_c, streak_need),
        "bounty_days": bounty_days,
        "appt_window": {"start": a_start.isoformat(), "end": a_end.isoformat(),
                        "status": "upcoming" if today < a_start else "closed" if today > a_end else "open"},
        "score_weights": {"new": round(w_new * 100, 2), "used": round(w_used * 100, 2), "appt": round(w_appt * 100, 2)},
    }


def _badge_defs(hat_units, heavy_c, streak_need):
    """Badge names/descriptions reflecting the admin's current thresholds."""
    d = {k: dict(v) for k, v in BADGES.items()}
    d["hat_trick"]["desc"] = f"{hat_units:g}+ new units in one day"
    d["heavy_hitter"]["desc"] = f"A single used deal of ${heavy_c / 100:,.0f}+ gross"
    d["on_fire"]["desc"] = f"A deal on {streak_need} selling days in a row"
    return d


def _badges(s, start, heavy_c, closed_sun, hat_units=3, streak_need=3):
    out = []
    if any(v >= hat_units for v in s["new_by_day"].values()):
        out.append("hat_trick")
    if s["best_deal_c"] is not None and heavy_c > 0 and s["best_deal_c"] >= heavy_c:
        out.append("heavy_hitter")
    if _longest_streak(s["days"], closed_sun) >= streak_need:
        out.append("on_fire")
    if any(d in s["used_days"] for d in s["new_by_day"]):
        out.append("double_down")
    if start in s["days"]:
        out.append("opening_day")
    return out


def _consecutive(a, b, closed_sun):
    gap = (b - a).days
    return gap == 1 or (closed_sun and gap == 2 and (a + timedelta(days=1)).weekday() == 6)


def _longest_streak(days, closed_sun):
    best = run = 0
    prev = None
    for d in sorted(days):
        run = run + 1 if prev is not None and _consecutive(prev, d, closed_sun) else 1
        best = max(best, run)
        prev = d
    return best


def _current_streak(days, last_day, closed_sun):
    """Streak of selling days ending on the last data day (or the selling day before it if closed Sunday)."""
    if not days:
        return 0
    ds = sorted(d for d in days if d <= last_day)
    if not ds:
        return 0
    end = ds[-1]
    gap_ok = (last_day - end).days == 0 or (closed_sun and (last_day - end).days == 1 and last_day.weekday() == 6)
    if not gap_ok:
        return 0
    run = 1
    for i in range(len(ds) - 1, 0, -1):
        if _consecutive(ds[i - 1], ds[i], closed_sun):
            run += 1
        else:
            break
    return run
