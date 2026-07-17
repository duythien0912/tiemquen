/* Plain REST helpers — ZERO LLM on the buyer path (ENGINE-SPEC §0/§8):
 * these only ever hit the pre-composed cache + order endpoints. */

export function vnd(n: number | null | undefined): string {
  return (typeof n === "number" ? n : 0).toLocaleString("vi-VN") + "đ";
}

export async function apiGet<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(await errDetail(r));
  return r.json();
}

export async function apiPost<T>(url: string, body?: unknown): Promise<T> {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await errDetail(r));
  return r.json();
}

async function errDetail(r: Response): Promise<string> {
  try {
    const b = await r.json();
    return typeof b.detail === "string" ? b.detail : JSON.stringify(b.detail ?? b);
  } catch {
    return `HTTP ${r.status}`;
  }
}

export interface ShopPublic {
  name?: string;
  phone?: string;
  hours?: string;
}

export interface OrderDoc {
  id: string;
  items: { dish_id: string; name: string; price: number; qty: number }[];
  total: number;
  status: string;
}

export const TERMINAL_STATUSES = ["done", "cancelled", "no_show_flagged"];
