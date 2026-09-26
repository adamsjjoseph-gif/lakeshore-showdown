// Store manager data entry: bulk "whole store" grid for a day + list of entries with edit/delete/copy.
let SHOW_RECENT = 12;
// STORE_ID is a store id, or "all" (admin only: every store's grid on one screen).
let D = null, ME = null, STORE_ID = null, GRID = [], ORIG = "", DATE = null;
const isAdmin = () => ME && ME.role === "admin";

async function init() {
  ME = await api("/api/me");
  if (!ME.role || ME.role === "view") return toLogin();
  topbar("enter", ME, isAdmin() ? "Enter Sales · Admin" : "Enter Sales");
  const qs = new URLSearchParams(location.search);
  if (ME.role === "store") STORE_ID = ME.store.id;
  else { const v = qs.get("store") || localStorage.getItem("adminStore") || "all"; STORE_ID = v === "all" ? "all" : +v; }
  await load(qs.get("date"));
}

async function load(date) {
  try {
    const base = STORE_ID === "all" ? "/api/entry/all" : `/api/entry/${STORE_ID}`;
    D = await api(base + (date ? `?date=${date}` : ""));
  } catch (e) {
    if (e.status === 401) return toLogin();
    if (e.status === 403 && STORE_ID === "all") { STORE_ID = ME.store ? ME.store.id : 1; return load(date); }
    return toast(e.message, true);
  }
  DATE = D.date;
  const flat = D.sections.flatMap((sec) => sec.grid);
  GRID = flat.map((r) => ({ ...r, used: r.used.map((u) => ({ ...u })) }));
  ORIG = JSON.stringify(flat.map(ser));
  render();
}

const ser = (r) => ({ sp_id: r.sp_id, store_id: r.store_id, new: +r.new || 0, appt: +r.appt || 0, used: r.used.map((u) => ({ gross: +u.gross, split: !!u.split })) });
const inApptWindow = (d) => D && d >= D.appt_start && d <= D.appt_end;
const mdTxt = (iso) => fmtDate(iso, { weekday: "short" }) + " " + fmtDate(iso, { month: "numeric", day: "numeric" });
const apptWinTxt = () => `${mdTxt(D.appt_start)} – ${mdTxt(D.appt_end)}`;
const dirtyRows = () => { const o = JSON.parse(ORIG); return GRID.map(ser).filter((r, i) => JSON.stringify(r) !== JSON.stringify(o[i])); };

function tabsHtml() {
  if (!isAdmin()) return "";
  const st = {}; (D.day_status || []).forEach((x) => (st[x.store_id] = x.rows));
  const done = D.stores.filter((s) => st[s.id] > 0).length;
  const tab = (id, label, color, extra) => `<button class="tab ${STORE_ID === id ? "on" : ""}" data-tab="${id}" style="--c:${color}">
      <span class="dot"></span><span class="tl">${label}</span><span class="ts">${extra}</span></button>`;
  return `<nav class="tabs" aria-label="Choose store">
    ${tab("all", "All stores", "#ffd23f", `${done}/${D.stores.length} stores have entries`)}
    ${D.stores.map((s) => tab(s.id, esc(s.short || s.name), s.color, st[s.id] ? `✓ ${st[s.id]} entr${st[s.id] === 1 ? "y" : "ies"}` : "nothing entered")).join("")}
  </nav>`;
}

