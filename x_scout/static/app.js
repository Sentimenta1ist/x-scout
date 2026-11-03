const $ = (id) => document.getElementById(id);
const api = async (path, opts = {}) => {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
};
const post = (path, body) => api(path, { method: "POST", body: JSON.stringify(body || {}) });

const COLS = [
  ["reply", "Reply", "worth my reply", "reply"],
  ["save", "Read", "interesting, worth saving", "bookmark"],
];
// runs before the reply/save split were stored as three columns
const LEGACY_COLS = [
  ["hot", "Hot", "rising fast now", "flame"],
  ["global", "Global", "what everyone talks about", "globe"],
  ["useful", "For me", "useful for my work", "target"],
];
const MAX_TOPICS = 10;
let current = null;      // loaded run
let activeTopic = null;
let wasRunning = false;
let logOpen = false;

// "seen" marks are a per-browser convenience
const seen = (() => {
  let s = {};
  try { s = JSON.parse(localStorage.getItem("seen") || "{}"); } catch {}
  return {
    has: (id) => !!s[id],
    toggle(id) { s[id] ? delete s[id] : (s[id] = Date.now()); try { localStorage.setItem("seen", JSON.stringify(s)); } catch {} },
  };
})();

const k = (n) => n == null ? "?" : n >= 1e6 ? (n / 1e6).toFixed(1).replace(/\.0$/, "") + "m" : n >= 1e3 ? (n / 1e3).toFixed(1).replace(/\.0$/, "") + "k" : String(n);
const age = (m) => m == null ? "?" : m < 60 ? Math.round(m) + "m" : m < 1440 ? (m / 60).toFixed(1).replace(/\.0$/, "") + "h" : Math.round(m / 1440) + "d";
const esc = (s) => (s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

const ICON = {
  views: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  likes: '<path d="M19 14c1.5-1.5 3-3.2 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.8 0-3 .5-4.5 2-1.5-1.5-2.7-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4 3 5.5l7 7z"/>',
  replies: '<path d="M21 12a8 8 0 0 1-11.6 7.1L3 21l1.9-6.4A8 8 0 1 1 21 12z"/>',
  reposts: '<path d="m17 2 4 4-4 4"/><path d="M3 11V9a3 3 0 0 1 3-3h15"/><path d="m7 22-4-4 4-4"/><path d="M21 13v2a3 3 0 0 1-3 3H3"/>',
  bookmarks: '<path d="M19 21l-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>',
  flame: '<path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/>',
  globe: '<circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/>',
  target: '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
  reply: '<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22z"/><path d="M8 12h.01"/><path d="M12 12h.01"/><path d="M16 12h.01"/>',
  bookmark: '<path d="m19 21-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16z"/><path d="M12 7v6"/><path d="M15 10H9"/>',
  x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  "file-search": '<path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M4.3 22H18a2 2 0 0 0 2-2V7l-5-5H6a2 2 0 0 0-2 2v6"/><circle cx="5" cy="14" r="3"/><path d="m9 18-1.5-1.5"/>',
  "columns-2": '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M12 3v18"/>',
  "sliders-horizontal": '<path d="M21 4h-7"/><path d="M10 4H3"/><path d="M21 12h-9"/><path d="M8 12H3"/><path d="M21 20h-5"/><path d="M12 20H3"/><path d="M14 2v4"/><path d="M8 10v4"/><path d="M16 18v4"/>',
  "user-search": '<circle cx="10" cy="7" r="4"/><path d="M10.3 15H7a4 4 0 0 0-4 4v2"/><circle cx="17" cy="17" r="3"/><path d="m21 21-1.9-1.9"/>',
  copy: '<rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>',
  "triangle-alert": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
};
const icon = (name) => `<svg viewBox="0 0 24 24" class="ic" aria-hidden="true">${ICON[name]}</svg>`;
const hue = (str) => [...str].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);
// escape, then turn bare links into a small "link" anchor so t.co noise doesn't eat lines
const richText = (t) => esc((t || "").replace(/\n\s*\n+/g, "\n")).replace(/https?:\/\/\S+/g, (u) => `<a class="inl" href="${u}" target="_blank" rel="noopener">link</a>`);

