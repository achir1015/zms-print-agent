// 離線快取：改了程式要遞增 CACHE，使用者才會拿到新版
const CACHE = "zms-print-agent-v2";
const CORE = ["./", "index.html", "icon.png", "manifest.webmanifest", "app/", "app/index.html", "app/style.css", "app/app.js",
  "app/data.js", "app/engine.js", "app/checks.js", "app/mesh.js", "app/agent.js", "app/viewer.js", "app/icon.png",
  "app/lib/manifold.js", "app/lib/manifold.wasm", "app/lib/three.module.min.js", "app/lib/three.core.min.js",
  "app/lib/jsm/controls/OrbitControls.js", "app/lib/jsm/libs/fflate.module.js", "app/lib/jsm/exporters/GLTFExporter.js",
  "app/lib/jsm/loaders/GLTFLoader.js", "app/lib/jsm/loaders/STLLoader.js", "app/lib/jsm/loaders/OBJLoader.js",
  "app/lib/jsm/loaders/PLYLoader.js", "app/lib/jsm/utils/BufferGeometryUtils.js"];
self.addEventListener("install", (e) => { e.waitUntil(caches.open(CACHE).then((c) => c.addAll(CORE)).then(() => self.skipWaiting())); });
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin) return;       // Claude API 等外部請求不快取
  e.respondWith(caches.match(e.request).then((hit) => hit || fetch(e.request).then((r) => {
    if (r.ok) { const copy = r.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); }
    return r;
  })));
});
