/* Buyer cart + order state — port of buyer/order.js semantics:
 * localStorage-persisted cart, double-submit guard, recap + resume,
 * status polling, group-order share. ZERO LLM — plain REST only. */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { apiGet, apiPost, TERMINAL_STATUSES, type OrderDoc, type ShopPublic } from "@/lib/api";

const POLL_MS = 3000;
const RESUME_WINDOW_MS = 2 * 3600 * 1000;

const cartKey = (slug: string) => `tq_cart_${slug}`;
const lastOrderKey = (slug: string) => `tq_last_order_${slug}`;

export interface LastOrder {
  id: string;
  items: OrderDoc["items"];
  total: number;
  at: string;
}

export function loadLastOrder(slug: string): LastOrder | null {
  try {
    const raw = localStorage.getItem(lastOrderKey(slug));
    return raw ? (JSON.parse(raw) as LastOrder) : null;
  } catch {
    return null;
  }
}

function saveLastOrder(slug: string, order: OrderDoc): void {
  try {
    localStorage.setItem(
      lastOrderKey(slug),
      JSON.stringify({ id: order.id, items: order.items, total: order.total, at: new Date().toISOString() }),
    );
  } catch {
    /* private mode */
  }
}

export interface BuyerContextValue {
  slug: string;
  shop: ShopPublic;
  batchId: string;
  variant: string | null;
  cart: Record<string, number>;
  prices: Record<string, number>;
  soldout: Record<string, boolean>;
  almostout: Record<string, boolean>;
  cartCount: number;
  cartTotal: number;
  add: (dishId: string) => void;
  remove: (dishId: string) => void;
  applyReorder: () => void;
  submitting: boolean;
  submitOrder: (customer: { name: string; phone: string; address: string; note?: string }) => Promise<void>;
  activeOrder: LastOrder | null;
  liveStatus: string | null;
  orderMore: () => void;
  startGroupOrder: () => Promise<void>;
  formError: string | null;
}

const Ctx = createContext<BuyerContextValue | null>(null);

export function useBuyer(): BuyerContextValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useBuyer outside provider");
  return v;
}

