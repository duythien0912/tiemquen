# Tiệm Quen — Engine Spec (tự build, MVP)

Spec kỹ thuật cho các module trong ARCH.md §5.2. Nguồn chân lý về nghiệp vụ: `ARCH.md`.
Nguyên tắc vàng: **LLM chỉ chạy compose-time**; đường người mua không có LLM call nào.

## 1. A2UI JSON protocol (v0.9 dialect, tự định nghĩa)

Một UI payload = **list message**. Mỗi message: `{"version": "v0.9", <đúng 1 action key>}`.
Action keys: `createSurface` · `updateComponents` · `updateDataModel` · `deleteSurface`.

```json
[
  {"version":"v0.9","createSurface":{"surfaceId":"shop_menu","catalogId":"tiemquen_emenu_v1"}},
  {"version":"v0.9","updateComponents":{
     "surfaceId":"shop_menu",
     "root":"root",
     "components":[
       {"id":"root","component":"Page","childIds":{"dataBinding":"/sections"}},
       {"id":"sec_lunch","component":"MenuSection","title":{"literalString":"Combo trưa"},
        "childIds":{"dataBinding":"/sections/lunch/items"}},
       {"id":"dish_comsuon","component":"DishCard",
        "name":{"literalString":"Cơm sườn"},"price":{"path":"/prices/dish_comsuon"},
        "soldOut":{"path":"/soldout/dish_comsuon"},
        "onPress":{"event":{"name":"add_to_cart","context":{"dishId":{"literalString":"dish_comsuon"}}}}}
     ]}},
  {"version":"v0.9","updateDataModel":{"surfaceId":"shop_menu","path":"/sections","value":["sec_lunch"]}}
]
```

Quy ước:
- **Flat wire format**: component list phẳng, tree nối bằng ID (`childId` / `childIds.explicitList` / `childIds.dataBinding`). Root = component có `id == "root"`.
- Leaf value: `{"path": "/x"}` (bind DataModel) hoặc `{"literalString"|"literalNumber"|"literalBoolean": ...}`.
- Event: `{"event": {"name": "...", "context": {...}}}` — renderer bắn về order API, không về LLM.
- **Hết món / đổi giá = `updateDataModel` patch**, KHÔNG recompose structure. Recompose chỉ khi menu/theme đổi cấu trúc.
- Validator chạy 1 lần lúc compose (tự vá: thiếu `version` → inject; đoán action key theo shape payload; auto-prepend `createSurface`). Cache JSON đã sạch — buyer page không validate lại.

## 2. Component catalog `tiemquen_emenu_v1` (thu gọn, JSON-Schema per component)

Layout: `Page`, `MenuSection`, `HeroHeader` (ảnh + tên tiệm + tagline), `Badge`.
Thương mại: `DishCard` (name, price, image, soldOut, almostOut, note), `ComboCard` (so giá sàn),
`ReorderCard` (đơn cũ, 1 chạm), `CartBar` (sticky, tổng tiền), `GroupOrderButton`, `ReviewStrip`.
Checkout: `CheckoutForm` (tên, SĐT, địa chỉ/toà nhà, ghi chú), `PaymentPicker` (COD mặc định; VietQR ẩn tới khi đủ trust), `OrderStatus` ("quán đã thấy đơn").
Catalog entry = JSON Schema (`type`, `properties` + description, `required`) — vừa validate vừa làm tài liệu prompt cho composer.

## 3. Repo layout (monorepo)

```
tiemquen/
  agents/            # Python 3.12 + FastAPI + google-genai
    tiemquen_agent/
      server.py        # FastAPI app, routing theo prefix deterministic
      a2ui.py          # protocol builders + validator/repair (§1)
      base_agent.py    # gọi Gemini, retry-1-lần khi output hỏng, racing
      toolable.py      # function-calling: model gọi tool typed → structured data
      agents/          # import_agent, interview_agent, storefront_agent,
                       # flyer_agent, order_parse_agent, reminder_agent
      prompts/         # 1 module / agent
      tools/           # 1 module / toolable agent, export TOOLS
      imagen.py        # gen ảnh (§6)
  compose/           # composer pipeline: menu chuẩn + theme → A2UI JSON → cache
  buyer/             # static site: renderer.js (~200 dòng, đi bộ component tree),
                     # context_rules.js (§5.3 ARCH), order.js (POST /orders)
  seller/            # web PWA: onboard, dashboard đơn + analytics, tải tờ rơi
  shared/            # menu_schema.json (SCHEMA LÕI — chốt trước), order states
  infra/             # storage adapter (local JSON dev / Firestore prod), notify (FCM+SMS stub),
                     # qr_batch.py, vietqr.py, pdf_export.py, publish.py (per-shop slug)
```

