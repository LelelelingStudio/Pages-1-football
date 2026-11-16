/* 今日球报 · PWA 桌面版 Service Worker
   策略：同源 HTML / JS 走「网络优先」保证每次打开都是最新快照，离线回退缓存；
   跨域的图片 / 视频（新闻配图、爱奇艺官方入口）完全不拦截，交给浏览器。
   前端改版时把 VERSION 加一号，activate 会自动清掉旧缓存。 */
var VERSION = 'qiubao-gh-v2';
var START = './index.html';
var SHELL = [START, './app.js', './news.json', './manifest.webmanifest', './icon-192.png', './icon.png'];

self.addEventListener('install', function (e) {
  e.waitUntil(
    caches.open(VERSION).then(function (c) {
      return Promise.all(SHELL.map(function (u) {
        return c.add(new Request(u, { cache: 'reload' })).catch(function () {});
      }));
    }).then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function (e) {
  e.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.map(function (k) {
        if (k !== VERSION) return caches.delete(k);
      }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function (e) {
  var req = e.request;
  if (req.method !== 'GET') return;
  var url;
  try { url = new URL(req.url); } catch (err) { return; }
  if (url.origin !== self.location.origin) return;   // 跨域资源不碰

  // 导航与 HTML：网络优先，成功即刷新缓存；离线回退到起始页缓存
  if (req.mode === 'navigate' || url.pathname === '/' || /\.html?$/i.test(url.pathname)) {
    e.respondWith(
      fetch(req).then(function (res) {
        var copy = res.clone();
        caches.open(VERSION).then(function (c) { c.put(START, copy); });
        return res;
      }).catch(function () {
        return caches.match(START).then(function (r) { return r || Response.error(); });
      })
    );
    return;
  }

  // 同源静态资源（app.js / manifest / 图标）：网络优先，离线用缓存
  e.respondWith(
    fetch(req).then(function (res) {
      if (res && res.ok) {
        var copy = res.clone();
        caches.open(VERSION).then(function (c) { c.put(req, copy); });
      }
      return res;
    }).catch(function () {
      return caches.match(req).then(function (r) { return r || Response.error(); });
    })
  );
});