function card(p) {
  const div = document.createElement("article");
  div.className = "card" + (seen.has(p.id) ? " seen" : "");
  const parts = Object.entries(p.parts || {}).map(([a, b]) => `${a} ${b}`).join(" · ");
  const media = [...new Set(p.media || [])].map((m) => (m === "photo" ? "photo" : "video")).filter((v, i, a) => a.indexOf(v) === i);
  const sub = [`@${esc(p.author.handle)}`, `${k(p.author.followers)} followers`, age(p.age_min), ...media].join(" · ");
  const name = (p.author.name || p.author.handle).replace(/\s*\(.*?\)\s*/g, " ").trim();
  div.innerHTML = `
    <header class="card-head">
      <span class="avatar" style="--h:${hue(p.author.handle || "x")}">${esc((name[0] || "?").toUpperCase())}</span>
      <div class="who"><b title="${esc(p.author.name)}">${esc(name)}</b><span>${sub}</span></div>
      <span class="score ${p.label}" title="virality score · ${esc(parts)}">${p.score}</span>
    </header>
    ${p.why ? `<p class="why">${esc(p.why)}</p>` : ""}
    ${p.gist ? `<p class="gist">${esc(p.gist)}</p>` : ""}
    <div class="body">
      <p class="text">${richText(p.text)}</p>
      ${p.quoted ? `<p class="quoted">${richText(p.quoted.slice(0, 400))}</p>` : ""}
    </div>
    ${p.angle ? `<div class="angle"><span class="angle-label">Reply angle</span><span class="angle-text">${esc(p.angle)}</span><button class="link copy" title="Copy angle">copy</button></div>` : ""}
    <footer class="card-foot">
      <span class="metrics">
        <span title="views">${icon("views")}${k(p.views)}</span>
        <span title="likes">${icon("likes")}${k(p.likes)}</span>
        <span title="replies">${icon("replies")}${k(p.replies)}</span>
        <span title="reposts">${icon("reposts")}${k(p.reposts)}</span>
        <span title="bookmarks">${icon("bookmarks")}${k(p.bookmarks)}</span>
      </span>
      ${p.q ? `<span class="depth" title="depth / quality by Claude">${"●".repeat(p.q)}<i>${"●".repeat(5 - p.q)}</i></span>` : ""}
      <button class="link seen-btn">${seen.has(p.id) ? "unmark" : "seen"}</button>
      <a class="open" href="${p.url}" target="_blank" rel="noopener">Open ↗</a>
    </footer>`;
  const body = div.querySelector(".body");
  body.onclick = (e) => { if (e.target.tagName !== "A") body.classList.toggle("open"); };
  div.querySelector(".seen-btn").onclick = () => { seen.toggle(p.id); renderBoard(); };
  const copy = div.querySelector(".copy");
  if (copy) copy.onclick = () => navigator.clipboard.writeText(p.angle).then(() => (copy.textContent = "copied"));
  return div;
}

// ---- topic feed: one quiet column, the breakdown folds out ----
const SECTIONS = [["reply", "Reply", "fresh posts with reach where you have something to add"],
                  ["save", "Read", "worth reading or saving"]];
const DETAILS = [["context", "What is going on"], ["spread", "Why it spreads"], ["take", "What to take"], ["doubt", "Careful"]];

function copyBtn(text) {
  const b = document.createElement("button");
  b.className = "link fcopy"; b.title = "Copy"; b.innerHTML = icon("copy");
  b.onclick = (e) => { e.stopPropagation(); navigator.clipboard.writeText(text).then(() => { b.classList.add("copied"); setTimeout(() => b.classList.remove("copied"), 1200); }); };
  return b;
}

