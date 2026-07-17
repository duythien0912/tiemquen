# Tiệm Quen — monorepo

> Tờ rơi 2.0 cho quán ăn thoát sàn. *"Tiệm quen, kêu là có."*

Nguồn chân lý: [`ARCH.md`](ARCH.md) (nghiệp vụ) và [`docs/ENGINE-SPEC.md`](docs/ENGINE-SPEC.md) (kỹ thuật).

## Quickstart

```bash
# 1. Python env (3.12+) — uv standalone build avoids broken Homebrew python bottles
uv venv .venv --python 3.13
./.venv/bin/python -m ensurepip
./.venv/bin/python -m pip install -r requirements.txt

# (fallback if no uv): python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt

# 2. Run the agent server (dev — no GEMINI_API_KEY needed)
./.venv/bin/uvicorn agents.tiemquen_agent.server:app --port 8787

# 3. Seed the demo shop (empty body -> data/fixtures/demo_shop.json) + compose its A2UI variants
curl -X POST http://127.0.0.1:8787/api/shops
curl -X POST http://127.0.0.1:8787/api/shops/com-tam-co-ba/compose

# 4. Open the pages
#    Buyer  : http://127.0.0.1:8787/t/com-tam-co-ba
#    Seller : http://127.0.0.1:8787/seller/
#    Health : http://127.0.0.1:8787/health

# 5. Run tests
./.venv/bin/python -m pytest -q

# 6. Run the end-to-end smoke (mock mode, no API key)
./.venv/bin/python scripts/e2e_smoke.py

# 7. Web UI (React 19 + shadcn/ui + OpenUI Lang renderer) — optional but default when built:
#    /t/{slug}, /g/{gid}, /seller/ serve web/dist when present, else the vanilla fallback.
cd web && npm install && npm run build && cd ..

# 8. Web e2e — MAIN + EDGE flows, DOM-asserted (needs playwright npm pkg + steps 2+7)
node scripts/e2e_web.js

# 9. Vision e2e: drive real Chrome through the journeys, screenshot every step
node scripts/e2e_vision.js            # -> data/e2e_vision/*.png + manifest.json
#    Review the screenshots visually (or feed them to a vision model).
```

## Repo layout (ENGINE-SPEC §3)

```
agents/tiemquen_agent/   FastAPI agent server (import agent, compose API, orders, flyers)
compose/                 A2UI composer pipeline (menu chuẩn + theme → A2UI JSON cache)
web/                     UI duy nhất — Vite + React 19 + shadcn/ui, render qua OpenUI Lang
                         (A2UI JSON → ElementNode → jsonToOpenUI → <Renderer>); build ra web/dist
seller/                  PWA assets tĩnh (manifest.json, icon.svg, sw.js) cho app quán
landing/                 landing page tĩnh
shared/                  menu_schema.json (SCHEMA LÕI) + order_states.py + menu_format
infra/                   storage, orders, group_orders, vietqr, qr_batch, pdf_export, notify
data/fixtures/           demo shop fixture (chuẩn menu format)
data/                    dev storage (LocalJSONStorage); data/media gitignored
scripts/e2e_smoke.py     API smoke 13 bước · e2e_web.js: 55 check main+edge · e2e_vision.js: chụp vision
tests/                   pytest suite
```

## Nguyên tắc vàng

LLM chỉ chạy **compose-time** (menu đổi, gen tờ rơi, parse đơn text) — kết quả cache
thành A2UI JSON + asset tĩnh. Đường người mua **không có** LLM call nào.
Mọi module chạy được **không cần `GEMINI_API_KEY`** (mock mode) trừ call compose/import thật.

## Dev vs prod

| | Dev | Prod |
|---|---|---|
| Storage | file JSON dưới `data/` (`infra.storage.LocalJSONStorage`) | Firestore (adapter cùng interface, swap-in) |
| Notify | console log | FCM push + SMS fallback |
| Env | không cần GCP/API key | Cloud Run + GCS, `GEMINI_API_KEY` qua env |

Override thư mục data dev bằng env `TIEMQUEN_DATA_DIR`.
