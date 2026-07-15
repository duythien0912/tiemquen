# Tiệm Quen — Landing Page Prompt

> Adapted from a "Prisma Creative Studio" React/Tailwind/framer-motion template.
> Reskinned for a Vietnamese food-ordering product; reimplemented as a single
> self-contained HTML/CSS/JS file (no build step, no external assets/CDNs,
> no third-party video/image URLs) to match this project's existing pattern.

```
Create a single self-contained HTML file (inline CSS + vanilla JS, no framework,
no external font/video/image URLs) for "Tiệm Quen" — a tool that turns a quán ăn's
paper flyer into a direct QR-ordering channel, so quán cơm/bún/đồ uống near office
clusters can escape delivery-platform commission (25–30%) and own their repeat
lunch customers directly. The page has 3 sections: Hero, Câu chuyện (About),
Cách vận hành (Features). Cinematic dark + warm-amber palette, cream accent text,
brand-orange (#E4572E family) as the identity color. Recreate framer-motion's
word-pull-up, scroll-linked letter reveal, and staggered card entrance using
IntersectionObserver + CSS transitions/rAF — no animation library.

FONTS

System font stack only (-apple-system, Segoe UI, Roboto, sans-serif) — no
Google Fonts load, fully offline-capable.

COLOR SYSTEM

Background: near-black #0D0A08 globally (not pure #000, so overlay-blend noise
  stays visible), #17120F for the About card, #1E1713 for feature cards
Cream accent (primary text/CTA fill): #E8DFC8
Brand orange (identity, kicker labels, hover, dot accent): #E4572E / hover #F0663C
Gray text: #C9BEB4 (body), #8F857C (muted/label)
Nav link color: rgba(232,223,200,.75), hover: #E8DFC8

CUSTOM CSS UTILITIES

Two inline-SVG feTurbulence noise textures (data URI, no external file):
  .noise-hero: baseFrequency 0.85, numOctaves 3, mix-blend-mode:overlay,
    opacity .35 — over the hero's ambient gradient
  .noise-features: baseFrequency 0.9, numOctaves 4, mix-blend-mode:overlay,
    opacity .12 — subtle background wash on the Features section

SECTION 1: HERO

Full viewport height. Section has ~1rem padding creating an inset frame; inside,
a container with large rounded corners (2rem) and overflow hidden.

Background: NOT a video (no licensed footage available) — an animated ambient
  canvas gradient (2-3 soft warm radial blobs: orange/amber/deep-ember) that
  drifts slowly (CSS/rAF driven by time, not scroll — this page is not
  scroll-scrubbed). Noise overlay on top. Gradient wash top+bottom for legibility
  (linear-gradient to bottom, black/30 → transparent → black/60).

Nav: absolutely positioned, hanging pill at top-center (dark bg, rounded bottom
  corners). Logo "Tiệm Quen" (bold, orange dot accent) + 5 links: "Câu chuyện",
  "Vì sao thoát sàn", "Cách vận hành", "Đơn nhóm văn phòng", "Liên hệ".
  Link color rgba(232,223,200,.75), hover #E8DFC8. Compress on mobile.

Hero content (bottom-aligned, 12-col grid: left ~8 cols giant wordmark,
  right ~4 cols description + CTA):
  Giant heading "Tiệm Quen" — each word slides up (translateY 100%→0, fade in)
    staggered ~0.08s, triggered once via IntersectionObserver. Responsive size
    ~14–22vw, font-weight 800, line-height 0.9, letter-spacing -0.03em, color
    cream. Small orange "•" superscript after "Quen" (brand dot, matches the
    existing logo mark elsewhere in the product).
  Description (right column, fade up +translateY(20px), delay ~0.4s):
    "Tiệm Quen biến tờ rơi giấy thành kênh đặt hàng riêng của quán — khách quét
    QR, đặt trong 3 chạm, không tốn hoa hồng sàn, không mất khách về tay ai."
  CTA pill "Tạo tiệm miễn phí" (cream bg, black text, black circle w/ cream
    arrow on the right; hover: gap widens, circle scales 1.1), fade up delay .6s.
  Bounce chevron at hero bottom (loops, generic chevron, no external icon lib).

SECTION 2: CÂU CHUYỆN (About)

Dark card (bg #17120F) inset in the black section, centered content, max-w ~72rem.
  Label: "Câu chuyện" (orange, small caps, mono-ish tracking).
  Multi-style heading (mixed weights in one flowing paragraph, word-pull-up per
    word, ~2.2–3.5rem):
    "Tụi mình từng là" (normal) + "khách quen bị sàn coi là người lạ." (italic,
    cream-on-cream serif-style emphasis via font-style + slightly larger) +
    "Nên tụi mình làm Tiệm Quen." (normal).
  Body paragraph below with SCROLL-LINKED PER-CHARACTER OPACITY reveal (each
    character its own span; opacity ramps 0.2→1 as the paragraph crosses the
    viewport, staggered by character index — same mechanic as the reference,
    reimplemented with rAF reading getBoundingClientRect instead of
    framer-motion's useScroll):
    "Hoa hồng sàn ăn mất 25–30% mỗi đơn. Khách văn phòng đặt lặp lại gần như
    mỗi trưa, nhưng quán không giữ nổi một số điện thoại, một lịch sử đơn nào
    của họ. Tiệm Quen sinh ra để quán giữ lại đúng thứ quan trọng nhất: khách
    của chính mình."

SECTION 3: CÁCH VẬN HÀNH (Features)

Near-black bg + .noise-features wash. Header, two-line multi-style pull-up:
  Line 1 (cream): "Vận hành gọn cho quán bận rộn."
  Line 2 (muted gray): "Không app, không hoa hồng, không giữ tiền hộ."

4-card grid (1 col mobile → 2 col tablet → 4 col desktop), each card:
  staggered scale(.95→1)+fade entrance via IntersectionObserver, ~0.15s stagger.

  Card 1 — showcase card (replaces the video card; no licensed footage):
    warm gradient card (amber → ember, drawn in CSS, no image asset), bottom-left
    text overlay in cream: "Tiệm của mình. Khách của mình."
  Card 2 — "Onboard nhanh" (01): simple inline-SVG upload/menu glyph (hand-drawn
    generic line icon, not a copied icon-library asset), 4-item checklist
    (orange check glyph): "Dán link Grab/ShopeeFood hoặc gửi ảnh menu" ·
    "Hệ thống tự đọc món, giá, ảnh, giờ mở cửa" · "Sửa giá, ẩn món trong vài cú
    chạm" · "Web tiệm + tờ rơi ra trong dưới 10 phút". "Tìm hiểu thêm" link with
    arrow rotated -45° on hover.
  Card 3 — "Đặt trong 3 chạm" (02): inline-SVG QR-corner glyph, 3-item checklist:
    "Quét QR → chọn món → xác nhận" · "Không cài app, không đăng nhập" ·
    "Nhớ đơn cũ — đặt lại 1 chạm".
  Card 4 — "Đơn nhóm văn phòng" (03): inline-SVG people glyph, 3-item checklist:
    "1 người quét, cả phòng tự chọn món vào chung 1 đơn" · "Chia tiền tự động +
    VietQR hoàn tiền người trả hộ" · "Hệ thống nhắc chuyển khoản giùm trưởng kèo".

FOOTER (not in the original reference — added because this is a real business
  site, not a portfolio teaser): shop name + tagline, Zalo contact CTA, minimal
  legal links (Chính sách dữ liệu · Điều khoản). Muted, small, doesn't compete
  with the cinematic sections above it.

SHARED ANIMATION BEHAVIOR (vanilla reimplementation, no framer-motion)

wordsPullUp(el): wraps each space-separated word in
  <span class="wpu"><span>word</span></span> (outer overflow:hidden, inner
  translateY(110%)+opacity:0 → translateY(0)+opacity:1 on an IntersectionObserver
  hit, once:true, each word's CSS transition-delay = index * 0.08s).
scrollLetterReveal(el): wraps each character in <span>, on scroll (rAF, passive)
  computes the paragraph's position in the viewport and sets each character's
  opacity from 0.2→1 based on (progress − charIndex/total) — matches the
  reference's charProgress formula.
cardEntrance: IntersectionObserver (threshold ~0.2, once) adds a `.in` class per
  card with transition-delay = index * 0.15s → scale(.95→1) + opacity(0→1).

ACCESSIBILITY / MARKETING-READY BASICS (carried over from this project's earlier
  landing iterations — keep them, don't regress):
  - Favicon (inline SVG data URI), theme-color meta.
  - Open Graph + Twitter Card meta tags (title/description/type/url); no
    og:image until a real hosted asset exists at deploy time.
  - Visible :focus-visible ring (brand orange) on links/buttons.
  - White-on-orange text must hit WCAG AA (4.5:1) — use the darker accessible
    shade (#C7431D, not the lighter #E4572E) wherever text sits on an orange
    fill; #E4572E stays fine as TEXT color on the dark background or as
    decorative/underline fills with no text on top.
  - Mobile: hero CTA must be reachable without scrolling on common phone
    heights (iPhone SE 667px included) and in landscape (short viewport height,
    not just narrow width — add a max-height media query, don't rely on
    max-width alone).

RESPONSIVE BREAKPOINTS

Fully responsive mobile/tablet/desktop. Features grid: 1-col mobile → 2-col
~768px → 4-col ~1100px+. Hero wordmark scales via clamp()/vw, not a fixed px
value. Nav link list hidden under ~768px (logo + CTA only). Landscape-short
viewports get a compact hero (see accessibility note above).

TECH STACK

Plain HTML + CSS + vanilla JS (IIFE), zero dependencies, zero build step,
opens directly in a browser. No React/Vite/Tailwind/framer-motion/icon library.
```