function pick(p, col) {
  const el = document.createElement("article");
  el.className = "fpick" + (seen.has(p.id) ? " seen" : "");
  const name = (p.author.name || p.author.handle).replace(/\s*\(.*?\)\s*/g, " ").trim();
  const meta = [`<b>${esc(name)}</b>`, `@${esc(p.author.handle)}`, `${k(p.author.followers)} followers`, age(p.age_min)].join(" · ");
  const headline = p.gist || (p.text || "").split("\n")[0].slice(0, 220);
  const replies = col === "reply" ? [["say", p.say || p.angle], ["ask", p.ask]].filter(([, t]) => t) : [];
  const details = DETAILS.filter(([key]) => p[key]).map(([key, label]) => `<div class="fd ${key}"><span>${label}</span><p>${esc(p[key])}</p></div>`).join("");
  const parts = Object.entries(p.parts || {}).map(([a, b]) => `${a} ${b}`).join(" · ");
  el.innerHTML = `
    <div class="fmeta-row">
      <span class="fwho">${meta}</span>
      ${p.q === 5 ? `<span class="ftop" title="Claude rated it 5/5">top</span>` : ""}
      <a class="fopen" href="${p.url}" target="_blank" rel="noopener" title="Open on X">↗</a>
    </div>
    <p class="fgist">${esc(headline)}</p>
    ${p.why ? `<p class="fwhy">${esc(p.why)}</p>` : ""}
    ${replies.length ? `<ul class="freplies">${replies.map(([kind, t]) => `<li><span class="fkind">${kind}</span><span class="ftext">${esc(t)}</span></li>`).join("")}</ul>` : ""}
    <details class="fmore">
      <summary><span class="fnums">${k(p.views)} views · ${k(p.likes)} likes · ${k(p.replies)} replies · ${k(p.bookmarks)} saves</span><span class="fopen-label">Breakdown</span></summary>
      ${details}
      <div class="fd"><span>Post</span><p class="ftext-full">${richText(p.text)}</p>${p.quoted ? `<p class="fquoted">${richText(p.quoted.slice(0, 600))}</p>` : ""}</div>
      <div class="ffoot"><span title="${esc(parts)}">virality ${p.score}${p.q ? ` · depth ${p.q}/5` : ""}</span><button class="link seen-btn">${seen.has(p.id) ? "unmark seen" : "mark seen"}</button></div>
    </details>`;
  el.querySelectorAll(".freplies li").forEach((li, i) => li.appendChild(copyBtn(replies[i][1])));
  el.querySelector(".seen-btn").onclick = () => { seen.toggle(p.id); renderBoard(); };
  return el;
}

function renderBoard() {
  const board = $("board"), tabs = $("tabs");
  board.innerHTML = ""; tabs.innerHTML = "";
  const result = current && current.result;
  $("empty").classList.toggle("hidden", !!result || (current && current.status !== "done"));
  if (!current) { $("meta").textContent = ""; return; }

  const s = current.stats || {};
  const c = s.claude, qg = s.query_gen;
  const tin = (c ? c.input_tokens : 0) + (qg ? qg.input_tokens : 0);
  const tout = (c ? c.output_tokens : 0) + (qg ? qg.output_tokens : 0);
  const usd = (c ? c.cost_usd_equiv : 0) + (qg ? qg.cost_usd_equiv : 0);
  const mins = (x) => x == null ? null : x < 60 ? `${x}s` : `${Math.floor(x / 60)}m ${x % 60}s`;
  const when = new Date(current.started_at);
  const bits = [
    when.toLocaleDateString([], { month: "short", day: "numeric" }) + ", " + when.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    s.scraped != null ? `${s.scraped} posts read` : null,
    s.sent != null ? `${s.sent} to Claude` : null,
    mins(s.total_s),
    c || qg ? `$${usd.toFixed(2)}` : null,
    s.reanalyzed_from ? `re-analysis of #${s.reanalyzed_from}` : null,
  ].filter(Boolean).map(esc);
  const warn = [s.rate_limited ? "X rate limit: search stopped early" : null, s.claude_error ? "Claude failed on some topics, local ranking there" : null,
                s.error ? String(s.error).slice(0, 80) : null].filter(Boolean).map((w) => `<span class="error">${esc(w)}</span>`);
  $("meta").innerHTML = bits.join(" · ") + (warn.length ? " · " + warn.join(" · ") : "");
  $("meta").title = c || qg ? `tokens in ${k(tin)} / out ${k(tout)} · scraping ${mins(s.scrape_s) || "?"} · Claude ${c ? mins(Math.round(c.duration_s)) : "?"}` : "";
  if (!result) return;

  if (!result.find((t) => t.topic === activeTopic)) activeTopic = result[0] && result[0].topic;
  for (const t of result) {
    const n = t.reply || t.save ? (t.reply || []).length + (t.save || []).length : LEGACY_COLS.reduce((a, [key]) => a + (t[key] || []).length, 0);
    const b = document.createElement("button");
    b.innerHTML = `${esc(t.topic)}<span class="count">${n}</span>`;
    b.title = `${t.candidates} candidates`;
    b.className = t.topic === activeTopic ? "active" : "";
    b.onclick = () => { activeTopic = t.topic; renderBoard(); };
    tabs.appendChild(b);
  }
  const t = result.find((x) => x.topic === activeTopic);
  if (!t) return;
  const sections = t.reply || t.save ? SECTIONS : LEGACY_COLS.map(([key, title, sub]) => [key, title, sub]);
  for (const [key, title, sub] of sections) {
    const items = t[key] || [];
    const sec = document.createElement("section");
    sec.className = "fsec";
    sec.innerHTML = `<h2>${title}<span class="n">${items.length}</span><span class="sub">${sub}</span></h2>`;
    if (!items.length) sec.insertAdjacentHTML("beforeend", `<p class="fnone">Nothing strong enough in this run.</p>`);
    if (key === "save" && t.local) sec.insertAdjacentHTML("beforeend", `<p class="fnone">Claude failed on this topic: top posts by local score, no breakdown.</p>`);
    items.forEach((p) => sec.appendChild(key === "reply" || key === "save" ? pick(p, key) : card(p)));
    board.appendChild(sec);
  }
}

