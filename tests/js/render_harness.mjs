/* Loads the real UI script with minimal DOM stubs and renders one view built
   from hostile metadata, so the escaping can be asserted from a test rather
   than by reading the source.

   argv[3] picks the view: "category" (default) or "installed". */

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
  classList: { add() {}, remove() {} },
  textContent: "",
  addEventListener() {},
  querySelector: () => null,
});
const mode = process.argv[3] || "category";
const nodes = {};
const sandbox = {
  console,
  document: {
    getElementById: (id) => (nodes[id] ||= el(id)),
    addEventListener() {},
  },
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  window: {
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
  "globalThis.__apps = (a) => { installedApps = a; };" +
  "globalThis.__state = (s) => { state = s; };", sandbox);

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
} else {
  sandbox.__state({
    targets: [
      {
        id: `window:${hostile}`,
        kind: "window",
        title: `Evil ${hostile}`,
        subtitle: `sub ${hostile}`,
        icon: hostile,
        actions: [],
      },
    ],
  });

  const out = el("out");
  sandbox.__renderCategory(out, "window");
  console.log(out.innerHTML);
}