## 4. Format menu chuẩn (schema lõi — mọi nguồn import đổ về đây)

```json
{
  "shop": {"id","slug","name","tagline","phone","zalo","address","hours",
            "ship_zone","payment":{"cod":true,"vietqr":{"bank","account","enabled_after_n_orders"}},
            "direct_discount_pct", "theme":{"seed_colors":["#..x4"]}},
  "menu": {
    "sections":[{"id","title","items":["dish_id"]}],
    "dishes":{"dish_id":{"name","price","platform_price","image_url","desc",
               "direct_only":false,"hidden":false,"sold_out":false,"almost_out":false}}
  },
  "source": {"type":"ocr_screenshot|html_parse|manual","imported_at","confidence"}
}
```

## 5. Import agent (OCR = đường chính)

Toolable pattern: gửi screenshot (image part) + prompt → model bắt buộc gọi tools
`set_shop_info(...)`, `add_section(...)`, `add_dish(name, price, section, desc?, ...)` →
server gom tool calls thành menu chuẩn + confidence. HTML parse (ShopeeFood) thử trước nếu có URL,
fail → OCR. Ảnh món rehost về storage riêng. Envelope trả về:
`{"menu": <chuẩn §4>, "warnings": [...], "confidence": 0-100}` → UI review sửa giá.

## 6. Imagen service (flyer + hero)

- `generate_content` multimodal, `response_modalities=["TEXT","IMAGE"]`, aspect ratio theo format (A5/A4 portrait, sticker vuông).
- Sanitize pre-pass bằng model rẻ (flash-lite) lọc prompt trước call đắt.
- Hard constraints lặp lại ở CUỐI prompt (model ảnh quên context giữa prompt dài). Flyer cần chữ CTA "THÈM? QUÉT." + vùng trống đặt QR → prompt yêu cầu safe-zone.
- 1 call trả cả ảnh + palette JSON (4 seed hex, contrast-checked) → theme tiệm từ 4 màu seed, phần còn lại derive bằng code.
- Retry 1 lần nếu trả text không pixel. Cache PNG ra static URL, TTL cleanup.

## 7. Racing (compose-time only)

`RACE_ENABLED`/`RACE_COUNT` env. `race_stream()`: bắn N call giống nhau trên session tạm,
lấy bản valid đầu tiên, huỷ phần còn lại. KHÔNG race tool-calling (side effects) và KHÔNG race đường buyer.

## 8. Order state machine + notify

States: `created → seller_seen → confirmed → delivering → done` | `cancelled` | `no_show_flagged`.
Notify khi `created`: FCM web push → không ack 120s → SMS (adapter stub ở dev, log ra console).
Buyer poll/SSE trạng thái `seller_seen` để hiện "quán đã thấy đơn".
Đơn nhóm: `group_order` chứa nhiều `member_items` + trạng thái chuyển khoản từng người; Reminder agent đọc và soạn tin nhắc.

## 9. Context rules (buyer, không LLM)

QR = `tiemquen.com/<slug>?b=<batch_id>`. Rules client-side theo bảng §5.3 ARCH.md:
batch tag office → promote GroupOrderButton; 10–13h → section combo lên đầu; localStorage có đơn cũ
→ prepend ReorderCard; soldOut flags từ shop store JSON (fetch tĩnh, cache-control ngắn).

## 10. Dev/prod

Dev: storage = file JSON dưới `data/`, notify = console, không cần GCP. Prod: Cloud Run + Firestore + GCS (theo runway ARCH §4.2). `GEMINI_API_KEY` qua env; mọi module chạy được không có key (mock mode) trừ call compose/import thật.
