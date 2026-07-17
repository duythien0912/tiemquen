# Tiệm Quen — Tờ Rơi 2.0 cho quán ăn thoát sàn

> Tờ rơi giấy = kênh đặt hàng thường trực. Khách đói nhìn tờ rơi trên bàn/tủ lạnh/pantry,
> quét QR, đặt trong 3 chạm — thay vì mở app Grab/ShopeeFood.
> Backend agent tự build (GenUI compose + A2UI JSON); trang khách là web tĩnh siêu nhẹ.

## 0. Brand

| | |
|---|---|
| Tên | **Tiệm Quen** |
| Domain | `tiemquen.com` |
| Tagline | *"Tiệm quen, kêu là có."* |
| CTA tờ rơi | **"THÈM? QUÉT."** + QR (chữ to, đọc 1 giây) |
| Câu chuyện | Biến khách lạ của sàn thành khách quen của tiệm — tiệm của mình, khách của mình |
| Giọng brand | Gen Z miền Nam, thân mật, tối giản; "tiệm" đủ rộng để mở ngang (quán ăn → bếp nhà làm → sạp tạp hoá) |

## 1. Vấn đề & Why now

| Đối tượng | Pain (đã xác nhận qua khảo sát Threads VN) |
|---|---|
| Quán ăn nhỏ | Hoa hồng sàn 25–30%; bị phạt tỷ lệ giao, cắt mã freeship; không sở hữu khách của chính mình |
| Khách văn phòng | Đặt cơm trưa lặp lại 90% quanh vài quán quen, nhưng mỗi lần phải mở app → tìm quán → lội khuyến mãi |
| Cả hai | Giao dịch trực tiếp (Zalo + chuyển khoản) đang diễn ra thủ công: chốt đơn chat tay, không menu, không nhắc tiền |

**Insight lõi:** đối thủ không phải Grab — là thói quen "mở app". Vật lý thắng digital đúng 1 điểm:
tờ rơi nằm sẵn trong tầm mắt lúc đói. Cải tiến tờ rơi thành giao diện đặt hàng, không phải tờ quảng cáo.

**Why now:**
- Sàn đang siết seller mạnh nhất từ trước tới nay (tăng hoa hồng, cắt trợ giá) → động lực thoát sàn cao điểm
- VietQR + Zalo phủ toàn dân → đặt trực tiếp không còn rào thanh toán/liên lạc
- Mô hình đã chứng minh ở nước ngoài (Owner.com, Flipdish) nhưng chưa ai làm bản VN đúng văn hoá tờ rơi + cơm trưa văn phòng

**Why us:** đã nắm trọn know-how engine sinh UI + sinh ảnh từ hội thoại — tự build bản tối giản,
đúng nhu cầu, thứ Sapo/iPOS phải mò từ đầu; và đánh ngách hẹp (cơm trưa văn phòng, bán kính
từng toà nhà) mà player lớn bỏ qua.

## 2. Sản phẩm

### Tờ rơi cũ vs Tờ rơi 2.0

| Tờ rơi cũ | Tờ rơi 2.0 |
|---|---|
| Nhìn xong vứt | Đáng giữ: menu + giá thật, thiết kế đẹp sinh theo quán, lịch món tuần |
| Muốn đặt phải gọi điện | QR → trang order 3 chạm, không cài app, không đăng nhập |
| Nội dung chết, in lại tốn tiền | QR tĩnh — nội dung sống: giấy in 1 lần, menu/giá sau QR cập nhật realtime, hết món tự ẩn |
| Không đo được hiệu quả | Mỗi batch in 1 mã QR riêng → biết tờ dán chỗ nào ra bao nhiêu đơn (flyer analytics) |

### 3 format vật lý

1. **A5** — nhét vào túi mỗi đơn sàn (sàn tự trả ship cho việc phát kênh thoát sàn)
2. **A4** — dán pantry văn phòng, cửa quán
3. **Sticker/magnet** — tủ lạnh, cạnh màn hình

### Chân dung quán mục tiêu (ICP)

