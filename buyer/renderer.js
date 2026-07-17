/* Tiệm Quen buyer renderer (ENGINE-SPEC §1/§2/§9) — vanilla JS, no build
 * step, no framework. Walks the FLAT A2UI v0.9 component list (tree linked
 * by id via childId / childIds.explicitList / childIds.dataBinding, root =
 * component with id "root") and renders semantic HTML. Fires DOM events
 * ("add_to_cart", "submit_order", ...) to whatever `order.js` registers via
 * `onEvent` — this file NEVER calls an LLM and NEVER calls the network
 * itself (ZERO-LLM golden rule on the buyer path, ENGINE-SPEC §0/§8).
 */
(function (global) {
  "use strict";

  function vnd(n) {
    return typeof n === "number" ? n.toLocaleString("vi-VN") + "đ" : "";
  }

  function ptrParts(path) {
    return (path || "").split("/").filter(Boolean);
  }

  function getPath(obj, path) {
    var parts = ptrParts(path), cur = obj;
    for (var i = 0; i < parts.length; i++) {
      if (cur == null) return undefined;
      cur = cur[parts[i]];
    }
    return cur;
  }

  function setPath(obj, path, value) {
    var parts = ptrParts(path), cur = obj;
    for (var i = 0; i < parts.length - 1; i++) {
      if (typeof cur[parts[i]] !== "object" || cur[parts[i]] === null) cur[parts[i]] = {};
      cur = cur[parts[i]];
    }
    if (parts.length) cur[parts[parts.length - 1]] = value;
  }

  // Leaf value {"path"|"literalString"|"literalNumber"|"literalBoolean"} ->
  // resolved JS value (ENGINE-SPEC §1). Passing an `{event: ...}` leaf back
  // through here just returns the leaf itself — callers check for `.event`.
  function resolveLeaf(leaf, dataModel) {
    if (leaf == null || typeof leaf !== "object") return leaf;
    if ("path" in leaf) return getPath(dataModel, leaf.path);
    if ("literalString" in leaf) return leaf.literalString;
    if ("literalNumber" in leaf) return leaf.literalNumber;
    if ("literalBoolean" in leaf) return leaf.literalBoolean;
    return undefined;
  }

  function childIdsOf(comp, dataModel) {
    if (typeof comp.childId === "string") return [comp.childId];
    var ch = comp.childIds;
    if (ch && Array.isArray(ch.explicitList)) return ch.explicitList;
    if (ch && typeof ch.dataBinding === "string") {
      var v = getPath(dataModel, ch.dataBinding);
      return Array.isArray(v) ? v : [];
    }
    return [];
  }

  function el(tag, className, text) {
    var e = document.createElement(tag);
    if (className) e.className = className;
    if (text != null) e.textContent = text;
    return e;
  }

  // ------------------------------------------------------------- component renderers
  // Each fn(this=Renderer, surfaceId, comp, dataModel) -> HTMLElement.

  var RENDERERS = {
    Page: function (sid, comp) {
      var wrap = el("div", "tq-page");
      this.renderChildrenInto(wrap, sid, comp);
      return wrap;
    },
    MenuSection: function (sid, comp, dm) {
      var sec = el("section", "tq-section");
      sec.appendChild(el("h2", "tq-section-title", resolveLeaf(comp.title, dm) || ""));
      if (comp.subtitle) sec.appendChild(el("p", "tq-section-sub", resolveLeaf(comp.subtitle, dm)));
      var grid = el("div", "tq-grid");
      this.renderChildrenInto(grid, sid, comp);
      sec.appendChild(grid);
      return sec;
    },
    HeroHeader: function (sid, comp, dm) {
      var hero = el("header", "tq-hero");
      var img = resolveLeaf(comp.image, dm);
      if (img) hero.style.backgroundImage = "url(" + JSON.stringify(img).slice(1, -1) + ")";
      hero.appendChild(el("h1", "tq-hero-name", resolveLeaf(comp.shopName, dm) || ""));
      if (comp.tagline) hero.appendChild(el("p", "tq-hero-tagline", resolveLeaf(comp.tagline, dm)));
      if (comp.hours) hero.appendChild(el("p", "tq-hero-hours", "⏰ " + resolveLeaf(comp.hours, dm)));
      return hero;
    },
    Badge: function (sid, comp, dm) {
      var kind = (comp.kind && resolveLeaf(comp.kind, dm)) || "info";
      return el("span", "tq-badge tq-badge-" + kind, resolveLeaf(comp.text, dm) || "");
    },
    DishCard: function (sid, comp, dm) {
      var soldOut = !!resolveLeaf(comp.soldOut, dm);
      var almostOut = !!resolveLeaf(comp.almostOut, dm);
      var card = el("article", "tq-dish" + (soldOut ? " tq-sold-out" : ""));
      if (comp.image) {
        var img = document.createElement("img");
        img.className = "tq-dish-img";
        img.loading = "lazy";
        img.src = resolveLeaf(comp.image, dm) || "";
        img.alt = "";
        card.appendChild(img);
      }
      var body = el("div", "tq-dish-body");
      body.appendChild(el("h3", "tq-dish-name", resolveLeaf(comp.name, dm) || ""));
      if (comp.note) body.appendChild(el("p", "tq-dish-note", resolveLeaf(comp.note, dm)));
      var priceRow = el("div", "tq-dish-price-row");
      priceRow.appendChild(el("span", "tq-dish-price", vnd(resolveLeaf(comp.price, dm))));
      if (comp.comparePrice != null) {
        var cmp = resolveLeaf(comp.comparePrice, dm);
        if (cmp) priceRow.appendChild(el("span", "tq-dish-compare", vnd(cmp)));
      }
      body.appendChild(priceRow);
      if (almostOut && !soldOut) body.appendChild(el("span", "tq-badge tq-badge-warn", "Sắp hết"));
      card.appendChild(body);

      // Số lượng hiện có trong giỏ (order.js sync /cart/qty) -> nút "Thêm"
      // biến thành stepper [− n +] để bấm nhầm còn gỡ ra được.
      var dishId = this._eventContext(comp.onPress, dm).dishId;
      var qty = (dishId && getPath(dm, "/cart/qty/" + dishId)) || 0;
      if (soldOut) {
        var btn = el("button", "tq-btn tq-btn-add", "Hết món");
        btn.type = "button";
        btn.disabled = true;
        card.appendChild(btn);
      } else if (!qty) {
        var add = el("button", "tq-btn tq-btn-add", "Thêm");
        add.type = "button";
        this.wireEvent(add, sid, comp, "onPress");
        card.appendChild(add);
      } else {
        var self = this;
        var stepper = el("div", "tq-stepper");
        var minus = el("button", "tq-btn tq-step-btn", "−");
        minus.type = "button";
        minus.setAttribute("aria-label", "Bớt 1");
        minus.addEventListener("click", function () {
          self._emit("remove_from_cart", { dishId: dishId }, comp.id);
        });
        stepper.appendChild(minus);
        stepper.appendChild(el("span", "tq-step-qty", String(qty)));
        var plus = el("button", "tq-btn tq-step-btn", "+");
        plus.type = "button";
        plus.setAttribute("aria-label", "Thêm 1");
        this.wireEvent(plus, sid, comp, "onPress");
        stepper.appendChild(plus);
        card.appendChild(stepper);
      }
      return card;
    },
    ComboCard: function (sid, comp, dm) {
      return RENDERERS.DishCard.call(this, sid, comp, dm); // same shape + comparePrice emphasis
    },
    ReorderCard: function (sid, comp, dm) {
      var card = el("article", "tq-reorder");
      card.appendChild(el("p", "tq-reorder-summary", resolveLeaf(comp.summary, dm) || ""));
      if (comp.total != null) card.appendChild(el("span", "tq-reorder-total", vnd(resolveLeaf(comp.total, dm))));
      var btn = el("button", "tq-btn tq-btn-reorder", "Đặt lại như hôm qua");
      btn.type = "button";
      this.wireEvent(btn, sid, comp, "onPress");
      card.appendChild(btn);
      return card;
    },
    CartBar: function (sid, comp, dm) {
      var count = resolveLeaf(comp.itemCount, dm) || 0;
      var bar = el("div", "tq-cartbar" + (count ? "" : " tq-hidden"));
      bar.appendChild(el("span", "tq-cartbar-count", count + " món"));
      bar.appendChild(el("span", "tq-cartbar-total", vnd(resolveLeaf(comp.total, dm) || 0)));
      var btn = el("button", "tq-btn tq-btn-checkout", (comp.label && resolveLeaf(comp.label, dm)) || "Đặt món");
      btn.type = "button";
      this.wireEvent(btn, sid, comp, "onCheckout");
      bar.appendChild(btn);
      return bar;
    },
    GroupOrderButton: function (sid, comp, dm) {
      var btn = el("button", "tq-btn tq-btn-group", resolveLeaf(comp.label, dm) || "Gom đơn cả phòng");
      btn.type = "button";
      this.wireEvent(btn, sid, comp, "onPress");
      return btn;
    },
    ReviewStrip: function (sid, comp, dm) {
      var strip = el("div", "tq-reviews");
      var rating = resolveLeaf(comp.rating, dm);
      if (rating != null) strip.appendChild(el("strong", null, "⭐ " + rating));
      if (comp.count != null) strip.appendChild(el("span", null, " (" + resolveLeaf(comp.count, dm) + " đơn)"));
      if (comp.quote) strip.appendChild(el("p", "tq-reviews-quote", "“" + resolveLeaf(comp.quote, dm) + "”"));
      return strip;
    },
    CheckoutForm: function (sid, comp, dm) {
      var form = document.createElement("form");
      // Giỏ trống -> giấu form (đỡ mời gọi submit sớm + alert "giỏ trống").
      var count = getPath(dm, "/cart/count") || 0;
      form.className = "tq-checkout" + (count ? "" : " tq-hidden");
      form.id = "tq-checkout-form";
      if (comp.title) form.appendChild(el("h2", null, resolveLeaf(comp.title, dm)));
      form.appendChild(this._field("name", (comp.nameLabel && resolveLeaf(comp.nameLabel, dm)) || "Tên", "text", true));
      form.appendChild(this._field("phone", (comp.phoneLabel && resolveLeaf(comp.phoneLabel, dm)) || "Số điện thoại", "tel", true));
      form.appendChild(this._field("address", (comp.addressLabel && resolveLeaf(comp.addressLabel, dm)) || "Địa chỉ / toà nhà", "text", true));
      form.appendChild(this._field("note", (comp.noteLabel && resolveLeaf(comp.noteLabel, dm)) || "Ghi chú", "text", false));
      var submit = el("button", "tq-btn tq-btn-submit", "Xác nhận đặt món (COD)");
      submit.type = "submit";
      form.appendChild(submit);
      var self = this, leaf = comp.onSubmit;
      form.addEventListener("submit", function (ev) {
        ev.preventDefault();
        var fd = new FormData(form);
        var ctx = self._eventContext(leaf, dm);
        ctx.customer = {
          name: (fd.get("name") || "").toString().trim(),
          phone: (fd.get("phone") || "").toString().trim(),
          address: (fd.get("address") || "").toString().trim(),
          note: (fd.get("note") || "").toString().trim(),
        };
        self._emit((leaf && leaf.event && leaf.event.name) || "submit_order", ctx, comp.id);
      });
      return form;
    },
    PaymentPicker: function (sid, comp, dm) {
      var wrap = el("div", "tq-payment");
      var cod = el("label", "tq-payment-option tq-payment-selected");
      cod.appendChild(el("span", null, "💰 " + ((comp.codLabel && resolveLeaf(comp.codLabel, dm)) || "Trả khi nhận")));
      wrap.appendChild(cod);
      if (resolveLeaf(comp.vietqrEnabled, dm)) {
        var qr = el("label", "tq-payment-option");
        qr.appendChild(el("span", null, "🆔 " + ((comp.vietqrLabel && resolveLeaf(comp.vietqrLabel, dm)) || "VietQR")));
        wrap.appendChild(qr);
      }
      return wrap;
    },
    OrderStatus: function (sid, comp, dm) {
      var status = resolveLeaf(comp.status, dm);
      var box = el("div", "tq-order-status" + (status ? "" : " tq-hidden"));
      box.appendChild(el("p", "tq-order-status-msg", (comp.message && resolveLeaf(comp.message, dm)) || ""));
      return box;
    },
  };

  // --------------------------------------------------------------------- Renderer

  function Renderer(container) {
    this.container = container;
    this.surfaces = {}; // surfaceId -> {root, order:[ids], components:Map, dataModel:{}}
    this._handlers = [];
  }

  Renderer.prototype.onEvent = function (fn) {
    this._handlers.push(fn);
  };

  Renderer.prototype._emit = function (name, context, componentId) {
    this._handlers.forEach(function (fn) {
      fn(name, context || {}, componentId);
    });
  };

  Renderer.prototype._surface = function (id) {
    if (!this.surfaces[id]) this.surfaces[id] = { root: "root", components: new Map(), dataModel: {} };
    return this.surfaces[id];
  };

  // ---- ingest cached A2UI messages (createSurface / updateComponents / updateDataModel)

  Renderer.prototype.applyMessages = function (messages) {
    var self = this;
    (messages || []).forEach(function (msg) {
      if (msg.createSurface) {
        self._surface(msg.createSurface.surfaceId);
      } else if (msg.updateComponents) {
        var p = msg.updateComponents, s = self._surface(p.surfaceId);
        s.root = p.root || "root";
        (p.components || []).forEach(function (c) {
          s.components.set(c.id, c);
        });
      } else if (msg.updateDataModel) {
        var p2 = msg.updateDataModel;
        setPath(self._surface(p2.surfaceId).dataModel, p2.path, p2.value);
      } else if (msg.deleteSurface) {
        delete self.surfaces[msg.deleteSurface.surfaceId];
      }
    });
  };

  // ---- data model + component-tree mutation helpers (context_rules.js / order.js)

  Renderer.prototype.getData = function (surfaceId, path) {
    return getPath(this._surface(surfaceId).dataModel, path);
  };
  Renderer.prototype.setData = function (surfaceId, path, value) {
    setPath(this._surface(surfaceId).dataModel, path, value);
  };
  Renderer.prototype.addComponent = function (surfaceId, comp) {
    this._surface(surfaceId).components.set(comp.id, comp);
  };
  Renderer.prototype.hasComponent = function (surfaceId, id) {
    return this._surface(surfaceId).components.has(id);
  };
  Renderer.prototype.prependChild = function (surfaceId, parentId, childId) {
    var parent = this._surface(surfaceId).components.get(parentId);
    if (!parent || !parent.childIds || !Array.isArray(parent.childIds.explicitList)) return;
    var list = parent.childIds.explicitList;
    if (list.indexOf(childId) === -1) list.unshift(childId);
  };

  // ---- event wiring shared by every clickable/submittable component

  Renderer.prototype._eventContext = function (leaf, dataModel) {
    var ctx = {};
    if (leaf && leaf.event && leaf.event.context) {
      Object.keys(leaf.event.context).forEach(function (k) {
        ctx[k] = resolveLeaf(leaf.event.context[k], dataModel);
      });
    }
    return ctx;
  };

  Renderer.prototype.wireEvent = function (button, surfaceId, comp, propName) {
    var self = this, leaf = comp[propName];
    if (!leaf || !leaf.event) return;
    button.addEventListener("click", function () {
      var dm = self._surface(surfaceId).dataModel;
      self._emit(leaf.event.name, self._eventContext(leaf, dm), comp.id);
    });
  };

  Renderer.prototype._field = function (name, label, type, required) {
    var wrap = el("label", "tq-field");
    wrap.appendChild(el("span", "tq-field-label", label));
    var input = document.createElement(name === "note" ? "textarea" : "input");
    if (name !== "note") input.type = type;
    input.name = name;
    if (required) input.required = true;
    if (type === "tel") {
      // Số VN: 0xxxxxxxxx (10 số) hoặc +84… — quán phải gọi lại được.
      input.pattern = "(0|\\+84)[0-9\\s.]{8,12}";
      input.inputMode = "tel";
      input.title = "Số điện thoại VN, ví dụ 0909123456";
    }
    wrap.appendChild(input);
    return wrap;
  };

  // ---- render: full rebuild of one surface into `this.container`

  Renderer.prototype.renderChildrenInto = function (container, surfaceId, comp) {
    var s = this._surface(surfaceId);
    var self = this;
    childIdsOf(comp, s.dataModel).forEach(function (id) {
      var child = s.components.get(id);
      if (!child) return; // dangling ref — cache is pre-validated, shouldn't happen
      container.appendChild(self._renderComponent(surfaceId, child));
    });
  };

  Renderer.prototype._renderComponent = function (surfaceId, comp) {
    var fn = RENDERERS[comp.component];
    var dm = this._surface(surfaceId).dataModel;
    if (!fn) return el("div", "tq-unknown"); // outside catalog — pre-validated cache shouldn't hit this
    return fn.call(this, surfaceId, comp, dm);
  };

  Renderer.prototype.render = function (surfaceId) {
    var s = this._surface(surfaceId);
    var root = s.components.get(s.root);

    // Full rebuild — nhưng khách đang gõ dở tên/SĐT rồi bấm "Thêm" món nữa
    // thì không được mất chữ: chụp giá trị input theo name, trả lại sau render.
    var saved = {};
    this.container.querySelectorAll("input[name], textarea[name]").forEach(function (inp) {
      if (inp.value) saved[inp.name] = inp.value;
    });

    this.container.innerHTML = "";
    if (!root) return;
    this.container.appendChild(this._renderComponent(surfaceId, root));

    Object.keys(saved).forEach(function (name) {
      var inp = this.container.querySelector('[name="' + name + '"]');
      if (inp && !inp.value) inp.value = saved[name];
    }, this);
  };

  global.TQRenderer = { create: function (container) { return new Renderer(container); }, vnd: vnd };
})(window);
