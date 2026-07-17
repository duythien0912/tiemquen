/* Buyer app — loads the pre-composed variant (context rules pick WHICH one,
 * same zero-LLM heuristics as before), converts A2UI → OpenUI Lang source,
 * renders through <Renderer> + the shadcn library. Recap/resume owns the
 * whole screen while an order is live. */

import { useEffect, useMemo, useState } from "react";
import { Renderer } from "@openuidev/react-lang";
import { jsonToOpenUI } from "@openuidev/lang-core";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { apiGet, vnd, type ShopPublic } from "@/lib/api";
import { ingest, toElementTree, themeOf, pricesOf, type A2UIMessage, type ElementNode } from "@/lib/a2ui";
import { applyShopTheme } from "@/lib/theme";
import { BuyerProvider, loadLastOrder, useBuyer } from "./cart";
import { buyerLibrary } from "./library";

const LUNCH = [10, 13] as const;

function resolveContext() {
  const params = new URLSearchParams(location.search);
  const rawBatchId = params.get("b") || "direct";
  const folded = rawBatchId
    .toLowerCase()
    .replace(/đ/g, "d")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "");
  const batchKind = /office|van\s*-?\s*phong|vp\b/.test(folded) ? "office" : "table";
  const h = new Date().getHours();
  const daypart = h >= LUNCH[0] && h < LUNCH[1] ? "lunch" : "regular";
  return { batchId: rawBatchId, variant: `${batchKind}-${daypart}` };
}

interface Boot {
  slug?: string;
  shop?: ShopPublic;
}

async function loadVariant(slug: string, variant: string): Promise<A2UIMessage[]> {
  try {
    return await apiGet<A2UIMessage[]>(
      `/api/shops/${encodeURIComponent(slug)}/composed/${encodeURIComponent(variant)}`,
    );
  } catch (e) {
    if (variant !== "table-regular") return loadVariant(slug, "table-regular"); // safe fallback
    throw e;
  }
}

/** Prepend the returning-customer ReorderCard (client data — never composed). */
function withReorder(tree: ElementNode, slug: string): ElementNode {
  const last = loadLastOrder(slug);
  if (!last?.items?.length) return tree;
  const summary = last.items.map((it) => `${it.qty}x ${it.name}`).join(", ");
  const reorder: ElementNode = {
    type: "element",
    typeName: "ReorderCard",
    statementId: "reorder_card",
    props: { summary, total: last.total },
    partial: false,
  };
  const children = (tree.props.children as ElementNode[]) || [];
  return { ...tree, props: { ...tree.props, children: [children[0], reorder, ...children.slice(1)].filter(Boolean) } };
}

function OrderRecap() {
  const { activeOrder, liveStatus, shop, orderMore } = useBuyer();
  if (!activeOrder) return null;
  return (
    <div data-testid="recap" className="max-w-2xl mx-auto pb-10">
      <Card className="m-4 border-primary/40 bg-primary/10">
        <CardContent className="p-4 text-center font-semibold" data-testid="live-status">
          {liveStatus || "Đơn đã gửi tới quán, đang chờ xác nhận…"}
        </CardContent>
      </Card>
      <Card className="mx-4">
        <CardContent className="p-4">
          <h2 className="text-lg font-bold mb-2.5">Đơn #{activeOrder.id.slice(-6)}</h2>
          <ul>
            {activeOrder.items.map((it) => (
              <li key={it.dish_id} className="flex justify-between gap-3 py-1.5 border-b last:border-0">
                <span>
                  {it.qty}× {it.name}
                </span>
                <strong>{vnd(it.price * it.qty)}</strong>
              </li>
            ))}
          </ul>
          <p className="mt-3">
            Chuẩn bị <strong>{vnd(activeOrder.total)}</strong> tiền mặt khi nhận hàng (COD).
          </p>
          {shop.phone && (
            <Button asChild className="mt-3 w-full min-h-12 rounded-full">
              <a href={`tel:${shop.phone}`}>
                📞 Gọi quán {shop.name || ""} — {shop.phone}
              </a>
            </Button>
          )}
        </CardContent>
      </Card>
      <Button
        data-testid="order-more"
        variant="secondary"
        className="mx-4 mt-3 w-[calc(100%-2rem)] min-h-12 rounded-full"
        onClick={orderMore}
      >
        Đặt thêm món
      </Button>
    </div>
  );
}

function BuyerView(props: { source: string }) {
  const { activeOrder } = useBuyer();
  if (activeOrder) return <OrderRecap />;
  return (
    <Renderer
      response={props.source}
      library={buyerLibrary}
      isStreaming={false}
      onParseResult={(r) => {
        if (r?.meta?.errors?.length) console.warn("[openui] parse errors:", JSON.stringify(r.meta.errors));
      }}
    />
  );
}

export default function App() {
  const boot: Boot = (window as any).__TIEMQUEN__ || {};
  const qs = new URLSearchParams(location.search);
  const slug = boot.slug || qs.get("slug") || "";
  const ctx = useMemo(resolveContext, []);
  const [state, setState] = useState<{
    source: string;
    prices: Record<string, number>;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!slug) {
      setError("Thiếu mã tiệm (slug) — quét lại QR trên tờ rơi.");
      return;
    }
    loadVariant(slug, ctx.variant)
      .then((messages) => {
        const surface = ingest(messages);
        applyShopTheme(themeOf(surface));
        const tree = toElementTree(surface);
        if (!tree) throw new Error("menu chưa sẵn sàng");
        const source = jsonToOpenUI(withReorder(tree, slug), buyerLibrary);
        setState({ source, prices: pricesOf(surface) });
      })
      .catch((e) => setError(`Không tải được menu — thử lại sau (${(e as Error).message}).`));
  }, [slug, ctx.variant]);

  if (error)
    return (
      <p data-testid="page-error" className="p-10 text-center text-destructive">
        {error}
      </p>
    );
  if (!state)
    return (
      <div className="max-w-2xl mx-auto p-4 grid gap-3" data-testid="loading">
        <Skeleton className="h-24 rounded-xl" />
        <Skeleton className="h-16 rounded-xl" />
        <Skeleton className="h-16 rounded-xl" />
      </div>
    );

  return (
    <BuyerProvider
      slug={slug}
      shop={boot.shop || {}}
      batchId={ctx.batchId}
      variant={ctx.variant}
      prices={state.prices}
    >
      <BuyerView source={state.source} />
    </BuyerProvider>
  );
}
