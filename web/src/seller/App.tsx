/* Seller PWA — React + shadcn: onboard (import → review → interview → publish),
 * orders (poll + VN badges + new-order chime), menu (sold-out/price via /patch),
 * flyers (batches + per-batch PDF re-download). */

import { useCallback, useEffect, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Toaster } from "@/components/ui/sonner";
import { toast } from "sonner";
import { apiGet, apiPost, vnd } from "@/lib/api";

const SLUG_KEY = "tq_seller_slug";

const STATUS_VN: Record<string, string> = {
  created: "Mới",
  seller_seen: "Đã thấy",
  confirmed: "Đã nhận",
  delivering: "Đang giao",
  done: "Xong",
  cancelled: "Đã huỷ",
  no_show_flagged: "Bom hàng?",
};

const ACTIONS: Record<string, { label: string; to?: string; ack?: boolean; danger?: boolean }[]> = {
  created: [{ label: "Đã thấy đơn ✓", ack: true }],
  seller_seen: [
    { label: "Xác nhận", to: "confirmed" },
    { label: "Huỷ", to: "cancelled", danger: true },
  ],
  confirmed: [
    { label: "Đang giao", to: "delivering" },
    { label: "Huỷ", to: "cancelled", danger: true },
  ],
  delivering: [{ label: "Đã giao xong", to: "done" }],
};

function localTime(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(+d) ? iso.slice(11, 16) : d.toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" });
}

/* Chuông đơn mới: FCM chưa nối — poll là kênh duy nhất, seller phải NGHE thấy. */
function chime() {
  try {
    const Ctx = window.AudioContext || (window as any).webkitAudioContext;
    if (!Ctx) return;
    const ctx: AudioContext = (chime as any)._ctx || ((chime as any)._ctx = new Ctx());
    if (ctx.state === "suspended") void ctx.resume();
    const t = ctx.currentTime;
    [880, 1174.66].forEach((freq, i) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.001, t + i * 0.18);
      gain.gain.exponentialRampToValueAtTime(0.4, t + i * 0.18 + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.001, t + i * 0.18 + 0.16);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(t + i * 0.18);
      osc.stop(t + i * 0.18 + 0.2);
    });
  } catch {
    /* audio blocked — title flash + vibrate still fire */
  }
}

let titleTimer: ReturnType<typeof setInterval> | null = null;
function flashTitle(count: number) {
  const base = "Tiệm Quen — app quán";
  if (titleTimer) clearInterval(titleTimer);
  document.title = `🔔 ${count} đơn mới!`;
  let on = false;
  titleTimer = setInterval(() => {
    on = !on;
    document.title = on ? base : `🔔 ${count} đơn mới!`;
  }, 1200);
  setTimeout(() => {
    if (titleTimer) clearInterval(titleTimer);
    titleTimer = null;
    document.title = base;
  }, 15000);
}

export default function App() {
  const [slug, setSlugState] = useState(() => localStorage.getItem(SLUG_KEY) || "");
  const setSlug = (s: string) => {
    localStorage.setItem(SLUG_KEY, s);
    setSlugState(s);
  };

  return (
    <div className="max-w-2xl mx-auto pb-6">
      <header className="sticky top-0 z-10 flex items-baseline gap-2 px-4 py-3 border-b bg-background">
        <span className="font-extrabold text-xl text-primary">Tiệm Quen</span>
        <span className="text-xs text-muted-foreground">app quán</span>
        {slug && (
          <Badge variant="outline" className="ml-auto" data-testid="shop-badge">
            /{slug}
          </Badge>
        )}
      </header>

      <Tabs defaultValue={slug ? "orders" : "onboard"} className="px-3 pt-3">
        <TabsList className="w-full grid grid-cols-4">
          <TabsTrigger value="onboard" data-testid="tab-onboard">🏪 Mở tiệm</TabsTrigger>
          <TabsTrigger value="orders" data-testid="tab-orders">🔔 Đơn</TabsTrigger>
          <TabsTrigger value="menu" data-testid="tab-menu">🍛 Menu</TabsTrigger>
          <TabsTrigger value="flyers" data-testid="tab-flyers">📄 Tờ rơi</TabsTrigger>
        </TabsList>
        <TabsContent value="onboard">
          <OnboardTab onPublished={setSlug} />
        </TabsContent>
        <TabsContent value="orders">
          <OrdersTab slug={slug} setSlug={setSlug} />
        </TabsContent>
        <TabsContent value="menu">
          <MenuTab slug={slug} />
        </TabsContent>
        <TabsContent value="flyers">
          <FlyersTab slug={slug} />
        </TabsContent>
      </Tabs>
      <Toaster position="top-center" />
    </div>
  );
}

