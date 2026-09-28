// Browser smoke test of the real UI: log in as a store manager, enter a day on the grid, save, correct it,
// edit + delete an entry, and confirm the public leaderboard reflects it. Run against a THROWAWAY server.
// Usage: NODE_PATH=/path/to/node_modules node tools/ui_smoke.js http://localhost:8799
const { chromium } = require("playwright-core");
const BASE = process.argv[2];
const assert = (c, m) => { if (!c) { console.error("FAIL: " + m); process.exit(1); } else console.log("ok - " + m); };
(async () => {
  const b = await chromium.launch({ executablePath: process.env.CHROME || "/usr/bin/google-chrome", args: ["--no-sandbox"] });
  const p = await (await b.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
  const errs = []; p.on("pageerror", (e) => errs.push(e.message));
  p.on("dialog", (d) => d.accept());
  const state = async () => (await (await p.request.get(BASE + "/api/state")).json()).result;
  const before = await state();
  const s1 = (r) => r.stores.find((s) => s.id === 1);

  await p.goto(BASE + "/enter");
  await p.waitForURL(/login/); assert(true, "entry page redirects to PIN login");
  await p.keyboard.type("1111"); await p.keyboard.press("Enter");
  await p.waitForSelector(".grow");
  const day = await p.inputValue("#dateIn");
  assert(/^\d{4}-\d{2}-\d{2}$/.test(day), "entry date defaults to the last selling day = " + day);
  assert((await p.$$(".grow")).length === 6, "store grid lists the 6 reps");
  // what's already saved for rep row 0
  const n0 = parseFloat(await p.inputValue('[data-new="0"]'));
  await p.click('[data-inc="0"]'); await p.click('[data-inc="0"]');           // +1 new unit
  await p.fill('[data-g="0"]', "3333"); await p.click('[data-add="0"]');      // + used deal $3,333
  await p.click('[data-split="1"]'); await p.fill('[data-g="1"]', "800"); await p.keyboard.press("Enter"); // split used deal
  assert(await p.isVisible("#saveBar"), "save bar appears with unsaved changes");
  await p.click("#saveBtn");
  await p.waitForSelector(".toast");
  await p.waitForTimeout(400);
  const after = await state();
  assert(Math.abs(s1(after).new - s1(before).new - 1) < 1e-9, `store new units +1 (${s1(before).new} -> ${s1(after).new})`);
  assert(Math.abs(s1(after).gross - s1(before).gross - 4133) < 0.01, `store used gross +$4,133`);
  assert(Math.abs(s1(after).used_units - s1(before).used_units - 1.5) < 1e-9, "used units +1.5 (split counted 0.5)");
  assert(parseFloat(await p.inputValue('[data-new="0"]')) === n0 + 1, "grid reloads with saved numbers");
  // correction via grid: remove the $3,333 deal chip and save
  const chips = await p.$$('.grow[data-i="0"] .dchip');
  await p.click(`[data-rm="0:${chips.length - 1}"]`);
  await p.click("#saveBtn"); await p.waitForTimeout(600);
  const corr = await state();
  assert(Math.abs(s1(corr).gross - s1(before).gross - 800) < 0.01, "grid correction removed the deal");
  // edit most recent entry via modal
  await p.click("[data-edit]");
  await p.waitForSelector("#mKind");
  const kind = await p.inputValue("#mKind");
  if (kind === "used") { await p.fill("#mGross", "900"); } else { await p.fill("#mUnits", "2"); }
  await p.click("#mSave"); await p.waitForTimeout(600);
  const ed = await state();
  assert(JSON.stringify(s1(ed)) !== JSON.stringify(s1(corr)), "edit modal changed the numbers (" + kind + ")");
  // delete (unwind) the most recent entry
  const cnt = (await p.$$("[data-del]")).length;
  await p.click("[data-del]"); await p.waitForTimeout(600);
  const del = await state();
  assert(JSON.stringify(s1(del)) !== JSON.stringify(s1(ed)), "delete removed an entry");
  // admin (single store): no store switcher, enter a PAST day, delete an entry
  await p.request.post(BASE + "/api/logout", { data: {} });
  await p.goto(BASE + "/login?next=/enter"); await p.keyboard.type("9999"); await p.keyboard.press("Enter");
  await p.waitForSelector(".grow");
  assert((await p.$$(".tab")).length === 0, "single store: admin sees no store tabs");
  assert((await p.textContent(".head h1")).includes("Chrysler Muskegon"), "admin entry header is Chrysler Muskegon");
  await p.fill("#dateIn", "2026-09-26"); await p.dispatchEvent("#dateIn", "change"); await p.waitForTimeout(500);
  assert((await p.inputValue("#dateIn")) === "2026-09-26", "admin can open a past day");
  const pre = await state();
  const rows = await p.$$eval(".grow", (els) => els.length);
  await p.click('[data-inc="0"]');
  await p.fill(`[data-g="${rows - 1}"]`, "2500"); await p.click(`[data-add="${rows - 1}"]`);
  await p.click("#saveBtn"); await p.waitForTimeout(800);
  const post = await state();
  assert(Math.abs(s1(post).new - s1(pre).new - 0.5) < 1e-9, "admin saved +0.5 new on a past day");
  assert(Math.abs(s1(post).gross - s1(pre).gross - 2500) < 0.01, "admin saved +$2,500 used in the same save");
  await p.click("[data-del]"); await p.waitForTimeout(600);
  assert(JSON.stringify(s1(await state())) !== JSON.stringify(s1(post)), "admin deleted an entry");
  // leaderboard renders
  await p.goto(BASE + "/"); await p.waitForSelector(".scard");
  assert((await p.$$(".scard")).length === 1, "leaderboard shows 1 store-goal card");
  assert((await p.$$(".lb")).length >= 4, "leaderboard shows the 4 individual boards + earnings");
  assert(errs.length === 0, "no JS errors " + errs.join("; "));
  await b.close();
})();
