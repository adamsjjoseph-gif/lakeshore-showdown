// Public leaderboard
let STATE = null, SHOW_ALL = { new: false, used: false, appt: false };
const md = (iso) => fmtDate(iso, { weekday: "short" }) + " " + fmtDate(iso, { month: "numeric", day: "numeric" });   // "Sat 9/26"
const apptWindowTxt = (st) => st.appt_start === st.appt_end ? md(st.appt_start) : `${md(st.appt_start)} – ${md(st.appt_end)}`;

// Live countdown to the contest end (end date 11:59:59 PM, dealership time zone). Updates every second.
function countdownHtml(st) {
  return `<section class="countdown card" id="countdown" data-end="${st.end_ts}">
    <div class="cd-k">⏱ <span id="cdLabel">Contest ends in</span></div>
    <div class="cd-clock" id="cdClock" aria-live="off"></div>
    <div class="cd-end">Ends <b>${fmtDate(st.end_date, { weekday: "short", month: "short", day: "numeric", year: "numeric" })} · 11:59:59 PM ${esc(st.tz_abbr === "EDT" || st.tz_abbr === "EST" ? "ET" : st.tz_abbr || "")}</b>
      <span class="cd-appt">📅 Appointments count ${apptWindowTxt(st)}</span></div>
  </section>`;
}
function tickCountdown() {
  const el = $("#countdown");
  if (!el) return;
  const left = Math.floor((+el.dataset.end - Date.now()) / 1000);
  if (left <= 0) {
    el.classList.add("over");
    $("#cdLabel").textContent = "Final";
    $("#cdClock").innerHTML = `<span class="cd-over">Contest over</span>`;
    return;
  }
  const d = Math.floor(left / 86400), h = Math.floor((left % 86400) / 3600), m = Math.floor((left % 3600) / 60), sec = left % 60;
  const u = (v, l) => `<span class="cd-u"><b class="num">${String(v).padStart(2, "0")}</b><small>${l}</small></span>`;
  $("#cdClock").innerHTML = u(d, d === 1 ? "day" : "days") + u(h, "hrs") + u(m, "min") + u(sec, "sec");
}
setInterval(tickCountdown, 1000);

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
  const multiStore = S.stores.length > 1;
  const chip = (sid) => { const s = ST[sid]; return s && multiStore ? `<span class="chip" style="background:${s.color}">${esc(s.short || s.name)}</span>` : ""; };
  const who = (pid) => (P[pid] ? `<b>${esc(P[pid].name)}</b> ${chip(P[pid].store_id)}` : "—");
  const badges = (arr) => (arr || []).map((b) => `<span title="${esc(R.badges[b].name)}: ${esc(R.badges[b].desc)}">${R.badges[b].icon}</span>`).join("");
  const pz = st.prizes;
  const store = R.stores[0] || { name: "", short: "", color: "#e11d48", score: 0, new: 0, new_target: 0, new_pct: 0, gross: 0, used_target: 0, used_pct: 0, appts: 0, appt_target: 0, appt_pct: 0, headcount: 0, new_per_rep: 0, gross_per_rep: 0, appts_per_rep: 0, used_units: 0 };
  const nReps = S.people.filter((p) => p.active).length;
  const topPts = R.leaderboards.points.filter((r) => r.points > 0 && r.rank === 1);
  const statusTxt = R.status === "upcoming" ? `Kicks off ${fmtDate(st.start_date)}` : R.status === "ended" ? "Final — contest over" : `Day ${R.elapsed_days + 1} of ${R.total_days}`;
  const po = R.payouts;
  const wtxt = (w) => (Math.abs(w - 100 / 3) < 0.05 ? "⅓" : pct(w, 0));

  let h = "";
  h += countdownHtml(st);
  if (S.demo) h += `<div class="demo-banner">⚠ <b>Demo mode</b> — fake sample numbers, simulated as of ${fmtDate(st.demo_today)}. Admin → Data → "Reset to empty" before launch.</div>`;

  // HERO
  h += `<section class="hero">
    <div class="card pool"><div class="k">💰 Total prize pool</div><div class="big num">${money(po.pool)}</div>
      <div class="muted">${esc(st.tagline)}</div>
      <div class="split"><span class="pill"><span style="color:${store.color}">●</span>${esc(store.name)}</span><span class="pill">👥 ${nReps} closers</span><span class="pill">🔥 ${R.periods.length} Hot Shots</span></div>
      <span class="emoji-bg">🏆</span></div>
    <div class="card days"><div class="k">⏱ ${R.status === "upcoming" ? "Days to kickoff" : "Days left"}</div>
      <div class="big num">${R.status === "upcoming" ? Math.max(0, Math.round((new Date(st.start_date) - new Date(R.today)) / 864e5)) : R.days_left}</div>
      <div class="muted">${statusTxt} · ends ${fmtDate(st.end_date)}</div>
      <div class="timebar"><i style="width:${R.pace_pct}%"></i></div><span class="emoji-bg">⏱</span></div>
    <div class="card lead" style="--c:${store.color}"><div class="k">👑 ${R.status === "ended" ? "Showdown Champion" : "Showdown leader"}</div>
      <div class="big" style="color:${topPts.length === 1 ? "var(--gold)" : "#fff"}">${!topPts.length ? "Wide open" : topPts.length > 1 ? "Dead heat" : esc(topPts[0].name)}</div>
      <div class="muted">${!topPts.length ? "Everybody starts at 0 points" : `${topPts[0].points.toFixed(1)} Showdown Points${topPts.length > 1 ? " · " + topPts.map((r) => esc(r.name)).join(" & ") : ""}`}</div><span class="emoji-bg">👑</span></div>
  </section>`;

  // STORE GOAL (one store: progress vs. its own targets, no store-vs-store ranking)
  const bar = (v) => `<div class="bar"><i class="${v >= 100 ? "over" : ""}" style="width:${Math.min(100, v)}%"></i>${R.status === "live" ? `<span class="pace" style="left:${R.pace_pct}%"></span>` : ""}</div>`;
  h += `<section class="section"><div class="sec-h"><h2>The <span class="accent">Goal</span></h2>
    <span class="sub">${esc(store.name)} vs. its targets · score = ${wtxt(R.score_weights.new)} new units + ${wtxt(R.score_weights.used)} used gross + ${wtxt(R.score_weights.appt)} appointments. Every deal you post moves the whole store. 📅 Appointments count ${apptWindowTxt(st)}.</span></div>
    <div class="battle solo"><div class="card scard first" style="--c:${store.color}">
        <div class="top"><span class="rankbadge">TEAM</span><span class="sname">${esc(store.name)}</span><span class="crown">🎯</span></div>
        <div class="score"><b class="num">${store.score.toFixed(1)}%</b><span>of<br>target</span></div>
        <div class="metric"><div class="lab"><span>🚗 New units</span><span><b class="num">${units(store.new)}</b> / ${units(store.new_target)} · ${pct(store.new_pct)}</span></div>${bar(store.new_pct)}</div>
        <div class="metric"><div class="lab"><span>💵 Used gross</span><span><b class="num">${money(store.gross, { k: true })}</b> / ${money(store.used_target, { k: true })} · ${pct(store.used_pct)}</span></div>${bar(store.used_pct)}</div>
        <div class="metric appt"><div class="lab"><span>📅 Appointments <span class="dim" style="font-size:11px">${apptWindowTxt(st)}</span></span><span><b class="num">${units(store.appts)}</b> / ${units(store.appt_target)} · ${pct(store.appt_pct)}</span></div>${bar(store.appt_pct)}</div>
        <div class="foot"><div class="pot">${R.status === "live" ? `Pace ${pct(R.pace_pct)}` : R.status === "upcoming" ? "0%" : "Final"}<small>${R.status === "live" ? (store.score >= R.pace_pct ? "🔥 ahead of pace" : "⚡ behind pace — pick it up") : "time elapsed"}</small></div>
          <div class="avgs">Per rep: <b>${units(store.new_per_rep)}</b> new · <b>${money(store.gross_per_rep, { k: true })}</b> gross · <b>${units(store.appts_per_rep)}</b> appts<br>${store.headcount} on roster · ${units(store.used_units)} used units</div></div>
      </div></div></section>`;

  // HIGHLIGHTS
  const H = R.highlights;
  if (H.day) {
    const tc = H.top_closer;
    const hot = (H.hot || [])[0];
    h += `<section class="section"><div class="sec-h"><h2>Yesterday's <span class="accent">Heat</span></h2><span class="sub">${fmtDate(H.day, { weekday: "long", month: "short", day: "numeric" })}</span></div>
    <div class="hl">
      <div class="card"><div class="ic">🎯</div><div class="k">Deal of the Day</div><div class="v gold num">${H.deal_of_day ? money(H.deal_of_day.gross) : "—"}</div>
        <div class="who">${H.deal_of_day ? who(H.deal_of_day.person_id) + (H.deal_of_day.split ? ' <span class="dim">(split)</span>' : "") : '<span class="muted">No used deals</span>'}</div></div>
      <div class="card"><div class="ic">🚀</div><div class="k">Top Closer · new units</div><div class="v num">${tc ? units(tc.units) : "—"}</div>
        <div class="who">${tc ? tc.person_ids.slice(0, 2).map(who).join("<br>") + (tc.person_ids.length > 2 ? `<br><span class="muted">+${tc.person_ids.length - 2} more tied</span>` : "") : '<span class="muted">No new units</span>'}</div></div>
      <div class="card"><div class="ic">📅</div><div class="k">Top Setter · appointments</div><div class="v num">${H.top_setter ? units(H.top_setter.appts) : "—"}</div>
        <div class="who">${H.top_setter ? H.top_setter.person_ids.slice(0, 2).map(who).join("<br>") + (H.top_setter.person_ids.length > 2 ? `<br><span class="muted">+${H.top_setter.person_ids.length - 2} more tied</span>` : "") : '<span class="muted">No appointments</span>'}</div></div>
      <div class="card"><div class="ic">📈</div><div class="k">Goal gained</div><div class="v num" style="color:${store.color}">+${H.store_of_day ? H.store_of_day.gain.toFixed(1) : 0}%</div>
        <div class="who"><b>${esc(store.short || store.name)}</b> <span class="muted">toward target</span></div></div>
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
    const paid = prizes.filter((x) => x > 0);
    return `<div class="card lb lb-${key}"><h3>${icon} ${title}</h3><div class="desc">${desc} · ${paid.length > 1 ? "Prizes " + paid.map((x) => money(x)).join(" / ") : "Winner takes " + money(paid[0] || 0)}</div>
      ${shown.map((r) => { const s = ST[r.store_id]; const pzv = prizeFor(r.id);
        return `<div class="row ${r.rank <= 3 && r[metric] > 0 ? "p" + r.rank : ""}">
          <div class="rk">${r[metric] > 0 ? (["🥇", "🥈", "🥉"][r.rank - 1] || r.rank) : "–"}</div>
          <div><div class="nm">${esc(r.name)} ${chip(r.store_id)} <span class="badges">${badges(r.badges)}</span></div>
            <div class="sub"><div class="mini"><i style="width:${Math.max(0, (r[metric] / max) * 100)}%;background:${s ? s.color : "#fff"}"></i></div></div></div>
          <div class="val"><b class="num">${valFn(r)}</b>${pzv ? `<span class="pz">${money(pzv)} ${R.status === "ended" ? "won" : "projected"}</span>` : ""}</div>
        </div>`; }).join("")}
      ${rows.length > lim ? `<button class="btn small more" data-more="${key}">${SHOW_ALL[key] ? `Show top ${lim}` : `Show all ${rows.length}`}</button>` : ""}</div>`;
  };
  h += `<section class="section"><div class="sec-h"><h2>Individual <span class="accent">Rankings</span></h2><span class="sub">All ${nReps} closers at ${esc(store.name)}, one board.</span></div>
    <div class="boards four">
      ${lb("points", "Showdown Champion", "👑", `Most Showdown Points (${st.points_new}/new unit + ${st.points_per_1k}/$1K used gross + ${st.points_per_appt}/appt)`, (r) => r.points.toFixed(1), "points", pz.points)}
      ${lb("new", "New Unit King", "🏁", "Most new units delivered · splits = 0.5", (r) => units(r.new), "new", pz.new)}
      ${lb("used", "Used Gross Boss", "💰", "Most used-car front gross", (r) => money(r.gross, { k: true }), "gross", pz.used)}
      ${lb("appt", "Appointment Ace", "📅", `Most appointments set · counts ${apptWindowTxt(st)} only`, (r) => units(r.appts), "appts", pz.appt)}
    </div></section>`;

  // DAILY HOT SHOT
  h += `<section class="section"><div class="sec-h"><h2>Daily <span class="accent">Hot Shot</span></h2><span class="sub">🔥 ${money(pz.hot_shot)} every ${R.bounty_days === 1 ? "day" : R.bounty_days + "-day period"} to the rep with the most Showdown Points (${st.points_new} per new unit + ${st.points_per_1k} per $1,000 used gross + ${st.points_per_appt} per appointment)</span></div>
    <div class="weeks days5">${R.periods.map((w) => {
      const tag = w.status === "live" ? '<span class="pill live">● Live</span>' : w.status === "won" ? '<span class="pill won">Won</span>' : '<span class="pill">Up for grabs</span>';
      const names = (ids) => ids.map((id) => (P[id] ? esc(P[id].name) : "")).join(", ");
      const hs = w.hot_shot;
      const title = w.days === 1 ? fmtDate(w.start, { weekday: "short" }) : `Period ${w.n}`;
      const sub = w.days === 1 ? fmtDate(w.start, { month: "short", day: "numeric" }) : `${fmtDate(w.start, { month: "short", day: "numeric" })} – ${fmtDate(w.end, { month: "short", day: "numeric" })}`;
      return `<div class="card week ${w.status}"><div class="wh"><div><b>${title}</b><div class="dim" style="font-size:12px">${sub}</div></div>${tag}</div>
        <div class="bty"><span class="ic">🔥</span><div class="t"><div class="k">Hot Shot${hs ? " · " + hs.points.toFixed(1) + " pts" : ""}</div>
        <div class="w">${hs ? names(hs.ids) : w.status === "upcoming" ? '<span class="dim">Starts ' + fmtDate(w.start) + "</span>" : '<span class="dim">Nobody yet</span>'}</div></div><span class="amt">${money(pz.hot_shot)}</span></div></div>`; }).join("")}</div></section>`;

  // CHARTS
  h += `<section class="section"><div class="sec-h"><h2>The <span class="accent">Race</span></h2><span class="sub">${esc(store.name)} cumulative goal score (% of target) by day vs. the pace line</span></div>
    <div class="charts"><div class="card chart">${lineChart(R, S.stores)}
      <div class="legend">${S.stores.map((s) => `<span><i style="background:${s.color}"></i>${esc(s.short)}</span>`).join("")}<span><i style="background:transparent;border:2px dashed #fff"></i>Pace to 100%</span></div></div>
      <div class="card chart">${barChart(R, S.stores)}<div class="legend">${S.stores.map((s) => `<span><i style="background:${s.color}"></i>${esc(s.short)}</span>`).join("")}<span>· daily new units, last 14 days</span></div></div></div></section>`;

  // MONEY
  const cats = [["points", "👑 Showdown Champion"], ["new", "🏁 New Unit King"], ["used", "💰 Used Gross Boss"], ["appt", "📅 Appointment Ace"], ["hot_shot", "🔥 Daily Hot Shots"]];
  const catSum = (c) => po.lines.filter((l) => l.cat === c).reduce((a, l) => a + l.amount, 0);
  const earners = Object.entries(po.by_person).map(([pid, v]) => ({ pid: +pid, v })).sort((a, b) => b.v - a.v).slice(0, window.innerWidth < 640 ? 6 : 10);
  h += `<section class="section"><div class="sec-h"><h2>Show Me The <span class="accent">Money</span></h2><span class="sub">${R.status === "ended" ? "Final payouts" : "If the contest ended today…"} · every dollar of the ${money(po.pool)} is accounted for</span></div>
    <div class="money">
      <div class="card"><table class="ptable"><thead><tr><th>Prize bucket</th><th class="amt">Budget</th><th class="amt">${R.status === "ended" ? "Paid" : "Projected"}</th></tr></thead><tbody>
        ${cats.map(([c, lab]) => { const b = po.budget[c];
          return `<tr><td>${lab}</td><td class="amt">${money(b)}</td><td class="amt">${money(catSum(c))}</td></tr>`; }).join("")}
        ${po.up_for_grabs > 0.004 ? `<tr><td class="muted">⏳ ${po.projecting ? "Daily Hot Shots still up for grabs" : "Up for grabs — nothing entered yet"}</td><td class="amt"></td><td class="amt">${money(po.up_for_grabs)}</td></tr>` : ""}
        <tr class="total"><td>Total</td><td class="amt">${money(po.budget.total)}</td><td class="amt">${money(po.assigned + po.up_for_grabs)}</td></tr></tbody></table>
        ${po.rollover ? `<p class="muted" style="font-size:13px">Includes ${money(po.rollover)} of unclaimed prizes rolled into the Showdown Champion 1st-place prize.</p>` : ""}
        ${!po.budget_ok ? `<p class="bad"><b>⚠ Prize settings (${money(po.budget.total)}) don't match the pool (${money(po.pool)}). Admin needs to fix this.</b></p>` : ""}
        <p class="dim" style="font-size:12px;margin-top:8px">Showdown Points = ${st.points_new} per new unit + ${st.points_per_1k} per $1,000 used gross + ${st.points_per_appt} per appointment (${apptWindowTxt(st)}).</p></div>
      <div class="card lb"><h3>🤑 Who's Getting Paid</h3><div class="desc">Projected total earnings per rep across every prize</div>
        ${earners.map((e, i) => { const p = P[e.pid]; const s = ST[p.store_id];
          return `<div class="row ${i === 0 ? "p1" : ""}"><div class="rk">${i + 1}</div><div><div class="nm">${esc(p.name)} ${chip(p.store_id)}</div>
            <div class="sub dim" style="font-size:12px">${po.lines.filter((l) => l.person_id === e.pid).map((l) => ({ points: "👑 ", new: "🏁 New Units ", used: "💰 Used Gross ", appt: "📅 Appointments ", hot_shot: "🔥 " }[l.cat] || "") + esc(l.label)).join(" · ")}</div></div>
            <div class="val"><b class="num gold">${money(e.v, { cents: false })}</b></div></div>`; }).join("") || '<p class="muted">No payouts yet — go sell something!</p>'}
      </div></div></section>`;

  // HOW IT WORKS
  h += `<section class="section"><div class="sec-h"><h2>How To <span class="accent">Win</span></h2><span class="sub"><a href="/Spiff_Rules.pdf" target="_blank">Full rules sheet (PDF)</a></span></div>
    <div class="how">
      <div class="card"><h4>👑 Showdown Champion</h4><p>Most Showdown Points for the whole contest: ${pz.points.filter((x) => x > 0).map((x, i) => ["1st", "2nd", "3rd"][i] + " " + money(x)).join(" · ")}. Points = ${st.points_new} per new unit + ${st.points_per_1k} per $1,000 used gross + ${st.points_per_appt} per appointment.</p></div>
      <div class="card"><h4>🏁 💰 📅 Category kings</h4><p>New Unit King ${pz.new.filter((x) => x > 0).map((x) => money(x)).join("/")} · Used Gross Boss ${pz.used.filter((x) => x > 0).map((x) => money(x)).join("/")} · Appointment Ace ${pz.appt.filter((x) => x > 0).map((x) => money(x)).join("/")} (appointments ${apptWindowTxt(st)}).</p></div>
      <div class="card"><h4>🔥 Daily Hot Shot</h4><p>Every contest day: most Showdown Points that day wins ${money(pz.hot_shot)}.</p></div>
      <div class="card"><h4>🎯 Store goal</h4><p>${esc(store.name)} chases its own targets for new units, used gross and appointments (${wtxt(R.score_weights.new)} / ${wtxt(R.score_weights.used)} / ${wtxt(R.score_weights.appt)}). Unclaimed prizes roll into the Champion's 1st-place prize. Stacking allowed.</p></div>
    </div>
    <div class="card" style="margin-top:12px"><div class="badge-legend">${Object.values(R.badges).map((b) => `<span>${b.icon} <b>${esc(b.name)}</b> <span class="muted">— ${esc(b.desc)}</span></span>`).join("")}</div></div>
  </section>
  <footer class="foot">Updated ${new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })} · refreshes every minute · Splits count 0.5 · Unwinds are removed</footer>`;

  $("#app").innerHTML = h;
  tickCountdown();
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
  for (let i = 0; i < n; i += n <= 10 ? 1 : m ? 10 : 7) g += `<text x="${x(i)}" y="${H - 8}" fill="#64708f" font-size="11" text-anchor="middle">${fmtDate(addDays(R.trend.dates[0], i), { month: "short", day: "numeric" })}</text>`;
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
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Store goal trend">${g}</svg>`;
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
