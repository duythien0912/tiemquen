/* Tiệm Quen buyer context rules (ENGINE-SPEC §9, ARCH §5.3 bảng rule).
 * Pure client-side heuristics — NO LLM, NO server round-trip beyond plain
 * data fetches. Picks WHICH pre-composed variant to load, then layers two
 * more zero-LLM adjustments on top of the static cache: a locally-stored
 * "đặt lại" card, and a fresh sold-out/almost-out patch (the composed cache
 * can lag a few minutes behind the live shop store).
 */
(function (global) {
  "use strict";

  var LUNCH_START_HOUR = 10;
  var LUNCH_END_HOUR = 13; // exclusive — ARCH §5.3 "10–13h"

  function fold(s) {
    return (s || "")
      .toString()
      .toLowerCase()
      .replace(/đ/g, "d")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "");
  }

  // "Batch (tờ rơi ở đâu)" -> office (nút gom đơn nổi) | table (mặc định).
  // The raw ?b= value is ALSO the batch_id sent with every order (flyer
  // analytics) — classification only decides which variant to fetch.
  function classifyBatch(rawBatchId) {
    var folded = fold(rawBatchId);
    return /office|van\s*-?\s*phong|vp\b/.test(folded) ? "office" : "table";
  }

  function daypartNow(date) {
    var h = (date || new Date()).getHours();
    return h >= LUNCH_START_HOUR && h < LUNCH_END_HOUR ? "lunch" : "regular";
  }

  function resolveContext(location, date) {
    var params = new URLSearchParams(location.search || "");
    var rawBatchId = params.get("b") || "direct";
    var batchKind = classifyBatch(rawBatchId);
    var daypart = daypartNow(date);
    return {
      batchId: rawBatchId,
      batchKind: batchKind,
      daypart: daypart,
      variant: batchKind + "-" + daypart,
    };
  }

  // ---- "Khách cũ/mới" -> prepend ReorderCard (ARCH §5.3 row 3) ----------

  function lastOrderKey(slug) {
    return "tq_last_order_" + slug;
  }

  function loadLastOrder(slug) {
    try {
      var raw = localStorage.getItem(lastOrderKey(slug));
      return raw ? JSON.parse(raw) : null;
    } catch (e) {
      return null;
    }
  }

  function saveLastOrder(slug, order) {
    try {
      localStorage.setItem(
        lastOrderKey(slug),
        JSON.stringify({
          id: order.id, // để mở lại trang là thấy đơn đang chạy (resume poll)
          items: order.items,
          total: order.total,
          at: new Date().toISOString(),
        })
      );
    } catch (e) {
      /* localStorage unavailable (private mode) — reorder just won't show next time */
    }
  }

  // Injects a ReorderCard right under the hero. The composed cache never
  // contains this component (it's not compose-time data — it's THIS
  // browser's last order), so it's added client-side via the renderer's
  // component-tree mutation helpers, no recompose involved.
  function applyReorderCard(renderer, surfaceId, slug) {
    var last = loadLastOrder(slug);
    if (!last || !last.items || !last.items.length) return false;
    var summary = last.items.map(function (it) { return it.qty + "x " + it.name; }).join(", ");
    renderer.setData(surfaceId, "/reorder/summary", summary);
    renderer.setData(surfaceId, "/reorder/total", last.total);
    renderer.addComponent(surfaceId, {
      id: "reorder_card",
      component: "ReorderCard",
      summary: { path: "/reorder/summary" },
      total: { path: "/reorder/total" },
      onPress: { event: { name: "reorder", context: {} } },
    });
    renderer.prependChild(surfaceId, "root", "reorder_card");
    return true;
  }

  // ---- "Trạng thái món" -> fresh sold-out/almost-out patch, no recompose --

  // The composed-variant cache already has soldout/almostout baked in from
  // whenever it was last composed/patched server-side; this just pulls the
  // CURRENT flags (short cache-control on this endpoint) and re-applies them
  // as a plain updateDataModel patch — same zero-recompose contract as the
  // server's own PATCH /api/shops/{slug}/patch (ENGINE-SPEC §1).
  function applySoldoutPatch(renderer, surfaceId, apiBase, slug) {
    return fetch(apiBase + "/api/shops/" + encodeURIComponent(slug) + "/menu", { cache: "no-store" })
      .then(function (r) {
        return r.ok ? r.json() : null;
      })
      .then(function (body) {
        if (!body) return false;
        var dishes = body.menu.dishes;
        var soldout = {}, almostout = {};
        Object.keys(dishes).forEach(function (id) {
          soldout[id] = !!dishes[id].sold_out;
          almostout[id] = !!dishes[id].almost_out;
        });
        renderer.setData(surfaceId, "/soldout", soldout);
        renderer.setData(surfaceId, "/almostout", almostout);
        return true;
      })
      .catch(function () {
        return false; // stale-but-cached data is fine — never block the page on this
      });
  }

  global.TQContextRules = {
    classifyBatch: classifyBatch,
    daypartNow: daypartNow,
    resolveContext: resolveContext,
    loadLastOrder: loadLastOrder,
    saveLastOrder: saveLastOrder,
    applyReorderCard: applyReorderCard,
    applySoldoutPatch: applySoldoutPatch,
  };
})(window);
