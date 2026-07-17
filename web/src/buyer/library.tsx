/* OpenUI Lang component library for the buyer page — the client-side half of
 * the OpenUI contract: the server streams abstract structure (converted from
 * the pre-composed A2UI cache), THIS library decides how each node renders.
 * Every visual is a shadcn/ui primitive (Card, Button, Badge, Input, ...).
 */

import { defineComponent, createLibrary } from "@openuidev/react-lang";
import { z } from "zod";
import { useState, type FormEvent } from "react";
import { Badge as UIBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { vnd } from "@/lib/api";
import { useBuyer } from "./cart";

/* ----------------------------------------------------------- leaf pieces */

const BadgeC = defineComponent({
  name: "Badge",
  description: "Small status/info badge",
  props: z.object({
    text: z.string(),
    kind: z.enum(["info", "warn", "success", "discount"]).optional(),
  }),
  component: ({ props }) => (
    <UIBadge
      data-testid="badge"
      variant={props.kind === "warn" ? "destructive" : "secondary"}
      className="mx-4 my-1 bg-[var(--tq-success,theme(colors.emerald.100))]/15 text-[var(--tq-success,inherit)]"
    >
      {props.text}
    </UIBadge>
  ),
});

const HeroHeader = defineComponent({
  name: "HeroHeader",
  description: "Shop hero header: name, tagline, hours",
  props: z.object({
    shopName: z.string(),
    tagline: z.string().optional(),
    hours: z.string().optional(),
    image: z.string().optional(),
  }),
  component: ({ props }) => (
    <header
      data-testid="hero"
      className="px-4 pb-4 pt-7 bg-cover bg-center"
      style={props.image ? { backgroundImage: `url(${props.image})` } : undefined}
    >
      <h1 className="text-2xl font-bold">{props.shopName}</h1>
      {props.tagline && <p className="text-muted-foreground text-sm mt-1">{props.tagline}</p>}
      {props.hours && <p className="text-muted-foreground text-sm mt-0.5">⏰ {props.hours}</p>}
    </header>
  ),
});

const ReviewStrip = defineComponent({
  name: "ReviewStrip",
  description: "Social proof strip: rating, order count, quote",
  props: z.object({
    rating: z.union([z.number(), z.string()]).optional(),
    count: z.union([z.number(), z.string()]).optional(),
    quote: z.string().optional(),
  }),
  component: ({ props }) => (
    <div data-testid="reviews" className="px-4 py-1.5 text-sm text-muted-foreground">
      {props.rating != null && <strong>⭐ {props.rating}</strong>}
      {props.count != null && <span> ({props.count} đơn)</span>}
      {props.quote && <p className="italic mt-1">“{props.quote}”</p>}
    </div>
  ),
});

/* --------------------------------------------------------------- dishes */

function DishBody(props: {
  dishId: string;
  name: string;
  note?: string;
  price: number;
  comparePrice?: number;
  soldOut: boolean;
  almostOut: boolean;
}) {
  const { cart, soldout, almostout, add, remove } = useBuyer();
  const soldOut = soldout[props.dishId] ?? props.soldOut;
  const almostOut = almostout[props.dishId] ?? props.almostOut;
  const qty = cart[props.dishId] || 0;

  return (
    <Card data-testid="dish-card" data-dish-id={props.dishId} className={soldOut ? "opacity-50" : ""}>
      <CardContent className="flex items-center gap-3 p-3">
        <div className="flex-1 min-w-0">
          <h3 className="font-semibold leading-tight">{props.name}</h3>
          {props.note && <p className="text-xs text-muted-foreground mt-0.5">{props.note}</p>}
          <div className="flex items-baseline gap-2 mt-1">
            <span className="font-bold text-primary">{vnd(props.price)}</span>
            {props.comparePrice ? (
              <span className="text-xs text-muted-foreground line-through">{vnd(props.comparePrice)}</span>
            ) : null}
          </div>
          {almostOut && !soldOut && (
            <UIBadge variant="destructive" className="mt-1">
              Sắp hết
            </UIBadge>
          )}
        </div>
        {soldOut ? (
          <Button data-testid="add-btn" disabled className="min-h-11 rounded-full">
            Hết món
          </Button>
        ) : qty === 0 ? (
          <Button
            data-testid="add-btn"
            className="min-h-11 rounded-full px-5"
            onClick={() => add(props.dishId)}
          >
            Thêm
          </Button>
        ) : (
          <div data-testid="stepper" className="flex items-center gap-1">
            <Button
              size="icon"
              aria-label="Bớt 1"
              className="size-11 rounded-full text-lg"
              onClick={() => remove(props.dishId)}
            >
              −
            </Button>
            <span data-testid="qty" className="min-w-7 text-center font-bold">
              {qty}
            </span>
            <Button
              size="icon"
              aria-label="Thêm 1"
              className="size-11 rounded-full text-lg"
              onClick={() => add(props.dishId)}
            >
              +
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// NOTE: mỗi defineComponent cần một Zod object RIÊNG — react-lang tag id vào
// schema instance (tagSchemaId), share chung là component sau đè component trước.
const dishProps = () =>
  z.object({
    dishId: z.string(),
    name: z.string(),
    note: z.string().optional(),
    price: z.number(),
    comparePrice: z.number().optional(),
    image: z.string().optional(),
    soldOut: z.boolean().optional(),
    almostOut: z.boolean().optional(),
  });

const DishCard = defineComponent({
  name: "DishCard",
  description: "One orderable dish with price + add-to-cart stepper",
  props: dishProps(),
  component: ({ props }) => (
    <DishBody {...props} soldOut={!!props.soldOut} almostOut={!!props.almostOut} />
  ),
});

const ComboCard = defineComponent({
  name: "ComboCard",
  description: "Combo dish (same shape as DishCard, compare-price emphasis)",
  props: dishProps(),
  component: ({ props }) => (
    <DishBody {...props} soldOut={!!props.soldOut} almostOut={!!props.almostOut} />
  ),
});

const ReorderCard = defineComponent({
  name: "ReorderCard",
  description: "Returning-customer one-tap reorder of the last order",
  props: z.object({ summary: z.string(), total: z.number().optional() }),
  component: ({ props }) => {
    const { applyReorder } = useBuyer();
    return (
      <Card data-testid="reorder" className="mx-4 my-2 border-primary/40">
        <CardContent className="flex items-center gap-3 p-3">
          <div className="flex-1">
            <p className="text-sm">{props.summary}</p>
            {props.total != null && <span className="font-bold text-primary">{vnd(props.total)}</span>}
          </div>
          <Button className="min-h-11 rounded-full" onClick={applyReorder}>
            Đặt lại như hôm qua
          </Button>
        </CardContent>
      </Card>
    );
  },
});

/* --------------------------------------------------------------- layout */

const MenuSection = defineComponent({
  name: "MenuSection",
  description: "Menu section with title and dish cards",
  props: z.object({
    title: z.string(),
    subtitle: z.string().optional(),
    children: z.array(z.union([DishCard.ref, ComboCard.ref, BadgeC.ref])),
  }),
  component: ({ props, renderNode }) => (
    <section data-testid="section" className="px-4 pt-2">
      <h2 className="text-lg font-bold mt-3 mb-2">{props.title}</h2>
      {props.subtitle && <p className="text-sm text-muted-foreground mb-2">{props.subtitle}</p>}
      <div className="grid gap-2.5">{renderNode(props.children)}</div>
    </section>
  ),
});

const GroupOrderButton = defineComponent({
  name: "GroupOrderButton",
  description: "Start a shared office group order",
  props: z.object({ label: z.string().optional() }),
  component: ({ props }) => {
    const { startGroupOrder } = useBuyer();
    return (
      <Button
        data-testid="group-btn"
        className="mx-4 my-2.5 block w-[calc(100%-2rem)] min-h-11 rounded-full"
        onClick={() => void startGroupOrder()}
      >
        {props.label || "Gom đơn cả phòng"}
      </Button>
    );
  },
});

const PaymentPicker = defineComponent({
  name: "PaymentPicker",
  description: "Payment options display (COD default, VietQR when unlocked)",
  props: z.object({
    codLabel: z.string().optional(),
    vietqrLabel: z.string().optional(),
    vietqrEnabled: z.boolean().optional(),
  }),
  component: ({ props }) => (
    <div data-testid="payment" className="flex gap-2.5 px-4 flex-wrap">
      <UIBadge variant="outline" className="border-primary text-primary py-1.5 px-3">
        💰 {props.codLabel || "Trả khi nhận"}
      </UIBadge>
      {props.vietqrEnabled && (
        <UIBadge variant="outline" className="py-1.5 px-3">
          🆔 {props.vietqrLabel || "VietQR"}
        </UIBadge>
      )}
    </div>
  ),
});

/* -------------------------------------------------------------- checkout */

function CheckoutFormBody(props: {
  title?: string;
  nameLabel?: string;
  phoneLabel?: string;
  addressLabel?: string;
  noteLabel?: string;
}) {
  const { cartCount, submitOrder, submitting, formError } = useBuyer();
  const [values, setValues] = useState({ name: "", phone: "", address: "", note: "" });
  if (!cartCount) return null; // giỏ trống -> giấu form

  const onSubmit = (ev: FormEvent) => {
    ev.preventDefault();
    void submitOrder(values);
  };
  const field = (key: keyof typeof values, label: string, type = "text", required = true) => (
    <div className="grid gap-1.5">
      <Label htmlFor={`f-${key}`}>{label}</Label>
      {key === "note" ? (
        <Textarea
          id={`f-${key}`}
          value={values[key]}
          onChange={(e) => setValues((v) => ({ ...v, [key]: e.target.value }))}
        />
      ) : (
        <Input
          id={`f-${key}`}
          type={type}
          required={required}
          inputMode={type === "tel" ? "tel" : undefined}
          pattern={type === "tel" ? "(0|\\+84)[0-9\\s.]{8,12}" : undefined}
          title={type === "tel" ? "Số điện thoại VN, ví dụ 0909123456" : undefined}
          value={values[key]}
          onChange={(e) => setValues((v) => ({ ...v, [key]: e.target.value }))}
        />
      )}
    </div>
  );

  return (
    <Card id="tq-checkout-form" data-testid="checkout" className="m-4">
      <CardContent className="p-4">
        <form onSubmit={onSubmit} className="grid gap-3">
          <h2 className="text-lg font-bold">{props.title || "Đặt món"}</h2>
          {field("name", props.nameLabel || "Tên của bạn")}
          {field("phone", props.phoneLabel || "Số điện thoại", "tel")}
          {field("address", props.addressLabel || "Địa chỉ / toà nhà")}
          {field("note", props.noteLabel || "Ghi chú cho quán", "text", false)}
          {formError && (
            <p data-testid="form-error" className="text-sm text-destructive">
              {formError}
            </p>
          )}
          <Button type="submit" data-testid="submit-btn" disabled={submitting} className="min-h-12 rounded-full">
            {submitting ? "Đang gửi đơn…" : "Xác nhận đặt món (COD)"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

const CheckoutForm = defineComponent({
  name: "CheckoutForm",
  description: "COD checkout form (name/phone/address/note)",
  props: z.object({
    title: z.string().optional(),
    nameLabel: z.string().optional(),
    phoneLabel: z.string().optional(),
    addressLabel: z.string().optional(),
    noteLabel: z.string().optional(),
  }),
  component: ({ props }) => <CheckoutFormBody {...props} />,
});

const CartBar = defineComponent({
  name: "CartBar",
  description: "Fixed bottom cart bar with count/total/checkout CTA",
  props: z.object({ label: z.string().optional() }),
  component: ({ props }) => {
    const { cartCount, cartTotal } = useBuyer();
    if (!cartCount) return null;
    return (
      <div
        data-testid="cartbar"
        className="fixed bottom-0 inset-x-0 z-10 flex items-center gap-3 px-4 py-3 bg-foreground text-background"
      >
        <span className="flex-1 text-sm opacity-85">{cartCount} món</span>
        <span data-testid="cart-total" className="font-bold">
          {vnd(cartTotal)}
        </span>
        <Button
          variant="secondary"
          className="min-h-11 rounded-full"
          onClick={() => document.getElementById("tq-checkout-form")?.scrollIntoView({ behavior: "smooth" })}
        >
          {props.label || "Đặt món"}
        </Button>
      </div>
    );
  },
});

const Page = defineComponent({
  name: "Page",
  description: "Buyer page root",
  props: z.object({
    children: z.array(
      z.union([
        HeroHeader.ref,
        BadgeC.ref,
        ReviewStrip.ref,
        MenuSection.ref,
        ReorderCard.ref,
        GroupOrderButton.ref,
        PaymentPicker.ref,
        CheckoutForm.ref,
        CartBar.ref,
      ]),
    ),
  }),
  component: ({ props, renderNode }) => (
    <div data-testid="page" className="max-w-2xl mx-auto pb-28">
      {renderNode(props.children)}
      <Separator className="my-4 opacity-0" />
    </div>
  ),
});

export const buyerLibrary = createLibrary({
  components: [
    Page,
    HeroHeader,
    BadgeC,
    ReviewStrip,
    MenuSection,
    DishCard,
    ComboCard,
    ReorderCard,
    GroupOrderButton,
    PaymentPicker,
    CheckoutForm,
    CartBar,
  ],
  root: "Page",
});
