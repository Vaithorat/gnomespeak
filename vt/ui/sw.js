// Service worker: an installed icon, an instant open, and the Android share
// sheet -- with nothing installed from a store.
//
// The share target is why this file does more than cache. A share POST is a
// navigation from Android and carries no headers, so it cannot be authorized:
// the credential lives in localStorage, which only the page can read. So the
// POST is intercepted here, the payload is parked in a cache, and the page --
// which does have the credential -- picks it up and uploads it normally.

const VERSION = "v1";
const SHELL = `gnomespeak-shell-${VERSION}`;
const SHARE = "gnomespeak-share";

const ASSETS = [
  "/icon-192.png",
  "/icon-512.png",
  "/icon-maskable-512.png",
  "/manifest.webmanifest",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL).then((cache) => cache.addAll(ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    for (const name of await caches.keys()) {
      if (name.startsWith("gnomespeak-shell-") && name !== SHELL) await caches.delete(name);
    }
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.method === "POST" && url.pathname === "/share") {
    event.respondWith(receiveShare(request));
    return;
  }
  if (request.method !== "GET") return;
  // The API and the live channel are the live state; a cached answer would be
  // a lie about what the PC is doing right now.
  if (url.pathname.startsWith("/api/") || url.pathname === "/ws") return;

  if (request.mode === "navigate") {
    event.respondWith(freshPage(request));
    return;
  }
  if (ASSETS.includes(url.pathname)) {
    event.respondWith(caches.match(request).then((hit) => hit || fetch(request)));
  }
});

// Network first, always. A cached index.html would survive an upgrade and keep
// serving an old UI against a new server; the cache is only the offline story.
async function freshPage(request) {
  try {
    const response = await fetch(request);
    if (response && response.ok) {
      const copy = response.clone();
      caches.open(SHELL).then((cache) => cache.put("/offline", copy));
    }
    return response;
  } catch (e) {
    const cached = await caches.match("/offline");
    if (cached) return cached;
    return new Response(
      "<!doctype html><meta charset=utf-8><title>GnomeSpeak</title>" +
      "<body style='font:16px system-ui;padding:2rem;background:#0e1013;color:#e6e9ef'>" +
      "<h1>PC unreachable</h1><p>GnomeSpeak is not answering. The PC may be asleep, " +
      "or the tunnel may be down.</p>",
      {status: 503, headers: {"Content-Type": "text/html; charset=utf-8"}}
    );
  }
}

async function receiveShare(request) {
  try {
    const form = await request.formData();
    const cache = await caches.open(SHARE);
    const files = form.getAll("files").filter((f) => f && f.name !== undefined);
    const meta = {
      title: form.get("title") || "",
      text: form.get("text") || "",
      url: form.get("url") || "",
      files: [],
    };
    for (let i = 0; i < files.length; i++) {
      const key = `/_share/file/${i}`;
      await cache.put(key, new Response(files[i], {
        headers: {"Content-Type": files[i].type || "application/octet-stream"},
      }));
      meta.files.push({key: key, name: files[i].name || `shared-${i}`});
    }
    await cache.put("/_share/meta", new Response(JSON.stringify(meta), {
      headers: {"Content-Type": "application/json"},
    }));
  } catch (e) {
    // Nothing to hand the page; still open it rather than showing a browser error.
  }
  return Response.redirect("/?share=1", 303);
}

// --- push -------------------------------------------------------------------
// The reason this worker exists at all beyond caching: a page that is closed
// runs no code, and this is the one thing that still wakes up. The payload is
// already decrypted by the browser by the time it arrives here.

self.addEventListener("push", (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch (e) {
    payload = {body: event.data ? event.data.text() : ""};
  }
  const title = payload.title || "GnomeSpeak";
  event.waitUntil(
    self.registration.showNotification(title, {
      body: payload.body || "",
      // The tag collapses repeats of the same thing rather than stacking six
      // banners for one chatty app.
      tag: payload.tag || "gnomespeak",
      icon: "/icon-192.png",
      badge: "/icon-192.png",
      data: {url: payload.url || "/"},
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil((async () => {
    const open = await self.clients.matchAll({type: "window", includeUncontrolled: true});
    for (const client of open) {
      // A tab is already open on this PC's page: take it there rather than
      // opening a second one.
      if (new URL(client.url).origin === self.location.origin) {
        await client.focus();
        if ("navigate" in client) await client.navigate(target);
        return;
      }
    }
    await self.clients.openWindow(target);
  })());
});
