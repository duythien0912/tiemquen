/* Tiệm Quen buyer order flow (ENGINE-SPEC §8, ARCH §3.2) — cart state,
 * COD checkout, order-status polling. ZERO LLM on this path: this file only
 * ever talks to plain REST endpoints (/orders, /orders/{id}/status).
 */
(function (global) {
  "use strict";

  var SURFACE_ID = "shop_menu";
  var POLL_INTERVAL_MS = 3000;
  var TERMINAL_STATUSES = ["done", "cancelled", "no_show_flagged"];

  function cartKey(slug) {
    return "tq_cart_" + slug;
  }

  function TQOrder(opts) {
    this.renderer = opts.renderer;
    this.apiBase = opts.apiBase || "";
    this.slug = opts.slug;
    this.context = opts.context; // {batchId, batchKind, daypart, variant}
    this.cart = {}; // dish_id -> qty
    this._pollTimer = null;

    var self = this;
    this.renderer.onEvent(function (name, ctx, componentId) {
      self._onEvent(name, ctx, componentId);
    });
  }

  TQOrder.prototype._onEvent = function (name, ctx) {
    if (name === "add_to_cart") this.addToCart(ctx.dishId, 1);
    else if (name === "open_checkout") this.scrollToCheckout();
    else if (name === "submit_order") this.submitOrder(ctx.customer || {});
    else if (name === "reorder") this.applyReorder();
    else if (name === "start_group_order") this.startGroupOrder();
    // unknown events are ignored — renderer already validated the catalog
  };

  // --------------------------------------------------------------------- cart

  TQOrder.prototype.addToCart = function (dishId, delta) {
    if (!dishId) return;
    var soldOut = this.renderer.getData(SURFACE_ID, "/soldout/" + dishId);
    if (soldOut) return;
    this.cart[dishId] = Math.max(0, (this.cart[dishId] || 0) + delta);
    if (this.cart[dishId] === 0) delete this.cart[dishId];
    this._syncCartData();
    this.renderer.render(SURFACE_ID);
  };

  TQOrder.prototype._cartItems = function () {
    var self = this;
    return Object.keys(this.cart).map(function (dishId) {
      var price = self.renderer.getData(SURFACE_ID, "/prices/" + dishId) || 0;
      return { dish_id: dishId, qty: self.cart[dishId], price: price };
    });
  };

  TQOrder.prototype._syncCartData = function () {
    var items = this._cartItems();
    var total = items.reduce(function (sum, it) { return sum + it.price * it.qty; }, 0);
    var count = items.reduce(function (sum, it) { return sum + it.qty; }, 0);
    this.renderer.setData(SURFACE_ID, "/cart/total", total);
    this.renderer.setData(SURFACE_ID, "/cart/count", count);
  };

  TQOrder.prototype.scrollToCheckout = function () {
    var form = document.getElementById("tq-checkout-form");
    if (form) form.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  // ---------------------------------------------------------------- checkout

  TQOrder.prototype.submitOrder = function (customer) {
    var items = this._cartItems();
    if (!items.length) {
      window.alert("Giỏ hàng trống — chọn món trước khi đặt.");
      return;
    }
    if (!customer.name || !customer.phone || !customer.address) {
      window.alert("Cần đủ tên, số điện thoại và địa chỉ để quán giao hàng.");
      return;
    }
    var self = this;
    var body = {
      slug: this.slug,
      batch_id: this.context.batchId,
      variant: this.context.variant,
      items: items.map(function (it) { return { dish_id: it.dish_id, qty: it.qty }; }),
      customer: customer,
      payment_method: "cod",
    };
    return fetch(this.apiBase + "/orders", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then(function (r) {
        if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || "đặt hàng lỗi"); });
        return r.json();
      })
      .then(function (order) {
        global.TQContextRules.saveLastOrder(self.slug, order);
        self.cart = {};
        self._syncCartData();
        self._showOrderStatus(order);
        self.startPolling(order.id);
        return order;
      })
      .catch(function (err) {
        window.alert(String(err.message || err));
      });
  };

  TQOrder.prototype._showOrderStatus = function (order) {
    this.renderer.setData(SURFACE_ID, "/order/status", order.status);
    this.renderer.setData(SURFACE_ID, "/order/message", "Đơn đã gửi tới quán, đang chờ xác nhận");
    if (!this.renderer.hasComponent(SURFACE_ID, "order_status")) {
      this.renderer.addComponent(SURFACE_ID, {
        id: "order_status",
        component: "OrderStatus",
        status: { path: "/order/status" },
        message: { path: "/order/message" },
      });
      this.renderer.prependChild(SURFACE_ID, "root", "order_status");
    }
    this.renderer.render(SURFACE_ID);
    var box = document.querySelector(".tq-order-status");
    if (box) box.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  // ------------------------------------------------------------------ polling

  TQOrder.prototype.startPolling = function (orderId) {
    var self = this;
    if (this._pollTimer) clearInterval(this._pollTimer);
    this._pollTimer = setInterval(function () {
      fetch(self.apiBase + "/orders/" + orderId + "/status")
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (body) {
          if (!body) return;
          self.renderer.setData(SURFACE_ID, "/order/status", body.status);
          self.renderer.setData(SURFACE_ID, "/order/message", body.message);
          self.renderer.render(SURFACE_ID);
          if (TERMINAL_STATUSES.indexOf(body.status) !== -1) clearInterval(self._pollTimer);
        })
        .catch(function () {}); // transient network blip — next tick retries
    }, POLL_INTERVAL_MS);
  };

  // ------------------------------------------------------------------ reorder

  TQOrder.prototype.applyReorder = function () {
    var last = global.TQContextRules.loadLastOrder(this.slug);
    if (!last) return;
    var self = this;
    last.items.forEach(function (it) {
      self.cart[it.dish_id] = (self.cart[it.dish_id] || 0) + it.qty;
    });
    this._syncCartData();
    this.renderer.render(SURFACE_ID);
    this.scrollToCheckout();
  };

  // -------------------------------------------------------------- group order

  TQOrder.prototype.startGroupOrder = function () {
    var self = this;
    fetch(this.apiBase + "/group-orders", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slug: this.slug, batch_id: this.context.batchId }),
    })
      .then(function (r) { return r.json(); })
      .then(function (body) {
        var url = self.apiBase + "/g/" + body.gid;
        window.prompt("Chia sẻ link này vào group Zalo để mọi người cùng order:", url);
      })
      .catch(function () {
        window.alert("Không tạo được đơn nhóm, thử lại sau.");
      });
  };

  global.TQOrder = TQOrder;
})(window);