/* ============================================================= ONBOARD */

interface Envelope {
  menu: { shop: Record<string, unknown>; menu: { sections: { id: string; title: string; items: string[] }[]; dishes: Record<string, any> } };
  warnings?: string[];
  confidence: number;
}

function OnboardTab(props: { onPublished: (slug: string) => void }) {
  const [envelope, setEnvelope] = useState<Envelope | null>(null);
  const [original, setOriginal] = useState<Record<string, { price: number; hidden: boolean }>>({});
  const [edits, setEdits] = useState<Record<string, { price?: number; hidden?: boolean }>>({});
  const [added, setAdded] = useState<{ section_id: string; name: string; price: number }[]>([]);
  const [busyMsg, setBusyMsg] = useState<string | null>(null);
  const [doneSlug, setDoneSlug] = useState<string | null>(null);
  const [url, setUrl] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const importDone = (env: Envelope) => {
    setEnvelope(env);
    const orig: typeof original = {};
    for (const [id, d] of Object.entries(env.menu.menu.dishes))
      orig[id] = { price: d.price, hidden: !!d.hidden };
    setOriginal(orig);
    setEdits({});
    setAdded([]);
    toast.success(`Đọc được ${Object.keys(env.menu.menu.dishes).length} món (độ tin cậy ${env.confidence}/100).`);
  };

  const importUrl = () => {
    if (!url.trim()) return toast.error("Dán link quán trước đã.");
    setBusyMsg("Đang import từ link…");
    apiPost<Envelope>("/api/import", { url: url.trim() })
      .then(importDone)
      .catch((e) => toast.error(`Import lỗi: ${e.message} — thử upload ảnh chụp màn hình menu.`))
      .finally(() => setBusyMsg(null));
  };

  const importShots = () => {
    const files = fileRef.current?.files;
    if (!files?.length) return toast.error("Chọn ít nhất 1 ảnh.");
    const form = new FormData();
    for (const f of files) form.append("screenshot", f);
    setBusyMsg("Đang đọc ảnh menu…");
    fetch("/api/import", { method: "POST", body: form })
      .then(async (r) => {
        if (!r.ok) throw new Error((await r.json()).detail || "import lỗi");
        return r.json();
      })
      .then(importDone)
      .catch((e) => toast.error(`Import lỗi: ${e.message}`))
      .finally(() => setBusyMsg(null));
  };

  const importFixture = () => {
    setBusyMsg("Đang nạp menu mẫu…");
    apiPost<Envelope>("/api/import", { fixture: "grab_screenshot_toolcalls" })
      .then(importDone)
      .catch((e) => toast.error(`Import lỗi: ${e.message}`))
      .finally(() => setBusyMsg(null));
  };

  const publish = async (form: FormData) => {
    if (!envelope) return;
    setBusyMsg("Đang mở tiệm…");
    try {
      const doc = JSON.parse(JSON.stringify(envelope.menu));
      const shipZone = String(form.get("ship_zone") || "").trim();
      if (shipZone) doc.shop.ship_zone = shipZone;
      doc.shop.direct_discount_pct = parseFloat(String(form.get("discount"))) || 0;
      const payment: Record<string, unknown> = { cod: true };
      const account = String(form.get("account") || "").trim();
      if (String(form.get("payment")) === "cod+vietqr" && account) {
        payment.vietqr = {
          bank: String(form.get("bank") || "VCB").trim() || "VCB",
          account,
          account_name: String(form.get("account_name") || "").trim() || undefined,
          enabled_after_n_orders: 3,
        };
        if (!(payment.vietqr as any).account_name) delete (payment.vietqr as any).account_name;
      }
      doc.shop.payment = payment;

      const created = await apiPost<{ shop: { slug: string } }>("/api/shops", doc);
      const slug = created.shop.slug;
      setBusyMsg("Tiệm tạo xong, đang sinh theme…");
      await apiPost(`/api/shops/${slug}/hero`, {});

      const editOps: Record<string, unknown>[] = [];
      for (const [dishId, e] of Object.entries(edits)) {
        const orig = original[dishId];
        if (!orig) continue;
        if (e.price !== undefined && e.price > 0 && e.price !== orig.price)
          editOps.push({ op: "set_price", dish_id: dishId, price: e.price });
        if (e.hidden !== undefined && e.hidden !== orig.hidden)
          editOps.push({ op: "hide_dish", dish_id: dishId, hidden: e.hidden });
      }
      for (const a of added)
        editOps.push({ op: "add_dish", section_id: a.section_id, name: a.name, price: a.price, direct_only: true });
      if (editOps.length) {
        setBusyMsg(`Đang áp ${editOps.length} chỉnh sửa menu…`);
        await fetch(`/api/shops/${slug}/menu`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ edits: editOps }),
        });
      }
      setBusyMsg("Đang dựng trang order…");
      await apiPost(`/api/shops/${slug}/compose`);
      props.onPublished(slug);
      setDoneSlug(slug);
    } catch (e) {
      toast.error(`Lỗi: ${(e as Error).message}`);
    } finally {
      setBusyMsg(null);
    }
  };

  if (doneSlug)
    return (
      <Card className="mt-3" data-testid="onboard-done">
        <CardContent className="p-4">
          <h2 className="text-lg font-bold">Tiệm đã lên sóng 🎉</h2>
          <p className="mt-2">
            Trang order:{" "}
            <a className="text-primary underline" href={`/t/${doneSlug}`} target="_blank" rel="noreferrer">
              {location.host}/t/{doneSlug}
            </a>
          </p>
          <p className="text-sm text-muted-foreground mt-2">
            Giờ qua tab <b>Tờ rơi</b> in bộ QR, và mở tab <b>Đơn</b> để nhận đơn.
          </p>
        </CardContent>
      </Card>
    );

  return (
    <div className="grid gap-3 mt-3" data-testid="onboard">
      <Card>
        <CardContent className="p-4 grid gap-3">
          <h2 className="text-lg font-bold">1 · Lấy menu của quán</h2>
          <p className="text-sm text-muted-foreground">
            Dán link ShopeeFood, hoặc chụp màn hình menu Grab/Shopee rồi upload.
          </p>
          <div className="grid gap-1.5">
            <Label htmlFor="ob-url">Link quán trên sàn</Label>
            <Input id="ob-url" type="url" placeholder="https://shopeefood.vn/..." value={url} onChange={(e) => setUrl(e.target.value)} />
          </div>
          <Button onClick={importUrl} disabled={!!busyMsg}>Import từ link</Button>
          <div className="text-center text-xs text-muted-foreground">hoặc</div>
          <div className="grid gap-1.5">
            <Label htmlFor="ob-shots">Ảnh chụp màn hình menu</Label>
            <Input id="ob-shots" ref={fileRef} type="file" accept="image/*" multiple />
          </div>
          <Button onClick={importShots} disabled={!!busyMsg}>Import từ ảnh</Button>
          <div className="text-center text-xs text-muted-foreground">hoặc</div>
          <Button variant="outline" onClick={importFixture} disabled={!!busyMsg} data-testid="import-fixture">
            Dùng menu mẫu
          </Button>
          {busyMsg && <p className="text-sm text-muted-foreground">{busyMsg}</p>}
        </CardContent>
      </Card>

      {envelope && (
        <ReviewAndPublish
          envelope={envelope}
          edits={edits}
          setEdits={setEdits}
          added={added}
          setAdded={setAdded}
          publish={publish}
          busy={!!busyMsg}
        />
      )}
    </div>
  );
}

