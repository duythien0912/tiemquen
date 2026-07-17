/* A2UI (cached compose output, ENGINE-SPEC §1) → OpenUI Lang ElementNode tree.
 *
 * The server keeps streaming the SAME pre-composed A2UI JSON it always has
 * (golden rule: zero LLM on the buyer path). This adapter walks the flat
 * component list (root = "root", children linked by childId /
 * childIds.explicitList / childIds.dataBinding), resolves every data-model
 * leaf to a concrete value, and emits the ElementNode tree that
 * `jsonToOpenUI(...)` serializes into openui-lang source for <Renderer>.
 */

export interface A2UIMessage {
  createSurface?: { surfaceId: string };
  updateComponents?: { surfaceId: string; root?: string; components: A2UIComponent[] };
  updateDataModel?: { surfaceId: string; path: string; value: unknown };
  deleteSurface?: { surfaceId: string };
}

export interface A2UIComponent {
  id: string;
  component: string;
  childId?: string;
  childIds?: { explicitList?: string[]; dataBinding?: string };
  [prop: string]: unknown;
}

export interface ElementNode {
  type: "element";
  statementId?: string;
  typeName: string;
  props: Record<string, unknown>;
  partial: boolean;
}

export interface Surface {
  root: string;
  components: Map<string, A2UIComponent>;
  dataModel: Record<string, unknown>;
}

const ptr = (path: string) => (path || "").split("/").filter(Boolean);

export function getPath(obj: unknown, path: string): unknown {
  let cur: any = obj;
  for (const part of ptr(path)) {
    if (cur == null) return undefined;
    cur = cur[part];
  }
  return cur;
}

function setPath(obj: Record<string, unknown>, path: string, value: unknown): void {
  const parts = ptr(path);
  let cur: any = obj;
  for (let i = 0; i < parts.length - 1; i++) {
    if (typeof cur[parts[i]] !== "object" || cur[parts[i]] === null) cur[parts[i]] = {};
    cur = cur[parts[i]];
  }
  if (parts.length) cur[parts[parts.length - 1]] = value;
}

export function ingest(messages: A2UIMessage[], surfaceId = "shop_menu"): Surface {
  const s: Surface = { root: "root", components: new Map(), dataModel: {} };
  for (const msg of messages || []) {
    if (msg.updateComponents && msg.updateComponents.surfaceId === surfaceId) {
      s.root = msg.updateComponents.root || "root";
      for (const c of msg.updateComponents.components || []) s.components.set(c.id, c);
    } else if (msg.updateDataModel && msg.updateDataModel.surfaceId === surfaceId) {
      setPath(s.dataModel, msg.updateDataModel.path, msg.updateDataModel.value);
    }
  }
  return s;
}

/** Resolve one A2UI leaf ({path|literalString|literalNumber|literalBoolean}). */
function leaf(v: unknown, dm: Record<string, unknown>): unknown {
  if (v == null || typeof v !== "object") return v;
  const o = v as Record<string, unknown>;
  if ("path" in o) return getPath(dm, String(o.path));
  if ("literalString" in o) return o.literalString;
  if ("literalNumber" in o) return o.literalNumber;
  if ("literalBoolean" in o) return o.literalBoolean;
  return undefined;
}

/** Resolve an event leaf's context (e.g. {dishId:{path:...}}) to plain values. */
function eventContext(v: unknown, dm: Record<string, unknown>): Record<string, unknown> {
  const ev = (v as any)?.event;
  const out: Record<string, unknown> = {};
  if (ev?.context) for (const k of Object.keys(ev.context)) out[k] = leaf(ev.context[k], dm);
  return out;
}

function childIdsOf(c: A2UIComponent, dm: Record<string, unknown>): string[] {
  if (typeof c.childId === "string") return [c.childId];
  if (c.childIds?.explicitList) return c.childIds.explicitList;
  if (c.childIds?.dataBinding) {
    const v = getPath(dm, c.childIds.dataBinding);
    return Array.isArray(v) ? (v as string[]) : [];
  }
  return [];
}

