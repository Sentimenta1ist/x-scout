// x-scout typer. Runs only on a tab x-scout opened (#xscout in the URL): takes the queued draft for this post, types it
// into the reply box one key at a time and leaves it there. You read it and press Reply. Nothing here clicks Reply.
(() => {
  if (location.hash !== "#xscout") return;
  const m = location.pathname.match(/\/status\/(\d+)/);
  if (!m) return;
  const id = m[1];
  history.replaceState(null, "", location.pathname + location.search); // a reload must not type again

  const BOX = '[data-testid="tweetTextarea_0"]';
  const SEND = '[data-testid="tweetButtonInline"], [data-testid="tweetButton"]';
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const rand = (a, b) => a + Math.random() * (b - a);
  const api = (path, body) => new Promise((res) => chrome.runtime.sendMessage({ path, body }, (r) => res(r || { ok: false })));
  const report = (status, extra = {}) => api("/api/type/status", { id, status, ...extra });

  // pause after a character, ms: 40-130, longer after spaces and punctuation, a rare long "thinking" pause
  function delay(ch) {
    let d = rand(40, 130);
    if (ch === " ") d += rand(50, 180);
    else if (".,!?:;\n".includes(ch)) d += rand(150, 400);
    if (Math.random() < 0.03) d += rand(600, 1600);
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

    await sleep(rand(1500, 2500)); // let the thread load
    const me = (own_handle || "").toLowerCase();
    if (me && [...document.querySelectorAll('article a[href*="/status/"]')].some((a) => a.getAttribute("href").toLowerCase().startsWith(`/${me}/status/`))) {
      return report("already");
    }

    box.click();
    box.focus();
    await sleep(rand(500, 1200));
    if (box.innerText.trim()) { // leftovers from an earlier draft
      document.execCommand("selectAll");
      document.execCommand("delete");
      await sleep(rand(300, 600));
    }
    for (const ch of draft) {
      if (!box.contains(document.activeElement) && document.activeElement !== box) {
        return report("error", { error: "focus left the reply box, typing stopped" });
      }
      // one character per input event, like typing. No synthetic keydown/keyup: X's Draft.js editor handles those
      // itself and duplicates the text ("twtotwt...", checked 2026-11-18)
      document.execCommand(ch === "\n" ? "insertLineBreak" : "insertText", false, ch);
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
