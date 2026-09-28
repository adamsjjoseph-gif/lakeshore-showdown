// Admin: contest settings, prizes, stores/targets, rosters, PINs, data export/reset.
let A = null, ME = null;

async function init() {
  ME = await api("/api/me");
  if (ME.role !== "admin") return toLogin();
  topbar("admin", ME, "Admin");
  await load();
}
async function load() {
  try { A = await api("/api/admin"); } catch (e) { if (e.status === 401 || e.status === 403) return toLogin(); return toast(e.message, true); }
  render();
}
const val = (id) => $("#" + id).value;
const nval = (id) => parseFloat(val(id) || "0");

function periodsFor(s, e, len) { const d = Math.round((new Date(e) - new Date(s)) / 864e5) + 1; return d > 0 ? Math.ceil(d / Math.max(1, len || 7)) : 0; }

function budgetHtml() {
  const g = (id) => parseFloat(($("#" + id) || {}).value || "0") || 0;
  const n = periodsFor(val("sStart"), val("sEnd"), g("sBd"));
  const champ = g("pC1") + g("pC2") + g("pC3"), nw = g("pN1") + g("pN2") + g("pN3"), us = g("pU1") + g("pU2") + g("pU3");
  const ap = g("pA1") + g("pA2") + g("pA3");
  const hs = g("pHs") * n;
  const tot = champ + nw + us + ap + hs;
  const ok = Math.abs(tot - A.pool) < 0.005;
  return `<div class="budget ${ok ? "ok" : "bad"}">${ok ? "✅" : "⚠"} Prizes ${money(tot)} ${ok ? "=" : "≠"} Pool ${money(A.pool)}
    <span class="muted" style="font-weight:500">= Showdown Champion ${money(champ)} + new ${money(nw)} + used ${money(us)} + appointments ${money(ap)} + Daily Hot Shot ${money(g("pHs"))}×${n} ${g("sBd") === 1 ? "days" : "periods"}</span>
    ${ok ? "" : `<b>Off by ${money(tot - A.pool)}. Adjust prizes or the store contribution.</b>`}</div>`;
}

