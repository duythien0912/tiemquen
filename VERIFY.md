# VERIFY — MVP-readiness sweep for the 3-shop pilot (2026-07-17)

Environment: macOS 26.1 (arm64), uv-managed CPython 3.13.12, branch `main`.

## A. Full-flow re-verification

- `pytest -q` → **260 passed** (was 253 — new group-order VietQR + flyer-filename tests).
- `scripts/e2e_smoke.py` (mock mode) → exit 0, all 13 steps PASS.
- **3-shop isolation**: seeded `com-tam-co-ba` + 2 clones (`bun-bo-di-bay`,
  `pho-ga-ut-nho`, distinct ids/themes/phones) over HTTP → create 201, compose
  200 ×4 variants each, buyer pages 200, orders route to the correct `shop_id`,
  flyers 200 per shop. Seller PWA is 1-shop-per-device (`tq_seller_slug`) — the
  right model for 3 independent quán.

## B. UI/UX review (Playwright, mobile 390×844 + desktop 1440×900) and fixes

Round-1 review found 0 blockers, 7 HIGH, 7 MEDIUM, 4 LOW (evidence in session
scratchpad `ui-review/`). Everything HIGH/MEDIUM was fixed:

| Fix | Where |
|---|---|
| Cart stepper `− qty +` (mis-tap recoverable) + cart persists reload | `buyer/renderer.js`, `buyer/order.js` |
| Post-submit **recap screen** (order #, line prices, "chuẩn bị Xđ tiền mặt", 📞 gọi quán, live status, "Đặt thêm món") replaces the silent banner; reload <2h resumes it | `buyer/order.js`, `buyer/index.html`, `agents/.../server.py` (shop name/phone in bootstrap) |
| Double-submit guard (1 tap = 1 đơn) | `buyer/order.js` |
| Group share link now full URL + `navigator.share`/clipboard (was dead bare path in `prompt()`) | `buyer/order.js` |
| Checkout form hidden while cart empty; typed input survives re-renders; VN phone pattern | `buyer/renderer.js` |
| All buyer tap targets ≥44px | `buyer/styles.css` |
| Group page: shop name (not slug), per-member item breakdown, live "Phần của bạn" subtotal, 5s auto-refresh, single-member close copy | `buyer/group.html` |
| **Real VietQR on group close**: closer optionally enters bank+STK → each member gets `dl.vietqr.io` deep link + copy-text with their exact amount (EMVCo payload, CRC-verified); bad bank fails BEFORE the order is created | `infra/group_orders.py`, `infra/vietqr.py` wiring, server, `buyer/group.html` |
| Seller **Menu tab**: sold-out / sắp hết toggles + price edit via `POST /patch` (instant, no recompose) | `seller/index.html`, `seller/app.js` |
| VN status badges (Mới/Đã thấy/Đã nhận/Đang giao/Xong/Đã huỷ), local-timezone times (was UTC), `tel:` buyer phone, 44px action buttons with Huỷ pushed right | `seller/app.js`, `seller/styles.css` |
| New-order alert: 2-note beep + vibrate + title flash "🔔 N đơn mới!" (FCM still stubbed — poll is the only channel) | `seller/app.js` |
| Flyer PDFs batch-suffixed (`flyer_<fmt>_<batchid>.pdf`) — new batch no longer overwrites the old; "⬇ Tải lại PDF" per batch; full QR URLs | `infra/pdf_export.py`, server, `seller/app.js` |
| "Dùng menu mẫu" (was "fixture"), 22px checkboxes, `[hidden]` CSS fix, sw cache bump v3 | `seller/*` |

Round-2 Playwright re-verification: **19/19 items PASS** (2 regressions found —
recap clobbered by the background sold-out re-render, "Lưu giá" always visible —
both fixed and probe-verified). Console clean, zero ≥400 responses.

## C. Go/no-go for the 3-shop pilot

**GO for a supervised dev pilot** (single host, `uvicorn` + `data/` JSON).
Before leaving it unattended: real FCM/SMS (seller alert today = open PWA tab),
a persistent store (LocalJSON → Firestore adapter), auth on seller/admin
endpoints, and one real-key Gemini/Imagen run (only mock verified so far).

---

# VERIFY — full verification sweep (2026-07-16)

Environment: macOS 26.1 (arm64), CPython 3.12.12, branch `wf/tiemquen-mvp`.

## 1. Fresh install

- `.venv` deleted and recreated from scratch; `./.venv/bin/pip install -r requirements.txt` → clean install, no errors.
- Machine note (not a repo issue): the Homebrew CPython 3.13/3.14 builds on this
  host have a broken `pyexpat` (`Symbol not found: _XML_SetAllocTrackerActivationThreshold`
  — libexpat mismatch with macOS 26.1), so `python3 -m venv` fails at `ensurepip`
  with those interpreters. The sweep used a uv-managed standalone CPython 3.12
  (`uv python` build), which works end to end. Any healthy 3.12+ interpreter is fine.

## 2. Test suite

- `./.venv/bin/python -m pytest -q` → **253 passed**, 0 failed (1 upstream
  starlette/httpx deprecation warning, harmless).

## 3. End-to-end smoke (mock mode)

- `env -u GEMINI_API_KEY ./.venv/bin/python scripts/e2e_smoke.py` → **exit 0**, all 13 steps PASS:
  fixture import/schema → storage roundtrip → slug registry → app boot →
  compose 4 variants (theme contrast ≥ 4.5) → compose cache → sold-out patch
  (no recompose) → import agent (OCR fixture) → import→shop→price-PATCH→recompose
  over HTTP → COD order lifecycle (created → seller_seen → confirmed → delivering
  → done; illegal transition → 409) → notify chain incl. SMS fallback →
  group order with uneven split (sums exactly) → A5+A4 QR batches with `?b=<batch_id>`
  → mock imagen heroes + print PDFs (>10KB) + batch analytics → VietQR EMVCo
  TLV payloads with valid CRC16-CCITT.

## 4. Real server boot (uvicorn, port 8787)

All against a live `./.venv/bin/uvicorn agents.tiemquen_agent.server:app --port 8787`,
starting from an empty dev `data/` dir:

| Check | Result |
|---|---|
| `GET /health` | 200 `{"status":"ok","service":"tiemquen-agent"}` |
| `POST /api/shops` (empty body → demo fixture) | 201, slug `com-tam-co-ba`; second POST → 409 (idempotence guard) |
| `POST /api/shops/com-tam-co-ba/compose` | 200, 4 variants cached |
| `GET /t/com-tam-co-ba` | 200 HTML, references `renderer.js` |
| `GET /api/shops/com-tam-co-ba/composed/office-lunch` | 200 A2UI messages |
| `POST /orders` (`dish_suon_nuong` ×2, COD) | 201, total 70.000đ, server-priced; then `GET /orders/{id}/status` → `created` / "Đơn đã gửi tới quán…"; unknown dish → 422 |
| `GET /seller` → `/seller/` | 307 → 200 (PWA loads) |
| `POST /api/shops/com-tam-co-ba/flyers` (a5) | 200; `GET /media/com-tam-co-ba/flyer_a5.pdf` → 200, 2.6MB valid PDF v1.4 |

Server killed cleanly after the sweep.

## 5. Golden-rule audit (zero LLM on the buyer path)

- `buyer/` (index.html, renderer.js, context_rules.js, order.js, styles.css, group.html):
  **no** google-genai / LLM usage — grep hits are only comments asserting the rule.
- Order-serving routes (`POST/GET /orders*`, `/t/{slug}`, `/g/{gid}`, `/group-orders*`)
  and their infra (`infra/orders.py`, `infra/group_orders.py`, `infra/notify.py`,
  `shared/order_states.py`): **no** LLM imports or calls.
- `google.genai` appears only in compose-time modules: `compose/composer.py`,
  `agents/tiemquen_agent/imagen.py`, `agents/tiemquen_agent/toolable.py`,
  `agents/.../import_agent.py` — all mock-mode capable without `GEMINI_API_KEY`.
- `POST /orders/parse-text` uses the order-parse agent, but it is the **seller**
  paste-Zalo-chat reverse path (explicitly allowed compose-time LLM per the golden
  rule), never invoked by the buyer page.

**Verdict: golden rule holds.**

## 6. Buyer payload budget (target < 150 KB)

| Asset | Size |
|---|---|
| buyer/index.html | 2.9 KB |
| buyer/renderer.js | 14.3 KB |
| buyer/context_rules.js | 4.8 KB |
| buyer/order.js | 6.8 KB |
| buyer/styles.css | 4.7 KB |
| composed variant JSON (each of 4, demo shop) | 15.2 KB |

- **What one buyer actually downloads (page + 1 variant): 48.7 KB** — uncompressed, well under 150 KB.
- Even page + all 4 variants: 94.2 KB, still under budget.

## 7. Known gaps / deferred

- **Real Gemini/Imagen calls untested** — no `GEMINI_API_KEY` in this environment;
  compose, import OCR, order-text parse and hero generation were verified in mock
  mode only. Real-mode code paths exist but have never run against the live API here.
- **FCM push and SMS are stubs** — `infra/notify.py` logs `[fcm-stub]` / `SMS to …`
  to console; no real FCM project or SMS gateway wired.
- **Storage is dev-only** — `LocalJSONStorage` under `data/`; the Firestore adapter
  is an interface swap that does not exist yet.
- **No auth** on seller/admin endpoints (acceptable for MVP dev; must gate before prod).
- Homebrew-Python `pyexpat` breakage on this host (see §1) — environment quirk, not repo code.
