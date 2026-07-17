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
```

## Repo layout (ENGINE-SPEC §3)

```
agents/tiemquen_agent/   FastAPI agent server (import/interview/storefront/flyer/... in later phases)
compose/                 A2UI composer pipeline (later phase)
buyer/                   static order page (renderer + context rules — later phase)
seller/                  seller web PWA (later phase)
shared/                  menu_schema.json (SCHEMA LÕI) + order_states.py
infra/                   storage adapter (local JSON dev / Firestore prod), publish (slug registry)
data/fixtures/           demo shop fixture (chuẩn menu format)
data/                    dev storage (LocalJSONStorage); data/media gitignored
scripts/e2e_smoke.py     numbered-step smoke test — later phases extend it
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
