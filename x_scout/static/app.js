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

function card(p) {
  const div = document.createElement("div");
  div.className = "card" + (seen.has(p.id) ? " seen" : "");
  const parts = Object.entries(p.parts || {}).map(([a, b]) => `${a} ${b}`).join(" · ");
  const media = (p.media || []).length ? ` · ${[...new Set(p.media)].join(", ")}` : "";
  div.innerHTML = `
    <div class="card-head">
      <span class="who">${esc(p.author.name)} @${esc(p.author.handle)}</span>
      <span>${k(p.author.followers)} fol · ${age(p.age_min)}${media}</span>
      <span class="score ${p.label}" title="${esc(parts)}">${p.score}</span>
    </div>
    <div class="text">${esc(p.text)}</div>
    ${p.quoted ? `<div class="quoted">${esc(p.quoted.slice(0, 280))}</div>` : ""}
    ${p.why ? `<div class="why">${esc(p.why)}</div>` : ""}
    ${p.angle ? `<div class="angle">↳ ${esc(p.angle)} <button class="link copy">copy</button></div>` : ""}
    <div class="metrics">
      <span>👁 ${k(p.views)}</span><span>♥ ${k(p.likes)}</span><span>💬 ${k(p.replies)}</span>
      <span>⟲ ${k(p.reposts)}</span><span>🔖 ${k(p.bookmarks)}</span>
    </div>
    <div class="card-foot">
      <a href="${p.url}" target="_blank" rel="noopener">Open on X ↗</a>
      ${p.q ? `<span class="q">depth ${p.q}/5</span>` : ""}
      <button class="link seen-btn" style="margin-left:auto">${seen.has(p.id) ? "unmark" : "seen"}</button>
    </div>`;
  div.querySelector(".text").onclick = (e) => e.currentTarget.classList.toggle("open");
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
  const stat = (v, label, cls = "") => v == null ? "" : `<div class="stat ${cls}"><b>${v}</b><span>${label}</span></div>`;
  $("meta").innerHTML = [
    stat(new Date(current.started_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }), new Date(current.started_at).toLocaleDateString([], { month: "short", day: "numeric" })),
    stat(s.scraped, "posts scraped"),
    stat(s.sent, "sent to Claude"),
    c || qg ? stat(`${k(tin)} / ${k(tout)}`, "tokens in / out") : "",
    c || qg ? stat(`$${usd.toFixed(2)}`, "API-price equiv") : "",
    stat(mins(s.scrape_s), "scraping"),
    stat(c ? mins(Math.round(c.duration_s)) : null, "Claude"),
    stat(mins(s.total_s), "total"),
    s.reanalyzed_from ? stat(`#${s.reanalyzed_from}`, "re-analysis of") : "",
    s.claude_error ? stat("Claude failed", "local ranking shown", "error") : "",
    s.error ? stat(esc(s.error).slice(0, 60), "error", "error") : "",
  ].join("");
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
    col.innerHTML = `<h2>${title} <span class="sub">${sub}</span></h2>`;
    const items = t[key] || [];
    if (!items.length) col.insertAdjacentHTML("beforeend", `<div class="none">nothing here</div>`);
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
    $("progress").classList.toggle("hidden", !s.running && !(s.log || []).length);
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

loadRuns();
loop();