Quán cơm/bún/đồ uống gần cụm văn phòng, **đơn sàn mức vừa** (30–100 đơn/ngày — đủ volume phát
tờ rơi, đủ đau vì hoa hồng), biên mỏng, có sẵn tệp khách văn phòng lặp lại, chủ quán dùng smartphone
thành thạo Zalo. KHÔNG nhắm: quán flagship đông nghịt (không cần mình) và quán ế (không có đơn sàn
để phát tờ rơi).

## 3. Flow nghiệp vụ

### 3.1 Seller onboarding (mục tiêu < 10 phút)

```
Seller dán link GrabFood/ShopeeFood/Shopee HOẶC upload screenshot menu
  → Import agent lấy menu + ảnh + giá + giờ mở cửa (ảnh rehost về storage riêng)
    · GrabFood: menu KHÔNG có trong HTML (đã verify 07/2026 — API portal.grab.com chặn
      anti-bot 502). Đường CHÍNH = seller chụp screenshot app/web Grab → Gemini vision
      OCR + parse. Headless browser (Playwright) chỉ là đường phụ, dễ vỡ.
    · ShopeeFood/khác: thử parse HTML trước, fail thì rơi về OCR screenshot
  → Mọi nguồn đều đổ về CÙNG format menu chuẩn → flow sau không quan tâm nguồn
  → Seller review: sửa giá trực tiếp (thường -10–15% vì không mất hoa hồng),
    ẩn món, thêm món "chỉ bán trực tiếp"
  → Interview agent hỏi phần thiếu (2–3 câu):
    "Ship khu nào? Trả khi nhận hay chuyển khoản? Giảm bao nhiêu cho đơn trực tiếp?"
  → Sinh: web tiệm (slug riêng) + bộ tờ rơi 3 format + bản post social
  → Seller tải file in (PDF chuẩn in) hoặc đặt in hộ (revenue phụ sau này)
```

### 3.2 Khách đặt hàng

```
Quét QR trên tờ rơi
  → Trang order (web tĩnh, tải < 2s trên 4G) hiển thị theo NGỮ CẢNH (xem §5.3):
    - Lần đầu: best-seller + review + giá so với giá sàn
    - Lần sau: "Đặt lại cơm sườn như hôm qua?" — 1 chạm
    - Giờ trưa + QR văn phòng: combo trưa lên đầu
  → Chọn món → xác nhận
  → Thanh toán:
    - MẶC ĐỊNH: trả khi nhận (COD/chuyển khoản lúc giao) — không ai mất tiền trước,
      không có rủi ro "trả rồi quán bùng" đổ lên brand
    - VietQR trả trước: opt-in, chỉ bật cho khách đã đặt thành công ≥ N lần với quán đó
      (QR sinh đúng số tiền; deep-link app ngân hàng + nút "copy số TK + số tiền" —
      khách không thể tự quét QR trên màn hình mình đang cầm)
    - Tiền luôn vào thẳng seller, platform KHÔNG giữ tiền → không dính giấy phép TGTT
  → Notify seller NGAY: FCM push (app seller) + SMS fallback nếu không ack trong 2 phút
    (đơn tới mà quán không biết = khách mất vĩnh viễn — đây là SLA quan trọng nhất)
  → Đường phụ: nút "Đặt qua Zalo" → soạn sẵn đơn text, copy clipboard, mở chat Zalo seller.
    Chiều ngược: seller dán tin nhắn khách vào app, Order agent parse text → đơn có cấu trúc
```

**Giao hàng: quán tự giao.** Tiệm Quen KHÔNG làm logistics — đơn trực tiếp chỉ khả thi trong
bán kính quán tự ship (~1–2km, chính là lý do đánh theo cụm văn phòng §4.5). Quán nào không tự
ship dùng Grab Express/Ahamove tự trả — ngoài phạm vi platform.

**Chính sách sự cố:** đơn đã xác nhận mà quán không giao → hệ thống ghi nhận, quán bị gắn cờ,
tái phạm bị hạ trạng thái "tiệm quen" (mất quyền bật VietQR trả trước). Khách không mất tiền
vì mặc định trả khi nhận.

### 3.3 Đơn nhóm văn phòng (use case chủ lực)

