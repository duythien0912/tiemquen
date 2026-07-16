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