async function loadRuns(selectId) {
  const runs = await api("/api/runs");
  const sel = $("runSelect");
  sel.innerHTML = runs.map((r) => {
    const when = new Date(r.started_at).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
    const topics = (r.topics || []).map((t) => t.name).join(", ");
    const mark = r.status === "done" ? "" : r.status === "running" ? " (running)" : r.status === "stopped" ? " (stopped)" : " (failed)";
    const c = (r.stats || {}).claude;
    const tok = c ? ` · ${k(c.input_tokens + c.output_tokens)} tok` : "";
    return `<option value="${r.id}">#${r.id} ${when}${mark} — ${esc(topics)}${tok}</option>`;
  }).join("");
  const id = selectId || (runs.find((r) => r.status === "done") || runs[0] || {}).id;
  if (id) { sel.value = id; await loadRun(id); } else { current = null; renderBoard(); $("empty").classList.remove("hidden"); }
}

async function loadRun(id) {
  current = await api(`/api/runs/${id}`);
  $("reBtn").disabled = !current.has_candidates;
  renderBoard();
}

// ---- state polling ----
async function refresh() {
  try {
    const s = await api("/api/state");
    const pill = $("loginPill");
    const L = { ok: ["X: logged in", "ok"], no: ["X: not logged in", "no"], waiting: ["X: finish login in the Chrome window", ""],
                checking: ["X: checking…", ""], unknown: ["X: press Check", ""] }[s.login] || ["X: ?", ""];
    pill.textContent = L[0]; pill.className = "pill " + L[1];
    const busy = s.running || s.login === "waiting" || s.login === "checking";
    ["runBtn", "loginBtn", "checkBtn"].forEach((id) => ($(id).disabled = busy));
    $("reBtn").disabled = busy || !(current && current.has_candidates);
    $("runBtn").classList.toggle("hidden", s.running);
    $("stopBtn").classList.toggle("hidden", !s.running);
    const topJob = !s.running || s.kind === "run";  // profile and post jobs show progress in their own section
    $("progress").classList.toggle("hidden", (!s.running && !logOpen) || !topJob);
    $("step").textContent = s.running ? `${s.step || "starting"}…` : "Last run finished";
    document.querySelector(".spinner").style.display = s.running ? "" : "none";
    $("progress").classList.toggle("done", !s.running);
    $("barFill").style.width = `${Math.round((s.running ? s.progress || 0.02 : 1) * 100)}%`;
    if (s.running && s.started) {
      const el = Math.round(Date.now() / 1000 - s.started);
      const left = s.eta_s ? Math.max(s.eta_s - el, 0) : null;
      const fmt = (x) => x < 60 ? `${x}s` : `${Math.floor(x / 60)}m ${String(x % 60).padStart(2, "0")}s`;
      $("timing").textContent = `${Math.round((s.progress || 0) * 100)}% · ${fmt(el)} elapsed` + (left != null ? ` · ~${left ? fmt(left) : "almost done"} left` : "");
    } else $("timing").textContent = "";
    $("log").textContent = (s.log || []).join("\n");
    $("log").scrollTop = 1e9;
    if (wasRunning && !s.running && s.kind === "run") await loadRuns(s.run_id);
    wasRunning = s.running;
    if (window.profilePanel) await window.profilePanel.onState(s);
    if (window.postPanel) await window.postPanel.onState(s);
  } catch {}
}
async function loop() { await refresh(); setTimeout(loop, wasRunning ? 1000 : 4000); }

