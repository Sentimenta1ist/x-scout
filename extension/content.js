// x-scout typer, page world (see bridge.js). Runs only on a tab x-scout opened (#xscout in the URL): takes the queued draft for this post, types it
// into the reply box one key at a time and leaves it there. You read it and press Reply. Nothing here clicks Reply.
(() => {
  // #xscout on a post page = reply to it; #xscout=<id> on /compose/post = an own post
  let id, own = false;
  if (location.hash === "#xscout") {
    const m = location.pathname.match(/\/status\/(\d+)/);
    if (!m) return;
    id = m[1];
  } else if (location.hash.startsWith("#xscout=")) {
    id = decodeURIComponent(location.hash.slice(8));
    own = true;
  } else return;
  history.replaceState(null, "", location.pathname + location.search); // a reload must not type again

  const BOX = '[data-testid="tweetTextarea_0"]';
  const SEND = '[data-testid="tweetButtonInline"], [data-testid="tweetButton"]';
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const rand = (a, b) => a + Math.random() * (b - a);
  // page world: x-scout is reached through bridge.js (isolated world) by postMessage
  let reqN = 0;
  const api = (path, body) => new Promise((res) => {
    const req = `${id}:${++reqN}`;
    const on = (e) => {
      if (e.source !== window || !e.data || e.data.xs !== "api-res" || e.data.req !== req) return;
      window.removeEventListener("message", on);
      res(e.data.res);
    };
    window.addEventListener("message", on);
    window.postMessage({ xs: "api", req, path, body }, location.origin);
  });
  const report = (status, extra = {}) => api("/api/type/status", { id, status, ...extra });

  // pause after a character, ms: 15-45, a bit longer after spaces and punctuation, a rare short "thinking" pause.
  // ~2-4 s for a 70-90 character reply (owner asked for faster, 2026-11-18; was 40-130 ms, ~8 s)
  function delay(ch) {
    let d = rand(15, 45);
    if (ch === " ") d += rand(10, 40);
    else if (".,!?:;\n".includes(ch)) d += rand(40, 120);
    if (Math.random() < 0.01) d += rand(200, 500);
    return d;
  }

  async function waitFor(sel, ms = 20000) {
    const end = Date.now() + ms;
    while (Date.now() < end) {
      const el = document.querySelector(sel);
      if (el) return el;
      await sleep(300);
    }
    return null;
  }

  async function run() {
    const r = await api(`/api/type/next/${id}`);
    if (!r.ok) return; // nothing queued for this post: a normal visit
    const { draft, own_handle } = r.data;
    report("typing");

    const box = await waitFor(BOX);
    if (!box) return report("error", { error: "reply box not found" });

    // the most private choice on X's cookie banner; it also covers the reply box
    const refuse = [...document.querySelectorAll('[role="button"], button')].find((b) => /refuse non-essential/i.test(b.textContent));
    if (refuse) refuse.click();

    await sleep(rand(800, 1200)); // let the thread load (for the already-replied check)
    const me = (own_handle || "").toLowerCase();
    if (!own && me && [...document.querySelectorAll('article a[href*="/status/"]')].some((a) => a.getAttribute("href").toLowerCase().startsWith(`/${me}/status/`))) {
      return report("already");
    }

    box.click();
    box.focus();
    await sleep(rand(250, 500));
    // always, even when empty: on a fresh Draft.js editor the first insertText doubles ("s" → "ss") and every next one
    // snowballs; one selectAll + delete first makes typing exact (checked on live X 2026-11-18). Also clears leftovers.
    const clear = () => { document.execCommand("selectAll"); document.execCommand("delete"); };
    clear();
    await sleep(rand(150, 300));
    let n = 0;
    for (const ch of draft) {
      if (!box.contains(document.activeElement) && document.activeElement !== box) {
        return report("error", { error: "focus left the reply box, typing stopped" });
      }
      // one character per input event, like typing. No synthetic keydown/keyup: X's Draft.js editor handles those
      // itself and duplicates the text ("twtotwt...", checked 2026-11-18)
      document.execCommand(ch === "\n" ? "insertLineBreak" : "insertText", false, ch);
      n++;
      if (n <= 3 || n % 10 === 0) { // fuse: stop before a mismatch snowballs
        const want = draft.slice(0, n).replace(/\s+/g, " ").trim(), have = box.innerText.replace(/\s+/g, " ").trim();
        if (have !== want) {
          clear();
          return report("error", { error: `typing went wrong after ${n} chars, cleared the box`, typed: have.slice(0, 80) });
        }
      }
      await sleep(delay(ch));
    }
    report("waiting", { typed: box.innerText.trim() });

    // you press Reply (or Cmd+Enter): log what actually went out, edits included
    let done = false;
    const sent = () => {
      if (done) return;
      done = true;
      api("/api/type/sent", { id, text: (document.querySelector(BOX) || box).innerText.trim() });
    };
    document.addEventListener("click", (e) => { if (e.target.closest(SEND)) sent(); }, true);
    document.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && e.target.closest(BOX)) sent(); }, true);
  }

  run().catch((e) => report("error", { error: String(e) }));
})();
