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

  function vndSafe(n) {
    return (typeof n === "number" ? n : 0).toLocaleString("vi-VN") + "đ";
  }

  function TQOrder(opts) {
    this.renderer = opts.renderer;
    this.apiBase = opts.apiBase || "";
    this.slug = opts.slug;
    this.shop = opts.shop || {}; // {name, phone, hours} from the server bootstrap
    this.context = opts.context; // {batchId, batchKind, daypart, variant}
    this.cart = this._loadCart(); // dish_id -> qty (survives an accidental reload)
    this._pollTimer = null;
    this._submitting = false;
    this._recapActive = false; // màn recap đang chiếm container -> đừng render đè

    var self = this;
    this.renderer.onEvent(function (name, ctx, componentId) {
      self._onEvent(name, ctx, componentId);
    });
    this._syncCartData();
  }

  TQOrder.prototype._onEvent = function (name, ctx) {
    if (name === "add_to_cart") this.addToCart(ctx.dishId, 1);
    else if (name === "remove_from_cart") this.addToCart(ctx.dishId, -1);
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
    this.renderer.setData(SURFACE_ID, "/cart/qty", Object.assign({}, this.cart));
    this._saveCart();
  };

  TQOrder.prototype._loadCart = function () {
    try {
      var raw = localStorage.getItem(cartKey(this.slug));
      var cart = raw ? JSON.parse(raw) : {};
      return cart && typeof cart === "object" ? cart : {};
    } catch (e) {
      return {};
    }
  };

  TQOrder.prototype._saveCart = function () {
    try {
      localStorage.setItem(cartKey(this.slug), JSON.stringify(this.cart));
    } catch (e) {
      /* private mode — cart just won't survive a reload */
    }
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
    if (this._submitting) return; // chống double-tap -> đơn trùng
    this._submitting = true;
    var submitBtn = document.querySelector(".tq-btn-submit");
    if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = "Đang gửi đơn…"; }

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
        self._showOrderRecap(order);
        self.startPolling(order.id);
        return order;
      })
      .catch(function (err) {
        window.alert(String(err.message || err));
      })
      .then(function (order) {
        self._submitting = false;
        var btn = document.querySelector(".tq-btn-submit");
        if (btn) { btn.disabled = false; btn.textContent = "Xác nhận đặt món (COD)"; }
        return order;
      });
  };

  // Màn xác nhận sau khi đặt: recap món + tổng tiền mặt cần chuẩn bị + trạng
  // thái sống (poll). Thay TOÀN BỘ trang menu — không để form trống + menu
  // hiện lại như chưa đặt gì. "Đặt thêm món" quay về menu.
  TQOrder.prototype.isRecapActive = function () {
    return this._recapActive;
  };

  TQOrder.prototype._showOrderRecap = function (order) {
    var self = this;
    this._recapActive = true;
    var wrap = document.createElement("div");
    wrap.className = "tq-recap";

    var status = document.createElement("div");
    status.className = "tq-order-status";
    status.innerHTML = '<p class="tq-order-status-msg" id="tq-live-status">' +
      "Đơn đã gửi tới quán, đang chờ xác nhận…</p>";
    wrap.appendChild(status);

    var card = document.createElement("div");
    card.className = "tq-recap-card";
    var h = document.createElement("h2");
    h.textContent = "Đơn #" + String(order.id || "").slice(-6);
    card.appendChild(h);

    var ul = document.createElement("ul");
    ul.className = "tq-recap-items";
    (order.items || []).forEach(function (it) {
      var li = document.createElement("li");
      li.innerHTML = "<span>" + it.qty + "× " + it.name + "</span><strong>" +
        vndSafe(it.price * it.qty) + "</strong>";
      ul.appendChild(li);
    });
    card.appendChild(ul);

    var total = document.createElement("p");
    total.className = "tq-recap-total";
    total.innerHTML = "Chuẩn bị <strong>" + vndSafe(order.total) +
      "</strong> tiền mặt khi nhận hàng (COD).";
    card.appendChild(total);

    if (this.shop.phone) {
      var call = document.createElement("a");
      call.className = "tq-btn tq-btn-call";
      call.href = "tel:" + this.shop.phone;
      call.textContent = "📞 Gọi quán " + (this.shop.name || "") + " — " + this.shop.phone;
      card.appendChild(call);
    }
    wrap.appendChild(card);

    var more = document.createElement("button");
    more.type = "button";
    more.className = "tq-btn tq-btn-more";
    more.textContent = "Đặt thêm món";
    more.addEventListener("click", function () {
      self.stopPolling();
      self._recapActive = false;
      self.renderer.render(SURFACE_ID);
      window.scrollTo({ top: 0 });
    });
    wrap.appendChild(more);

    this.renderer.container.innerHTML = "";
    this.renderer.container.appendChild(wrap);
    window.scrollTo({ top: 0 });
  };

  // Mở lại trang khi còn đơn đang chạy (< 2h, chưa kết thúc) -> hiện lại
  // recap + tiếp tục poll thay vì menu "như chưa có gì xảy ra".
  TQOrder.prototype.resumeActiveOrder = function () {
    var last = global.TQContextRules.loadLastOrder(this.slug);
    if (!last || !last.id || !last.at) return false;
    if (Date.now() - new Date(last.at).getTime() > 2 * 3600 * 1000) return false;
    var self = this;
    fetch(this.apiBase + "/orders/" + last.id + "/status")
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (body) {
        if (!body || TERMINAL_STATUSES.indexOf(body.status) !== -1) return;
        self._showOrderRecap({ id: last.id, items: last.items, total: last.total });
        var live = document.getElementById("tq-live-status");
        if (live && body.message) live.textContent = body.message;
        self.startPolling(last.id);
      })
      .catch(function () {});
    return true;
  };

  // ------------------------------------------------------------------ polling

  TQOrder.prototype.startPolling = function (orderId) {
    var self = this;
    this.stopPolling();
    this._pollTimer = setInterval(function () {
      fetch(self.apiBase + "/orders/" + orderId + "/status")
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (body) {
          if (!body) return;
          var live = document.getElementById("tq-live-status");
          if (live) live.textContent = body.message || body.status;
          if (TERMINAL_STATUSES.indexOf(body.status) !== -1) self.stopPolling();
        })
        .catch(function () {}); // transient network blip — next tick retries
    }, POLL_INTERVAL_MS);
  };

  TQOrder.prototype.stopPolling = function () {
    if (this._pollTimer) { clearInterval(this._pollTimer); this._pollTimer = null; }
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
        // Link phải là URL đầy đủ — path trần dán vào Zalo là link chết.
        var url = location.origin + "/g/" + body.gid;
        var text = "Gom đơn " + (self.shop.name || "cả phòng") + " — vô chọn món: " + url;
        var goTo = function () { window.location.href = url; }; // người mở kèo cũng vào trang nhóm
        if (navigator.share) {
          navigator.share({ title: "Tiệm Quen — đơn nhóm", text: text, url: url })
            .catch(function () { self._copyGroupLink(url); })
            .then(goTo, goTo);
        } else {
          self._copyGroupLink(url); // alert/prompt chặn tới khi user bấm OK
          goTo();
        }
      })
      .catch(function () {
        window.alert("Không tạo được đơn nhóm, thử lại sau.");
      });
  };

  TQOrder.prototype._copyGroupLink = function (url) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(url).then(function () {
        window.alert("Đã copy link đơn nhóm — dán vào group Zalo:\n" + url);
      }).catch(function () {
        window.prompt("Copy link này gửi group Zalo:", url);
      });
    } else {
      window.prompt("Copy link này gửi group Zalo:", url);
    }
  };

  global.TQOrder = TQOrder;
})(window);