function render() {
  const all = STORE_ID === "all";
  const s = all ? { name: "All stores", color: "#ffd23f" } : D.store;
  const multi = D.sections.length > 1;
  const SN = {}; D.stores.forEach((x) => (SN[x.id] = x));
  const isYesterday = DATE === D.default_date;
  const minD = D.start_date, maxD = D.today < D.end_date ? D.today : D.end_date;
  let h = "";
  if (D.demo) h += `<div class="demo-banner">⚠ <b>Demo mode</b> — these are fake numbers. Admin will reset to empty before launch.</div>`;
  if (D.today < D.start_date) h += `<div class="card" style="margin-top:14px;border-color:rgba(255,210,63,.5)">⏳ <b>The contest hasn't started yet.</b> It kicks off <b>${fmtDate(D.start_date, { weekday: "long", month: "long", day: "numeric" })}</b>. You can enter each day's deals that day or the next morning. Saving is blocked until then.</div>`;
  h += `<section class="card head" style="--c:${s.color}">
    <h1><small>${isAdmin() ? "Admin · enter or fix sales for" : "Enter sales for"}</small>${esc(s.name)}</h1>
    <div class="datebox">
      <button class="btn" id="prevD" ${DATE <= minD ? "disabled" : ""}>◀</button>
      <div><div class="big">${fmtDate(DATE)}</div></div>
      <button class="btn" id="nextD" ${DATE >= maxD ? "disabled" : ""}>▶</button>
      <input type="date" id="dateIn" value="${DATE}" min="${minD}" max="${maxD}">
      ${DATE === D.today ? '<span class="pill gold">Today</span>' : isYesterday ? '<span class="pill gold">Yesterday</span>' : `<button class="btn small" id="yestBtn">Jump to ${fmtDate(D.default_date, { month: "short", day: "numeric" })}</button>`}
    </div></section>
  ${tabsHtml()}
  <p class="hint">${isAdmin() ? "<b>Admin:</b> you can enter, correct or delete sales for <b>any store</b> and <b>any day</b> of the contest (use ◀ ▶ or the calendar for past days). " : ""}Type each rep's numbers for <b>${fmtDate(DATE, { weekday: "long", month: "long", day: "numeric" })}</b>, then hit <b>Save day</b>. This shows what's already saved for the day — changing it corrects it.
    New units go in steps of <b>0.5</b> (split deal = 0.5). Add each used deal's front gross; tap <b>½ split</b> for a split deal and enter <b>this rep's half</b>.
    <b>📅 Appointments</b> = appointments the rep set that day (whole numbers). Appointments count <b>${apptWinTxt()}</b> only${inApptWindow(DATE) ? "" : ` — <b class="bad">${fmtDate(DATE, { month: "short", day: "numeric" })} is outside that window, so appointments are locked for this day</b>`}.</p>
  <section class="card grid">
    <div class="ghead"><span>Salesperson</span><span>New units</span><span>📅 Appointments</span><span>Used deals · front gross each</span><span style="text-align:right">Day total</span></div>
    ${(() => { let i = 0, out = "";
      D.sections.forEach((sec) => {
        if (multi) out += `<div class="gsec" style="--c:${sec.store.color}"><span class="dot"></span>${esc(sec.store.name)}<span class="gsec-tot" data-sectot="${sec.store.id}"></span></div>`;
        sec.grid.forEach(() => { out += rowHtml(GRID[i], i); i++; });
      });
      return out; })()}
    <div class="gtotal" id="gtotal"></div>
  </section>
  <section class="section"><div class="sec-h"><h2>Recent <span class="accent">Entries</span></h2><span class="sub">Fix a typo, remove an unwind, or copy an entry.</span>
    <div class="toolbar" style="margin-left:auto"><button class="btn small" id="addOne">+ Add single entry</button>${D.recent.length ? '<button class="btn small" id="copyLast">⧉ Copy last entry</button>' : ""}</div></div>
    <div class="card" style="padding:6px 10px;overflow-x:auto"><table class="recent"><thead><tr><th>Date</th>${multi ? "<th>Store</th>" : ""}<th>Salesperson</th><th>Type</th><th>Units</th><th>Gross</th><th class="hide-m">By</th><th></th></tr></thead><tbody>
    ${D.recent.slice(0, SHOW_RECENT).map((d) => `<tr><td>${fmtDate(d.date, { month: "short", day: "numeric" })}</td>${multi ? `<td><span class="chip" style="background:${(SN[d.store_id] || {}).color}">${esc((SN[d.store_id] || {}).short || "")}</span></td>` : ""}<td><b>${esc(d.sp_name)}</b>${d.note ? `<div class="dim" style="font-size:12px">${esc(d.note)}</div>` : ""}</td>
      <td><span class="typ ${d.kind}">${d.kind === "appt" ? "appts" : d.kind}</span></td><td class="num">${units(d.units)}${d.units === 0.5 && d.kind !== "appt" ? " <span class='dim'>split</span>" : ""}</td>
      <td class="num">${d.kind === "used" ? money(d.gross) : ""}</td><td class="hide-m dim" style="font-size:12px">${esc(d.entered_by || "")}</td>
      <td style="white-space:nowrap;text-align:right"><button class="btn small" data-edit="${d.id}">Edit</button><button class="btn small" data-copy="${d.id}" title="Copy to ${fmtDate(DATE, { month: "short", day: "numeric" })}">⧉</button><button class="btn small danger" data-del="${d.id}">✕</button></td></tr>`).join("") || `<tr><td colspan="8" class="muted">No entries yet.</td></tr>`}
    </tbody></table>${D.recent.length > SHOW_RECENT ? `<button class="btn small more" id="moreRecent" style="width:100%;margin:8px 0">Show more (${D.recent.length - SHOW_RECENT} older)</button>` : ""}</div></section>`;
  $("#app").innerHTML = h;
  bind();
  refreshDirty();
}

