// Post analysis section: one post or article, one screen. Uses helpers from app.js.
(() => {
  let data = null, wasJob = false;
  const section = (title, html) => html ? `<section class="pf-sec"><h3>${esc(title)}</h3>${html}</section>` : "";
  const pairs = (xs) => xs.length ? `<ul class="po-pairs">${xs.map((x) => `<li><b>${esc(x.what)}</b><span>${esc(x.how)}</span></li>`).join("")}</ul>` : "";
  const list = (xs) => xs.length ? `<ul class="pf-list">${xs.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : "";
  const REPEAT = { yes: "Worth repeating", adapt: "Adapt it", no: "Don't repeat" };
  const NUMS = (m) => [m.vs_median != null ? `${m.vs_median}× author's typical views` : null, m.views_per_follower != null ? `${m.views_per_follower} views per follower` : null,
    m.bookmark_ratio != null ? `${m.bookmark_ratio} bookmarks per like` : null, m.views_per_h != null ? `${k(m.views_per_h)} views per hour` : null].filter(Boolean);

  const copyBtn = (text, title) => `<button class="link po-copy" data-copy="${esc(text)}" title="${title}" aria-label="${title}">${icon("copy")}</button>`;
  const REPLY_KIND = { say: "Say", ask: "Ask" };
  function replies(r, m) {
    const xs = r.replies || [];
    if (!xs.length) return "";
    const late = m.age_h > 24 ? `<p class="hint">The post is ${Math.round(m.age_h / 24)}d old, a reply here will get few views.</p>` : "";
    return late + `<ul class="po-replies">${xs.map((x) => `<li><span class="po-kind">${REPLY_KIND[x.kind]}</span><span class="po-reply">${esc(x.text)}</span>${copyBtn(x.text, "Copy reply")}</li>`).join("")}</ul>`;
  }
  const block = (label, lines, title) => lines && lines.length ? `<h4 class="po-sub">${label}</h4><pre class="po-draft">${esc(lines.join("\n"))}${copyBtn(lines.join("\n"), title)}</pre>` : "";

  function render() {
    const body = $("poBody");
    $("poRe").disabled = !data;
    if (!data) {
      body.innerHTML = `<div class="empty"><h2>No post open</h2><p>Paste a link or the text. You get whether it is really useful, why it spread and what to take from it.</p></div>`;
      return;
    }
    const r = data.report, p = data.post, m = data.metrics || {}, c = (data.stats || {}).claude;
    const cost = c ? `<div class="summary"><span><b>${k(c.input_tokens)} / ${k(c.output_tokens)}</b> tokens in / out</span><span><b>$${c.cost_usd_equiv.toFixed(2)}</b> at API prices</span><span><b>${data.stats.total_s}s</b> total</span></div>` : "";
    const nums = NUMS(m);
    body.innerHTML = (r ? `
      <div class="po-verdict"><div class="po-score">${r.score ?? "?"}<small>/5</small></div><div><p>${esc(r.verdict)}</p><p class="po-gist">${esc(r.gist)}</p></div></div>
      ${section("Actually useful", r.useful.length ? list(r.useful) : `<p class="hint">Nothing concrete to apply.</p>`)}
      ${section("Fluff and unverified", list(r.empty))}
      ${section("Reply options", replies(r, m))}
      ${section("Why it spread", pairs(r.viral) + (nums.length ? `<p class="hint">${nums.join(" · ")}</p>` : ""))}
      ${section("Take for your posts", pairs(r.take))}
      ${section("Repeat it?", `<p class="pf-line">${r.repeat ? `<span class="po-repeat">${REPEAT[r.repeat]}</span>` : ""}${esc(r.repeat_why)}</p>${block("Base version, fill it in", r.base, "Copy base version")}${block("Your version", r.draft, "Copy your version")}`)}
    ` : `<div class="none">No Claude analysis in this record${(data.stats || {}).claude_error ? ": Claude failed" : ""}. Re-analyze uses the stored post.</div>`)
      + `<details class="pf-fold"><summary>The post</summary><div id="poOriginal"></div></details>${cost}`;
    const box = $("poOriginal");
    if (p.views != null) {
      const el = card({ ...p, age_min: (Date.now() - new Date(p.created_at)) / 60000, score: r && r.score != null ? `${r.score}/5` : "", label: "normal", why: "", gist: "", parts: {} });
      el.querySelector(".seen-btn").remove();
      el.querySelector(".body").classList.add("open");
      box.appendChild(el);
    } else box.innerHTML = `<p class="po-text">${esc(p.text)}</p>`;
    body.querySelectorAll(".po-copy").forEach((b) => (b.onclick = () => navigator.clipboard.writeText(b.dataset.copy).then(() => { b.classList.add("copied"); setTimeout(() => b.classList.remove("copied"), 1200); })));
  }

  async function loadHistory(key) {
    const list = await api("/api/posts");
    const sel = $("poHistory");
    sel.innerHTML = list.length ? list.map((x) => `<option value="${esc(x.key)}">${x.score != null ? x.score + "/5 · " : ""}${x.author ? "@" + esc(x.author) + " · " : ""}${esc(x.preview)}</option>`).join("") : `<option value="">No analyzed posts</option>`;
    sel.disabled = !list.length;
    if (key) sel.value = key;
    if (sel.value) await open(sel.value); else { data = null; render(); }
  }

  async function open(key) {
    data = await api(`/api/posts/${encodeURIComponent(key)}`);
    render();
  }

  window.postPanel = {
    async onState(s) {
      const job = s.running && s.kind === "post";
      const busy = s.running || s.login === "waiting" || s.login === "checking";
      $("poGo").disabled = busy; $("poRe").disabled = busy || !data;
      $("poGo").classList.toggle("hidden", job); $("poStop").classList.toggle("hidden", !job);
      $("poProgress").classList.toggle("hidden", !job);
      $("navPost").querySelector(".nav-busy").classList.toggle("hidden", !job);
      if (job) {
        $("poStep").textContent = `${s.step || "starting"}…`;
        $("poBar").style.width = `${Math.round((s.progress || 0.02) * 100)}%`;
        const el = Math.round(Date.now() / 1000 - s.started), left = s.eta_s ? Math.max(s.eta_s - el, 0) : null;
        $("poTiming").textContent = `${el}s` + (left != null ? ` · ~${left ? left + "s" : "almost done"} left` : "");
      }
      if (wasJob && !job && s.kind === "post") {
        if (s.post_key) { $("poInput").value = ""; await loadHistory(s.post_key); }
        else if (s.error && s.error !== "stopped") alert(s.error);
      }
      wasJob = job;
    },
  };

  $("poForm").onsubmit = (e) => {
    e.preventDefault();
    const input = $("poInput").value.trim();
    if (input) act(() => post("/api/posts/analyze", { input }))();
  };
  $("poStop").onclick = act(() => post("/api/stop"));
  $("poRe").onclick = () => { if (data) act(() => post(`/api/posts/${encodeURIComponent(data.key)}/reanalyze`))(); };
  $("poHistory").onchange = (e) => { if (e.target.value) open(e.target.value); };
  loadHistory();
})();
