// Shared helpers (no framework)
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, opts = {}) {
  const o = { method: opts.method || "GET", headers: {}, credentials: "same-origin" };
  if (opts.body !== undefined) { o.headers["Content-Type"] = "application/json"; o.body = JSON.stringify(opts.body); }
  const r = await fetch(path, o);
  let data = null;
  try { data = await r.json(); } catch (e) { data = {}; }
  if (!r.ok) { const err = new Error(data.error || r.statusText); err.status = r.status; throw err; }
  return data;
}

const money = (n, opts = {}) => {
  n = Number(n || 0);
  if (opts.k && Math.abs(n) >= 1000) return (n < 0 ? "-$" : "$") + (Math.abs(n) / 1000).toFixed(Math.abs(n) >= 100000 ? 0 : 1) + "K";
  const cents = opts.cents || (Math.round(n * 100) % 100 !== 0 && opts.cents !== false);
  return (n < 0 ? "-$" : "$") + Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: cents ? 2 : 0, maximumFractionDigits: cents ? 2 : 0 });
};
const units = (n) => { n = Number(n || 0); return Number.isInteger(n) ? String(n) : n.toFixed(1); };
const pct = (n, d = 0) => `${Number(n || 0).toFixed(d)}%`;
const fmtDate = (iso, o = { weekday: "short", month: "short", day: "numeric" }) => {
  if (!iso) return "";
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-US", o);
};
const addDays = (iso, n) => { const [y, m, d] = iso.split("-").map(Number); const dt = new Date(y, m - 1, d + n);
  return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`; };

function toast(msg, err = false) {
  const t = document.createElement("div");
  t.className = "toast" + (err ? " err" : "");
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), err ? 5000 : 2600);
}

function toLogin() { location.href = "/login?next=" + encodeURIComponent(location.pathname + location.search); }

function topbar(active, me, sub) {
  const role = me && me.role;
  const el = document.createElement("header");
  el.className = "topbar";
  el.innerHTML = `<div class="wrap">
    <a class="logo" href="/"><span class="bolt">⚡</span><span class="t">${esc((me && me.contest_name) || "Lakeshore Showdown")}<small>${esc(sub || "Sales Spiff")}</small></span></a>
    <nav class="nav">
      <a href="/" class="${active === "board" ? "on" : ""}">Leaderboard</a>
      <a href="/enter" class="${active === "enter" ? "on" : ""}">Enter Sales</a>
      <a href="/admin" class="${active === "admin" ? "on" : ""}">Admin</a>
      <a href="/Spiff_Rules.pdf" target="_blank">Rules</a>
      ${role ? `<button id="logoutBtn" title="Signed in as ${esc(role)}">Log out</button>` : ""}
    </nav></div>`;
  document.body.prepend(el);
  if (me && me.contest_name) document.title = document.title.replace(/^[^—]*/, me.contest_name + " ");
  const lb = $("#logoutBtn", el);
  if (lb) lb.onclick = async () => { await api("/api/logout", { method: "POST", body: {} }); location.href = "/"; };
}
