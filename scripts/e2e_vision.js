/* Tiệm Quen — vision e2e: drive real Chrome/Chromium through the FULL buyer,
 * group-order and seller journeys and screenshot every step. The screenshots
 * are then reviewed visually (by a human or a vision model) — this complements
 * scripts/e2e_smoke.py (API truth) and the DOM-asserting Playwright reviews:
 * it catches what only eyes catch (contrast, clipped text, broken layout,
 * theme bleed, wrong copy).
 *
 * Usage:  node scripts/e2e_vision.js [--base http://127.0.0.1:8787] [--out DIR]
 * Needs:  a running server (uvicorn agents.tiemquen_agent.server:app) with the
 *         demo shop seeded+composed, and `playwright` resolvable (falls back to
 *         ~/node_modules). Exits non-zero on any navigation/console error;
 *         screenshot review happens after.
 */
"use strict";

function requirePlaywright() {
  var candidates = ["playwright", process.env.HOME + "/node_modules/playwright"];
  for (var i = 0; i < candidates.length; i++) {
    try { return require(candidates[i]); } catch (e) { /* next */ }
  }
  console.error("playwright not found — npm i playwright (or set NODE_PATH)");
  process.exit(2);
}
var { chromium } = requirePlaywright();
var fs = require("fs");
var path = require("path");

var args = process.argv.slice(2);
function argOf(flag, dflt) {
  var i = args.indexOf(flag);
  return i !== -1 && args[i + 1] ? args[i + 1] : dflt;
}
var BASE = argOf("--base", "http://127.0.0.1:8787");
var OUT = argOf("--out", path.join(__dirname, "..", "data", "e2e_vision"));
var SLUG = argOf("--slug", "com-tam-co-ba");
var MOBILE = { width: 390, height: 844 };
var DESKTOP = { width: 1440, height: 900 };

fs.mkdirSync(OUT, { recursive: true });

var errors = [];   // console/page/network errors — hard fail
var shots = [];    // {file, caption} manifest for the reviewer
var n = 0;

function watch(page, label) {
  page.on("console", function (msg) {
    if (msg.type() === "error") errors.push(label + " console: " + msg.text());
  });
  page.on("pageerror", function (err) { errors.push(label + " pageerror: " + err.message); });
  page.on("response", function (r) {
    if (r.status() >= 400) errors.push(label + " HTTP " + r.status() + " " + r.url());
  });
}

async function snap(page, name, caption) {
  n += 1;
  var file = String(n).padStart(2, "0") + "-" + name + ".png";
  await page.screenshot({ path: path.join(OUT, file), fullPage: true });
  shots.push({ file: file, caption: caption });
  console.log("  📸 " + file + " — " + caption);
}

