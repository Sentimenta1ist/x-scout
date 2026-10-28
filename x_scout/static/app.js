const $ = (id) => document.getElementById(id);
const api = async (path, opts = {}) => {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
};
const post = (path, body) => api(path, { method: "POST", body: JSON.stringify(body || {}) });

const COLS = [
  ["hot", "Hot", "rising fast now"],
  ["global", "Global", "what everyone talks about"],
  ["useful", "For me", "useful for my work"],
];
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
  const item = (v, label, cls = "") => v == null ? "" : `<span class="${cls}"><b>${v}</b> ${label}</span>`;
  const when = new Date(current.started_at);
  $("meta").innerHTML = [
    item(when.toLocaleDateString([], { month: "short", day: "numeric" }) + ", " + when.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }), ""),
    item(s.scraped, "scraped"),
    item(s.sent, "sent to Claude"),
    c || qg ? item(`${k(tin)} / ${k(tout)}`, "tokens in / out") : "",
    c || qg ? item(`$${usd.toFixed(2)}`, "at API prices") : "",
    item(mins(s.scrape_s), "scraping"),
    item(c ? mins(Math.round(c.duration_s)) : null, "Claude"),
    item(mins(s.total_s), "total"),
    s.reanalyzed_from ? item(`#${s.reanalyzed_from}`, "re-analysis of") : "",
    s.claude_error ? item("Claude failed", "local ranking shown", "error") : "",
    s.error ? item(esc(s.error).slice(0, 80), "", "error") : "",
  ].filter(Boolean).join("");
  if (!result) return;

  if (!result.find((t) => t.topic === activeTopic)) activeTopic = result[0] && result[0].topic;
  for (const t of result) {
    const b = document.createElement("button");
    b.innerHTML = `${esc(t.topic)}<span class="count">${t.candidates}</span>`;
    b.className = t.topic === activeTopic ? "active" : "";
    b.onclick = () => { activeTopic = t.topic; renderBoard(); };
    tabs.appendChild(b);
  }
  const t = result.find((x) => x.topic === activeTopic);
  if (!t) return;
  for (const [key, title, sub] of COLS) {
    const col = document.createElement("section");
    col.className = "col";
    const items = t[key] || [];
    col.innerHTML = `<h2 class="col-${key}">${title}<span class="n">${items.length}</span><span class="sub">${sub}</span></h2>`;
    if (!items.length) col.insertAdjacentHTML("beforeend", `<div class="none">Nothing worth it in this run</div>`);
    items.forEach((p) => col.appendChild(card(p)));
    board.appendChild(col);
  }
}

async function loadRuns(selectId) {
  const runs = await api("/api/runs");
  const sel = $("runSelect");
  sel.innerHTML = runs.map((r) => {
    const when = new Date(r.started_at).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
    const topics = (r.topics || []).map((t) => t.name).join(", ");
    const mark = r.status === "done" ? "" : r.status === "running" ? " ⏳" : " ✕";
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
    $("progress").classList.toggle("hidden", !s.running && !logOpen);
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
    if (wasRunning && !s.running) await loadRuns(s.run_id);
    else if (s.running && s.run_id && $("runSelect").value != s.run_id) await loadRuns(s.run_id);
    wasRunning = s.running;
  } catch {}
}
async function loop() { await refresh(); setTimeout(loop, wasRunning ? 1000 : 4000); }

// ---- settings ----
function topicRow(t = { name: "", query: "" }) {
  const row = document.createElement("div");
  row.className = "topic-row";
  row.innerHTML = `<input class="tname" placeholder="AI agents" value="${esc(t.name)}">
    <input class="tquery" placeholder='query, e.g. ("AI agent" OR agentic) -crypto' value="${esc(t.query || "")}">
    <button class="ghost small">✕</button>`;
  row.querySelector("button").onclick = () => row.remove();
  return row;
}

async function openSettings() {
  const panel = $("settings");
  if (!panel.classList.contains("hidden")) return panel.classList.add("hidden");
  const [s, p] = await Promise.all([api("/api/settings"), api("/api/profile")]);
  $("topics").innerHTML = "";
  s.topics.forEach((t) => $("topics").appendChild(topicRow(t)));
  $("lang").value = s.lang; $("perMode").value = s.per_mode; $("cands").value = s.candidates;
  $("model").value = s.model; $("headless").checked = s.headless;
  $("profile").value = p.text;
  $("saveMsg").textContent = p.custom ? "" : "Profile is the example: edit it to describe yourself.";
  panel.classList.remove("hidden");
}

async function saveSettings() {
  const topics = [...document.querySelectorAll(".topic-row")].map((r) => ({
    name: r.querySelector(".tname").value.trim(), query: r.querySelector(".tquery").value.trim(),
  })).filter((t) => t.name);
  if (topics.length > 5) return ($("saveMsg").textContent = "Max 5 topics.");
  await post("/api/settings", {
    topics, lang: $("lang").value.trim(), per_mode: +$("perMode").value || 30, candidates: +$("cands").value || 25,
    model: $("model").value, headless: $("headless").checked,
  });
  await post("/api/profile", { text: $("profile").value });
  $("saveMsg").textContent = "Saved.";
  setTimeout(() => $("settings").classList.add("hidden"), 600);
}

const act = (fn) => async () => { try { await fn(); } catch (e) { alert(e.message); } refresh(); };
$("runBtn").onclick = act(() => post("/api/run"));
$("loginBtn").onclick = act(() => post("/api/login"));
$("checkBtn").onclick = act(() => post("/api/login/check"));
$("reBtn").onclick = act(() => post(`/api/runs/${$("runSelect").value}/reanalyze`));
$("settingsBtn").onclick = openSettings;
$("saveBtn").onclick = act(saveSettings);
$("addTopic").onclick = () => document.querySelectorAll(".topic-row").length < 5 && $("topics").appendChild(topicRow());
$("runSelect").onchange = (e) => loadRun(e.target.value);
$("logToggle").onclick = () => $("log").classList.toggle("hidden");
$("logBtn").onclick = () => { logOpen = !logOpen; $("log").classList.toggle("hidden", !logOpen); refresh(); };

loadRuns();
loop();