function rowHtml(r, i) {
  return `<div class="grow" data-i="${i}">
    <div class="c-nm"><span class="nm">${esc(r.name)}${r.placeholder ? '<span class="ph">placeholder</span>' : ""}${!r.active ? '<span class="ph">inactive</span>' : ""}</span></div>
    <div class="c-new"><div class="lbl">New units</div><div class="step"><button data-dec="${i}" aria-label="minus half">−</button>
      <input inputmode="decimal" data-new="${i}" value="${units(r.new)}" aria-label="New units for ${esc(r.name)}"><button data-inc="${i}" aria-label="plus half">+</button></div></div>
    <div class="c-appt"><div class="lbl">📅 Appts <span class="dim">${fmtDate(D.appt_start, { month: "numeric", day: "numeric" })}–${fmtDate(D.appt_end, { month: "numeric", day: "numeric" })}</span></div>${(() => {
      const locked = !inApptWindow(DATE) && !(+r.appt);
      return `<div class="step appt ${locked ? "locked" : ""}"><button data-adec="${i}" aria-label="one fewer appointment" ${locked ? "disabled" : ""}>−</button>
      <input inputmode="numeric" data-appt="${i}" value="${+r.appt || 0}" aria-label="Appointments for ${esc(r.name)}" ${locked ? "disabled title='Appointments only count " + apptWinTxt() + "'" : ""}><button data-ainc="${i}" aria-label="one more appointment" ${locked ? "disabled" : ""}>+</button></div>`; })()}</div>
    <div class="c-used"><div class="lbl">Used deals · front gross each</div><div class="used">
      ${r.used.map((u, j) => `<span class="dchip ${u.gross < 0 ? "neg" : ""}">${u.split ? '<span class="sp">½ SPLIT</span>' : ""}${money(u.gross)}<button data-rm="${i}:${j}" aria-label="remove deal">✕</button></span>`).join("")}
      <span class="adddeal"><input inputmode="decimal" placeholder="Gross $" data-g="${i}" aria-label="Used gross for ${esc(r.name)}"><button class="splitbtn" data-split="${i}" title="Split deal (0.5 unit)">½ split</button><button class="btn small" data-add="${i}">+ Deal</button></span>
    </div></div>
    <div class="c-tot tot"><b class="num">${units(r.new)} new · ${units(r.used.reduce((a, u) => a + (u.split ? 0.5 : 1), 0))} used</b>${money(r.used.reduce((a, u) => a + +u.gross, 0))}${+r.appt ? ` · <span class="gold">${r.appt} appt${r.appt === 1 ? "" : "s"}</span>` : ""}</div>
  </div>`;
}

function rerow(i) {
  const el = $(`.grow[data-i="${i}"]`);
  const splitOn = $(`[data-split="${i}"]`, el).classList.contains("on");
  const tmp = document.createElement("div");
  tmp.innerHTML = rowHtml(GRID[i], i);
  el.replaceWith(tmp.firstElementChild);
  if (splitOn) $(`[data-split="${i}"]`).classList.add("on");
  bindRow(i);
  refreshDirty();
}