function render() {
  const s = A.settings, p = s.prizes;
  const PB = {}; A.people.forEach((x) => (PB[x.store_id] = PB[x.store_id] || []).push(x));
  let h = "";
  if (s.demo_today) h += `<div class="demo-banner">⚠ <b>Demo mode is ON</b> — ${A.demo_count} fake entries, simulated "today" = ${fmtDate(s.demo_today)}. Use <b>Reset to empty</b> (bottom) before launch.</div>`;
  h += `<section class="card routine">
    <div><h3 style="margin:0 0 6px">☀️ Admin daily routine <span class="muted" style="font-size:14px;font-family:var(--body);font-style:normal;text-transform:none">about 5 minutes each morning</span></h3>
    <ol><li><b>Enter yesterday.</b> Open <a href="/enter">Enter Sales</a> (it opens on yesterday; Saturday on Mondays). Type or fix each rep's new units, appointments and used deals, then press <b>Save day</b>.</li>
      <li><b>Review.</b> Look over the <a href="/">leaderboard</a>. Fix mistakes or remove unwinds in <i>Recent entries</i> (any past day). If you change targets, prizes, rosters or dates below, the leaderboard and payouts recalculate right away.</li>
      <li><b>Done.</b> Everything you change is recorded in the Activity log at the bottom. Mondays: download <i>All entries CSV</i> and <i>Full database backup</i>.</li></ol></div>
    <a class="btn primary" href="/enter" style="align-self:center;text-decoration:none;white-space:nowrap">✍️ Enter / fix sales →</a>
  </section>`;
  h += `<section class="status">
    <div class="card"><div class="k">Prize pool</div><div class="v gold">${money(A.pool)}</div></div>
    <div class="card"><div class="k">Budget check</div><div class="v ${A.budget_ok ? "ok" : "bad"}">${A.budget_ok ? "Balanced ✓" : "Off!"}</div></div>
    <div class="card"><div class="k">Entries in DB</div><div class="v">${A.deal_count}</div></div>
    <div class="card"><div class="k">Leaderboard access</div><div class="v">${s.view_pin_required ? "PIN 🔒" : "Open 🌐"}</div></div>
    <div class="card"><div class="k">Database storage</div><div class="v ${A.storage && A.storage.db_dir_is_mount ? "ok" : "bad"}" style="font-size:18px">${A.storage && A.storage.db_dir_is_mount ? "Persistent disk ✓" : "⚠ Not on a mounted disk"}</div>
      <div class="muted" style="font-size:11px">${esc(A.storage ? A.storage.db_path : "")}</div></div></section>`;

  h += `<div class="adm section">
  <section class="card full"><h3>🏁 Contest & Prizes</h3>
    <div class="fields">
      <label class="f wide">Contest name<input id="sName" value="${esc(s.contest_name)}"></label>
      <label class="f wide">Tagline<input id="sTag" value="${esc(s.tagline)}"></label>
      <label class="f">Start date<input type="date" id="sStart" value="${s.start_date}" style="color-scheme:dark"></label>
      <label class="f">End date<input type="date" id="sEnd" value="${s.end_date}" style="color-scheme:dark"></label>
      <label class="f">📅 Appointments count from<input type="date" id="sAs" value="${s.appt_start}" style="color-scheme:dark"></label>
      <label class="f">📅 Appointments count through<input type="date" id="sAe" value="${s.appt_end}" style="color-scheme:dark"></label>
      <label class="f">Store goal weight: new units<input id="sW" value="${s.weight_new}" inputmode="decimal"></label>
      <label class="f">Store goal weight: used gross<input id="sWu" value="${s.weight_used}" inputmode="decimal"></label>
      <label class="f">Store goal weight: appointments<input id="sWa" value="${s.weight_appt}" inputmode="decimal"></label>
      <label class="f">Points per new unit<input id="sPn" value="${s.points_new}" inputmode="decimal"></label>
      <label class="f">Points per $1,000 used gross<input id="sPk" value="${s.points_per_1k}" inputmode="decimal"></label>
      <label class="f">Points per appointment<input id="sPa" value="${s.points_per_appt}" inputmode="decimal"></label>
      <label class="f">Heavy Hitter badge ($ gross)<input id="sHh" value="${s.heavy_hitter}" inputmode="decimal"></label>
      <label class="f">Hat Trick badge (new units in a day)<input id="sHt" value="${s.hat_trick_units}" inputmode="decimal"></label>
      <label class="f">On Fire badge (selling days in a row)<input id="sSd" value="${s.streak_days}" inputmode="numeric"></label>
      <label class="f">Hot Shot period length (days, 1 = daily)<input id="sBd" value="${s.bounty_days}" inputmode="numeric"></label>
      <label class="f">Time zone<input id="sTz" value="${esc(s.timezone)}"></label>
      <label class="f">Closed Sundays?<select id="sSun"><option value="1" ${s.closed_sundays ? "selected" : ""}>Yes — skip Sundays</option><option value="0" ${!s.closed_sundays ? "selected" : ""}>No</option></select></label>
    </div>
    <p class="muted" style="font-size:13px;margin:8px 0 0">Store goal weights are relative (1 / 1 / 1 = equal thirds; currently ${[s.weight_new, s.weight_used, s.weight_appt].map((w) => pct((100 * w) / ((+s.weight_new + +s.weight_used + +s.weight_appt) || 1), 1)).join(" / ")}). Appointments entered outside the appointment window are kept but don't count.</p>
    <h4 class="cond muted" style="margin:18px 0 8px">Prize amounts ($)</h4>
    <div class="fields">
      <label class="f">Showdown Champion 1st<input id="pC1" value="${p.points[0] ?? 0}" inputmode="decimal"></label>
      <label class="f">Showdown Champion 2nd<input id="pC2" value="${p.points[1] ?? 0}" inputmode="decimal"></label>
      <label class="f">Showdown Champion 3rd<input id="pC3" value="${p.points[2] ?? 0}" inputmode="decimal"></label>
      <label class="f">New units 1st<input id="pN1" value="${p.new[0] ?? 0}" inputmode="decimal"></label>
      <label class="f">New units 2nd<input id="pN2" value="${p.new[1] ?? 0}" inputmode="decimal"></label>
      <label class="f">New units 3rd<input id="pN3" value="${p.new[2] ?? 0}" inputmode="decimal"></label>
      <label class="f">Used gross 1st<input id="pU1" value="${p.used[0] ?? 0}" inputmode="decimal"></label>
      <label class="f">Used gross 2nd<input id="pU2" value="${p.used[1] ?? 0}" inputmode="decimal"></label>
      <label class="f">Used gross 3rd<input id="pU3" value="${p.used[2] ?? 0}" inputmode="decimal"></label>
      <label class="f">Appointment Ace 1st<input id="pA1" value="${p.appt[0] ?? 0}" inputmode="decimal"></label>
      <label class="f">Appointment Ace 2nd<input id="pA2" value="${p.appt[1] ?? 0}" inputmode="decimal"></label>
      <label class="f">Appointment Ace 3rd<input id="pA3" value="${p.appt[2] ?? 0}" inputmode="decimal"></label>
      <label class="f">Daily Hot Shot (each day)<input id="pHs" value="${p.hot_shot}" inputmode="decimal"></label>
    </div>
    <div id="budget"></div>
    <div class="btns" style="margin-top:14px"><button class="btn primary" id="saveSettings">Save contest settings</button></div>
  </section>

  <section class="card full"><h3>🏪 Store, targets & PIN</h3>
    <p class="muted" style="margin-top:-4px">Targets drive the store-goal progress bars and race chart. The contribution is the prize pool.</p>
    ${A.stores.map((st) => `<div class="srow" data-sid="${st.id}">
      <label class="f">Store name<input id="stN${st.id}" value="${esc(st.name)}"></label>
      <label class="f">Short name<input id="stS${st.id}" value="${esc(st.short || "")}"></label>
      <label class="f">Color<input type="color" id="stC${st.id}" value="${st.color}"></label>
      <label class="f">New target<input id="stNT${st.id}" value="${st.new_target}" inputmode="decimal"></label>
      <label class="f">Used gross target $<input id="stUT${st.id}" value="${st.used_target}" inputmode="decimal"></label>
      <label class="f">📅 Appointment target<input id="stAT${st.id}" value="${st.appt_target}" inputmode="decimal"></label>
      <label class="f">Contribution $<input id="stK${st.id}" value="${st.contribution}" inputmode="decimal"></label>
      <div class="btns"><button class="btn small primary" data-savestore="${st.id}">Save</button></div>
      <div class="pinrow" style="grid-column:1/-1;margin:0"><label class="f">New manager PIN (4–8 digits)<input id="stP${st.id}" inputmode="numeric" type="password" autocomplete="new-password" placeholder="${st.has_pin ? "•••• (set)" : "not set"}"></label>
        <button class="btn small" data-storepin="${st.id}">Set store PIN</button></div>
    </div>`).join("")}
  </section>

  <section class="card full"><h3>👥 Roster</h3>
    <p class="muted" style="margin-top:-4px">Someone leaves? Mark them <b>inactive</b> (their deals still count for the store goal, but they drop off individual prizes).</p>
    <div class="rosters">${A.stores.map((st) => `<div class="card roster" style="--c:${st.color}"><h4>${esc(st.name)}</h4>
      ${(PB[st.id] || []).map((x) => `<div class="rp ${x.active ? "" : "off"}"><input type="text" id="pn${x.id}" value="${esc(x.name)}" data-rename="${x.id}">
        ${x.placeholder ? '<span class="ph">placeholder</span>' : ""}
        <button class="btn small" data-toggle="${x.id}" title="${x.active ? "Mark inactive" : "Reactivate"}">${x.active ? "Active" : "Inactive"}</button>
        ${x.deal_rows ? "" : `<button class="btn small danger" data-delp="${x.id}" title="Delete (only when no entries)">✕</button>`}</div>`).join("")}
      <div class="rp" style="margin-top:10px"><input type="text" id="add${st.id}" placeholder="Add salesperson…"><button class="btn small primary" data-addp="${st.id}">Add</button></div></div>`).join("")}</div>
  </section>

  <section class="card"><h3>🔐 PINs</h3>
    <div class="pinrow"><label class="f">New admin PIN<input id="adminPin" type="password" inputmode="numeric" autocomplete="new-password"></label><button class="btn small" id="setAdminPin">Set admin PIN</button></div>
    <div class="pinrow"><label class="f">Leaderboard view PIN<input id="viewPin" type="password" inputmode="numeric" autocomplete="new-password" placeholder="${s.has_view_pin ? "•••• (set)" : "none — open"}"></label>
      <button class="btn small" id="setViewPin">Require this PIN</button><button class="btn small" id="openView">Make leaderboard open</button></div>
    <p class="muted" style="font-size:13px">PINs are stored hashed (PBKDF2). Each PIN must be unique — the login screen figures out who you are from the PIN. PINs set with environment variables (ADMIN_PIN, VIEW_PIN, STORE_PIN_1) are re-applied on every restart.</p>
  </section>

  <section class="card"><h3>💾 Data</h3>
    <div class="btns">
      <a class="btn small" href="/api/admin/export/deals.csv">⬇ All entries CSV</a>
      <a class="btn small" href="/api/admin/export/standings.csv">⬇ Store goal CSV</a>
      <a class="btn small" href="/api/admin/export/individuals.csv">⬇ Individuals CSV</a>
      <a class="btn small" href="/api/admin/export/payouts.csv">⬇ Payouts CSV</a>
      <a class="btn small" href="/api/admin/export/roster.csv">⬇ Roster CSV</a>
      <a class="btn small" href="/api/admin/backup.db">⬇ Full database backup</a>
    </div>
    <hr style="border:0;border-top:1px solid var(--line);margin:16px 0">
    <div class="btns"><button class="btn small" id="loadDemo">Load demo data</button>
      <button class="btn danger" id="resetBtn">🧨 Reset to empty (delete all entries)</button></div>
    <p class="muted" style="font-size:13px">Reset deletes every sales entry and turns demo mode off. The store, roster, targets, prizes and PINs are kept. Download a backup first if unsure.</p>
  </section>

  <section class="card full"><details><summary class="cond" style="cursor:pointer;font-size:15px">📊 What controls each leaderboard number? (click)</summary>
    <table style="margin-top:10px;font-size:13px"><tbody>
      <tr><td><b>Units, used gross, deals, highlights, streaks, trend charts</b></td><td class="muted">Sales entries → Enter Sales (any contest day) or Recent entries (edit/delete)</td></tr>
      <tr><td><b>Store goal % / progress bars / race chart</b></td><td class="muted">New units, used gross and appointments ÷ store targets (Store section) × weights (Contest & Prizes)</td></tr>
      <tr><td><b>Appointments (store bar, Appointment Ace, points)</b></td><td class="muted">Appointment entries dated inside the appointment window (Contest & Prizes)</td></tr>
      <tr><td><b>Prize pool</b></td><td class="muted">Store contribution (Store section)</td></tr>
      <tr><td><b>Projected payouts</b></td><td class="muted">Prize amounts (Contest & Prizes), roster active/inactive</td></tr>
      <tr><td><b>Daily Hot Shot days</b></td><td class="muted">Start/end dates + Hot Shot period length; amount in Contest & Prizes</td></tr>
      <tr><td><b>Days left / day X of Y / pace line</b></td><td class="muted">Contest dates + time zone (the calendar decides "today")</td></tr>
      <tr><td><b>Showdown Champion / Hot Shot points</b></td><td class="muted">Points per new unit / per $1,000 used gross / per appointment</td></tr>
      <tr><td><b>Badges</b></td><td class="muted">Hat Trick units, Heavy Hitter $, On Fire days, closed Sundays</td></tr>
      <tr><td><b>Names, store name/color, contest name & tagline</b></td><td class="muted">Roster, Store, Contest & Prizes</td></tr>
    </tbody></table></details></section>
  <section class="card full"><h3>📜 Activity log</h3><div class="audit"><table><tbody>
    ${A.audit.map((a) => `<tr><td class="dim" style="white-space:nowrap">${esc(a.ts.replace("T", " "))}</td><td>${esc(a.who)}</td><td><b>${esc(a.action)}</b></td><td class="muted">${esc(a.detail)}</td></tr>`).join("")}
  </tbody></table></div></section></div>`;
  $("#app").innerHTML = h;
  bind();
}