// ---- settings ----
function topicRow(t = { name: "", query: "" }) {
  const row = document.createElement("div");
  row.className = "topic-row";
  row.innerHTML = `<input class="tname" placeholder="AI agents" value="${esc(t.name)}">
    <input class="tquery" placeholder='query, e.g. ("AI agent" OR agentic) -crypto' value="${esc(t.query || "")}">
    <button class="ghost small" title="Remove topic">${icon("x")}</button>
    <input class="textra" placeholder="extra queries; separated by ;  (empty: Claude writes 2)" value="${esc((t.extra || []).join(" ; "))}">`;
  row.querySelector("button").onclick = () => row.remove();
  return row;
}

async function loadSettings() {
  const [s, p] = await Promise.all([api("/api/settings"), api("/api/profile")]);
  $("topics").innerHTML = "";
  s.topics.forEach((t) => $("topics").appendChild(topicRow(t)));
  $("lang").value = s.lang; $("perMode").value = s.per_mode; $("cands").value = s.candidates;
  $("model").value = s.model; $("headless").checked = s.headless; $("gistLang").value = s.gist_lang;
  $("pfPosts").value = s.profile_max_posts; $("pfDays").value = s.profile_max_days; $("pfReplies").value = s.profile_max_replies;
  $("profile").value = p.text;
  $("saveMsg").textContent = p.custom ? "" : "Profile is the example: edit it to describe yourself.";
}

async function saveSettings() {
  const topics = [...document.querySelectorAll(".topic-row")].map((r) => {
    const t = { name: r.querySelector(".tname").value.trim(), query: r.querySelector(".tquery").value.trim() };
    const extra = r.querySelector(".textra").value.split(";").map((x) => x.trim()).filter(Boolean);
    if (extra.length) t.extra = extra;  // left out → Claude writes extra queries on the next run
    return t;
  }).filter((t) => t.name);
  if (topics.length > MAX_TOPICS) return ($("saveMsg").textContent = `Max ${MAX_TOPICS} topics.`);
  await post("/api/settings", {
    topics, lang: $("lang").value.trim(), per_mode: +$("perMode").value || 50, candidates: +$("cands").value || 50,
    model: $("model").value, headless: $("headless").checked, gist_lang: $("gistLang").value.trim() || "English",
    profile_max_posts: +$("pfPosts").value || 300, profile_max_days: +$("pfDays").value || 120,
    profile_max_replies: $("pfReplies").value === "" ? 60 : +$("pfReplies").value,
  });
  await post("/api/profile", { text: $("profile").value });
  $("saveMsg").textContent = "Saved.";
}

// ---- sidebar: one section at a time ----
const VIEWS = {
  feed: ["viewFeed", "navFeed", "columns-2", "Topics"],
  profiles: ["viewProfiles", "navProfiles", "user-search", "Profiles"],
  post: ["viewPost", "navPost", "file-search", "Post"],
  settings: ["viewSettings", "settingsBtn", "sliders-horizontal", "Settings"],
};
function setView(view) {
  if (!VIEWS[view]) view = "feed";
  for (const [key, [pane, nav]] of Object.entries(VIEWS)) {
    $(pane).classList.toggle("hidden", key !== view);
    $(nav).classList.toggle("active", key === view);
    if (key === view) $(nav).setAttribute("aria-current", "page"); else $(nav).removeAttribute("aria-current");
  }
  try { localStorage.setItem("view", view); } catch {}
  if (view === "settings") loadSettings();
}
for (const [view, [, nav, ic, label]] of Object.entries(VIEWS)) {
  $(nav).innerHTML = `${icon(ic)}<span>${label}</span><i class="nav-busy hidden"></i>`;
  $(nav).onclick = () => setView(view);
}
try { setView(localStorage.getItem("view") || "feed"); } catch { setView("feed"); }

const act = (fn) => async () => { try { await fn(); } catch (e) { alert(e.message); } refresh(); };
$("runBtn").onclick = act(() => post("/api/run"));
$("stopBtn").onclick = act(() => post("/api/stop"));
$("loginBtn").onclick = act(() => post("/api/login"));
$("checkBtn").onclick = act(() => post("/api/login/check"));
$("reBtn").onclick = act(() => post(`/api/runs/${$("runSelect").value}/reanalyze`));
$("saveBtn").onclick = act(saveSettings);
$("addTopic").onclick = () => document.querySelectorAll(".topic-row").length < MAX_TOPICS && $("topics").appendChild(topicRow());
$("runSelect").onchange = (e) => loadRun(e.target.value);
$("logToggle").onclick = () => $("log").classList.toggle("hidden");
$("logBtn").onclick = () => { logOpen = !logOpen; $("log").classList.toggle("hidden", !logOpen); refresh(); };

loadRuns();
loop();
