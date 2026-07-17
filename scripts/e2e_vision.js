/* Tiệm Quen — vision e2e: drive real Chrome/Chromium through the FULL buyer,
 * group-order and seller journeys (React + shadcn + OpenUI Lang UI) and
 * screenshot every step. Screenshots are then reviewed visually (human or
 * vision model) — complements scripts/e2e_smoke.py (API truth) and
 * scripts/e2e_web.js (DOM assertions): catches what only eyes catch
 * (contrast, clipped text, broken layout, theme bleed, wrong copy).
 *
 * Usage:  node scripts/e2e_vision.js [--base http://127.0.0.1:8787] [--out DIR]
 * Needs:  running server + web/dist built + demo shop seeded/composed, and
 *         `playwright` resolvable (falls back to ~/node_modules).
 * Exits non-zero on any console/page/network error; review happens after.
 */
"use strict";

function requirePlaywright() {
  for (const c of ["playwright", process.env.HOME + "/node_modules/playwright"]) {
    try { return require(c); } catch { /* next */ }
  }
  console.error("playwright not found — npm i playwright (or set NODE_PATH)");
  process.exit(2);
}
const { chromium } = requirePlaywright();
const fs = require("fs");
const path = require("path");

const args = process.argv.slice(2);
const argOf = (f, d) => { const i = args.indexOf(f); return i !== -1 && args[i + 1] ? args[i + 1] : d; };
const BASE = argOf("--base", "http://127.0.0.1:8787");
const OUT = argOf("--out", path.join(__dirname, "..", "data", "e2e_vision"));
const SLUG = argOf("--slug", "com-tam-co-ba");
const MOBILE = { width: 390, height: 844 };
const DESKTOP = { width: 1440, height: 900 };

fs.mkdirSync(OUT, { recursive: true });

const errors = [];
const shots = [];
let n = 0;

function watch(page, label) {
  page.on("console", (m) => {
    if (m.type() === "error" && !/favicon/.test(m.text())) errors.push(`${label} console: ${m.text()}`);
  });
  page.on("pageerror", (e) => errors.push(`${label} pageerror: ${e.message}`));
  page.on("response", (r) => {
    if (r.status() >= 400 && !/favicon/.test(r.url())) errors.push(`${label} HTTP ${r.status()} ${r.url()}`);
  });
}

async function snap(page, name, caption) {
  n += 1;
  const file = `${String(n).padStart(2, "0")}-${name}.png`;
  await page.screenshot({ path: path.join(OUT, file), fullPage: true });
  shots.push({ file, caption });
  console.log(`  📸 ${file} — ${caption}`);
}