function addDeal(i) {
  const inp = $(`[data-g="${i}"]`);
  const v = parseFloat(String(inp.value).replace(/[$,\s]/g, ""));
  if (!isFinite(v)) { inp.focus(); return toast("Type the deal's front gross first (e.g. 2450)", true); }
  const split = $(`[data-split="${i}"]`).classList.contains("on");
  GRID[i].used.push({ gross: v, split });
  rerow(i);
  $(`[data-split="${i}"]`).classList.remove("on");
  $(`[data-g="${i}"]`).focus();
}

function bindRow(i) {
  const el = $(`.grow[data-i="${i}"]`);
  const setNew = (v) => { v = Math.max(0, Math.round(v * 2) / 2); GRID[i].new = v; rerow(i); };
  $(`[data-dec="${i}"]`, el).onclick = () => setNew((+GRID[i].new || 0) - 0.5);
  $(`[data-inc="${i}"]`, el).onclick = () => setNew((+GRID[i].new || 0) + 0.5);
  $(`[data-new="${i}"]`, el).onchange = (e) => {
    const v = parseFloat(e.target.value || "0");
    if (!isFinite(v) || v < 0 || Math.abs(v * 2 - Math.round(v * 2)) > 1e-9) { toast("New units must be whole or half numbers (0, 0.5, 1, 1.5…)", true); e.target.value = units(GRID[i].new); return; }
    setNew(v);
  };
  const setAppt = (v) => { v = Math.max(0, Math.min(200, Math.round(v))); GRID[i].appt = v; rerow(i); };
  const ad = $(`[data-adec="${i}"]`, el), ai = $(`[data-ainc="${i}"]`, el), ain = $(`[data-appt="${i}"]`, el);
  if (ad) ad.onclick = () => setAppt((+GRID[i].appt || 0) - 1);
  if (ai) ai.onclick = () => setAppt((+GRID[i].appt || 0) + 1);
  if (ain) ain.onchange = (e) => {
    const v = Number(e.target.value || "0");
    if (!Number.isInteger(v) || v < 0) { toast("Appointments must be a whole number (0, 1, 2…)", true); e.target.value = +GRID[i].appt || 0; return; }
    setAppt(v);
  };
  $(`[data-add="${i}"]`, el).onclick = () => addDeal(i);
  $(`[data-g="${i}"]`, el).onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); addDeal(i); } };
  $(`[data-split="${i}"]`, el).onclick = (e) => e.currentTarget.classList.toggle("on");
  $$(`[data-rm^="${i}:"]`, el).forEach((b) => (b.onclick = () => { const j = +b.dataset.rm.split(":")[1]; GRID[i].used.splice(j, 1); rerow(i); }));
}

function refreshDirty() {
  const dr = dirtyRows();
  const o = JSON.parse(ORIG);
  GRID.forEach((r, i) => { const el = $(`.grow[data-i="${i}"]`); if (el) el.classList.toggle("dirty", JSON.stringify(ser(r)) !== JSON.stringify(o[i])); });
  const na = GRID.reduce((a, r) => a + (+r.appt || 0), 0);
  const n = GRID.reduce((a, r) => a + (+r.new || 0), 0), uu = GRID.reduce((a, r) => a + r.used.reduce((b, u) => b + (u.split ? 0.5 : 1), 0), 0), g = GRID.reduce((a, r) => a + r.used.reduce((b, u) => b + +u.gross, 0), 0);
  $$("[data-sectot]").forEach((el) => {
    const rows = GRID.filter((r) => r.store_id === +el.dataset.sectot);
    const sa = rows.reduce((a, r) => a + (+r.appt || 0), 0);
    const sn = rows.reduce((a, r) => a + (+r.new || 0), 0), su = rows.reduce((a, r) => a + r.used.reduce((b, u) => b + (u.split ? 0.5 : 1), 0), 0), sg = rows.reduce((a, r) => a + r.used.reduce((b, u) => b + +u.gross, 0), 0);
    el.textContent = `${units(sn)} new · ${units(su)} used · ${money(sg)} · ${sa} appts`;
  });
  const gt = $("#gtotal");
  if (gt) gt.innerHTML = `<span>${STORE_ID === "all" ? "All stores day total" : "Store day total"}</span><span>New<b class="num">${units(n)}</b></span><span>Used<b class="num">${units(uu)}</b></span><span>Used gross<b class="num">${money(g)}</b></span><span>Appts<b class="num">${na}</b></span>`;
  $("#saveBar").classList.toggle("hidden", !dr.length);
  $("#saveMsg").textContent = `${dr.length} rep${dr.length === 1 ? "" : "s"} changed for ${fmtDate(DATE, { month: "short", day: "numeric" })}`;
}