function ReviewAndPublish(props: {
  envelope: Envelope;
  edits: Record<string, { price?: number; hidden?: boolean }>;
  setEdits: React.Dispatch<React.SetStateAction<Record<string, { price?: number; hidden?: boolean }>>>;
  added: { section_id: string; name: string; price: number }[];
  setAdded: React.Dispatch<React.SetStateAction<{ section_id: string; name: string; price: number }[]>>;
  publish: (form: FormData) => Promise<void>;
  busy: boolean;
}) {
  const menu = props.envelope.menu.menu;
  const [payMode, setPayMode] = useState("cod");
  const [addName, setAddName] = useState("");
  const [addPrice, setAddPrice] = useState("");
  const [addSection, setAddSection] = useState(menu.sections[0]?.id || "");

  return (
    <>
      <Card data-testid="review">
        <CardContent className="p-4 grid gap-3">
          <h2 className="text-lg font-bold">2 · Kiểm tra menu</h2>
          <p className="text-sm text-muted-foreground">
            Sửa giá trực tiếp (thường rẻ hơn sàn 10–15%), ẩn món không bán, thêm món chỉ bán trực tiếp.
          </p>
          {(props.envelope.warnings || []).map((w, i) => (
            <p key={i} className="text-sm text-[var(--tq-warn,#b45309)]">⚠ {w}</p>
          ))}
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Món</TableHead>
                <TableHead>Giá (đ)</TableHead>
                <TableHead>Ẩn</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {menu.sections.map((section) => (
                <SectionRows key={section.id} section={section} menu={menu} edits={props.edits} setEdits={props.setEdits} />
              ))}
              {props.added.map((a, i) => (
                <TableRow key={`new-${i}`}>
                  <TableCell>
                    {a.name} <span className="text-xs text-emerald-600">chỉ bán trực tiếp (mới)</span>
                  </TableCell>
                  <TableCell>{vnd(a.price)}</TableCell>
                  <TableCell />
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <details>
            <summary className="cursor-pointer text-primary text-sm">+ Thêm món chỉ bán trực tiếp</summary>
            <div className="grid gap-2 mt-2">
              <Input placeholder="Tên món" value={addName} onChange={(e) => setAddName(e.target.value)} />
              <Input placeholder="Giá (đ)" type="number" min={1000} step={1000} value={addPrice} onChange={(e) => setAddPrice(e.target.value)} />
              <select className="border-input h-9 rounded-md border bg-transparent px-3 text-sm" value={addSection} onChange={(e) => setAddSection(e.target.value)}>
                {menu.sections.map((s) => (
                  <option key={s.id} value={s.id}>{s.title}</option>
                ))}
              </select>
              <Button
                variant="outline"
                onClick={() => {
                  const price = parseInt(addPrice, 10);
                  if (!addName.trim() || !(price > 0)) return;
                  props.setAdded((a) => [...a, { section_id: addSection, name: addName.trim(), price }]);
                  setAddName("");
                  setAddPrice("");
                }}
              >
                Thêm món
              </Button>
            </div>
          </details>
        </CardContent>
      </Card>

      <Card data-testid="interview">
        <CardContent className="p-4">
          <form
            className="grid gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              void props.publish(new FormData(e.currentTarget));
            }}
          >
            <h2 className="text-lg font-bold">3 · Ba câu cuối</h2>
            <div className="grid gap-1.5">
              <Label htmlFor="ob-ship">Quán ship khu nào?</Label>
              <Input id="ob-ship" name="ship_zone" placeholder="Bán kính 2km quanh Q.1..." />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="ob-pay">Nhận tiền kiểu gì?</Label>
              <select id="ob-pay" name="payment" value={payMode} onChange={(e) => setPayMode(e.target.value)} className="border-input h-9 rounded-md border bg-transparent px-3 text-sm">
                <option value="cod">Trả khi nhận (mặc định)</option>
                <option value="cod+vietqr">Trả khi nhận + VietQR chuyển khoản</option>
              </select>
            </div>
            {payMode === "cod+vietqr" && (
              <>
                <Input name="bank" placeholder="Ngân hàng (VCB)" />
                <Input name="account" placeholder="Số tài khoản" />
                <Input name="account_name" placeholder="Tên chủ TK" />
              </>
            )}
            <div className="grid gap-1.5">
              <Label htmlFor="ob-discount">Giảm bao nhiêu % cho đơn trực tiếp?</Label>
              <Input id="ob-discount" name="discount" type="number" min={0} max={100} defaultValue={10} />
            </div>
            <Button type="submit" disabled={props.busy} className="min-h-12" data-testid="publish-btn">
              Mở tiệm 🚀
            </Button>
          </form>
        </CardContent>
      </Card>
    </>
  );
}

function SectionRows(props: {
  section: { id: string; title: string; items: string[] };
  menu: Envelope["menu"]["menu"];
  edits: Record<string, { price?: number; hidden?: boolean }>;
  setEdits: React.Dispatch<React.SetStateAction<Record<string, { price?: number; hidden?: boolean }>>>;
}) {
  return (
    <>
      <TableRow>
        <TableCell colSpan={3} className="font-bold">{props.section.title}</TableCell>
      </TableRow>
      {props.section.items.map((dishId) => {
        const dish = props.menu.dishes[dishId];
        if (!dish) return null;
        const e = props.edits[dishId] || {};
        return (
          <TableRow key={dishId}>
            <TableCell>
              {dish.name}
              {dish.direct_only && <span className="text-xs text-emerald-600"> chỉ bán trực tiếp</span>}
            </TableCell>
            <TableCell>
              <Input
                type="number"
                step={1000}
                min={0}
                className="w-24"
                value={e.price ?? dish.price}
                onChange={(ev) =>
                  props.setEdits((old) => ({ ...old, [dishId]: { ...old[dishId], price: parseInt(ev.target.value, 10) || 0 } }))
                }
              />
            </TableCell>
            <TableCell>
              <Switch
                checked={e.hidden ?? !!dish.hidden}
                onCheckedChange={(checked) =>
                  props.setEdits((old) => ({ ...old, [dishId]: { ...old[dishId], hidden: checked } }))
                }
              />
            </TableCell>
          </TableRow>
        );
      })}
    </>
  );
}

/* =============================================================== ORDERS */

interface Order {
  id: string;
  status: string;
  created_at: string;
  batch_id?: string;
  items: { qty: number; name: string }[];
  total: number;
  customer?: { name?: string; phone?: string; address?: string };
}

function OrdersTab(props: { slug: string; setSlug: (s: string) => void }) {
  const { slug } = props;
  const [orders, setOrders] = useState<Order[] | null>(null);
  const [batchStats, setBatchStats] = useState<Record<string, any>>({});
  const [slugInput, setSlugInput] = useState("");
  const knownIds = useRef<string[] | null>(null);

  const refresh = useCallback(() => {
    if (!slug) return;
    apiGet<{ orders: Order[] }>(`/api/shops/${slug}/orders`)
      .then((body) => {
        setOrders(body.orders);
        const ids = body.orders.map((o) => o.id);
        if (knownIds.current !== null) {
          const fresh = ids.filter((id) => !knownIds.current!.includes(id));
          if (fresh.length) {
            chime();
            navigator.vibrate?.([200, 100, 200]);
            flashTitle(fresh.length);
            toast(`🔔 ${fresh.length} đơn mới!`);
          }
        }
        knownIds.current = ids;
      })
      .catch(() => {});
    apiGet<{ per_batch: Record<string, any> }>(`/api/shops/${slug}/batch-analytics`)
      .then((body) => setBatchStats(body.per_batch))
      .catch(() => {});
  }, [slug]);

  useEffect(() => {
    knownIds.current = null;
    refresh();
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, [refresh]);

  if (!slug)
    return (
      <Card className="mt-3" data-testid="need-slug">
        <CardContent className="p-4 grid gap-3">
          <h2 className="text-lg font-bold">Tiệm của bạn</h2>
          <div className="grid gap-1.5">
            <Label htmlFor="slug-input">Slug tiệm (tiemquen.com/&lt;slug&gt;)</Label>
            <Input id="slug-input" placeholder="com-tam-co-ba" value={slugInput} onChange={(e) => setSlugInput(e.target.value)} />
          </div>
          <Button onClick={() => slugInput.trim() && props.setSlug(slugInput.trim())}>Xem đơn</Button>
        </CardContent>
      </Card>
    );

  return (
    <div className="grid gap-3 mt-3" data-testid="orders-live">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold">Đơn mới nhất</h2>
        <span className="text-emerald-500 animate-pulse" title="đang tự cập nhật">●</span>
      </div>
      {orders?.length === 0 && (
        <p className="text-sm text-muted-foreground">Chưa có đơn nào — dán tờ rơi đi chờ chi.</p>
      )}
      {(orders || []).map((o) => (
        <OrderCard key={o.id} order={o} onChanged={refresh} />
      ))}

      <h2 className="text-lg font-bold mt-2">Đơn theo batch tờ rơi</h2>
      <p className="text-sm text-muted-foreground -mt-2">Tờ dán chỗ nào ra đơn — in thêm đúng chỗ hiệu quả.</p>
      <Table data-testid="batch-stats">
        <TableHeader>
          <TableRow>
            <TableHead>Batch</TableHead>
            <TableHead>Chỗ dán</TableHead>
            <TableHead>Đơn</TableHead>
            <TableHead>Doanh thu</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {Object.keys(batchStats).length === 0 && (
            <TableRow>
              <TableCell colSpan={4} className="text-muted-foreground">Chưa có dữ liệu.</TableCell>
            </TableRow>
          )}
          {Object.entries(batchStats).map(([batchId, s]) => (
            <TableRow key={batchId}>
              <TableCell>{batchId}</TableCell>
              <TableCell>{s.location_tag || "—"}</TableCell>
              <TableCell>{s.orders}</TableCell>
              <TableCell>{vnd(s.revenue)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function OrderCard(props: { order: Order; onChanged: () => void }) {
  const o = props.order;
  const [busy, setBusy] = useState(false);
  const who = o.customer || {};
  const border =
    o.status === "created"
      ? "border-l-destructive"
      : o.status === "seller_seen"
        ? "border-l-[var(--tq-warn,#f59e0b)]"
        : o.status === "done"
          ? "border-l-emerald-500 opacity-75"
          : ["cancelled", "no_show_flagged"].includes(o.status)
            ? "opacity-50"
            : "border-l-primary";

  return (
    <Card className={`border-l-4 ${border}`} data-testid="order-card" data-status={o.status}>
      <CardContent className="p-3.5">
        <div className="flex justify-between text-xs text-muted-foreground">
          <span>
            #{o.id.slice(-6)} · {localTime(o.created_at)} · batch {o.batch_id || "direct"}
          </span>
          <Badge variant="secondary" data-testid="status-badge">
            {STATUS_VN[o.status] || o.status}
          </Badge>
        </div>
        <p className="my-1.5 text-sm">
          {o.items.map((it) => `${it.qty}× ${it.name}`).join(", ")} —{" "}
          <strong className="text-primary">{vnd(o.total)}</strong>
        </p>
        <p className="text-xs text-muted-foreground">
          {who.name} ·{" "}
          {who.phone && (
            <a className="text-primary font-bold" href={`tel:${who.phone}`}>
              📞 {who.phone}
            </a>
          )}{" "}
          · {who.address}
        </p>
        {ACTIONS[o.status] && (
          <div className="flex gap-2.5 mt-2.5">
            {ACTIONS[o.status].map((a) => (
              <Button
                key={a.label}
                size="sm"
                disabled={busy}
                variant={a.danger ? "outline" : "default"}
                className={`min-h-11 ${a.danger ? "ml-auto border-destructive text-destructive" : ""}`}
                onClick={async () => {
                  setBusy(true);
                  try {
                    await apiPost(a.ack ? `/orders/${o.id}/ack` : `/orders/${o.id}/transition`, a.ack ? undefined : { to: a.to });
                    props.onChanged();
                  } catch (e) {
                    toast.error(String((e as Error).message));
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                {a.label}
              </Button>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/* ================================================================= MENU */

function MenuTab(props: { slug: string }) {
  const { slug } = props;
  const [menu, setMenu] = useState<Envelope["menu"]["menu"] | null>(null);
  const [priceDraft, setPriceDraft] = useState<Record<string, string>>({});

  const refresh = useCallback(() => {
    if (!slug) return;
    apiGet<{ menu: Envelope["menu"]["menu"] }>(`/api/shops/${slug}/menu`)
      .then((b) => setMenu(b.menu))
      .catch((e) => toast.error(`Không tải được menu: ${e.message}`));
  }, [slug]);
  useEffect(refresh, [refresh]);

  if (!slug)
    return (
      <p className="text-sm text-muted-foreground mt-4">
        Chưa có tiệm — mở tiệm ở tab <b>Mở tiệm</b>, hoặc nhập slug ở tab <b>Đơn</b>.
      </p>
    );
  if (!menu) return <p className="text-sm text-muted-foreground mt-4">Đang tải menu…</p>;

  const patch = async (body: Record<string, unknown>, then: () => void) => {
    try {
      await apiPost(`/api/shops/${slug}/patch`, body);
      toast.success("Đã cập nhật ✓");
      then();
    } catch (e) {
      toast.error(`Lỗi: ${(e as Error).message}`);
    }
  };

  return (
    <div className="mt-3" data-testid="menu-live">
      <h2 className="text-lg font-bold">Món hôm nay</h2>
      <p className="text-sm text-muted-foreground">
        Hết món → gạt công tắc, áp dụng NGAY lên trang order. Sửa giá xong bấm Lưu.
      </p>
      {menu.sections.map((section) => (
        <div key={section.id}>
          <h3 className="text-xs uppercase tracking-wide text-muted-foreground mt-4 mb-1.5">{section.title}</h3>
          {section.items.map((dishId) => {
            const dish = menu.dishes[dishId];
            if (!dish) return null;
            const draft = priceDraft[dishId];
            const changed = draft !== undefined && parseInt(draft, 10) !== dish.price;
            return (
              <div key={dishId} className="flex flex-wrap items-center gap-2.5 py-2.5 border-b" data-testid="menu-row">
                <span className={`w-full text-sm font-medium ${dish.sold_out ? "line-through opacity-50" : ""}`}>
                  {dish.name}
                  {dish.hidden && <span className="text-xs text-emerald-600"> đang ẩn</span>}
                </span>
                <Input
                  type="number"
                  step={1000}
                  min={0}
                  inputMode="numeric"
                  className="w-28"
                  value={draft ?? dish.price}
                  onChange={(e) => setPriceDraft((d) => ({ ...d, [dishId]: e.target.value }))}
                />
                {changed && (
                  <Button
                    size="sm"
                    data-testid="save-price"
                    onClick={() => {
                      const v = parseInt(draft, 10);
                      if (!(v > 0)) return toast.error("Giá phải > 0.");
                      void patch({ dish_id: dishId, price: v }, () => {
                        dish.price = v;
                        setPriceDraft((d) => {
                          const { [dishId]: _, ...rest } = d;
                          return rest;
                        });
                      });
                    }}
                  >
                    Lưu giá
                  </Button>
                )}
                <div className="ml-auto flex items-center gap-3">
                  <label className="flex items-center gap-1.5 text-xs">
                    Hết món
                    <Switch
                      data-testid="soldout-switch"
                      checked={!!dish.sold_out}
                      onCheckedChange={(checked) =>
                        void patch({ dish_id: dishId, sold_out: checked }, () => {
                          dish.sold_out = checked;
                          setMenu({ ...menu });
                        })
                      }
                    />
                  </label>
                  <label className="flex items-center gap-1.5 text-xs">
                    Sắp hết
                    <Switch
                      checked={!!dish.almost_out}
                      onCheckedChange={(checked) =>
                        void patch({ dish_id: dishId, almost_out: checked }, () => {
                          dish.almost_out = checked;
                          setMenu({ ...menu });
                        })
                      }
                    />
                  </label>
                </div>
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}

/* ================================================================ FLYERS */

interface Batch {
  id: string;
  format: string;
  location_tag: string;
  created_at?: string;
  qr_url: string;
  pdf_url?: string;
}

function FlyersTab(props: { slug: string }) {
  const { slug } = props;
  const [batches, setBatches] = useState<Batch[]>([]);
  const [location_, setLocation] = useState("");
  const [formats, setFormats] = useState<Record<string, boolean>>({ a5: true, a4: true, sticker: false });
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<{ fmt: string; pdf_url: string; batch_id: string; qr_url: string }[]>([]);

  const refresh = useCallback(() => {
    if (!slug) return;
    apiGet<{ batches: Batch[] }>(`/api/shops/${slug}/batches`)
      .then((b) => setBatches(b.batches.reverse()))
      .catch(() => {});
  }, [slug]);
  useEffect(refresh, [refresh]);

  if (!slug)
    return (
      <p className="text-sm text-muted-foreground mt-4">
        Mở tiệm trước (tab Mở tiệm) hoặc nhập slug ở tab Đơn.
      </p>
    );

  const generate = async () => {
    const fmts = Object.entries(formats).filter(([, on]) => on).map(([f]) => f);
    if (!fmts.length) return toast.error("Chọn ít nhất 1 format.");
    setBusy(true);
    setResults([]);
    try {
      const body = await apiPost<{ flyers: Record<string, { pdf_url: string; batch_id: string; qr_url: string }> }>(
        `/api/shops/${slug}/flyers`,
        { formats: fmts, location_tag: location_.trim() || "cua-quan" },
      );
      setResults(Object.entries(body.flyers).map(([fmt, f]) => ({ fmt, ...f })));
      toast.success("Xong! Tải PDF đem in.");
      refresh();
    } catch (e) {
      toast.error(`Lỗi: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  const fullUrl = (p: string) => (/^https?:/.test(p) ? p : location.origin + p);

  return (
    <div className="grid gap-3 mt-3" data-testid="flyers">
      <Card>
        <CardContent className="p-4 grid gap-3">
          <h2 className="text-lg font-bold">In tờ rơi mới</h2>
          <p className="text-sm text-muted-foreground">
            Mỗi lần in = 1 batch = 1 mã QR riêng, để biết tờ dán ở đâu ra đơn.
          </p>
          <div className="grid gap-1.5">
            <Label htmlFor="fl-loc">Dán ở đâu? (batch tag)</Label>
            <Input id="fl-loc" placeholder="office plaza 1 / cửa quán / pantry A..." value={location_} onChange={(e) => setLocation(e.target.value)} />
          </div>
          {(["a5", "a4", "sticker"] as const).map((f) => (
            <label key={f} className="flex items-center gap-2 text-sm">
              <Switch checked={!!formats[f]} onCheckedChange={(on) => setFormats((x) => ({ ...x, [f]: on }))} />
              {f === "a5" ? "A5 — nhét túi đơn sàn" : f === "a4" ? "A4 — poster pantry" : "Sticker vuông"}
            </label>
          ))}
          <Button onClick={generate} disabled={busy} className="min-h-12" data-testid="generate-flyers">
            {busy ? "Đang sinh ảnh nền + dựng PDF…" : "Tạo tờ rơi (PDF in được)"}
          </Button>
          {results.map((r) => (
            <a key={r.fmt} className="block rounded-lg border p-3 text-primary font-bold" href={r.pdf_url} download data-testid="flyer-result">
              ⬇ Tờ rơi {r.fmt.toUpperCase()}
              <span className="block text-xs font-normal text-muted-foreground">
                batch {r.batch_id} · QR → {fullUrl(r.qr_url)}
              </span>
            </a>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-4">
          <h2 className="text-lg font-bold mb-2">Batch đã in</h2>
          {!batches.length && <p className="text-sm text-muted-foreground">Chưa in batch nào.</p>}
          {batches.map((b) => (
            <div key={b.id} className="py-2.5 border-b last:border-0" data-testid="batch-card">
              <div className="flex justify-between text-sm">
                <span>
                  <b>{b.id}</b> · {b.format.toUpperCase()} · {b.location_tag}
                </span>
                <Badge variant="secondary">{(b.created_at || "").slice(0, 10)}</Badge>
              </div>
              <p className="text-xs text-muted-foreground mt-1">QR → {fullUrl(b.qr_url)}</p>
              {b.pdf_url && (
                <a className="text-primary text-sm font-bold" href={b.pdf_url} download>
                  ⬇ Tải lại PDF
                </a>
              )}
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