async function call(path, method, body, msg) {
  try { await api(path, { method, body }); toast(msg || "Saved"); await load(); return true; }
  catch (e) { toast(e.message, true); if (e.status === 401) toLogin(); return false; }
}

async function saveSettings(body) {
  try {
    const r = await api("/api/admin/settings", { method: "PUT", body });
    toast(r.changes.length ? `Saved ${r.changes.length} change${r.changes.length === 1 ? "" : "s"} — leaderboard recalculated` : "No changes");
    if (r.entries_outside_dates) setTimeout(() => toast(`Note: ${r.entries_outside_dates} saved entries fall outside the new contest dates, so they don't count (they're kept, not deleted).`, true), 2700);
    await load();
  } catch (e) { toast(e.message, true); if (e.status === 401) toLogin(); }
}

function bind() {
  const upd = () => ($("#budget").innerHTML = budgetHtml());
  $$("#app input[id^=p], #sStart, #sEnd, #sBd").forEach((i) => i.addEventListener("input", upd));
  upd();
  $("#saveSettings").onclick = () => saveSettings({
    contest_name: val("sName"), tagline: val("sTag"), start_date: val("sStart"), end_date: val("sEnd"),
    hat_trick_units: nval("sHt"), streak_days: nval("sSd"), bounty_days: nval("sBd"), timezone: val("sTz"),
    weight_new: nval("sW"), weight_used: nval("sWu"), weight_appt: nval("sWa"), appt_start: val("sAs"), appt_end: val("sAe"),
    points_new: nval("sPn"), points_per_1k: nval("sPk"), points_per_appt: nval("sPa"), heavy_hitter: nval("sHh"),
    closed_sundays: val("sSun") === "1",
    prizes: { points: [nval("pC1"), nval("pC2"), nval("pC3")], new: [nval("pN1"), nval("pN2"), nval("pN3")], used: [nval("pU1"), nval("pU2"), nval("pU3")],
      appt: [nval("pA1"), nval("pA2"), nval("pA3")], hot_shot: nval("pHs") } });
  $$("[data-savestore]").forEach((b) => (b.onclick = () => { const i = b.dataset.savestore; call(`/api/admin/stores/${i}`, "PUT", {
    name: val("stN" + i), short: val("stS" + i), color: val("stC" + i), new_target: nval("stNT" + i), used_target: nval("stUT" + i), appt_target: nval("stAT" + i), contribution: nval("stK" + i) }, "Store saved"); }));
  $$("[data-storepin]").forEach((b) => (b.onclick = () => { const i = b.dataset.storepin; call("/api/admin/pin", "POST", { which: "store", store_id: +i, pin: val("stP" + i) }, "Store PIN updated"); }));
  $$("[data-rename]").forEach((inp) => (inp.onchange = () => call(`/api/admin/people/${inp.dataset.rename}`, "PUT", { name: inp.value }, "Renamed")));
  $$("[data-toggle]").forEach((b) => (b.onclick = () => { const x = A.people.find((p) => p.id === +b.dataset.toggle); call(`/api/admin/people/${x.id}`, "PUT", { active: !x.active }, x.active ? "Marked inactive" : "Reactivated"); }));
  $$("[data-delp]").forEach((b) => (b.onclick = () => confirm("Delete this salesperson?") && call(`/api/admin/people/${b.dataset.delp}`, "DELETE", undefined, "Deleted")));
  $$("[data-addp]").forEach((b) => (b.onclick = () => { const i = b.dataset.addp; if (!val("add" + i).trim()) return; call("/api/admin/people", "POST", { store_id: +i, name: val("add" + i) }, "Added"); }));
  $("#setAdminPin").onclick = () => call("/api/admin/pin", "POST", { which: "admin", pin: val("adminPin") }, "Admin PIN updated");
  $("#setViewPin").onclick = () => call("/api/admin/pin", "POST", { which: "view", pin: val("viewPin") }, "Leaderboard now needs the view PIN");
  $("#openView").onclick = () => call("/api/admin/pin", "POST", { which: "view", pin: "" }, "Leaderboard is open to anyone with the link");
  $("#loadDemo").onclick = () => confirm("Replace ALL entries with fake demo data?") && call("/api/admin/demo", "POST", {}, "Demo data loaded");
  $("#resetBtn").onclick = () => { const t = prompt('This deletes ALL sales entries. Type RESET to confirm.'); if (t === "RESET") call("/api/admin/reset", "POST", { confirm: "RESET" }, "All entries deleted — ready for launch"); };
}
init();