async function saveDay() {
  const rows = dirtyRows();
  if (!rows.length) return;
  $("#saveBtn").disabled = true;
  try {
    const byStore = {};
    rows.forEach((r) => (byStore[r.store_id] = byStore[r.store_id] || []).push(r));
    for (const [sid, rs] of Object.entries(byStore)) await api(`/api/entry/${sid}/grid`, { method: "POST", body: { date: DATE, rows: rs } });
    const n = Object.keys(byStore).length;
    toast(`✅ Saved ${fmtDate(DATE, { month: "short", day: "numeric" })}${n > 1 ? ` for ${n} stores` : ""} — leaderboard updated`);
    await load(DATE);
  } catch (e) { toast(e.message, true); if (e.status === 401) toLogin(); }
  $("#saveBtn").disabled = false;
}

function go(date) {
  if (dirtyRows().length && !confirm("You have unsaved changes for this day. Discard them?")) return;
  history.replaceState(null, "", `/enter?date=${date}` + (isAdmin() ? `&store=${STORE_ID}` : ""));
  load(date);
}

function bind() {
  GRID.forEach((_, i) => bindRow(i));
  $("#prevD").onclick = () => go(addDays(DATE, -1));
  $("#nextD").onclick = () => go(addDays(DATE, 1));
  $("#dateIn").onchange = (e) => e.target.value && go(e.target.value);
  if ($("#yestBtn")) $("#yestBtn").onclick = () => go(D.default_date);
  $$("[data-tab]").forEach((b) => (b.onclick = () => {
    if (dirtyRows().length && !confirm("You have unsaved changes. Discard them?")) return;
    STORE_ID = b.dataset.tab === "all" ? "all" : +b.dataset.tab;
    localStorage.setItem("adminStore", STORE_ID);
    history.replaceState(null, "", `/enter?date=${DATE}&store=${STORE_ID}`);
    load(DATE);
  }));
  if ($("#moreRecent")) $("#moreRecent").onclick = () => { SHOW_RECENT += 30; render(); };
  $("#addOne").onclick = () => dealModal(null, { date: DATE, kind: "new", units: 1 });
  if ($("#copyLast")) $("#copyLast").onclick = () => { const d = D.recent[0]; dealModal(null, { ...d, date: DATE }); };
  $$("[data-edit]").forEach((b) => (b.onclick = () => dealModal(D.recent.find((d) => d.id === +b.dataset.edit))));
  $$("[data-copy]").forEach((b) => (b.onclick = () => { const d = D.recent.find((x) => x.id === +b.dataset.copy); dealModal(null, { ...d, date: DATE }); }));
  $$("[data-del]").forEach((b) => (b.onclick = async () => {
    const d = D.recent.find((x) => x.id === +b.dataset.del);
    if (!confirm(`Delete this entry?\n${d.sp_name} · ${d.date} · ${d.kind === "appt" ? "appointments" : d.kind} ${units(d.units)}${d.kind === "used" ? " · " + money(d.gross) : ""}\n(Use this for unwinds and mistakes.)`)) return;
    try { await api(`/api/deals/${d.id}`, { method: "DELETE" }); toast("Entry deleted"); load(DATE); } catch (e) { toast(e.message, true); }
  }));
}

