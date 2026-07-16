/* Tiệm Quen — seller PWA (vanilla JS, no build step — ENGINE-SPEC §3 seller/).
 *
 * 3 tab (ARCH §3.1, §3.2, §2):
 *  - Mở tiệm: import menu (link / screenshot / fixture) -> review (sửa giá,
 *    ẩn món, thêm món chỉ bán trực tiếp) -> 3 câu phỏng vấn -> publish
 *    (POST /api/shops -> /hero (theme từ palette imagen) -> PATCH menu edits
 *     -> POST /compose).
 *  - Đơn: poll đơn mới, ACK "Đã thấy đơn" (SLA #1), chuyển trạng thái,
 *    đơn-theo-batch.
 *  - Tờ rơi: chọn format -> tạo batch + hero + PDF -> link tải.
 */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var state = {
    slug: localStorage.getItem("tq_seller_slug") || "",
    envelope: null,      // /api/import result {menu, warnings, confidence}
    original: {},        // dish_id -> {price, hidden} as imported (diff -> edits)
    added: [],           // add_dish edits queued from the review step
    pollTimer: null,
  };

  // ------------------------------------------------------------------ utils

  function api(path, opts) {
    return fetch(path, opts).then(function (r) {
      if (r.status === 204) return null;
      return r.json().then(function (body) {
        if (!r.ok) {
          var detail = body && body.detail;
          throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail || body));
        }
        return body;
      });
    });
  }
  function postJSON(path, body) {
    return api(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
  }
  function vnd(n) {
    return (n || 0).toLocaleString("vi-VN") + "đ";
  }
  function esc(s) {
    var div = document.createElement("div");
    div.textContent = s == null ? "" : String(s);
    return div.innerHTML;
  }
  function setMsg(id, text, kind) {
    var el = $(id);
    el.textContent = text || "";
    el.className = "tq-msg" + (kind ? " is-" + kind : "");
  }
  function setSlug(slug) {
    state.slug = slug;
    localStorage.setItem("tq_seller_slug", slug);
    var badge = $("shop-badge");
    badge.textContent = "/" + slug;
    badge.hidden = !slug;
  }
  if (state.slug) setSlug(state.slug);

  // ------------------------------------------------------------------- tabs

  var tabs = { onboard: $("tab-onboard"), orders: $("tab-orders"), flyers: $("tab-flyers") };
  function showTab(name) {
    Object.keys(tabs).forEach(function (k) { tabs[k].hidden = k !== name; });
    document.querySelectorAll(".tq-tab-btn").forEach(function (btn) {
      btn.classList.toggle("is-active", btn.dataset.tab === name);
    });
    stopPolling();
    if (name === "orders") initOrdersTab();
    if (name === "flyers") initFlyersTab();
  }
  document.querySelectorAll(".tq-tab-btn").forEach(function (btn) {
    btn.addEventListener("click", function () { showTab(btn.dataset.tab); });
  });

  // ========================================================= TAB 1: ONBOARD

  function importDone(envelope) {
    state.envelope = envelope;
    state.original = {};
    state.added = [];
    var dishes = envelope.menu.menu.dishes;
    Object.keys(dishes).forEach(function (id) {
      state.original[id] = { price: dishes[id].price, hidden: !!dishes[id].hidden };
    });
    setMsg("ob-source-msg",
      "Đọc được " + Object.keys(dishes).length + " món (độ tin cậy " +
      envelope.confidence + "/100).", "ok");
    renderReview();
    $("ob-step-review").hidden = false;
    $("ob-step-review").scrollIntoView({ behavior: "smooth" });
  }
  function importFail(err) {
    setMsg("ob-source-msg", "Import lỗi: " + err.message +
      " — thử upload ảnh chụp màn hình menu.", "error");
  }

  $("ob-import-url").addEventListener("click", function () {
    var url = $("ob-url").value.trim();
    if (!url) return setMsg("ob-source-msg", "Dán link quán trước đã.", "error");
    setMsg("ob-source-msg", "Đang import từ link…");
    postJSON("/api/import", { url: url }).then(importDone).catch(importFail);
  });
  $("ob-import-shots").addEventListener("click", function () {
    var files = $("ob-shots").files;
    if (!files.length) return setMsg("ob-source-msg", "Chọn ít nhất 1 ảnh.", "error");
    var form = new FormData();
    for (var i = 0; i < files.length; i++) form.append("screenshot", files[i]);
    setMsg("ob-source-msg", "Đang đọc ảnh menu…");
    api("/api/import", { method: "POST", body: form }).then(importDone).catch(importFail);
  });
  $("ob-import-fixture").addEventListener("click", function () {
    setMsg("ob-source-msg", "Đang nạp menu demo…");
    postJSON("/api/import", { fixture: "grab_screenshot_toolcalls" })
      .then(importDone).catch(importFail);
  });

  function renderReview() {
    var menu = state.envelope.menu.menu;
    var tbody = $("ob-review-table").querySelector("tbody");
    tbody.innerHTML = "";
    var warnBox = $("ob-warnings");
    warnBox.innerHTML = (state.envelope.warnings || [])
      .map(function (w) { return '<p class="tq-warn">⚠ ' + esc(w) + "</p>"; }).join("");

    menu.sections.forEach(function (section) {
      var tr = document.createElement("tr");
      tr.innerHTML = '<td colspan="3"><b>' + esc(section.title) + "</b></td>";
      tbody.appendChild(tr);
      section.items.forEach(function (dishId) {
        var dish = menu.dishes[dishId];
        if (!dish) return;
        var row = document.createElement("tr");
        row.innerHTML =
          "<td>" + esc(dish.name) +
            (dish.direct_only ? ' <span class="tq-dish-direct">chỉ bán trực tiếp</span>' : "") +
          "</td>" +
          '<td><input type="number" step="1000" min="0" data-dish="' + esc(dishId) +
            '" data-kind="price" value="' + dish.price + '"></td>' +
          '<td><input type="checkbox" data-dish="' + esc(dishId) +
            '" data-kind="hidden"' + (dish.hidden ? " checked" : "") + "></td>";
        tbody.appendChild(row);
      });
    });

    var sectionSel = $("ob-add-section");
    sectionSel.innerHTML = menu.sections
      .map(function (s) { return '<option value="' + esc(s.id) + '">' + esc(s.title) + "</option>"; })
      .join("");
  }

  $("ob-add-dish").addEventListener("click", function () {
    var name = $("ob-add-name").value.trim();
    var price = parseInt($("ob-add-price").value, 10);
    if (!name || !(price > 0)) return;
    var sectionId = $("ob-add-section").value;
    state.added.push({
      op: "add_dish", section_id: sectionId, name: name, price: price, direct_only: true,
    });
    // Show it in the table immediately (client-side preview only).
    var menu = state.envelope.menu.menu;
    var tbody = $("ob-review-table").querySelector("tbody");
    var row = document.createElement("tr");
    row.innerHTML = "<td>" + esc(name) +
      ' <span class="tq-dish-direct">chỉ bán trực tiếp (mới)</span></td>' +
      "<td>" + vnd(price) + "</td><td></td>";
    tbody.appendChild(row);
    $("ob-add-name").value = ""; $("ob-add-price").value = "";
  });

  $("ob-to-interview").addEventListener("click", function () {
    $("ob-step-interview").hidden = false;
    $("ob-step-interview").scrollIntoView({ behavior: "smooth" });
  });

  $("ob-payment").addEventListener("change", function () {
    $("ob-vietqr-fields").hidden = this.value !== "cod+vietqr";
  });

  function collectEdits() {
    var edits = [];
    document.querySelectorAll("#ob-review-table input[data-dish]").forEach(function (input) {
      var dishId = input.dataset.dish;
      var orig = state.original[dishId];
      if (!orig) return;
      if (input.dataset.kind === "price") {
        var price = parseInt(input.value, 10);
        if (price > 0 && price !== orig.price) {
          edits.push({ op: "set_price", dish_id: dishId, price: price });
        }
      } else if (input.dataset.kind === "hidden" && input.checked !== orig.hidden) {
        edits.push({ op: "hide_dish", dish_id: dishId, hidden: input.checked });
      }
    });
    return edits.concat(state.added);
  }

  $("ob-publish").addEventListener("click", function () {
    var btn = this;
    if (!state.envelope) return setMsg("ob-publish-msg", "Chưa import menu.", "error");
    btn.disabled = true;
    setMsg("ob-publish-msg", "Đang mở tiệm…");

    // Merge 3 interview answers into the shop doc (ARCH §3.1).
    var doc = JSON.parse(JSON.stringify(state.envelope.menu));
    if ($("ob-ship-zone").value.trim()) doc.shop.ship_zone = $("ob-ship-zone").value.trim();
    doc.shop.direct_discount_pct = parseFloat($("ob-discount").value) || 0;
    var payment = { cod: true };
    if ($("ob-payment").value === "cod+vietqr" && $("ob-account").value.trim()) {
      payment.vietqr = {
        bank: $("ob-bank").value.trim() || "VCB",
        account: $("ob-account").value.trim(),
        account_name: $("ob-account-name").value.trim() || undefined,
        enabled_after_n_orders: 3,
      };
      if (!payment.vietqr.account_name) delete payment.vietqr.account_name;
    }
    doc.shop.payment = payment;

    var edits = collectEdits();
    var slug;
    postJSON("/api/shops", doc)
      .then(function (created) {
        slug = created.shop.slug;
        setMsg("ob-publish-msg", "Tiệm tạo xong, đang sinh theme (imagen)…");
        return postJSON("/api/shops/" + slug + "/hero", {}); // palette -> theme seeds
      })
      .then(function () {
        if (!edits.length) return null;
        setMsg("ob-publish-msg", "Đang áp " + edits.length + " chỉnh sửa menu…");
        return api("/api/shops/" + slug + "/menu", {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ edits: edits }),
        });
      })
      .then(function () {
        setMsg("ob-publish-msg", "Đang dựng trang order…");
        return postJSON("/api/shops/" + slug + "/compose");
      })
      .then(function () {
        setSlug(slug);
        setMsg("ob-publish-msg", "", null);
        var link = $("ob-shop-link");
        link.href = "/t/" + slug;
        link.textContent = location.host + "/t/" + slug;
        $("ob-step-done").hidden = false;
        $("ob-step-done").scrollIntoView({ behavior: "smooth" });
      })
      .catch(function (err) { setMsg("ob-publish-msg", "Lỗi: " + err.message, "error"); })
      .then(function () { btn.disabled = false; });
  });

  $("ob-goto-flyers").addEventListener("click", function () { showTab("flyers"); });

  // ============================================================ TAB 2: ĐƠN

  var ACTIONS = {
    created: [{ label: "Đã thấy đơn ✓", cls: "", ack: true }],
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

  function initOrdersTab() {
    var has = !!state.slug;
    $("orders-need-slug").hidden = has;
    $("orders-live").hidden = !has;
    if (has) { refreshOrders(); startPolling(); }
  }
  $("orders-slug-save").addEventListener("click", function () {
    var slug = $("orders-slug-input").value.trim();
    if (!slug) return;
    setSlug(slug);
    initOrdersTab();
  });

  function startPolling() {
    stopPolling();
    state.pollTimer = setInterval(refreshOrders, 5000);
  }
  function stopPolling() {
    if (state.pollTimer) { clearInterval(state.pollTimer); state.pollTimer = null; }
  }

  function orderCard(order) {
    var div = document.createElement("div");
    div.className = "tq-order is-" + order.status;
    var items = order.items
      .map(function (it) { return it.qty + "× " + esc(it.name); }).join(", ");
    var who = order.customer || {};
    div.innerHTML =
      '<div class="tq-order-head"><span>#' + esc(order.id.slice(-6)) +
      " · " + esc((order.created_at || "").slice(11, 16)) + " · batch " +
      esc(order.batch_id || "direct") + '</span><span class="tq-badge">' +
      esc(order.status) + "</span></div>" +
      '<div class="tq-order-items">' + items +
      ' — <span class="tq-order-total">' + vnd(order.total) + "</span></div>" +
      '<div class="tq-order-head"><span>' + esc(who.name || "") + " · " +
      esc(who.phone || "") + " · " + esc(who.address || "") + "</span></div>";
    (ACTIONS[order.status] || []).forEach(function (action) {
      var btn = document.createElement("button");
      btn.className = "tq-btn-mini" + (action.danger ? " is-danger" : "");
      btn.textContent = action.label;
      btn.addEventListener("click", function () {
        btn.disabled = true;
        var req = action.ack
          ? postJSON("/orders/" + order.id + "/ack")
          : postJSON("/orders/" + order.id + "/transition", { to: action.to });
        req.then(refreshOrders).catch(function () { btn.disabled = false; });
      });
      div.appendChild(btn);
    });
    return div;
  }

  function refreshOrders() {
    if (!state.slug) return;
    api("/api/shops/" + state.slug + "/orders")
      .then(function (body) {
        var list = $("orders-list");
        list.innerHTML = "";
        if (!body.orders.length) {
          list.innerHTML = '<p class="tq-hint">Chưa có đơn nào — dán tờ rơi đi chờ chi.</p>';
        }
        body.orders.forEach(function (order) { list.appendChild(orderCard(order)); });
      })
      .catch(function () {});
    api("/api/shops/" + state.slug + "/batch-analytics")
      .then(function (body) {
        var tbody = $("batch-stats").querySelector("tbody");
        tbody.innerHTML = "";
        Object.keys(body.per_batch).forEach(function (batchId) {
          var s = body.per_batch[batchId];
          var tr = document.createElement("tr");
          tr.innerHTML = "<td>" + esc(batchId) + "</td><td>" +
            esc(s.location_tag || "—") + "</td><td>" + s.orders + "</td><td>" +
            vnd(s.revenue) + "</td>";
          tbody.appendChild(tr);
        });
        if (!Object.keys(body.per_batch).length) {
          tbody.innerHTML = '<tr><td colspan="4" class="tq-hint">Chưa có dữ liệu.</td></tr>';
        }
      })
      .catch(function () {});
  }

  // ========================================================== TAB 3: TỜ RƠI

  function initFlyersTab() {
    if (!state.slug) {
      $("fl-msg").textContent = "Mở tiệm trước (tab Mở tiệm) hoặc nhập slug ở tab Đơn.";
      return;
    }
    setMsg("fl-msg", "");
    refreshBatches();
  }

  $("fl-generate").addEventListener("click", function () {
    var btn = this;
    if (!state.slug) return setMsg("fl-msg", "Chưa có tiệm — mở tiệm trước.", "error");
    var formats = Array.prototype.slice
      .call(document.querySelectorAll(".fl-format:checked"))
      .map(function (cb) { return cb.value; });
    if (!formats.length) return setMsg("fl-msg", "Chọn ít nhất 1 format.", "error");
    var location = $("fl-location").value.trim() || "cua-quan";
    btn.disabled = true;
    setMsg("fl-msg", "Đang sinh ảnh nền + dựng PDF (lần đầu hơi lâu)…");
    postJSON("/api/shops/" + state.slug + "/flyers", {
      formats: formats, location_tag: location,
    })
      .then(function (body) {
        setMsg("fl-msg", "Xong! Tải PDF đem in:", "ok");
        var box = $("fl-results");
        box.innerHTML = "";
        Object.keys(body.flyers).forEach(function (fmt) {
          var f = body.flyers[fmt];
          var a = document.createElement("a");
          a.className = "tq-flyer-link";
          a.href = f.pdf_url;
          a.download = "";
          a.innerHTML = "⬇ Tờ rơi " + fmt.toUpperCase() +
            ' <span class="tq-flyer-meta">batch ' + esc(f.batch_id) +
            " · QR → " + esc(f.qr_url) + "</span>";
          box.appendChild(a);
        });
        refreshBatches();
      })
      .catch(function (err) { setMsg("fl-msg", "Lỗi: " + err.message, "error"); })
      .then(function () { btn.disabled = false; });
  });

  function refreshBatches() {
    api("/api/shops/" + state.slug + "/batches")
      .then(function (body) {
        var box = $("fl-batches");
        box.innerHTML = body.batches.length ? "" : '<p class="tq-hint">Chưa in batch nào.</p>';
        body.batches.reverse().forEach(function (b) {
          var div = document.createElement("div");
          div.className = "tq-order";
          div.innerHTML = '<div class="tq-order-head"><span><b>' + esc(b.id) +
            "</b> · " + esc(b.format.toUpperCase()) + " · " + esc(b.location_tag) +
            '</span><span class="tq-badge">' + esc((b.created_at || "").slice(0, 10)) +
            "</span></div>" +
            '<div class="tq-flyer-meta">QR → ' + esc(b.qr_url) + "</div>";
          box.appendChild(div);
        });
      })
      .catch(function () {});
  }

  // ------------------------------------------------------------------ boot

  showTab(state.slug ? "orders" : "onboard");
})();
