/* Group order (office pantry, ARCH §3.3) — React + shadcn.
 * Poll 5s while open; per-member breakdown; live "phần của bạn";
 * close with optional payer bank → real VietQR deep links per member. */

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { apiGet, apiPost, vnd, type ShopPublic } from "@/lib/api";

interface Member {
  items: { dish_id: string; name: string; price: number; qty: number }[];
  subtotal: number;
}
interface Group {
  id: string;
  shop_slug: string;
  status: "open" | "closed";
  members: Record<string, Member>;
  split?: Record<string, SplitEntry>;
}
interface SplitEntry {
  amount: number;
  is_payer: boolean;
  vietqr?: { deep_link: string; copy_text: string; amount: number };
  vietqr_placeholder?: { payee: string; note: string };
}
interface Dish {
  name: string;
  price: number;
  hidden?: boolean;
  sold_out?: boolean;
}

const POLL_MS = 5000;

export default function App() {
  const boot = ((window as any).__TIEMQUEN_GROUP__ || {}) as { gid?: string; shop?: ShopPublic };
  const gid = boot.gid || location.pathname.split("/").filter(Boolean).pop() || "";
  const shop = boot.shop || {};

  const [group, setGroup] = useState<Group | null>(null);
  const [dishes, setDishes] = useState<Record<string, Dish> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const snapRef = useRef("");

  const load = useCallback(async () => {
    const g = await apiGet<Group>(`/group-orders/${gid}`);
    snapRef.current = JSON.stringify({ m: g.members, s: g.status });
    setGroup(g);
    if (!dishes) {
      const body = await apiGet<{ menu: { dishes: Record<string, Dish> } }>(
        `/api/shops/${encodeURIComponent(g.shop_slug)}/menu`,
      );
      setDishes(body.menu.dishes);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gid]);

  useEffect(() => {
    load().catch((e) => setError((e as Error).message));
  }, [load]);

  // Poll: group Zalo thêm món rải rác — thấy người khác vào kèo không cần F5.
  useEffect(() => {
    if (!group || group.status === "closed") return;
    const t = setInterval(() => {
      apiGet<Group>(`/group-orders/${gid}`)
        .then((g) => {
          const snap = JSON.stringify({ m: g.members, s: g.status });
          if (snap === snapRef.current) return;
          const active = document.activeElement as HTMLElement | null;
          const typing =
            active && ["INPUT", "TEXTAREA"].includes(active.tagName) && (active as HTMLInputElement).value;
          if (typing && g.status !== "closed") return; // đợi gõ xong
          snapRef.current = snap;
          setGroup(g);
        })
        .catch(() => {});
    }, POLL_MS);
    return () => clearInterval(t);
  }, [group, gid]);

  if (error)
    return (
      <p data-testid="page-error" className="p-10 text-center text-destructive">
        Không tải được đơn nhóm ({error}).
      </p>
    );
  if (!group || !dishes)
    return (
      <div className="max-w-2xl mx-auto p-4 grid gap-3">
        <Skeleton className="h-20 rounded-xl" />
        <Skeleton className="h-40 rounded-xl" />
      </div>
    );

  return (
    <div className="max-w-2xl mx-auto p-4 pb-10">
      <h1 className="text-2xl font-bold">
        Đặt chung — {shop.name || group.shop_slug}
      </h1>
      {group.status === "closed" ? (
        <ClosedView group={group} shopName={shop.name} />
      ) : (
        <OpenView group={group} dishes={dishes} onChanged={load} msg={msg} setMsg={setMsg} />
      )}
    </div>
  );
}

function OpenView(props: {
  group: Group;
  dishes: Record<string, Dish>;
  onChanged: () => Promise<void>;
  msg: string | null;
  setMsg: (m: string | null) => void;
}) {
  const { group, dishes } = props;
  const memberNames = Object.keys(group.members);
  const [name, setName] = useState("");
  const [qty, setQty] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState(false);

  const subtotal = useMemo(
    () => Object.entries(qty).reduce((sum, [id, q]) => sum + (q || 0) * (dishes[id]?.price || 0), 0),
    [qty, dishes],
  );

  const addPart = async (ev: FormEvent) => {
    ev.preventDefault();
    props.setMsg(null);
    const items = Object.entries(qty)
      .filter(([, q]) => q > 0)
      .map(([dish_id, q]) => ({ dish_id, name: dishes[dish_id].name, price: dishes[dish_id].price, qty: q }));
    if (!name.trim() || !items.length) {
      props.setMsg("Cần tên và ít nhất 1 món.");
      return;
    }
    setBusy(true);
    try {
      await apiPost(`/group-orders/${group.id}/members`, { name: name.trim(), items });
      setQty({});
      await props.onChanged();
    } catch (e) {
      props.setMsg(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <p className="text-sm text-muted-foreground mt-1">
        Mỗi người tự chọn món, chốt xong 1 đơn 1 ship. Trang tự cập nhật khi có người thêm món.
      </p>

      <Card className="mt-4" data-testid="members">
        <CardContent className="p-4">
          <h2 className="font-bold text-lg">Đã order ({memberNames.length})</h2>
          {!memberNames.length && (
            <p className="text-sm text-muted-foreground mt-1">Chưa ai chọn món — bạn mở hàng đi!</p>
          )}
          {memberNames.map((n) => (
            <div key={n} className="py-2 border-b last:border-0">
              <div className="flex justify-between gap-3">
                <span>{n}</span>
                <strong>{vnd(group.members[n].subtotal)}</strong>
              </div>
              <p className="text-xs text-muted-foreground mt-0.5">
                {group.members[n].items.map((it) => `${it.qty}× ${it.name}`).join(", ")}
              </p>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card className="mt-4" data-testid="add-part">
        <CardContent className="p-4">
          <form onSubmit={addPart} className="grid gap-3">
            <h2 className="font-bold text-lg">Thêm phần của bạn</h2>
            <p className="text-xs text-muted-foreground">
              Đã order rồi? Nhập lại đúng tên cũ để sửa phần của mình.
            </p>
            <div className="grid gap-1.5">
              <Label htmlFor="g-name">Tên bạn</Label>
              <Input id="g-name" required value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            {Object.entries(props.dishes)
              .filter(([, d]) => !d.hidden && !d.sold_out)
              .map(([id, d]) => (
                <div key={id} className="flex items-center gap-3 border-b pb-2 last:border-0">
                  <span className="flex-1 text-sm">
                    {d.name} — {vnd(d.price)}
                  </span>
                  <Input
                    type="number"
                    min={0}
                    inputMode="numeric"
                    className="w-16 text-center"
                    value={qty[id] ?? 0}
                    onChange={(e) => setQty((q) => ({ ...q, [id]: parseInt(e.target.value, 10) || 0 }))}
                  />
                </div>
              ))}
            <p data-testid="my-subtotal" className="text-right font-bold">
              Phần của bạn: {vnd(subtotal)}
            </p>
            {props.msg && (
              <p data-testid="form-error" className="text-sm text-destructive">
                {props.msg}
              </p>
            )}
            <Button type="submit" disabled={busy} className="min-h-12 rounded-full">
              Thêm vào đơn nhóm
            </Button>
          </form>
        </CardContent>
      </Card>

      {memberNames.length > 0 && (
        <CloseForm group={group} memberNames={memberNames} onChanged={props.onChanged} />
      )}
    </>
  );
}

function CloseForm(props: { group: Group; memberNames: string[]; onChanged: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const close = async (ev: FormEvent) => {
    ev.preventDefault();
    setErr(null);
    const fd = new FormData(ev.currentTarget as HTMLFormElement);
    const bank = String(fd.get("payer_bank") || "").trim();
    const account = String(fd.get("payer_account") || "").trim();
    const body: Record<string, unknown> = {
      closer_name: fd.get("closer"),
      customer: {
        name: fd.get("closer"),
        phone: fd.get("phone"),
        address: fd.get("address"),
        note: fd.get("note") || "",
      },
    };
    if (bank && account) body.payer_vietqr = { bank, account };
    setBusy(true);
    try {
      await apiPost(`/group-orders/${props.group.id}/close`, body);
      await props.onChanged();
    } catch (e) {
      setErr(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="mt-4" data-testid="close-form">
      <CardContent className="p-4">
        <form onSubmit={close} className="grid gap-3">
          <h2 className="font-bold text-lg">Chốt kèo (bạn trả hộ cả nhóm)</h2>
          <div className="grid gap-1.5">
            <Label htmlFor="g-closer">Ai trả hộ?</Label>
            <select
              id="g-closer"
              name="closer"
              className="border-input h-9 rounded-md border bg-transparent px-3 text-sm"
            >
              {props.memberNames.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="g-phone">SĐT nhận hàng</Label>
            <Input id="g-phone" name="phone" type="tel" inputMode="tel" required />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="g-address">Địa chỉ / toà nhà</Label>
            <Input id="g-address" name="address" required />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="g-note">Ghi chú</Label>
            <Input id="g-note" name="note" />
          </div>
          <Separator />
          <p className="text-xs text-muted-foreground">
            Nhập STK của bạn (không bắt buộc) — mỗi người sẽ có nút chuyển khoản đúng số tiền phần mình.
          </p>
          <div className="grid gap-1.5">
            <Label htmlFor="g-bank">Ngân hàng (VCB, TCB, MB…)</Label>
            <Input id="g-bank" name="payer_bank" placeholder="VCB" />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="g-account">Số tài khoản của bạn</Label>
            <Input id="g-account" name="payer_account" inputMode="numeric" />
          </div>
          {err && (
            <p data-testid="close-error" className="text-sm text-destructive">
              {err}
            </p>
          )}
          <Button type="submit" disabled={busy} className="min-h-12 rounded-full">
            Chốt đơn — báo quán giao
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

function ClosedView(props: { group: Group; shopName?: string }) {
  const split = props.group.split || {};
  const names = Object.keys(split);
  const payer = names.find((n) => split[n].is_payer) || "";
  const hasDebtors = names.some((n) => !split[n].is_payer && split[n].amount > 0);
  const total = names.reduce((t, n) => t + split[n].amount, 0);

  return (
    <div data-testid="closed">
      <h2 className="text-xl font-bold mt-2">Đơn nhóm đã chốt ✅</h2>
      <p className="mt-1">
        Quán sẽ giao 1 lần{props.shopName ? ` từ ${props.shopName}` : ""}.
        {hasDebtors ? ` Chuyển khoản lại cho ${payer} (người trả hộ):` : ""}
      </p>
      <Card className="mt-3">
        <CardContent className="p-4">
          {names.map((n) => {
            const s = split[n];
            return (
              <div key={n} className="py-2 border-b last:border-0">
                <div className="flex justify-between gap-3">
                  <span className={s.is_payer ? "font-semibold text-primary" : ""}>
                    {s.is_payer ? `${n} (đã trả hộ)` : n}
                  </span>
                  <strong>{vnd(s.amount)}</strong>
                </div>
                {s.vietqr && (
                  <div className="grid gap-2 mt-2" data-testid="pay-actions">
                    <Button asChild className="min-h-11 rounded-full">
                      <a href={s.vietqr.deep_link}>
                        🏦 {n} — mở app bank, chuyển {vnd(s.vietqr.amount)}
                      </a>
                    </Button>
                    <CopyButton text={s.vietqr.copy_text} />
                  </div>
                )}
                {s.vietqr_placeholder && (
                  <p className="text-xs text-muted-foreground mt-1">
                    Chuyển cho {s.vietqr_placeholder.payee} — nội dung: {s.vietqr_placeholder.note}
                  </p>
                )}
              </div>
            );
          })}
        </CardContent>
      </Card>
      <p className="text-xs text-muted-foreground mt-3">
        Quán đang chuẩn bị đơn. Người nhận hàng chuẩn bị tổng {vnd(total)} nếu cả nhóm trả tiền mặt.
      </p>
    </div>
  );
}

function CopyButton(props: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <Button
      variant="outline"
      className="min-h-11 rounded-full"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(props.text);
          setDone(true);
        } catch {
          window.prompt("Copy nội dung này:", props.text);
        }
      }}
    >
      {done ? "✓ Đã copy" : "📋 Copy số TK + số tiền"}
    </Button>
  );
}
