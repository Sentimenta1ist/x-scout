// Isolated world: the only part that can reach x-scout (through background.js). content.js runs in the page's own world
// (typing from the isolated world makes X's Draft.js editor duplicate the text, checked 2026-11-18) and asks here.
// Only /api/type/ paths pass, so a page script can't use this to reach the rest of the local API.
window.addEventListener("message", (e) => {
  const m = e.data;
  if (e.source !== window || !m || m.xs !== "api" || typeof m.path !== "string" || !m.path.startsWith("/api/type/")) return;
  chrome.runtime.sendMessage({ path: m.path, body: m.body }, (r) => {
    window.postMessage({ xs: "api-res", req: m.req, res: r || { ok: false } }, location.origin);
  });
});