```
1 người quét QR ở pantry
  → bấm "Đặt cho cả phòng" → sinh link đơn nhóm, share vào group Zalo
  → mỗi người tự chọn món vào chung 1 đơn (không cần chuyển tiếp screenshot menu)
  → chốt giờ → 1 đơn, 1 ship, chia tiền hiển thị từng người + VietQR hoàn lại cho người trả hộ
  → Reminder agent nhắc ai chưa chuyển khoản (agent làm "người xấu" thay trưởng kèo)
```

### 3.4 Growth loop & kênh giữ khách

```
Seller giao đơn sàn → nhét tờ rơi A5 vào túi
  → khách của sàn nhận tờ rơi → lần sau đặt trực tiếp (rẻ hơn, 3 chạm)
  → seller thấy batch nào ra đơn (analytics) → in thêm đúng chỗ hiệu quả
  → footer mỗi trang order: "Tạo tiệm cho quán của bạn — miễn phí" → seller mới
```

**Kênh re-engage (không đặt cược 100% vào tờ giấy):** ngay sau đơn đầu, mời khách follow
Zalo OA của Tiệm Quen (1 OA chung, tin theo quán) → kênh push "quán quen hôm nay có món mới /
giờ trưa rồi, đặt lại?" — Zalo OA nằm ở giai đoạn 2 (tuần 7–10), không phải "để sau vô hạn".
Cookie/localStorage chỉ là nhận diện tối thiểu, không phải kênh chủ động.

## 4. Kinh doanh

### 4.1 Test giấy trước khi code (~2 triệu VND, 3 tuần)

- 3 quán cơm quen gần 2 toà văn phòng; tờ rơi Canva + QR trỏ Google Form/Zalo quán; quán chịu giảm 10% đơn trực tiếp
- **Go:** > 10 đơn / tờ A4 pantry / tuần → thói quen đổi được
- **Kill:** 2–3 đơn/tuần → khách không rời app; dừng, đỡ mất 6 tháng
- Đo kèm: seller có tự cập nhật menu không (seller lười = chết chậm)

### 4.2 Team & nguồn lực (thực tế, không tô hồng)

| | |
|---|---|
| Team | Solo founder (dev). Cam kết: full-time NẾU test giấy đạt ngưỡng Go; trước đó làm ngoài giờ |
| Sales/onboarding pilot | Founder tự đi bán từng quán (5 quán pilot = ~5 buổi tối). Đây là điểm nghẽn scale — chấp nhận ở giai đoạn này, thuê sales part-time khi có doanh thu |
| Ngân sách 12 tháng | < 50 triệu VND, bootstrap |

**Runway table (burn/tháng):**

| Khoản | VND/tháng |
|---|---|
| Hosting (Cloud Run free tier + Firestore + storage) | ~300k |
| Gemini API (compose-time + gen ảnh, xem §4.3) | ~500k–1.5tr |
| In ấn pilot (khấu hao) | ~300k |
| Domain + linh tinh | ~100k |
| **Tổng** | **~1.2–2.2tr/tháng → 50tr sống 18–24 tháng** |

Không thuê ai cho tới khi có ≥ 20 quán trả phí. Gọi vốn angel chỉ sau khi có số
"đơn/tờ rơi/tuần" từ pilot thật.

### 4.3 Unit economics (ước tính, phải đo lại ở pilot)

| Chỉ số | Ước tính | Ghi chú |
|---|---|---|
| Chi phí hệ thống / đơn | **< 100đ** (giai đoạn 2, FCM); **~800đ** ở pilot (SMS là kênh notify chính) | Nhờ compose-time + cache (§5.3): xem menu KHÔNG gọi LLM; chỉ ghi DB + notify. SMS pilot chấp nhận được vì volume nhỏ, chuyển FCM khi có app |
| Chi phí gen lại UI khi menu đổi | ~200–500đ/lần | 1 call Gemini Flash; quán đổi menu ~1 lần/ngày |
| Chi phí gen bộ tờ rơi | ~3–5k/bộ | Imagen; làm 1 lần + refresh theo mùa |
| CAC 1 quán (pilot) | ~150k tiền mặt + 1 buổi sales | In tặng batch đầu 100 tờ |
| Doanh thu mục tiêu / quán | 200–300k/tháng (giai đoạn thu phí) | Chuẩn giá KiotViet/Sapo — SMB VN chấp nhận được |
| Hoà vốn / quán | ~1 tháng phí | Nếu churn < 30%/năm thì LTV/CAC > 10 |

