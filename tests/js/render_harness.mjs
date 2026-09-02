/* Loads the real UI script with minimal DOM stubs and renders one view built
   from hostile metadata, so the escaping can be asserted from a test rather
   than by reading the source.

   argv[3] picks the view: "category" (default), "installed", "youtube",
   "home", "notifications" or "touchpad". */

import fs from "node:fs";
import vm from "node:vm";

const html = fs.readFileSync(process.argv[2], "utf8");
const script = html.slice(
  html.indexOf("<script>") + "<script>".length,
  html.lastIndexOf("</script>")
);

const el = (id) => ({
  id,
  innerHTML: "",
  classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
  textContent: "",
  scrollTop: 0,
  dataset: {},
  addEventListener() {},
  querySelector: () => null,
  querySelectorAll: () => [],
  closest: () => null,
  focus() {},
});
const mode = process.argv[3] || "category";
const nodes = {};
const sandbox = {
  console,
  document: {
    getElementById: (id) => (nodes[id] ||= el(id)),
    querySelector: () => null,
    querySelectorAll: () => [],
    activeElement: null,
    addEventListener() {},
  },
  navigator: { userAgent: "node", vibrate() {} },
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  window: {
    addEventListener() {},
    isSecureContext: false,
    location: {
      pathname: "/",
      search: "",
      href: "http://localhost/",
      replace() {},
      toString() {
        return "http://localhost/";
      },
    },
  },
  URL: globalThis.URL,
  URLSearchParams: globalThis.URLSearchParams,
  fetch: async () => ({ ok: true, json: async () => ({ targets: [] }) }),
  setInterval: () => 0,
  setTimeout: () => 0,
  clearTimeout: () => {},
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(script + "\n;globalThis.__renderCategory = renderCategory;" +
  "globalThis.__renderAppList = renderAppList;" +
  "globalThis.__renderYoutube = renderYoutube;" +
  "globalThis.__apps = (a) => { installedApps = a; };" +
  "globalThis.__nav = (n) => { navStack = n; };" +
  "globalThis.__renderHome = renderHome;" +
  "globalThis.__signature = () => viewSignature();" +
  "globalThis.__state = (s) => { state = s; };" +
  "globalThis.__rowsOf = (el) => el.innerHTML;" +
  "globalThis.__renderNotifList = renderNotifList;" +
  "globalThis.__setNotifs = (n) => { notifs = n; };" +
  "globalThis.__renderTouchpad = renderTouchpad;", sandbox);

const hostile = "<img src=x onerror=alert(1)>";

if (mode === "installed") {
  // A .desktop file is a plain text file anyone can drop in ~/.local/share,
  // so its Name reaches the page as untrusted as any window title.
  sandbox.__apps([
    {
      id: `launcher:${hostile}`,
      kind: "launcher",
      title: `Evil ${hostile}`,
      subtitle: `sub ${hostile}`,
      icon: hostile,
      actions: [{ id: "launch", label: "Launch", kind: "button" }],
    },
  ]);
  nodes.appList = el("appList");
  sandbox.__renderAppList();
  console.log(nodes.appList.innerHTML);
} else if (mode === "category") {
  sandbox.__state({
    targets: [
      {
        id: `window:${hostile}`,
        kind: "window",
        title: `Evil ${hostile}`,
        subtitle: `sub ${hostile}`,
        icon: hostile,
        // A real window always offers at least focus, and the row's tap runs
        // it directly -- so the hostile id lands in a data attribute twice.
        actions: [
          { id: "focus", label: "Focus", kind: "button" },
          { id: "close", label: "Close", kind: "confirm" },
        ],
      },
    ],
  });

  const out = el("out");
  sandbox.__renderCategory(out, "window");
  console.log(out.innerHTML);
}

if (mode === "youtube") {
  // The autoplay banner renders a server-supplied note next to a real action
  // button, above a search field -- the one place in the UI where explanatory
  // prose and a control share a container.
  sandbox.__state({
    targets: [
      {
        id: "youtube:search",
        kind: "youtube",
        title: "YouTube",
        status: "autoplay blocked",
        note: `Firefox blocks autoplay ${hostile}`,
        actions: [
          { id: "search", label: "Search", kind: "button" },
          { id: "fix_autoplay", label: `Allow autoplay ${hostile}`, kind: "confirm" },
        ],
      },
    ],
  });
  sandbox.__nav(["youtube:search"]);
  const out = el("out");
  sandbox.__renderYoutube(out);
  // The signature must move with the note, or the banner would never clear.
  console.log(out.innerHTML);
  console.log("SIGNATURE:" + sandbox.__signature());
}

if (mode === "home") {
  // The dashboard is the whole point of the tab bar: what is playing and the
  // controls for it are on screen before anything is tapped.
  sandbox.__state({
    targets: [
      {
        id: "mpris:vlc",
        kind: "player",
        title: `Now ${hostile}`,
        subtitle: `by ${hostile}`,
        icon: "♪",
        status: "playing",
        position: 30,
        length: 120,
        actions: [
          { id: "play_pause", label: "Pause", kind: "button" },
          { id: "next", label: "Next", kind: "button" },
          { id: "prev", label: "Previous", kind: "button" },
        ],
      },
      {
        id: "system:audio",
        kind: "system",
        title: "System Audio",
        icon: "🔊",
        status: "active",
        actions: [
          { id: "volume", label: "Volume (40%)", kind: "slider", value: 0.4 },
          { id: "mute", label: "Mute", kind: "button" },
        ],
      },
      {
        id: `window:${hostile}`,
        kind: "window",
        title: `Evil ${hostile}`,
        icon: "▣",
        actions: [
          { id: "focus", label: "Focus", kind: "button" },
          { id: "close", label: "Close", kind: "confirm" },
        ],
      },
    ],
  });
  const out = el("out");
  sandbox.__renderHome(out);
  console.log(nodes.homeResults.innerHTML);
}

if (mode === "notifications") {
  // Notification text is written by whatever app raised it -- a browser page
  // title, a chat message -- so it is as untrusted as a window title, and it
  // lands in the same row builder.
  sandbox.__setNotifs([
    {
      seq: 1,
      ts: Date.now() / 1000,
      app: `App ${hostile}`,
      summary: `Summary ${hostile}`,
      body: `Body ${hostile}`,
    },
  ]);
  nodes.notifList = el("notifList");
  sandbox.__renderNotifList();
  console.log(nodes.notifList.innerHTML);
}

if (mode === "touchpad") {
  // Without the extension the touchpad cannot work at all, so the screen says
  // so at the top instead of failing one tap at a time.
  sandbox.__state({
    targets: [
      {
        id: "system:extension",
        kind: "system",
        title: "GNOME extension not loaded",
        subtitle: "No window, workspace, touchpad or typing control",
        icon: "\u26a0",
        status: "missing",
        note: `Install it with vt install-extension ${hostile}`,
        actions: [],
      },
    ],
  });
  sandbox.__nav(["input:touchpad"]);
  const out = el("out");
  sandbox.__renderTouchpad(out);
  console.log(out.innerHTML);
  console.log("SIGNATURE:" + sandbox.__signature());
}
