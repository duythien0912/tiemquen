/* Tiệm Quen — web e2e (React + shadcn + OpenUI Lang renderer).
 * MAIN flows AND EDGE flows, DOM-asserted with Playwright against a running
 * server (uvicorn agents.tiemquen_agent.server:app --port 8787) with the demo
 * shop seeded + composed and web/dist built.
 *
 * Usage: node scripts/e2e_web.js [--base http://127.0.0.1:8787]
 * Exit 0 = every check passed. Prints a PASS/FAIL table.
 */
"use strict";

function requirePlaywright() {
  for (const c of ["playwright", process.env.HOME + "/node_modules/playwright"]) {
    try { return require(c); } catch { /* next */ }
  }
  console.error("playwright not found");
  process.exit(2);
}
const { chromium } = requirePlaywright();

const args = process.argv.slice(2);
const BASE = (() => { const i = args.indexOf("--base"); return i >= 0 ? args[i + 1] : "http://127.0.0.1:8787"; })();
const SLUG = "com-tam-co-ba";
const MOBILE = { width: 390, height: 844 };

const results = [];
let failures = 0;
function check(name, ok, detail) {
  results.push({ name, ok, detail: detail || "" });
  if (!ok) failures++;
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${detail && !ok ? " — " + detail : ""}`);
}

async function api(ctx, method, url, body) {
  const res = await ctx.request.fetch(BASE + url, {
    method,
    headers: { "Content-Type": "application/json" },
    data: body ? JSON.stringify(body) : undefined,
  });
  return { status: res.status(), body: res.ok() ? await res.json() : await res.text() };
}

(async () => {
  const browser = await chromium.launch();
  const consoleErrors = [];

  async function newPage(ctxOpts = {}) {
    const ctx = await browser.newContext({
      viewport: MOBILE,
      locale: "vi-VN",
      timezoneId: "Asia/Ho_Chi_Minh",
      ...ctxOpts,
    });
    const pg = await ctx.newPage();
    pg.on("console", (m) => m.type() === "error" && consoleErrors.push(m.text()));
    pg.on("pageerror", (e) => consoleErrors.push("PAGEERR " + e.message));
    return { ctx, pg };
  }

  /* ================================ MAIN: buyer order flow ================ */
  console.log("== MAIN: buyer order ==");
  {
    const { ctx, pg } = await newPage();
    await pg.goto(`${BASE}/t/${SLUG}`);
    await pg.waitForSelector('[data-testid="dish-card"]');
    check("buyer: menu renders via OpenUI", (await pg.locator('[data-testid="dish-card"]').count()) >= 8);
    check("buyer: checkout hidden while cart empty", (await pg.locator('[data-testid="checkout"]').count()) === 0);

    const add = pg.locator('[data-testid="dish-card"]:not(:has(button[disabled])) [data-testid="add-btn"]');
    await add.first().click();
    await pg.waitForSelector('[data-testid="stepper"]');
    check("buyer: stepper appears after add", true);
    await add.first().click(); // second dish (list shifts as first became stepper)
    check("buyer: cart bar shows 2 items", await pg.locator('[data-testid="cartbar"]').innerText().then((t) => t.includes("2 món")));

    // stepper minus returns to Thêm
    await pg.locator('[data-testid="stepper"] button', { hasText: "−" }).first().click();
    await pg.waitForTimeout(200);
    check("buyer: minus removes item", (await pg.locator('[data-testid="stepper"]').count()) === 1);
    // re-add
    await add.first().click();

    // typed text survives re-render (state lives in React now, still assert)
    await pg.fill("#f-name", "Chị Loan");
    await add.nth(1).click().catch(() => {});
    check("buyer: typed name survives adding dish", (await pg.inputValue("#f-name")) === "Chị Loan");

    // cart persists reload
    await pg.reload();
    await pg.waitForSelector('[data-testid="cartbar"]');
    check("buyer: cart persists reload", (await pg.locator('[data-testid="cartbar"]').innerText()).includes("món"));

    // submit
    await pg.fill("#f-name", "Chị Loan");
    await pg.fill("#f-phone", "0909123456");
    await pg.fill("#f-address", "Tầng 4, toà nhà ABC, Q.1");
    // count POSTs to /orders while double-clicking
    let orderPosts = 0;
    pg.on("request", (r) => { if (r.url().endsWith("/orders") && r.method() === "POST") orderPosts++; });
    await pg.click('[data-testid="submit-btn"]');
    await pg.click('[data-testid="submit-btn"]').catch(() => {});
    await pg.waitForSelector('[data-testid="recap"]', { timeout: 8000 });
    check("buyer: recap after submit", true);
    check("edge: double-tap submit → 1 order", orderPosts === 1, `posts=${orderPosts}`);
    check("buyer: recap shows COD total", (await pg.locator('[data-testid="recap"]').innerText()).includes("tiền mặt"));
    check("buyer: recap has tel link", (await pg.locator('[data-testid="recap"] a[href^="tel:"]').count()) === 1);

    // live status poll updates (ack via API)
    const recapText = await pg.locator('[data-testid="live-status"]').innerText();
    const orders = await api(pg, "GET", `/api/shops/${SLUG}/orders`);
    const latest = orders.body.orders[0];
    await api(pg, "POST", `/orders/${latest.id}/ack`);
    await pg.waitForTimeout(4000);
    const after = await pg.locator('[data-testid="live-status"]').innerText();
    check("buyer: live status updates on ack", after !== recapText && after.length > 0, `before=${recapText} after=${after}`);

    // reload → recap resumes
    await pg.reload();
    await pg.waitForSelector('[data-testid="recap"]', { timeout: 8000 });
    check("buyer: recap resumes after reload", true);

    // đặt thêm món returns to menu
    await pg.click('[data-testid="order-more"]');
    await pg.waitForSelector('[data-testid="dish-card"]');
    check("buyer: 'Đặt thêm món' returns to menu", true);
    await ctx.close();
  }

  /* ============================= EDGE: buyer ============================= */
  console.log("== EDGE: buyer ==");
  {
    const { ctx, pg } = await newPage();
    // 404 shop
    const r404 = await api(pg, "GET", "/t/khong-ton-tai");
    check("edge: unknown slug → 404", r404.status === 404);

    // missing slug on static page
    await pg.goto(`${BASE}/webapp/buyer.html`);
    await pg.waitForSelector('[data-testid="page-error"]');
    check("edge: missing slug shows friendly error", (await pg.locator('[data-testid="page-error"]').innerText()).includes("slug"));

    // sold-out dish cannot be added
    await api(pg, "POST", `/api/shops/${SLUG}/patch`, { dish_id: "dish_tra_da", sold_out: true });
    await pg.goto(`${BASE}/t/${SLUG}`);
    await pg.waitForSelector('[data-testid="dish-card"]');
    // clear any resumed recap state first
    if (await pg.locator('[data-testid="order-more"]').count()) await pg.click('[data-testid="order-more"]');
    await pg.waitForTimeout(600); // soldout patch fetch
    const soldBtn = pg.locator('[data-dish-id="dish_tra_da"] [data-testid="add-btn"]');
    check("edge: sold-out dish button disabled", await soldBtn.isDisabled());
    await api(pg, "POST", `/api/shops/${SLUG}/patch`, { dish_id: "dish_tra_da", sold_out: false });

    // invalid phone blocked by HTML5 validation
    await pg.reload();
    await pg.waitForSelector('[data-testid="dish-card"]');
    if (await pg.locator('[data-testid="order-more"]').count()) await pg.click('[data-testid="order-more"]');
    await pg.locator('[data-testid="add-btn"]').first().click();
    await pg.fill("#f-name", "X");
    await pg.fill("#f-phone", "abc");
    await pg.fill("#f-address", "Y");
    let posts = 0;
    pg.on("request", (r) => { if (r.url().endsWith("/orders") && r.method() === "POST") posts++; });
    await pg.click('[data-testid="submit-btn"]');
    await pg.waitForTimeout(500);
    check("edge: invalid phone blocks submit", posts === 0 && (await pg.locator('[data-testid="recap"]').count()) === 0);

    // unknown dish in order → 422 (API-level)
    const bad = await api(pg, "POST", "/orders", {
      slug: SLUG,
      items: [{ dish_id: "dish_khong_co", qty: 1 }],
      customer: { name: "X", phone: "0909", address: "Y" },
      payment_method: "cod",
    });
    check("edge: unknown dish → 422", bad.status === 422, `status=${bad.status}`);

    // empty items → 422
    const empty = await api(pg, "POST", "/orders", {
      slug: SLUG, items: [], customer: { name: "X", phone: "0909", address: "Y" }, payment_method: "cod",
    });
    check("edge: empty items → 4xx", empty.status >= 400 && empty.status < 500, `status=${empty.status}`);
    await ctx.close();
  }

  /* ============================== MAIN: group ============================ */
  console.log("== MAIN: group order ==");
  let gid;
  {
    const { ctx, pg } = await newPage();
    const g = await api(pg, "POST", "/group-orders", { slug: SLUG, batch_id: "office-e2e" });
    gid = g.body.gid;
    await pg.goto(`${BASE}/g/${gid}`);
    await pg.waitForSelector('[data-testid="add-part"]');
    check("group: header shows shop name", (await pg.locator("h1").innerText()).includes("Cơm Tấm Cô Ba"));
    check("group: close form hidden with no members", (await pg.locator('[data-testid="close-form"]').count()) === 0);

    // edge: empty submit
    await pg.click('[data-testid="add-part"] button[type="submit"]');
    await pg.waitForTimeout(300);
    check("edge: group add without name/items shows error", (await pg.locator('[data-testid="form-error"], [data-testid="add-part"] :invalid').count()) > 0);

    // add my part via UI
    await pg.fill("#g-name", "An");
    await pg.locator('[data-testid="add-part"] input[type="number"]').first().fill("2");
    const sub = await pg.locator('[data-testid="my-subtotal"]').innerText();
    check("group: live subtotal", /[1-9]/.test(sub), sub);
    await pg.click('[data-testid="add-part"] button[type="submit"]');
    await pg.waitForSelector('[data-testid="close-form"]', { timeout: 5000 });
    check("group: member added, close form appears", true);

    // second member via API → poll updates page without reload
    await api(pg, "POST", `/group-orders/${gid}/members`, {
      name: "Bình",
      items: [{ dish_id: "dish_tra_da", name: "Trà đá", price: 3000, qty: 2 }],
    });
    await pg.waitForTimeout(6500);
    check("group: poll shows new member", (await pg.locator('[data-testid="members"]').innerText()).includes("Bình"));

    // edge: close with UNKNOWN bank → 422 surfaced, group still open
    await pg.fill("#g-phone", "0909111222");
    await pg.fill("#g-address", "Toà A, Q.1");
    await pg.fill("#g-bank", "NGANHANGLA");
    await pg.fill("#g-account", "123");
    await pg.click('[data-testid="close-form"] button[type="submit"]');
    await pg.waitForSelector('[data-testid="close-error"]', { timeout: 5000 });
    check("edge: unknown bank rejected, close fails cleanly", true);
    const still = await api(pg, "GET", `/group-orders/${gid}`);
    check("edge: group still open after failed close", still.body.status === "open");

    // real close with valid bank
    await pg.fill("#g-bank", "MB");
    await pg.fill("#g-account", "0123456789");
    await pg.click('[data-testid="close-form"] button[type="submit"]');
    await pg.waitForSelector('[data-testid="closed"]', { timeout: 8000 });
    const payHref = await pg.locator('[data-testid="pay-actions"] a').first().getAttribute("href");
    check("group: closed view has VietQR deep link", /dl\.vietqr\.io.*am=6000/.test(payHref || ""), payHref || "");

    // edge: close twice → 422
    const again = await api(pg, "POST", `/group-orders/${gid}/close`, {
      closer_name: "An", customer: { name: "An", phone: "0909", address: "X" },
    });
    check("edge: double close → 422", again.status === 422, `status=${again.status}`);

    // edge: add member after close → 422
    const late = await api(pg, "POST", `/group-orders/${gid}/members`, {
      name: "Chi", items: [{ dish_id: "dish_tra_da", name: "Trà đá", price: 3000, qty: 1 }],
    });
    check("edge: member after close → 422", late.status === 422, `status=${late.status}`);

    // edge: unknown gid page → 404
    const g404 = await api(pg, "GET", "/g/g_khongcothat");
    check("edge: unknown gid → 404", g404.status === 404);
    await ctx.close();
  }

  /* ============================== MAIN: seller ============================ */
  console.log("== MAIN: seller ==");
  {
    const { ctx, pg } = await newPage();
    await pg.addInitScript((slug) => localStorage.setItem("tq_seller_slug", slug), SLUG);
    await pg.goto(`${BASE}/seller/`);
    await pg.waitForSelector('[data-testid="order-card"]', { timeout: 8000 });
    check("seller: orders list renders", true);
    const badge = await pg.locator('[data-testid="status-badge"]').first().innerText();
    check("seller: VN status badge", ["Mới", "Đã thấy", "Đã nhận", "Đang giao", "Xong", "Đã huỷ", "Bom hàng?"].includes(badge), badge);
    check("seller: tel link on buyer phone", (await pg.locator('[data-testid="order-card"] a[href^="tel:"]').count()) > 0);

    // local time not UTC: create fresh order, compare hour
    const created = await api(pg, "POST", "/orders", {
      slug: SLUG,
      items: [{ dish_id: "dish_tra_da", qty: 1 }],
      customer: { name: "Giờ Test", phone: "0900000009", address: "tz check" },
      payment_method: "cod",
    });
    const localHH = new Date().toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Ho_Chi_Minh" }).slice(0, 2);
    await pg.waitForTimeout(5600); // one poll cycle — also rings the new-order chime
    const cardText = await pg.locator('[data-testid="order-card"]').first().innerText();
    check("seller: local timezone time", cardText.includes(`${localHH}:`), cardText.slice(0, 60));
    const title = await pg.title();
    check("seller: new-order title flash", title.includes("đơn mới"), title);

    // ack the fresh order via UI
    await pg.locator('[data-testid="order-card"]').first().locator("button", { hasText: "Đã thấy đơn" }).click();
    await pg.waitForTimeout(1000);
    check("seller: ack via UI", (await pg.locator('[data-testid="order-card"]').first().innerText()).includes("Đã thấy"));

    // edge: illegal transition via API → 409
    const ord = created.body;
    const bad = await api(pg, "POST", `/orders/${ord.id}/transition`, { to: "done" });
    check("edge: illegal transition → 409", bad.status === 409, `status=${bad.status}`);

    // menu tab — sold-out toggle syncs buyer
    await pg.click('[data-testid="tab-menu"]');
    await pg.waitForSelector('[data-testid="menu-row"]');
    const row = pg.locator('[data-testid="menu-row"]').first();
    await row.locator('[data-testid="soldout-switch"]').click();
    await pg.waitForTimeout(800);
    const menuNow = await api(pg, "GET", `/api/shops/${SLUG}/menu`);
    const firstDishId = Object.entries(menuNow.body.menu.dishes).find(([, d]) => d.sold_out)?.[0];
    check("seller: sold-out toggle patches", !!firstDishId, JSON.stringify(firstDishId));
    // buyer sees it
    const { ctx: bctx, pg: bpg } = await newPage();
    await bpg.goto(`${BASE}/t/${SLUG}`);
    await bpg.waitForSelector('[data-testid="dish-card"]');
    await bpg.waitForTimeout(800);
    check(
      "seller→buyer: sold-out visible on buyer",
      await bpg.locator(`[data-dish-id="${firstDishId}"] [data-testid="add-btn"]`).isDisabled(),
    );
    await bctx.close();
    await row.locator('[data-testid="soldout-switch"]').click(); // restore
    await pg.waitForTimeout(500);

    // price edit: Lưu giá hidden until change
    check("seller: Lưu giá hidden before edit", (await pg.locator('[data-testid="save-price"]').count()) === 0);
    const priceInput = row.locator('input[type="number"]');
    const oldPrice = await priceInput.inputValue();
    await priceInput.fill(String(parseInt(oldPrice, 10) + 1000));
    check("seller: Lưu giá appears after edit", (await pg.locator('[data-testid="save-price"]').count()) === 1);
    await pg.click('[data-testid="save-price"]');
    await pg.waitForTimeout(700);
    const menuAfter = await api(pg, "GET", `/api/shops/${SLUG}/menu`);
    const changed = Object.values(menuAfter.body.menu.dishes).some((d) => d.price === parseInt(oldPrice, 10) + 1000);
    check("seller: price patch persisted", changed);
    await priceInput.fill(oldPrice);
    await pg.click('[data-testid="save-price"]');
    await pg.waitForTimeout(500);

    // flyers: generate A5, batch card with PDF; second batch doesn't kill first
    await pg.click('[data-testid="tab-flyers"]');
    await pg.fill("#fl-loc", "e2e-web-a");
    // only A5 (A4+sticker off)
    const switches = pg.locator('[data-testid="flyers"] label:has(button[role="switch"])');
    await switches.nth(1).locator('button[role="switch"]').click(); // a4 off
    await pg.click('[data-testid="generate-flyers"]');
    await pg.waitForSelector('[data-testid="flyer-result"]', { timeout: 60000 });
    const href1 = await pg.locator('[data-testid="flyer-result"]').first().getAttribute("href");
    check("seller: flyer PDF batch-suffixed", /flyer_a5_.+\.pdf$/.test(href1 || ""), href1 || "");
    const pdf1 = await pg.request.fetch(BASE + href1);
    check("seller: flyer PDF downloads", pdf1.status() === 200);
    // second batch
    await pg.fill("#fl-loc", "e2e-web-b");
    await pg.click('[data-testid="generate-flyers"]');
    await pg.waitForSelector('[data-testid="flyer-result"]', { timeout: 60000 });
    const pdf1again = await pg.request.fetch(BASE + href1);
    check("edge: first batch PDF survives second print", pdf1again.status() === 200);
    check("seller: batch cards have re-download", (await pg.locator('[data-testid="batch-card"] a[download]').count()) > 0);

    // onboard tab copy
    await pg.click('[data-testid="tab-onboard"]');
    check("seller: 'Dùng menu mẫu' (no dev jargon)", (await pg.locator('[data-testid="import-fixture"]').innerText()).includes("menu mẫu"));
    await ctx.close();
  }

  /* ===================== MAIN: seller onboarding (2nd shop e2e) =========== */
  console.log("== MAIN: onboarding a new shop ==");
  {
    const { ctx, pg } = await newPage();
    await pg.addInitScript(() => localStorage.removeItem("tq_seller_slug"));
    await pg.goto(`${BASE}/seller/`);
    await pg.click('[data-testid="import-fixture"]');
    await pg.waitForSelector('[data-testid="review"]', { timeout: 15000 });
    check("onboard: fixture import shows review", true);

    // edge: publishing while the shop already exists → clear 409 error, no hang
    await pg.click('[data-testid="publish-btn"]');
    const errToast = pg.locator("[data-sonner-toast]", { hasText: /Lỗi|tồn tại/i });
    await errToast.first().waitFor({ timeout: 15000 });
    check("edge: duplicate publish shows clear error", true);

    // delete + republish end-to-end (re-onboarding path)
    const del = await pg.request.fetch(`${BASE}/api/shops/${SLUG}`, { method: "DELETE" });
    check("onboard: old shop deleted", del.status() === 204, String(del.status()));
    await pg.click('[data-testid="publish-btn"]');
    await pg.waitForSelector('[data-testid="onboard-done"]', { timeout: 90000 });
    const link = await pg.locator('[data-testid="onboard-done"] a').getAttribute("href");
    check("onboard: publish → live shop link", /^\/t\/.+/.test(link || ""), link || "");
    const live = await pg.request.fetch(BASE + (link || "/t/x"));
    check("onboard: recreated shop buyer page 200", live.status() === 200);
    await ctx.close();
  }

  await browser.close();

  /* ================================ summary =============================== */
  // 4xx resource logs are the deliberate edge-case requests asserted above;
  // anything else (JS errors, 5xx, unexpected fetch fails) still fails the run.
  const errs = consoleErrors.filter(
    (e) => !/favicon/.test(e) && !/Failed to load resource:.*(409|422|404)/.test(e),
  );
  check("console: zero errors across all sessions", errs.length === 0, errs.slice(0, 3).join(" | "));

  console.log(`\n${results.filter((r) => r.ok).length}/${results.length} checks passed`);
  if (failures) {
    console.error(`${failures} FAILURES`);
    process.exit(1);
  }
  console.log("E2E WEB OK — main + edge flows all green.");
})().catch((e) => {
  console.error("e2e crashed:", e);
  process.exit(1);
});