Điều kiện sống của model: **giữ chi phí biến đổi/đơn gần 0**. Mọi quyết định kỹ thuật ở §5
phục vụ điều này.

### 4.4 Monetize

| Giai đoạn | Nguồn thu |
|---|---|
| MVP → PMF | Free hoàn toàn (giữ pitch "rẻ hơn sàn tuyệt đối", không lấy % đơn). Checkpoint: sau 3 tháng pilot phải có ≥ 10 quán active, nếu không → dừng/pivot |
| Scale | Freemium: 1 tiệm free; nhiều chi nhánh / custom domain / analytics sâu / Zalo OA push ≈ 200–300k/tháng |
| Phụ | In hộ tờ rơi; đặt in định kỳ |
| Đường quay lại % đơn | Không lấy % ở đơn thường — nhưng module tương lai có giá trị giao dịch (đặt cọc đơn nhóm lớn, catering) có thể thu phí giao dịch khi đủ trust |

### 4.5 Rủi ro & đối phó

| Rủi ro | Đối phó |
|---|---|
| Khách nghiện voucher sàn (rủi ro #1) | Nhắm use case lặp (cơm trưa) nơi voucher ít quyết định; giá trực tiếp + tích điểm quán |
| Cold-start 2 chiều (quán chờ khách, khách chờ quán) | Đánh theo CỤM: 1 toà văn phòng + 5 quán quanh nó cùng lúc; không rải mỏng |
| Sàn chặn scrape (Grab đã chặn — verify 07/2026) / ToS | OCR screenshot là đường import CHÍNH, không phải fallback — không phụ thuộc anti-bot; import tách khỏi serve (§5.4) — nguồn chết không làm chết tiệm đã publish |
| Seller lười duy trì menu | Menu sống sau QR tĩnh — sửa 1 chỗ; agent nhắc khi món liên tục hết |
| Sapo/iPOS copy trong ~6 tháng | Moat = tốc độ phủ cụm văn phòng + flyer analytics + engine gen tự chủ (pattern đã nắm); đua tốc độ, không đua feature |
| Tự build toàn bộ engine → MVP dài hơn | Chấp nhận MVP 4 → 6 tuần; compose engine cắt về tối thiểu (catalog component thu gọn cho e-menu, không framework tổng quát); pattern GenUI/racing/imagen đã nắm sẵn, không nghiên cứu từ đầu |
| Solo founder = single point of failure | Phạm vi MVP cắt tối đa (§6); không hứa SLA doanh nghiệp ở pilot |
| Giữ tiền hộ = giấy phép fintech | Không giữ tiền: COD mặc định, VietQR thẳng seller. Escrow để giai đoạn sau khi có vốn |

### 4.6 Thuế & pháp lý (lập trường rõ ràng)

- **Thuế hộ kinh doanh:** VN đang siết thuế TMĐT + hoá đơn điện tử máy tính tiền. Quán có thể
  ngại app ghi lại doanh thu. Lập trường Tiệm Quen: **đứng về phía tuân thủ** — cung cấp báo cáo
  doanh thu xuất được để quán kê khai; marketing nói "sổ sách tự động", không bao giờ nói "né thuế".
  Đây là feature bán thêm khi quy định siết, không phải rủi ro phải giấu.
- **Dữ liệu cá nhân (Luật BVDLCN hiệu lực 2026):** thu SĐT/địa chỉ khách ở mức tối thiểu,
  có consent checkbox + trang chính sách; dữ liệu khách thuộc về quán, Tiệm Quen xử lý thay.
- **Không marketing chữ "lách sàn/thoát phí"** công khai — pitch bằng "kênh riêng của quán".

## 5. Kiến trúc kỹ thuật

### 5.1 Tổng quan — 2 mặt tách biệt

```
BUYER SIDE (tối ưu tốc độ, không LLM runtime)          SELLER SIDE (web PWA, tự build)
┌───────────────────────────────┐                  ┌────────────────────────────────────┐
│ Trang order sau QR            │                  │ Seller app (web PWA, mobile-first) │
│ - Web tĩnh/SSR siêu nhẹ       │                  │ - Onboard: import, interview       │
│   (HTML + JS tối thiểu, <2s   │                  │ - Dashboard đơn + flyer analytics  │
│   trên 4G — KHÔNG Flutter)    │                  │ - Gen/tải tờ rơi                   │
│ - Render từ A2UI JSON đã cache│                  │ - Nhận FCM push đơn mới            │
│ - Context rules chạy client/  │                  └────────────────────────────────────┘
│   edge, không gọi LLM         │                                  │ A2UI (JSON)
└───────────────────────────────┘                                  ▼
        │ đọc                                     ┌────────────────────────────────────┐
        ▼                                         │ Python agent server (tự build)     │
┌───────────────────────────────┐    ghi/compose  │  ├─ Import agent (scrape/OCR)      │
│ Data & cache layer            │◄────────────────│  ├─ Interview agent                │
│ - Shop store + menu           │                 │  ├─ Storefront/Theme agent         │
│ - A2UI JSON đã compose        │                 │  ├─ Flyer agent (Imagen)           │
│ - Order store (state machine) │                 │  ├─ Order agent (parse text đơn)   │
│ - QR batch registry           │                 │  └─ Reminder agent (đòi tiền nhóm) │
│ - Image storage (rehost)      │                 │  Gemini API, racing compose N bản  │
└───────────────────────────────┘                 │  chọn 1 — không phục vụ buyer      │
        │                                         └────────────────────────────────────┘
        ▼
  Notify pipeline: FCM push seller → không ack 2' → SMS fallback
```

**Nguyên tắc vàng:** LLM chỉ chạy lúc **compose** (menu đổi, theme đổi, gen tờ rơi, parse đơn text)
— kết quả cache thành A2UI JSON + asset tĩnh. Khách xem menu/đặt đơn KHÔNG chạm LLM.
→ chi phí/đơn ~0, latency ~0, agent server sập thì tiệm vẫn bán được (chỉ không sửa được menu).

### 5.2 Module tự build

Toàn bộ code viết mới, cắt về tối thiểu đúng nhu cầu Tiệm Quen:

| Module | Nội dung |
|---|---|
| `agents/` — Python agent server | FastAPI: Import (OCR/scrape), Interview, Storefront/Theme, Flyer (Imagen), Order-parse, Reminder — prompt per-feature + tool registry |
| `compose/` — A2UI composer | Sinh A2UI JSON từ format menu chuẩn + theme; racing N bản chọn 1 (chỉ compose-time) |
| `web/` — trang order | React 19 + shadcn/ui đọc A2UI JSON cache qua OpenUI Lang renderer; component catalog thu gọn cho e-menu; context rules client/edge |
| `seller/` — web app PWA | Onboard (import + interview), dashboard đơn + flyer analytics, tải tờ rơi, nhận push; 2 persona seller/buyer trên cùng data |
| `imagen/` — image service | Gemini/Imagen gen hero image + nền tờ rơi; rehost ảnh về storage riêng |
| Hạ tầng | QR batch registry; VietQR generator + bank deep-link; order store + state machine; notify pipeline (FCM+SMS); publish per-shop slug; PDF export tờ rơi |

### 5.3 Context không cần LLM — bảng rule

QR encode: `shop_id` + `batch_id` (+ optional location tag). Trang buyer chọn biến thể UI
từ **A2UI JSON đã compose sẵn** bằng rule thường:

| Tín hiệu | Nguồn | Ảnh hưởng UI | Cần LLM? |
|---|---|---|---|
| Batch (tờ rơi ở đâu) | QR | Văn phòng → nút đơn nhóm nổi; quán → menu tại bàn | Không — biến thể compose sẵn |
| Giờ trong ngày | client/edge | Trưa → section combo trưa lên đầu | Không — reorder section |
| Khách cũ/mới | localStorage | Cũ → card "đặt lại đơn trước" | Không — template + data đơn cũ |
| Trạng thái món | shop store | Hết món tự ẩn, sắp hết badge | Không — flag data |
| Menu/theme thay đổi | seller action | Compose lại toàn bộ A2UI JSON | **Có** — 1 call, cache lại |

### 5.4 Quyết định kỹ thuật đã chốt

- **Tự build toàn bộ engine, không dependency ngoài** — bản tối giản đúng nhu cầu. Đổi lại: MVP 4 → 6 tuần
- **Không Flutter ở đâu cả** — buyer page = SSR/static HTML nhẹ (< 2s trên 4G); seller app = web PWA mobile-first; app Android native/APK chỉ cân nhắc ở giai đoạn 2 nếu FCM web push không đủ tin cậy
- **LLM compose-time only** — không có LLM call nào trên đường đi của người mua
- **Không login cho buyer**: localStorage; đơn nhóm nhận diện bằng tên tự nhập
- **Thanh toán: COD mặc định, VietQR opt-in theo trust** (quyết định đã chốt với founder); platform không giữ tiền
- **Notify seller = SLA số 1**: FCM push, không ack 2 phút → SMS; hiển thị trạng thái "quán đã thấy đơn" cho khách.
  Pilot chưa cần app trên store: **SMS là kênh chính** (chi phí ~700đ/tin, volume pilot nhỏ) +
  seller app bản web mở sẵn tab; app Android (APK sideload/nội bộ) lên ở giai đoạn 2 mới bật FCM làm kênh chính
- **Zalo không dùng API ở MVP**: deep-link + copy clipboard; Zalo OA lên giai đoạn 2 (tuần 7–10) làm kênh re-engage
- **Scraper server-side, tách khỏi serve**: import chết không ảnh hưởng tiệm đang chạy; cache + OCR fallback

## 6. Roadmap

### Giai đoạn 0 — Test giấy (3 tuần, TRƯỚC khi code): §4.1. Không đạt Go = không code.

### Giai đoạn 1 — MVP 6 tuần (sau Go; tự build toàn bộ engine)

| Tuần | Deliverable |
|---|---|
| 1 | Nền: monorepo, **format menu chuẩn** (schema lõi — chốt trước mọi thứ), shop store + publish slug, skeleton agent server |
| 2 | Import agent: OCR screenshot (đường chính, cover mọi sàn kể cả Grab) + HTML parse cho sàn nào cho phép + UI review/sửa giá |
| 3 | Compose engine (A2UI JSON + component catalog thu gọn) + buyer page SSR + COD flow |
| 4 | **Notify pipeline (FCM + SMS)** + order state machine + nhớ đơn cũ + đơn nhóm share Zalo + parse đơn text |
| 5 | Gen tờ rơi 3 format (Imagen + PDF, QR per-batch) + dashboard đơn-theo-batch + seller PWA hoàn thiện |
| 6 | Hardening (đo <2s trên 4G, test notify SLA thật) + pilot 5 quán quanh 2–3 toà văn phòng (đánh theo cụm) |

### Giai đoạn 2 — tuần 7–10

Zalo OA re-engage · VietQR trả trước cho khách quen · tích điểm quán · in hộ tờ rơi ·
báo cáo doanh thu xuất được (feature thuế)

### Metric quyết định

- **Số đơn / tờ rơi / tuần** theo batch (North Star pilot)
- % khách quay lại đặt lần 2 trong 7 ngày
- % seller tự cập nhật menu ≥ 1 lần/tuần
- Tỷ lệ đơn nhóm / tổng đơn ở batch văn phòng
- Chi phí hệ thống / đơn (phải < 100đ như §4.3)
- Checkpoint 3 tháng: ≥ 10 quán active, nếu không → dừng/pivot

## 7. Tầm nhìn (1 đoạn, không kéo kiến trúc)

Ngách hiện tại: tờ rơi 2.0 cho quán ăn văn phòng. Mở ngang: mọi seller bán qua chat (bếp nhà làm,
sạp tạp hoá, salon) — cùng engine, đổi catalog. Dài hạn: engine "QR ngữ cảnh → UI theo người quét"
có thể thành SDK cho ngành khác — nhưng KHÔNG quyết định kiến trúc hôm nay; mọi thiết kế phục vụ
việc bán được 5 quán cơm đầu tiên.