export function BuyerProvider(props: {
  slug: string;
  shop: ShopPublic;
  batchId: string;
  variant: string | null;
  prices: Record<string, number>;
  children: ReactNode;
}) {
  const { slug, shop, batchId, variant } = props;
  const [cart, setCart] = useState<Record<string, number>>(() => {
    try {
      const raw = localStorage.getItem(cartKey(slug));
      const parsed = raw ? JSON.parse(raw) : {};
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch {
      return {};
    }
  });
  const [soldout, setSoldout] = useState<Record<string, boolean>>({});
  const [almostout, setAlmostout] = useState<Record<string, boolean>>({});
  const [livePrices, setLivePrices] = useState<Record<string, number>>(props.prices);
  const [submitting, setSubmitting] = useState(false);
  const [activeOrder, setActiveOrder] = useState<LastOrder | null>(null);
  const [liveStatus, setLiveStatus] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    try {
      localStorage.setItem(cartKey(slug), JSON.stringify(cart));
    } catch {
      /* private mode — cart just won't survive a reload */
    }
  }, [cart, slug]);

  // Fresh sold-out/almost-out/price patch — never blocks first paint.
  useEffect(() => {
    apiGet<{ menu: { dishes: Record<string, any> } }>(`/api/shops/${encodeURIComponent(slug)}/menu`)
      .then((body) => {
        const so: Record<string, boolean> = {};
        const ao: Record<string, boolean> = {};
        const pr: Record<string, number> = {};
        for (const [id, d] of Object.entries(body.menu.dishes)) {
          so[id] = !!d.sold_out;
          ao[id] = !!d.almost_out;
          pr[id] = d.price;
        }
        setSoldout(so);
        setAlmostout(ao);
        setLivePrices((old) => ({ ...old, ...pr }));
      })
      .catch(() => {});
  }, [slug]);

  const stopPolling = useCallback(() => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = null;
  }, []);

  const startPolling = useCallback(
    (orderId: string) => {
      stopPolling();
      pollRef.current = setInterval(() => {
        apiGet<{ status: string; message: string }>(`/orders/${orderId}/status`)
          .then((body) => {
            setLiveStatus(body.message || body.status);
            if (TERMINAL_STATUSES.includes(body.status)) stopPolling();
          })
          .catch(() => {}); // transient blip — next tick retries
      }, POLL_MS);
    },
    [stopPolling],
  );

  // Resume an active order (<2h, non-terminal) on load — recap instead of menu.
  useEffect(() => {
    const last = loadLastOrder(slug);
    if (!last?.id || !last.at) return;
    if (Date.now() - new Date(last.at).getTime() > RESUME_WINDOW_MS) return;
    apiGet<{ status: string; message: string }>(`/orders/${last.id}/status`)
      .then((body) => {
        if (TERMINAL_STATUSES.includes(body.status)) return;
        setActiveOrder(last);
        setLiveStatus(body.message || body.status);
        startPolling(last.id);
      })
      .catch(() => {});
    return stopPolling;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug]);

  const add = useCallback(
    (dishId: string) => {
      if (soldout[dishId]) return;
      setCart((c) => ({ ...c, [dishId]: (c[dishId] || 0) + 1 }));
    },
    [soldout],
  );
  const remove = useCallback((dishId: string) => {
    setCart((c) => {
      const next = { ...c, [dishId]: Math.max(0, (c[dishId] || 0) - 1) };
      if (!next[dishId]) delete next[dishId];
      return next;
    });
  }, []);

  const applyReorder = useCallback(() => {
    const last = loadLastOrder(slug);
    if (!last) return;
    setCart((c) => {
      const next = { ...c };
      for (const it of last.items) next[it.dish_id] = (next[it.dish_id] || 0) + it.qty;
      return next;
    });
    document.getElementById("tq-checkout-form")?.scrollIntoView({ behavior: "smooth" });
  }, [slug]);

  const { cartCount, cartTotal } = useMemo(() => {
    let count = 0;
    let total = 0;
    for (const [id, qty] of Object.entries(cart)) {
      count += qty;
      total += qty * (livePrices[id] || 0);
    }
    return { cartCount: count, cartTotal: total };
  }, [cart, livePrices]);

  const submitOrder = useCallback(
    async (customer: { name: string; phone: string; address: string; note?: string }) => {
      setFormError(null);
      const items = Object.entries(cart).map(([dish_id, qty]) => ({ dish_id, qty }));
      if (!items.length) {
        setFormError("Giỏ hàng trống — chọn món trước khi đặt.");
        return;
      }
      if (!customer.name || !customer.phone || !customer.address) {
        setFormError("Cần đủ tên, số điện thoại và địa chỉ để quán giao hàng.");
        return;
      }
      if (submitting) return; // chống double-tap -> đơn trùng
      setSubmitting(true);
      try {
        const order = await apiPost<OrderDoc>("/orders", {
          slug,
          batch_id: batchId,
          variant,
          items,
          customer,
          payment_method: "cod",
        });
        saveLastOrder(slug, order);
        setCart({});
        setActiveOrder({ id: order.id, items: order.items, total: order.total, at: new Date().toISOString() });
        setLiveStatus("Đơn đã gửi tới quán, đang chờ xác nhận…");
        startPolling(order.id);
        window.scrollTo({ top: 0 });
      } catch (e) {
        setFormError(String((e as Error).message || e));
      } finally {
        setSubmitting(false);
      }
    },
    [cart, slug, batchId, variant, submitting, startPolling],
  );

  const orderMore = useCallback(() => {
    stopPolling();
    setActiveOrder(null);
    setLiveStatus(null);
    window.scrollTo({ top: 0 });
  }, [stopPolling]);

  const startGroupOrder = useCallback(async () => {
    try {
      const body = await apiPost<{ gid: string }>("/group-orders", { slug, batch_id: batchId });
      const url = `${location.origin}/g/${body.gid}`;
      const text = `Gom đơn ${shop.name || "cả phòng"} — vô chọn món: ${url}`;
      const go = () => {
        window.location.href = url;
      };
      if (navigator.share) {
        navigator
          .share({ title: "Tiệm Quen — đơn nhóm", text, url })
          .catch(async () => copyLink(url))
          .then(go, go);
      } else {
        await copyLink(url);
        go();
      }
    } catch {
      window.alert("Không tạo được đơn nhóm, thử lại sau.");
    }
  }, [slug, batchId, shop.name]);

  const value: BuyerContextValue = {
    slug,
    shop,
    batchId,
    variant,
    cart,
    prices: livePrices,
    soldout,
    almostout,
    cartCount,
    cartTotal,
    add,
    remove,
    applyReorder,
    submitting,
    submitOrder,
    activeOrder,
    liveStatus,
    orderMore,
    startGroupOrder,
    formError,
  };
  return <Ctx.Provider value={value}>{props.children}</Ctx.Provider>;
}

async function copyLink(url: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(url);
    window.alert(`Đã copy link đơn nhóm — dán vào group Zalo:\n${url}`);
  } catch {
    window.prompt("Copy link này gửi group Zalo:", url);
  }
}
