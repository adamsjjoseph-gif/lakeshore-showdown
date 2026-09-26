// Screenshots of the leaderboard + entry form (phone and desktop) against any base URL. Never saves entries.
// Usage: NODE_PATH=/usr/local/lib/node_modules STORE_PIN=xxxxxx PREFIX=live_ node tools/screenshots_v2.js https://lakeshore-showdown.onrender.com
const { chromium } = require("playwright-core");
const BASE = process.argv[2] || "http://localhost:8787";
const OUT = __dirname + "/../screenshots";
const PIN = process.env.STORE_PIN, PREFIX = process.env.PREFIX || "";
const ONLY = (process.env.ONLY || "board,entry").split(",");
(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROME || "/usr/bin/google-chrome", args: ["--no-sandbox"] });
  const errors = [], saved = [];
  const shot = async (ctxOpts, fn, name, full = true) => {
    const ctx = await browser.newContext({ ...ctxOpts, timezoneId: "America/New_York" });
    const page = await ctx.newPage();
    page.on("pageerror", (e) => errors.push(name + ": " + e.message));
    page.on("console", (m) => m.type() === "error" && errors.push(name + " console: " + m.text()));
    await fn(page);
    await page.waitForTimeout(1200);
    const path = `${OUT}/${PREFIX}${name}.png`;
    await page.screenshot({ path, fullPage: full });
    saved.push(path);
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
  const board = async (p) => { await p.goto(BASE + "/"); await p.waitForSelector(".scard"); await p.waitForSelector("#cdClock .cd-u, #cdClock .cd-over"); };
  if (ONLY.includes("board")) {
    await shot(desktop, board, "leaderboard_desktop");
    await shot(desktop, board, "leaderboard_desktop_top", false);
    await shot(phone, board, "leaderboard_phone");
    await shot(phone, board, "leaderboard_phone_top", false);
  }
  if (ONLY.includes("entry") && PIN) {
    // typed but NOT saved: shows the appointments field in use
    const fill = async (p) => {
      await login(p, PIN, "/enter"); await p.waitForSelector(".grow");
      await p.click('[data-inc="0"]'); await p.click('[data-ainc="0"]'); await p.click('[data-ainc="0"]'); await p.click('[data-ainc="0"]');
      await p.click('[data-ainc="1"]'); await p.fill('[data-g="1"]', "2875"); await p.click('[data-add="1"]');
      await p.evaluate(() => { document.activeElement.blur(); window.scrollTo(0, 0); });
    };
    await shot(desktop, fill, "entry_desktop_appointments", false);
    await shot(desktop, async (p) => { await login(p, PIN, "/enter"); await p.waitForSelector(".grow"); }, "entry_desktop_appointments_full");
    await shot(phone, fill, "entry_phone_appointments", false);
    await shot(phone, async (p) => { await login(p, PIN, "/enter"); await p.waitForSelector(".grow"); }, "entry_phone_appointments_full");
  }
  await browser.close();
  console.log(saved.join("\n"));
  if (errors.length) { console.log("PAGE ERRORS:\n" + errors.join("\n")); process.exitCode = 1; } else console.log("screenshots ok");
})();