const el = (typeName: string, props: Record<string, unknown>, statementId?: string): ElementNode => ({
  type: "element",
  typeName,
  props: Object.fromEntries(Object.entries(props).filter(([, v]) => v !== undefined)),
  partial: false,
  ...(statementId ? { statementId } : {}),
});

/** Per-component prop extraction: A2UI leaves → concrete openui props. */
function convertComponent(c: A2UIComponent, s: Surface): ElementNode | null {
  const dm = s.dataModel;
  const kids = () =>
    childIdsOf(c, dm)
      .map((id) => {
        const child = s.components.get(id);
        return child ? convertComponent(child, s) : null;
      })
      .filter(Boolean) as ElementNode[];

  switch (c.component) {
    case "Page":
      return el("Page", { children: kids() }, c.id);
    case "MenuSection":
      return el(
        "MenuSection",
        { title: leaf(c.title, dm) ?? "", subtitle: leaf(c.subtitle, dm), children: kids() },
        c.id,
      );
    case "HeroHeader":
      return el(
        "HeroHeader",
        {
          shopName: leaf(c.shopName, dm) ?? "",
          tagline: leaf(c.tagline, dm),
          hours: leaf(c.hours, dm),
          image: leaf(c.image, dm),
        },
        c.id,
      );
    case "Badge":
      return el("Badge", { text: leaf(c.text, dm) ?? "", kind: leaf(c.kind, dm) }, c.id);
    case "DishCard":
    case "ComboCard": {
      const ctx = eventContext(c.onPress, dm);
      const dishId = String(ctx.dishId ?? c.id);
      return el(
        c.component,
        {
          dishId,
          name: leaf(c.name, dm) ?? "",
          note: leaf(c.note, dm),
          price: Number(leaf(c.price, dm) ?? 0),
          comparePrice: leaf(c.comparePrice, dm),
          image: leaf(c.image, dm),
          soldOut: Boolean(leaf(c.soldOut, dm)),
          almostOut: Boolean(leaf(c.almostOut, dm)),
        },
        c.id,
      );
    }
    case "ReorderCard":
      return el(
        "ReorderCard",
        { summary: leaf(c.summary, dm) ?? "", total: leaf(c.total, dm) },
        c.id,
      );
    case "CartBar":
      return el("CartBar", { label: leaf(c.label, dm) }, c.id);
    case "GroupOrderButton":
      return el("GroupOrderButton", { label: leaf(c.label, dm) }, c.id);
    case "ReviewStrip":
      return el(
        "ReviewStrip",
        { rating: leaf(c.rating, dm), count: leaf(c.count, dm), quote: leaf(c.quote, dm) },
        c.id,
      );
    case "CheckoutForm":
      return el(
        "CheckoutForm",
        {
          title: leaf(c.title, dm),
          nameLabel: leaf(c.nameLabel, dm),
          phoneLabel: leaf(c.phoneLabel, dm),
          addressLabel: leaf(c.addressLabel, dm),
          noteLabel: leaf(c.noteLabel, dm),
        },
        c.id,
      );
    case "PaymentPicker":
      return el(
        "PaymentPicker",
        {
          codLabel: leaf(c.codLabel, dm),
          vietqrLabel: leaf(c.vietqrLabel, dm),
          vietqrEnabled: Boolean(leaf(c.vietqrEnabled, dm)),
        },
        c.id,
      );
    case "OrderStatus":
      return null; // client-injected in the old renderer; React recap owns this now
    default:
      return null; // outside catalog — pre-validated cache shouldn't hit this
  }
}

export function toElementTree(s: Surface): ElementNode | null {
  const root = s.components.get(s.root);
  if (!root) return null;
  return convertComponent(root, s);
}

/** Theme block from the data model (compose derives it from seed colors). */
export function themeOf(s: Surface): Record<string, string> {
  const t = getPath(s.dataModel, "/theme");
  return t && typeof t === "object" ? (t as Record<string, string>) : {};
}

/** Fresh sold-out flags (same zero-recompose patch contract as before). */
export function pricesOf(s: Surface): Record<string, number> {
  return (getPath(s.dataModel, "/prices") as Record<string, number>) || {};
}