function dealModal(existing, preset) {
  const d = existing || preset || {};
  const bg = document.createElement("div");
  bg.className = "modal-bg";
  const maxD = D.today < D.end_date ? D.today : D.end_date;
  bg.innerHTML = `<div class="card modal"><h2 class="display" style="margin:0 0 12px;font-size:30px">${existing ? "Edit entry" : "Add entry"}</h2>
    <div style="display:grid;gap:12px">
      <label class="f">Salesperson<select id="mSp">${D.stores.filter((st) => D.people.some((p) => p.store_id === st.id)).map((st) => {
        const opts = D.people.filter((p) => p.store_id === st.id && (p.active || p.id === d.sp_id)).map((p) => `<option value="${p.id}" ${p.id === d.sp_id ? "selected" : ""}>${esc(p.name)}</option>`).join("");
        return STORE_ID === "all" ? `<optgroup label="${esc(st.name)}">${opts}</optgroup>` : opts; }).join("")}</select></label>
      <div class="grid2"><label class="f">Date<input type="date" id="mDate" value="${d.date || DATE}" min="${D.start_date}" max="${maxD}" style="color-scheme:dark"></label>
        <label class="f">Type<select id="mKind"><option value="new" ${d.kind !== "used" && d.kind !== "appt" ? "selected" : ""}>New car units</option><option value="used" ${d.kind === "used" ? "selected" : ""}>Used car deal</option><option value="appt" ${d.kind === "appt" ? "selected" : ""}>Appointments set</option></select></label></div>
      <div class="grid2"><label class="f" id="mUnitsL">Units (0.5 steps)<input id="mUnits" inputmode="decimal" value="${d.units ?? 1}"></label>
        <label class="f" id="mGrossL">Front gross (this rep's share)<input id="mGross" inputmode="decimal" value="${d.kind === "used" ? d.gross : ""}"></label></div>
      <label id="mSplitL" style="display:flex;gap:8px;align-items:center"><input type="checkbox" id="mSplit" ${d.kind === "used" && d.units === 0.5 ? "checked" : ""}> Split deal (counts 0.5 unit)</label>
      <label class="f">Note (optional)<input id="mNote" value="${esc(d.note || "")}" maxlength="200" placeholder="Stock #, customer last name…"></label>
      <div style="display:flex;gap:10px;justify-content:flex-end"><button class="btn" id="mCancel">Cancel</button><button class="btn primary" id="mSave">${existing ? "Save changes" : "Add"}</button></div>
    </div></div>`;
  document.body.appendChild(bg);
  const sync = () => { const u = $("#mKind").value === "used", a = $("#mKind").value === "appt"; $("#mGrossL").style.display = u ? "" : "none"; $("#mSplitL").style.display = u ? "flex" : "none"; $("#mUnitsL").style.display = u ? "none" : "";
    $("#mUnitsL").firstChild.textContent = a ? `Appointments (whole number · count ${apptWinTxt()})` : "Units (0.5 steps)"; };
  $("#mKind").onchange = sync; sync();
  $("#mCancel").onclick = () => bg.remove();
  bg.onclick = (e) => { if (e.target === bg) bg.remove(); };
  $("#mSave").onclick = async () => {
    const kind = $("#mKind").value;
    const body = { sp_id: +$("#mSp").value, date: $("#mDate").value, kind, note: $("#mNote").value,
      units: kind !== "used" ? parseFloat($("#mUnits").value) : ($("#mSplit").checked ? 0.5 : 1),
      split: $("#mSplit").checked, gross: kind === "used" ? parseFloat(String($("#mGross").value).replace(/[$,]/g, "")) : 0 };
    try {
      if (existing) await api(`/api/deals/${existing.id}`, { method: "PUT", body });
      else {
        const rep = D.people.find((p) => p.id === body.sp_id);
        await api(`/api/entry/${rep ? rep.store_id : STORE_ID}/deal`, { method: "POST", body });
      }
      bg.remove(); toast(existing ? "Entry updated" : "Entry added"); load(DATE);
    } catch (e) { toast(e.message, true); }
  };
}

$("#saveBtn").onclick = saveDay;
$("#undoBtn").onclick = () => load(DATE);
window.addEventListener("beforeunload", (e) => { if (GRID.length && dirtyRows().length) { e.preventDefault(); e.returnValue = ""; } });
init();
