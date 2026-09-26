// Public leaderboard
let STATE = null, SHOW_ALL = { new: false, used: false };

async function load() {
  try {
    STATE = await api("/api/state");
  } catch (e) {
    if (e.status === 401) return toLogin();
    $("#app").innerHTML = `<div class="loading">Couldn't load: ${esc(e.message)}</div>`;
    return;
  }
  render();
}

function render() {
  const S = STATE, R = S.result, st = S.settings;
  if (!$(".topbar")) topbar("board", { ...S.me, contest_name: st.contest_name }, `${fmtDate(st.start_date, { month: "short", day: "numeric" })} – ${fmtDate(st.end_date, { month: "short", day: "numeric", year: "numeric" })}`);
  const P = {}; S.people.forEach((p) => (P[p.id] = p));
  const ST = {}; S.stores.forEach((s) => (ST[s.id] = s));
  const chip = (sid) => { const s = ST[sid]; return s ? `<span class="chip" style="background:${s.color}">${esc(s.short || s.name)}</span>` : ""; };
  const who = (pid) => (P[pid] ? `<b>${esc(P[pid].name)}</b> ${chip(P[pid].store_id)}` : "—");
  const badges = (arr) => (arr || []).map((b) => `<span title="${esc(R.badges[b].name)}: ${esc(R.badges[b].desc)}">${R.badges[b].icon}</span>`).join("");
  const pz = st.prizes;
  const leader = R.stores[0];
  const statusTxt = R.status === "upcoming" ? `Kicks off ${fmtDate(st.start_date)}` : R.status === "ended" ? "Final — contest over" : `Day ${R.elapsed_days + 1} of ${R.total_days}`;
  const po = R.payouts;

  let h = "";
  if (S.demo) h += `<div class="demo-banner">⚠ <b>Demo mode</b> — fake sample numbers, simulated as of ${fmtDate(st.demo_today)}. Admin → Data → "Reset to empty" before launch.</div>`;

  // HERO
  const leadTie = R.stores.length > 1 && R.stores[1].score === leader.score;
  h += `<section class="hero">
    <div class="card pool"><div class="k">💰 Total prize pool</div><div class="big num">${money(po.pool)}</div>
      <div class="muted">${esc(st.tagline)}</div>
      <div class="split">${S.stores.map((s) => `<span class="pill"><span style="color:${s.color}">●</span>${esc(s.short)} ${money(s.contribution)}</span>`).join("")}</div>
      <span class="emoji-bg">🏆</span></div>
    <div class="card days"><div class="k">⏱ ${R.status === "upcoming" ? "Days to kickoff" : "Days left"}</div>
      <div class="big num">${R.status === "upcoming" ? Math.max(0, Math.round((new Date(st.start_date) - new Date(R.today)) / 864e5)) : R.days_left}</div>
      <div class="muted">${statusTxt} · ends ${fmtDate(st.end_date)}</div>
      <div class="timebar"><i style="width:${R.pace_pct}%"></i></div><span class="emoji-bg">⏱</span></div>
    <div class="card lead" style="--c:${leader.color}"><div class="k">👑 ${R.status === "ended" ? "Champion" : "Leading store"}</div>
      <div class="big" style="color:${leadTie || R.status === "upcoming" ? "#fff" : leader.color}">${R.status === "upcoming" || leadTie ? "All square" : esc(leader.short)}</div>
      <div class="muted">${R.status === "upcoming" ? "Every store starts at 0%" : `${pct(leader.score, 1)} of target · pace ${pct(R.pace_pct)}`}</div><span class="emoji-bg">👑</span></div>
  </section>`;

  // STORE BATTLE
  h += `<section class="section"><div class="sec-h"><h2>The <span class="accent">Throwdown</span></h2>
    <span class="sub">Store vs. store · score = ${st.weight_new}% new units vs. target + ${100 - st.weight_new}% used gross vs. target — size doesn't matter, beating <i>your</i> target does.</span></div>
    <div class="battle">${R.stores.map((s, i) => {
      const medal = ["🥇", "🥈", "🥉"][s.rank - 1] || "";
      const bar = (v) => `<div class="bar"><i class="${v >= 100 ? "over" : ""}" style="width:${Math.min(100, v)}%"></i>${R.status === "live" ? `<span class="pace" style="left:${R.pace_pct}%"></span>` : ""}</div>`;
      return `<div class="card scard ${s.rank === 1 && po.projecting ? "first" : ""}" style="--c:${s.color}">
        <div class="top"><span class="rankbadge">${!po.projecting ? "—" : s.rank === 1 ? "1ST" : s.rank === 2 ? "2ND" : s.rank === 3 ? "3RD" : s.rank + "TH"}</span>
          <span class="sname">${esc(s.name)}</span><span class="crown">${po.projecting ? medal : ""}</span></div>
        <div class="score"><b class="num">${s.score.toFixed(1)}%</b><span>of<br>target</span></div>
        <div class="metric"><div class="lab"><span>🚗 New units</span><span><b class="num">${units(s.new)}</b> / ${units(s.new_target)} · ${pct(s.new_pct)}</span></div>${bar(s.new_pct)}</div>
        <div class="metric"><div class="lab"><span>💵 Used gross</span><span><b class="num">${money(s.gross, { k: true })}</b> / ${money(s.used_target, { k: true })} · ${pct(s.used_pct)}</span></div>${bar(s.used_pct)}</div>
        <div class="foot"><div class="pot">${po.projecting ? money(s.team_prize) : "🔓 Up for grabs"}<small>${s.team_prize ? `team pot → ${money(s.per_rep_share, { cents: false })}/rep (${s.qualifiers.length} qualified)` : po.projecting ? "no team pot at this spot" : `team pots up for grabs: ${pz.team.filter((x) => x > 0).map((x, i) => ["1st", "2nd", "3rd"][i] + " " + money(x)).join(" · ")}`}</small></div>
          <div class="avgs">Per rep: <b>${units(s.new_per_rep)}</b> new · <b>${money(s.gross_per_rep, { k: true })}</b> gross<br>${s.headcount} on roster · ${units(s.used_units)} used units</div></div>
      </div>`; }).join("")}</div></section>`;

  // HIGHLIGHTS
  const H = R.highlights;
  if (H.day) {
    const tc = H.top_closer;
    const hot = (H.hot || [])[0];
    const sod = H.store_of_day && ST[H.store_of_day.store_id];
    h += `<section class="section"><div class="sec-h"><h2>Yesterday's <span class="accent">Heat</span></h2><span class="sub">${fmtDate(H.day, { weekday: "long", month: "short", day: "numeric" })}</span></div>
    <div class="hl">
      <div class="card"><div class="ic">🎯</div><div class="k">Deal of the Day</div><div class="v gold num">${H.deal_of_day ? money(H.deal_of_day.gross) : "—"}</div>
        <div class="who">${H.deal_of_day ? who(H.deal_of_day.person_id) + (H.deal_of_day.split ? ' <span class="dim">(split)</span>' : "") : '<span class="muted">No used deals</span>'}</div></div>
      <div class="card"><div class="ic">🚀</div><div class="k">Top Closer · new units</div><div class="v num">${tc ? units(tc.units) : "—"}</div>
        <div class="who">${tc ? tc.person_ids.slice(0, 2).map(who).join("<br>") + (tc.person_ids.length > 2 ? `<br><span class="muted">+${tc.person_ids.length - 2} more tied</span>` : "") : '<span class="muted">No new units</span>'}</div></div>
      <div class="card"><div class="ic">📈</div><div class="k">Store of the Day</div><div class="v num" style="color:${sod ? sod.color : "#fff"}">+${H.store_of_day ? H.store_of_day.gain.toFixed(1) : 0} pts</div>
        <div class="who">${sod ? `<b>${esc(sod.name)}</b>` : ""}</div></div>
      <div class="card"><div class="ic">🔥</div><div class="k">Hottest streak</div><div class="v num">${hot ? hot.streak + " days" : "—"}</div>
        <div class="who">${hot ? who(hot.person_id) : '<span class="muted">Sell 3 days straight to get on fire</span>'}</div></div>
    </div></section>`;
  }

  // INDIVIDUAL LEADERBOARDS
  const lb = (key, title, icon, desc, valFn, metric, prizes) => {
    const rows = R.leaderboards[key];
    const max = Math.max(1e-9, ...rows.map((r) => r[metric]));
    const topPrizes = po.lines.filter((l) => l.cat === key);
    const prizeFor = (pid) => topPrizes.filter((l) => l.person_id === pid).reduce((a, l) => a + l.amount, 0);
    const lim = window.innerWidth < 640 ? 5 : 10;
    const shown = SHOW_ALL[key] ? rows : rows.slice(0, lim);
    return `<div class="card lb"><h3>${icon} ${title}</h3><div class="desc">${desc} · Prizes ${prizes.map((x) => money(x)).join(" / ")}</div>
      ${shown.map((r) => { const s = ST[r.store_id]; const pzv = prizeFor(r.id);
        return `<div class="row ${r.rank <= 3 && r[metric] > 0 ? "p" + r.rank : ""}">
          <div class="rk">${r[metric] > 0 ? (["🥇", "🥈", "🥉"][r.rank - 1] || r.rank) : "–"}</div>
          <div><div class="nm">${esc(r.name)} ${chip(r.store_id)} <span class="badges">${badges(r.badges)}</span></div>
            <div class="sub"><div class="mini"><i style="width:${Math.max(0, (r[metric] / max) * 100)}%;background:${s ? s.color : "#fff"}"></i></div></div></div>
          <div class="val"><b class="num">${valFn(r)}</b>${pzv ? `<span class="pz">${money(pzv)} ${R.status === "ended" ? "won" : "projected"}</span>` : ""}</div>
        </div>`; }).join("")}
      ${rows.length > lim ? `<button class="btn small more" data-more="${key}">${SHOW_ALL[key] ? `Show top ${lim}` : `Show all ${rows.length}`}</button>` : ""}</div>`;
  };
  h += `<section class="section"><div class="sec-h"><h2>Individual <span class="accent">Rankings</span></h2><span class="sub">All ${S.people.filter((p) => p.active).length} reps, all three stores, one board.</span></div>
    <div class="boards">
      ${lb("new", "New Unit King", "🏁", "Most new units delivered · splits = 0.5", (r) => units(r.new), "new", pz.new)}
      ${lb("used", "Used Gross Boss", "💰", "Most used-car front gross", (r) => money(r.gross, { k: true }), "gross", pz.used)}
    </div></section>`;

  // BOUNTIES
  h += `<section class="section"><div class="sec-h"><h2>Weekly <span class="accent">Bounties</span></h2><span class="sub">Every ${R.bounty_days === 7 ? "week" : R.bounty_days + "-day bounty period"}: 🎯 Top Gun (most new units) ${money(pz.top_gun)} · 🐟 Big Fish (biggest single used deal) ${money(pz.big_fish)}</span></div>
    <div class="weeks">${R.periods.map((w) => {
      const tag = w.status === "live" ? '<span class="pill live">● Live</span>' : w.status === "won" ? '<span class="pill won">Won</span>' : '<span class="pill">Up for grabs</span>';
      const names = (ids) => ids.map((id) => (P[id] ? `${esc(P[id].name)} <span class="dim">${esc((ST[P[id].store_id] || {}).short || "")}</span>` : "")).join(", ");
      const line = (ic, k, obj, val, amt) => `<div class="bty"><span class="ic">${ic}</span><div class="t"><div class="k">${k}${obj ? " · " + val : ""}</div>
        <div class="w">${obj ? names(obj.ids) : w.status === "upcoming" ? '<span class="dim">Starts ' + fmtDate(w.start) + "</span>" : '<span class="dim">Nobody yet</span>'}</div></div><span class="amt">${money(amt)}</span></div>`;
      return `<div class="card week ${w.status}"><div class="wh"><div><b>Week ${w.n}</b><div class="dim" style="font-size:12px">${fmtDate(w.start, { month: "short", day: "numeric" })} – ${fmtDate(w.end, { month: "short", day: "numeric" })}</div></div>${tag}</div>
        ${line("🎯", "Top Gun", w.top_gun, w.top_gun ? units(w.top_gun.units) + " units" : "", pz.top_gun)}
        ${line("🐟", "Big Fish", w.big_fish, w.big_fish ? money(w.big_fish.gross) : "", pz.big_fish)}</div>`; }).join("")}</div></section>`;

  // CHARTS
  h += `<section class="section"><div class="sec-h"><h2>The <span class="accent">Race</span></h2><span class="sub">Cumulative store score (% of target) by day vs. the pace line</span></div>
    <div class="charts"><div class="card chart">${lineChart(R, S.stores)}
      <div class="legend">${S.stores.map((s) => `<span><i style="background:${s.color}"></i>${esc(s.short)}</span>`).join("")}<span><i style="background:transparent;border:2px dashed #fff"></i>Pace to 100%</span></div></div>
      <div class="card chart">${barChart(R, S.stores)}<div class="legend">${S.stores.map((s) => `<span><i style="background:${s.color}"></i>${esc(s.short)}</span>`).join("")}<span>· daily new units, last 14 days</span></div></div></div></section>`;

  // MONEY
  const cats = [["team", "🏆 Store Battle (team pots)"], ["new", "🏁 New Unit King"], ["used", "💰 Used Gross Boss"], ["mvp", "⭐ Store MVPs"], ["top_gun", "🎯 Top Gun bounties"], ["big_fish", "🐟 Big Fish bounties"]];
  const catSum = (c) => po.lines.filter((l) => l.cat === c).reduce((a, l) => a + l.amount, 0);
  const earners = Object.entries(po.by_person).map(([pid, v]) => ({ pid: +pid, v })).sort((a, b) => b.v - a.v).slice(0, window.innerWidth < 640 ? 6 : 10);
  const mvps = S.stores.map((s) => ({ s, l: po.lines.filter((l) => l.cat === "mvp" && l.store_id === s.id) }));
  const ptsBy = {}; R.leaderboards.points.forEach((r) => (ptsBy[r.id] = r.points));
  h += `<section class="section"><div class="sec-h"><h2>Show Me The <span class="accent">Money</span></h2><span class="sub">${R.status === "ended" ? "Final payouts" : "If the contest ended today…"} · every dollar of the ${money(po.pool)} is accounted for</span></div>
    <div class="money">
      <div class="card"><table class="ptable"><thead><tr><th>Prize bucket</th><th class="amt">Budget</th><th class="amt">${R.status === "ended" ? "Paid" : "Projected"}</th></tr></thead><tbody>
        ${cats.map(([c, lab]) => { const b = c === "top_gun" ? po.budget.bounties / 2 : c === "big_fish" ? po.budget.bounties / 2 : po.budget[c];
          return `<tr><td>${lab}</td><td class="amt">${money(b)}</td><td class="amt">${money(catSum(c))}</td></tr>`; }).join("")}
        ${po.up_for_grabs > 0.004 ? `<tr><td class="muted">⏳ ${po.projecting ? "Bounties still up for grabs" : "Up for grabs — nothing sold yet"}</td><td class="amt"></td><td class="amt">${money(po.up_for_grabs)}</td></tr>` : ""}
        <tr class="total"><td>Total</td><td class="amt">${money(po.budget.total)}</td><td class="amt">${money(po.assigned + po.up_for_grabs)}</td></tr></tbody></table>
        ${po.rollover ? `<p class="muted" style="font-size:13px">Includes ${money(po.rollover)} of unclaimed prizes rolled into the 1st-place store's team pot.</p>` : ""}
        ${!po.budget_ok ? `<p class="bad"><b>⚠ Prize settings (${money(po.budget.total)}) don't match the pool (${money(po.pool)}). Admin needs to fix this.</b></p>` : ""}
        <h3 class="display" style="margin:18px 0 8px;font-size:22px">⭐ Store MVPs <span class="muted" style="font-size:14px;font-family:var(--body);font-style:normal;text-transform:none">most Showdown Points at each store · ${money(pz.mvp)} each</span></h3>
        <div class="mvps">${mvps.map(({ s, l }) => `<div class="mvp" style="--c:${s.color}"><span class="ic">⭐</span><div><div class="dim cond" style="font-size:12px">${esc(s.name)}</div>
          <div class="n">${l.length ? l.map((x) => esc(P[x.person_id].name)).join(" & ") : "—"}</div></div>
          <div class="v"><b class="num">${l.length ? ptsBy[l[0].person_id].toFixed(1) : 0}</b><div class="dim" style="font-size:12px">points</div></div></div>`).join("")}</div>
        <p class="dim" style="font-size:12px;margin-top:8px">Showdown Points = ${st.points_new} per new unit + ${st.points_per_1k} per $1,000 used gross.</p></div>
      <div class="card lb"><h3>🤑 Who's Getting Paid</h3><div class="desc">Projected total earnings per rep across every prize</div>
        ${earners.map((e, i) => { const p = P[e.pid]; const s = ST[p.store_id];
          return `<div class="row ${i === 0 ? "p1" : ""}"><div class="rk">${i + 1}</div><div><div class="nm">${esc(p.name)} ${chip(p.store_id)}</div>
            <div class="sub dim" style="font-size:12px">${po.lines.filter((l) => l.person_id === e.pid).map((l) => ({ team: "🏆 ", new: "🏁 New Units ", used: "💰 Used Gross ", mvp: "⭐ ", top_gun: "🎯 ", big_fish: "🐟 " }[l.cat] || "") + esc(l.label)).join(" · ")}</div></div>
            <div class="val"><b class="num gold">${money(e.v, { cents: false })}</b></div></div>`; }).join("") || '<p class="muted">No payouts yet — go sell something!</p>'}
      </div></div></section>`;

  // HOW IT WORKS
  h += `<section class="section"><div class="sec-h"><h2>How To <span class="accent">Win</span></h2><span class="sub"><a href="/Spiff_Rules.pdf" target="_blank">Full rules sheet (PDF)</a></span></div>
    <div class="how">
      <div class="card"><h4>🏆 Store Battle</h4><p>Your store's score = % of its own new-unit target and used-gross target. 1st place store: ${money(pz.team[0])} team pot, 2nd: ${money(pz.team[1])}, split evenly by every rep with ${st.qualifier_units}+ unit.</p></div>
      <div class="card"><h4>🏁 💰 Individual</h4><p>Top 3 in new units win ${pz.new.map((x) => money(x)).join("/")}; top 3 in used gross win ${pz.used.map((x) => money(x)).join("/")}. All stores on one board.</p></div>
      <div class="card"><h4>🎯 🐟 Weekly Bounties</h4><p>Every contest week: most new units wins ${money(pz.top_gun)}; biggest single used gross deal wins ${money(pz.big_fish)}.</p></div>
      <div class="card"><h4>⭐ Store MVP</h4><p>Most Showdown Points at your own store wins ${money(pz.mvp)} — every store crowns one.</p></div>
    </div>
    <div class="card" style="margin-top:12px"><div class="badge-legend">${Object.values(R.badges).map((b) => `<span>${b.icon} <b>${esc(b.name)}</b> <span class="muted">— ${esc(b.desc)}</span></span>`).join("")}</div></div>
  </section>
  <footer class="foot">Updated ${new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })} · refreshes every minute · Splits count 0.5 · Unwinds are removed</footer>`;

  $("#app").innerHTML = h;
  $$("[data-more]").forEach((b) => (b.onclick = () => { SHOW_ALL[b.dataset.more] = !SHOW_ALL[b.dataset.more]; render(); }));
}

function lineChart(R, stores) {
  const m = window.innerWidth < 640;
  const T = R.trend, W = m ? 360 : 640, H = m ? 250 : 300, L = 40, Rm = m ? 34 : 12, Tp = 14, B = 30;
  if (!T.dates.length) return `<div class="muted" style="padding:60px 0;text-align:center">The race chart lights up after day 1.</div>`;
  const n = R.total_days;
  const maxY = Math.max(100, ...stores.flatMap((s) => T.stores[s.id] || []), ...T.pace) * 1.05;
  const x = (i) => L + (i / Math.max(1, n - 1)) * (W - L - Rm);
  const y = (v) => Tp + (1 - v / maxY) * (H - Tp - B);
  let g = "";
  for (let v = 0; v <= maxY; v += 25) g += `<line x1="${L}" x2="${W - Rm}" y1="${y(v)}" y2="${y(v)}" stroke="rgba(255,255,255,${v === 100 ? 0.25 : 0.07})"/><text x="${L - 6}" y="${y(v) + 4}" fill="#64708f" font-size="11" text-anchor="end">${v}%</text>`;
  for (let i = 0; i < n; i += m ? 10 : 7) g += `<text x="${x(i)}" y="${H - 8}" fill="#64708f" font-size="11" text-anchor="middle">${fmtDate(addDays(R.trend.dates[0], i), { month: "short", day: "numeric" })}</text>`;
  const fullPace = Array.from({ length: n }, (_, i) => ((i + 1) / n) * 100);
  g += `<polyline fill="none" stroke="#fff" stroke-opacity=".55" stroke-width="2" stroke-dasharray="5 6" points="${fullPace.map((v, i) => `${x(i)},${y(v)}`).join(" ")}"/>`;
  stores.forEach((s) => {
    const arr = T.stores[s.id] || [];
    const pts = arr.map((v, i) => `${x(i)},${y(v)}`).join(" ");
    g += `<polygon fill="${s.color}" fill-opacity=".07" points="${x(0)},${y(0)} ${pts} ${x(arr.length - 1)},${y(0)}"/>`;
    g += `<polyline fill="none" stroke="${s.color}" stroke-width="3.5" stroke-linejoin="round" stroke-linecap="round" points="${pts}" style="filter:drop-shadow(0 0 6px ${s.color})"/>`;
    const li = arr.length - 1;
    g += `<circle cx="${x(li)}" cy="${y(arr[li])}" r="5.5" fill="${s.color}" stroke="#fff" stroke-width="2"/><text x="${x(li) + 9}" y="${y(arr[li]) + 4}" fill="#fff" font-size="12" font-weight="700">${arr[li].toFixed(0)}%</text>`;
  });
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Store score trend">${g}</svg>`;
}

