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
  assert(day === "2026-10-17", "entry date defaults to last selling day (Sat before simulated Sunday) = " + day);
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
  // admin: all-stores grid, enter for two different stores on a PAST day, then correct another store's entry
  await p.request.post(BASE + "/api/logout", { data: {} });
  await p.goto(BASE + "/login?next=/enter"); await p.keyboard.type("9999"); await p.keyboard.press("Enter");
  await p.waitForSelector(".tabs");
  assert((await p.$$(".tab")).length === 4, "admin sees store switcher: All stores + 3 stores");
  await p.click('[data-tab="all"]'); await p.waitForSelector(".gsec");
  assert((await p.$$(".gsec")).length === 3, "All-stores grid shows 3 store sections");
  await p.fill("#dateIn", "2026-10-05"); await p.dispatchEvent("#dateIn", "change"); await p.waitForTimeout(500);
  assert((await p.inputValue("#dateIn")) === "2026-10-05", "admin can open a past day");
  const pre = await state();
  const secRows = await p.$$eval(".grow", (els) => els.length);
  await p.click('[data-inc="0"]');                                   // store 1, first rep +0.5
  await p.fill(`[data-g="${secRows - 1}"]`, "2500"); await p.click(`[data-add="${secRows - 1}"]`); // last rep = store 3
  await p.click("#saveBtn"); await p.waitForTimeout(800);
  const post = await state();
  const sx = (r, id) => r.stores.find((s) => s.id === id);
  assert(Math.abs(sx(post, 1).new - sx(pre, 1).new - 0.5) < 1e-9, "admin saved store 1 (+0.5 new) from the All-stores grid");
  assert(Math.abs(sx(post, 3).gross - sx(pre, 3).gross - 2500) < 0.01, "admin saved store 3 (+$2,500 used) in the same save");
  await p.click('[data-tab="2"]'); await p.waitForSelector(".grow");
  await p.click("[data-del]"); await p.waitForTimeout(600);
  assert(JSON.stringify(sx(await state(), 2)) !== JSON.stringify(sx(post, 2)), "admin deleted a store-2 entry");
  // leaderboard renders
  await p.goto(BASE + "/"); await p.waitForSelector(".scard");
  assert((await p.$$(".scard")).length === 3, "leaderboard shows 3 store cards");
  assert(errs.length === 0, "no JS errors " + errs.join("; "));
  await b.close();
})();
