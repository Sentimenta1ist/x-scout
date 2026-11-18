// Talks to the local x-scout server for the content script (a page on x.com can't call localhost itself).
const API = "http://localhost:8765";

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  fetch(API + msg.path, msg.body ? { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(msg.body) } : {})
    .then(async (r) => reply({ ok: r.ok, data: r.ok ? await r.json() : null }))
    .catch((e) => reply({ ok: false, error: String(e) }));
  return true; // async reply
});
