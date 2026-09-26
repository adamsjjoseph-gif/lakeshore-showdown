// Takes the README screenshots with headless Chrome via playwright-core.
// Usage: NODE_PATH=/path/to/node_modules node tools/screenshots.js http://localhost:8787
const { chromium } = require("playwright-core");
const BASE = process.argv[2] || "http://localhost:8787";
const OUT = __dirname + "/../screenshots";
(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROME || "/usr/bin/google-chrome", args: ["--no-sandbox"] });
  const errors = [];
  const shot = async (ctxOpts, fn, name, full = true) => {
    const ctx = await browser.newContext(ctxOpts);
    const page = await ctx.newPage();
    page.on("pageerror", (e) => errors.push(name + ": " + e.message));
    page.on("console", (m) => m.type() === "error" && errors.push(name + " console: " + m.text()));
    await fn(page);
    await page.waitForTimeout(700);
    await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: full });
    await ctx.close();
  };
  const login = async (page, pin, next) => {
    await page.goto(`${BASE}/login?next=${encodeURIComponent(next)}`);
    await page.keyboard.type(pin);
    await page.keyboard.press("Enter");
    await page.waitForURL((u) => !u.pathname.startsWith("/login"));
    await page.waitForLoadState("networkidle");
  };
  const desktop = { viewport: { width: 1440, height: 960 }, deviceScaleFactor: 1 };
  const phone = { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true };
  await shot(desktop, async (p) => { await p.goto(BASE + "/"); await p.waitForSelector(".scard"); }, "leaderboard_desktop");
  await shot(desktop, async (p) => { await p.goto(BASE + "/"); await p.waitForSelector(".scard"); }, "leaderboard_desktop_top", false);
  await shot(phone, async (p) => { await p.goto(BASE + "/"); await p.waitForSelector(".scard"); }, "leaderboard_phone");
  await shot(phone, async (p) => { await p.goto(BASE + "/"); await p.waitForSelector(".scard"); }, "leaderboard_phone_top", false);
  await shot(desktop, async (p) => {
    await login(p, "1111", "/enter"); await p.waitForSelector(".grow");
    // simulate a manager typing: bump a rep's new units and add a used deal (not saved)
    await p.click('[data-inc="0"]'); await p.click('[data-inc="0"]'); await p.fill('[data-g="1"]', "2875"); await p.click('[data-add="1"]');
    await p.click('[data-split="5"]'); await p.fill('[data-g="5"]', "1150"); await p.click('[data-add="5"]');
  }, "entry_desktop", false);
  await shot(desktop, async (p) => { await login(p, "1111", "/enter"); await p.waitForSelector(".grow"); }, "entry_desktop_full");
  await shot(phone, async (p) => { await login(p, "2222", "/enter"); await p.waitForSelector(".grow"); await p.click('[data-inc="2"]'); await p.fill('[data-g="0"]', "3100"); await p.click('[data-add="0"]'); }, "entry_phone", false);
  await shot(desktop, async (p) => { await login(p, "9999", "/admin"); await p.waitForSelector("#saveSettings"); }, "admin_desktop");
  await shot(desktop, async (p) => { await login(p, "9999", "/admin"); await p.waitForSelector("#saveSettings"); await p.evaluate(() => { const el = document.querySelector("#saveSettings").closest("section"); window.scrollTo(0, el.getBoundingClientRect().top + scrollY - 80); }); }, "admin_settings", false);
  await shot(desktop, async (p) => {
    await login(p, "9999", "/enter?store=all"); await p.waitForSelector(".gsec");
    await p.click('[data-inc="0"]'); await p.fill('[data-g="8"]', "2650"); await p.click('[data-add="8"]');
    await p.evaluate(() => { document.activeElement.blur(); window.scrollTo(0, 0); });
  }, "admin_entry_all_stores", false);
  await shot(desktop, async (p) => { await login(p, "9999", "/enter?store=all"); await p.waitForSelector(".gsec"); }, "admin_entry_all_stores_full");
  await shot(desktop, async (p) => {
    await login(p, "9999", "/enter?store=3&date=2026-10-05"); await p.waitForSelector(".grow");
  }, "admin_entry_store_tab_past_day", false);
  await shot(phone, async (p) => { await login(p, "9999", "/enter?store=all"); await p.waitForSelector(".gsec"); }, "admin_entry_phone", false);
  await shot(phone, async (p) => { await p.goto(BASE + "/login?next=/enter"); await p.keyboard.type("11"); }, "login_phone", false);
  await browser.close();
  if (errors.length) { console.log("PAGE ERRORS:\n" + errors.join("\n")); process.exitCode = 1; } else console.log("screenshots ok");
})();
