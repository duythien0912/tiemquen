/* Tiệm Quen seller PWA — minimal service worker: cache the app SHELL only.
 * API/orders are always network (đơn sống, không cache); shell cache-first
 * with background refresh so the app opens instantly ở sóng yếu. */
var CACHE = "tq-seller-shell-v1";
var SHELL = [
  "/seller/",
  "/seller/index.html",
  "/seller/app.js",
  "/seller/styles.css",
  "/seller/manifest.json",
  "/seller/icon.svg",
];

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(CACHE).then(function (cache) { return cache.addAll(SHELL); })
      .then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.filter(function (k) { return k !== CACHE; })
        .map(function (k) { return caches.delete(k); }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener("fetch", function (event) {
  var url = new URL(event.request.url);
  var isShell = event.request.method === "GET" &&
    url.origin === location.origin &&
    (SHELL.indexOf(url.pathname) !== -1 ||
      (event.request.mode === "navigate" && url.pathname.indexOf("/seller") === 0));
  if (!isShell) return; // API + media: always network, never stale orders
  event.respondWith(
    caches.match(event.request, { ignoreSearch: true }).then(function (cached) {
      var fresh = fetch(event.request).then(function (resp) {
        if (resp.ok) {
          var copy = resp.clone();
          caches.open(CACHE).then(function (cache) { cache.put(event.request, copy); });
        }
        return resp;
      }).catch(function () { return cached; });
      return cached || fresh;
    })
  );
});
