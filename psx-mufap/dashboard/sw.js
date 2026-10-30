// Offline cache for the GitHub Pages copy of the dashboard. Data is never cached here:
// it lives in this browser's IndexedDB after you load your own data.json. Bump VERSION on release.
const VERSION = 'psxdash-v1';
const SHELL = ['./', 'index.html', 'app.js', 'theme.js', 'manifest.webmanifest', 'icons/icon.svg', 'icons/icon-192.png', 'icons/icon-512.png'];
self.addEventListener('install', e => {
  e.waitUntil(caches.open(VERSION).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== VERSION).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== 'GET') return;
  const sameOrigin = url.origin === location.origin;
  const isChartJs = url.hostname === 'cdnjs.cloudflare.com';
  if (!sameOrigin && !isChartJs) return;
  if (sameOrigin && /\/(data\.json|api\/)/.test(url.pathname)) return;   // never cache data or API calls
  e.respondWith(
    fetch(req, { cache: 'no-cache' }).then(res => {
      if (res.ok || res.type === 'opaque') { const copy = res.clone(); caches.open(VERSION).then(c => c.put(req, copy)); }
      return res;
    }).catch(() => caches.match(req, { ignoreSearch: true }).then(r => r || (sameOrigin ? caches.match('index.html') : undefined)))
  );
});