function barChart(R, stores) {
  const m = window.innerWidth < 640;
  const T = R.trend, W = m ? 360 : 420, H = m ? 240 : 300, L = 28, Rm = 8, Tp = 14, B = 30;
  if (!T.dates.length) return `<div class="muted" style="padding:60px 0;text-align:center">Daily bars appear once sales roll in.</div>`;
  const days = T.dates.slice(-14), off = T.dates.length - days.length;
  const tot = days.map((_, i) => stores.reduce((a, s) => a + (T.daily_new[s.id][off + i] || 0), 0));
  const maxY = Math.max(4, ...tot) * 1.1;
  const bw = (W - L - Rm) / days.length;
  const y = (v) => Tp + (1 - v / maxY) * (H - Tp - B);
  let g = "";
  for (let v = 0; v <= maxY; v += Math.max(2, Math.ceil(maxY / 5 / 2) * 2)) g += `<line x1="${L}" x2="${W - Rm}" y1="${y(v)}" y2="${y(v)}" stroke="rgba(255,255,255,.07)"/><text x="${L - 5}" y="${y(v) + 4}" fill="#64708f" font-size="11" text-anchor="end">${v}</text>`;
  days.forEach((d, i) => {
    let acc = 0;
    stores.forEach((s) => {
      const v = T.daily_new[s.id][off + i] || 0;
      if (v) g += `<rect x="${L + i * bw + 2}" y="${y(acc + v)}" width="${bw - 4}" height="${y(acc) - y(acc + v)}" rx="2" fill="${s.color}"/>`;
      acc += v;
    });
    if (i % 2 === 0) g += `<text x="${L + i * bw + bw / 2}" y="${H - 8}" fill="#64708f" font-size="10" text-anchor="middle">${fmtDate(d, { month: "numeric", day: "numeric" })}</text>`;
  });
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Daily new units">${g}</svg>`;
}

load();
setInterval(load, 60000);