async function api(pageOrCtx, method, url, body) {
  var res = await pageOrCtx.request.fetch(BASE + url, {
    method: method,
    headers: { "Content-Type": "application/json" },
    data: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok()) throw new Error(method + " " + url + " -> " + res.status() + " " + (await res.text()));
  return res.json();
}

(async function main() {
  var browser;
  try {
    browser = await chromium.launch({ channel: "chrome" });
    console.log("engine: real Chrome");
  } catch (e) {
    browser = await chromium.launch();
    console.log("engine: bundled Chromium (Chrome channel unavailable)");
  }

  var ctx = await browser.newContext({
    viewport: MOBILE,
    locale: "vi-VN",
    timezoneId: "Asia/Ho_Chi_Minh",
    permissions: ["clipboard-read", "clipboard-write"],
  });
  var page = await ctx.newPage();
  watch(page, "buyer");
  page.on("dialog", function (d) { d.accept(); });

  // ------------------------------------------------------------ BUYER (mobile)
  console.log("== buyer flow (mobile) ==");
  await page.goto(BASE + "/t/" + SLUG);
  await page.waitForSelector(".tq-dish");
  await snap(page, "buyer-menu", "Buyer menu, mobile — hero, sections, dish cards, prices");

  var addBtns = page.locator(".tq-btn-add:not([disabled])");
  await addBtns.nth(0).click();
  await page.waitForSelector(".tq-stepper");
  await addBtns.nth(0).click(); // second distinct dish (list re-rendered)
  await snap(page, "buyer-cart", "2 dishes added — steppers [− n +] + cart bar + checkout form visible");

  await page.fill('input[name="name"]', "Chị Loan");
  await page.fill('input[name="phone"]', "0909123456");
  await page.fill('input[name="address"]', "Tầng 4, toà nhà ABC, Q.1");
  await snap(page, "buyer-checkout-filled", "Checkout form filled (tên/SĐT/địa chỉ)");

  await page.click(".tq-btn-submit");
  await page.waitForSelector(".tq-recap-card");
  await snap(page, "buyer-recap", "Post-submit recap — order #, line prices, COD total, gọi quán, live status");

  await page.reload();
  await page.waitForSelector(".tq-recap-card", { timeout: 8000 });
  await snap(page, "buyer-recap-resume", "Reload right after ordering — recap + live status resumed");

  await page.click(".tq-btn-more");
  await page.waitForSelector(".tq-dish");

  // Order still active -> every fresh /t/{slug} visit resumes the recap (by
  // design). Clear it so the remaining menu steps see the menu.
  await page.evaluate(function (slug) { localStorage.removeItem("tq_last_order_" + slug); }, SLUG);

  // office-batch variant: group-order button should be prominent
  await page.goto(BASE + "/t/" + SLUG + "?b=office-plaza1");
  await page.waitForSelector(".tq-dish");
  await snap(page, "buyer-office-variant", "Office variant (?b=office-plaza1) — nút Gom đơn cả phòng");

  // ------------------------------------------------------------ GROUP ORDER
  console.log("== group order flow ==");
  var g = await api(page, "POST", "/group-orders", { slug: SLUG, batch_id: "office-plaza1" });
  await page.goto(BASE + "/g/" + g.gid);
  await page.waitForSelector("form.tq-checkout");
  await snap(page, "group-empty", "Group page fresh — shop name in header, empty member list, dish qty form");

  await api(page, "POST", "/group-orders/" + g.gid + "/members", {
    name: "An", items: [{ dish_id: "dish_suon_nuong", name: "Cơm tấm sườn nướng", price: 35000, qty: 1 }],
  });
  await api(page, "POST", "/group-orders/" + g.gid + "/members", {
    name: "Bình", items: [
      { dish_id: "dish_suon_bi_cha", name: "Cơm tấm sườn bì chả", price: 45000, qty: 1 },
      { dish_id: "dish_tra_da", name: "Trà đá", price: 3000, qty: 2 },
    ],
  });
  await page.waitForTimeout(6000); // 5s poll picks the members up
  await snap(page, "group-members", "2 members auto-appeared via poll — per-member items + subtotals");

  var qty = page.locator(".tqg-dish-row input").first();
  await qty.fill("2");
  await snap(page, "group-subtotal", "Live 'Phần của bạn' subtotal while picking quantities");

  var closeForm = page.locator("form.tq-checkout").last();
  await closeForm.locator('input[name="phone"]').fill("0909111222");
  await closeForm.locator('input[name="address"]').fill("Toà A, Q.1");
  await closeForm.locator('input[name="payer_bank"]').fill("MB");
  await closeForm.locator('input[name="payer_account"]').fill("0123456789");
  await snap(page, "group-close-form", "Close form — closer picker + optional bank/STK fields");

  await closeForm.locator(".tq-btn-submit").click();
  await page.waitForSelector(".tqg-pay-actions", { timeout: 8000 });
  await snap(page, "group-closed", "Closed — per-member 🏦 mở app bank (đúng số tiền) + 📋 copy STK");

  // ------------------------------------------------------------ SELLER (mobile)
  console.log("== seller flow (mobile) ==");
  var sctx = await browser.newContext({
    viewport: MOBILE, locale: "vi-VN", timezoneId: "Asia/Ho_Chi_Minh",
  });
  var sp = await sctx.newPage();
  watch(sp, "seller");
  await sp.addInitScript(function (slug) { localStorage.setItem("tq_seller_slug", slug); }, SLUG);

  await sp.goto(BASE + "/seller/");
  await sp.waitForSelector(".tq-order, #orders-list .tq-hint");
  await snap(sp, "seller-orders", "Đơn tab — VN status badges, local times, tel: phone, 44px actions");

  await sp.click('[data-tab="menu"]');
  await sp.waitForSelector(".tq-menu-row");
  await snap(sp, "seller-menu", "Menu tab — sections, Còn/HẾT toggles, Sắp hết, price edit");

  await sp.locator(".tq-menu-row .tq-toggle").first().click();
  await sp.waitForTimeout(600);
  await snap(sp, "seller-menu-soldout", "First dish toggled HẾT MÓN (red)");

  // buyer sees it immediately
  await page.goto(BASE + "/t/" + SLUG);
  await page.waitForSelector(".tq-dish");
  await page.waitForTimeout(800); // background soldout patch
  await snap(page, "buyer-sees-soldout", "Buyer page — dish now 'Hết món' (disabled, dimmed)");

  await sp.locator(".tq-menu-row .tq-toggle").first().click(); // restore
  await sp.waitForTimeout(400);

  await sp.click('[data-tab="flyers"]');
  await sp.fill("#fl-location", "pantry-vision");
  await sp.locator(".fl-format").nth(1).uncheck(); // just A5 — keep the run fast
  await sp.click("#fl-generate");
  // old batch cards also carry .tq-flyer-link — wait for THIS run's result box
  await sp.waitForSelector("#fl-results .tq-flyer-link", { timeout: 60000 });
  await snap(sp, "seller-flyer", "Tờ rơi tab — download links, batch list with ⬇ Tải lại PDF");

  await sp.click('[data-tab="onboard"]');
  await snap(sp, "seller-onboard", "Mở tiệm tab — import options ('Dùng menu mẫu')");

  // ------------------------------------------------------------ DESKTOP + 3 SHOPS
  console.log("== desktop + other shops ==");
  var dctx = await browser.newContext({ viewport: DESKTOP, locale: "vi-VN", timezoneId: "Asia/Ho_Chi_Minh" });
  var dp = await dctx.newPage();
  watch(dp, "desktop");
  await dp.goto(BASE + "/t/" + SLUG);
  await dp.waitForSelector(".tq-dish");
  await snap(dp, "buyer-desktop", "Buyer menu desktop 1440px — centered column, no stretching");

  // Extra pilot shops — skipped gracefully when not seeded.
  var otherSlugs = ["bun-bo-di-bay", "pho-ga-ut-nho"];
  for (var k = 0; k < otherSlugs.length; k++) {
    var s = otherSlugs[k];
    var r = await page.request.fetch(BASE + "/t/" + s);
    if (!r.ok()) { console.log("  (skip " + s + " — not seeded)"); continue; }
    await page.goto(BASE + "/t/" + s);
    await page.waitForSelector(".tq-dish");
    await snap(page, "buyer-" + s, "Shop #" + (k + 2) + " '" + s + "' — own theme, no theme bleed");
  }

  await browser.close();

  fs.writeFileSync(path.join(OUT, "manifest.json"), JSON.stringify({ base: BASE, shots: shots, errors: errors }, null, 2));
  console.log("\n" + shots.length + " screenshots -> " + OUT);
  if (errors.length) {
    console.error("HARD ERRORS (" + errors.length + "):");
    errors.forEach(function (e) { console.error("  ✗ " + e); });
    process.exit(1);
  }
  console.log("no console/page/network errors — review the screenshots visually.");
})().catch(function (err) {
  console.error("vision e2e crashed:", err);
  process.exit(1);
});