async function api(pg, method, url, body) {
  const res = await pg.request.fetch(BASE + url, {
    method,
    headers: { "Content-Type": "application/json" },
    data: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok()) throw new Error(`${method} ${url} -> ${res.status()} ${await res.text()}`);
  return res.json();
}

(async () => {
  let browser;
  try {
    browser = await chromium.launch({ channel: "chrome" });
    console.log("engine: real Chrome");
  } catch {
    browser = await chromium.launch();
    console.log("engine: bundled Chromium (Chrome channel unavailable)");
  }

  const mkCtx = (vp) =>
    browser.newContext({ viewport: vp, locale: "vi-VN", timezoneId: "Asia/Ho_Chi_Minh" });

  // ------------------------------------------------------------ BUYER (mobile)
  console.log("== buyer flow (mobile) ==");
  const ctx = await mkCtx(MOBILE);
  const page = await ctx.newPage();
  watch(page, "buyer");
  page.on("dialog", (d) => d.accept());

  await page.goto(`${BASE}/t/${SLUG}`);
  await page.waitForSelector('[data-testid="dish-card"]');
  await snap(page, "buyer-menu", "Buyer menu, mobile — hero, sections, dish cards, prices");

  const addBtns = page.locator('[data-testid="add-btn"]:not([disabled])');
  await addBtns.first().click();
  await page.waitForSelector('[data-testid="stepper"]');
  await addBtns.first().click(); // second distinct dish
  await snap(page, "buyer-cart", "2 dishes added — steppers [− n +] + cart bar + checkout form visible");

  await page.fill("#f-name", "Chị Loan");
  await page.fill("#f-phone", "0909123456");
  await page.fill("#f-address", "Tầng 4, toà nhà ABC, Q.1");
  await snap(page, "buyer-checkout-filled", "Checkout form filled (tên/SĐT/địa chỉ)");

  await page.click('[data-testid="submit-btn"]');
  await page.waitForSelector('[data-testid="recap"]');
  await snap(page, "buyer-recap", "Post-submit recap — order #, line prices, COD total, gọi quán, live status");

  await page.reload();
  await page.waitForSelector('[data-testid="recap"]', { timeout: 8000 });
  await snap(page, "buyer-recap-resume", "Reload right after ordering — recap + live status resumed");

  await page.click('[data-testid="order-more"]');
  await page.waitForSelector('[data-testid="dish-card"]');
  // Order still active -> fresh /t/{slug} visits resume the recap (by design).
  await page.evaluate((slug) => localStorage.removeItem(`tq_last_order_${slug}`), SLUG);

  await page.goto(`${BASE}/t/${SLUG}?b=office-plaza1`);
  await page.waitForSelector('[data-testid="dish-card"]');
  await snap(page, "buyer-office-variant", "Office variant (?b=office-plaza1) — nút Gom đơn cả phòng");

  // ------------------------------------------------------------ GROUP ORDER
  console.log("== group order flow ==");
  const g = await api(page, "POST", "/group-orders", { slug: SLUG, batch_id: "office-plaza1" });
  await page.goto(`${BASE}/g/${g.gid}`);
  await page.waitForSelector('[data-testid="add-part"]');
  await snap(page, "group-empty", "Group page fresh — shop name in header, empty member list, dish qty form");

  await api(page, "POST", `/group-orders/${g.gid}/members`, {
    name: "An", items: [{ dish_id: "dish_suon_nuong", name: "Cơm tấm sườn nướng", price: 35000, qty: 1 }],
  });
  await api(page, "POST", `/group-orders/${g.gid}/members`, {
    name: "Bình",
    items: [
      { dish_id: "dish_suon_bi_cha", name: "Cơm tấm sườn bì chả", price: 45000, qty: 1 },
      { dish_id: "dish_tra_da", name: "Trà đá", price: 3000, qty: 2 },
    ],
  });
  await page.waitForTimeout(6000); // 5s poll picks the members up
  await snap(page, "group-members", "2 members auto-appeared via poll — per-member items + subtotals");

  await page.locator('[data-testid="add-part"] input[type="number"]').first().fill("2");
  await snap(page, "group-subtotal", "Live 'Phần của bạn' subtotal while picking quantities");

  await page.fill("#g-phone", "0909111222");
  await page.fill("#g-address", "Toà A, Q.1");
  await page.fill("#g-bank", "MB");
  await page.fill("#g-account", "0123456789");
  await snap(page, "group-close-form", "Close form — closer picker + optional bank/STK fields");

  await page.locator('[data-testid="close-form"] button[type="submit"]').click();
  await page.waitForSelector('[data-testid="closed"]', { timeout: 8000 });
  await snap(page, "group-closed", "Closed — per-member 🏦 mở app bank (đúng số tiền) + 📋 copy STK");

  // ------------------------------------------------------------ SELLER (mobile)
  console.log("== seller flow (mobile) ==");
  const sctx = await mkCtx(MOBILE);
  const sp = await sctx.newPage();
  watch(sp, "seller");
  await sp.addInitScript((slug) => localStorage.setItem("tq_seller_slug", slug), SLUG);

  await sp.goto(`${BASE}/seller/`);
  await sp.waitForSelector('[data-testid="order-card"]', { timeout: 8000 });
  await snap(sp, "seller-orders", "Đơn tab — VN status badges, local times, tel: phone, action buttons");

  await sp.click('[data-testid="tab-menu"]');
  await sp.waitForSelector('[data-testid="menu-row"]');
  await snap(sp, "seller-menu", "Menu tab — sections, Hết món/Sắp hết switches, price edit");

  await sp.locator('[data-testid="menu-row"]').first().locator('[data-testid="soldout-switch"]').click();
  await sp.waitForTimeout(700);
  await snap(sp, "seller-menu-soldout", "First dish toggled HẾT MÓN (strikethrough)");

  await page.goto(`${BASE}/t/${SLUG}`);
  await page.waitForSelector('[data-testid="dish-card"]');
  await page.waitForTimeout(800); // background sold-out patch
  await snap(page, "buyer-sees-soldout", "Buyer page — dish now 'Hết món' (disabled, dimmed)");

  await sp.locator('[data-testid="menu-row"]').first().locator('[data-testid="soldout-switch"]').click(); // restore
  await sp.waitForTimeout(500);

  await sp.click('[data-testid="tab-flyers"]');
  await sp.waitForSelector('[data-testid="flyers"]');
  await sp.fill("#fl-loc", "pantry-vision");
  // only A5: turn A4 off (switch #2 in the flyers card)
  await sp.locator('[data-testid="flyers"] button[role="switch"]').nth(1).click();
  await sp.click('[data-testid="generate-flyers"]');
  await sp.waitForSelector('[data-testid="flyer-result"]', { timeout: 60000 });
  await snap(sp, "seller-flyer", "Tờ rơi tab — download links, batch list with ⬇ Tải lại PDF");

  await sp.click('[data-testid="tab-onboard"]');
  await sp.waitForSelector('[data-testid="onboard"]');
  await snap(sp, "seller-onboard", "Mở tiệm tab — import options ('Dùng menu mẫu')");

  // ------------------------------------------------------------ DESKTOP + 3 SHOPS
  console.log("== desktop + other shops ==");
  const dctx = await mkCtx(DESKTOP);
  const dp = await dctx.newPage();
  watch(dp, "desktop");
  await dp.goto(`${BASE}/t/${SLUG}`);
  await dp.waitForSelector('[data-testid="dish-card"]');
  await snap(dp, "buyer-desktop", "Buyer menu desktop 1440px — centered column, no stretching");

  for (const [i, s] of ["bun-bo-di-bay", "pho-ga-ut-nho"].entries()) {
    const r = await page.request.fetch(`${BASE}/t/${s}`);
    if (!r.ok()) { console.log(`  (skip ${s} — not seeded)`); continue; }
    await page.goto(`${BASE}/t/${s}`);
    await page.waitForSelector('[data-testid="dish-card"]');
    await snap(page, `buyer-${s}`, `Shop #${i + 2} '${s}' — own theme, no theme bleed`);
  }

  await browser.close();

  fs.writeFileSync(path.join(OUT, "manifest.json"), JSON.stringify({ base: BASE, shots, errors }, null, 2));
  console.log(`\n${shots.length} screenshots -> ${OUT}`);
  if (errors.length) {
    console.error(`HARD ERRORS (${errors.length}):`);
    errors.forEach((e) => console.error(`  ✗ ${e}`));
    process.exit(1);
  }
  console.log("no console/page/network errors — review the screenshots visually.");
})().catch((err) => {
  console.error("vision e2e crashed:", err);
  process.exit(1);
});
