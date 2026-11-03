// Profile analysis section. Uses helpers from app.js: $, api, post, k, esc, icon, card, richText, act.
(() => {
  const TABS = [["overview", "Overview"], ["growth", "Growth"], ["viral", "Viral posts"], ["patterns", "Patterns"], ["repeat", "Repeat for me"], ["raw", "Raw"]];
  const COLUMNS = [["created_at", "Date"], ["type", "Type"], ["media_type", "Media"], ["views", "Views"], ["likes", "Likes"], ["replies", "Replies"],
    ["reposts", "Reposts"], ["quotes", "Quotes"], ["bookmarks", "Saves"], ["er", "ER"], ["ratio", "× median"], ["text", "Text"]];
  const STATUS = { stopped: "Stopped: partial data", rate_limited: "X rate limit: partial data", need_login: "Logged out: partial data" };
  let data = null, tab = "overview", wasJob = false, sort = { key: "created_at", dir: -1 };

  const num = (x) => x == null ? "?" : Math.round(x).toLocaleString("en-US");
  const pct = (x) => x == null ? "?" : (x * 100).toFixed(1) + "%";
  const day = (s) => s ? new Date(s).toLocaleDateString([], { month: "short", day: "numeric" }) : "?";
  const dur = (x) => x == null ? null : x < 60 ? `${x}s` : `${Math.floor(x / 60)}m ${x % 60}s`;
  const byId = () => Object.fromEntries((data.posts || []).map((p) => [p.id, p]));
  const postLinks = (ids) => {
    const m = byId();
    return (ids || []).filter((i) => m[i]).map((i) => `<a class="inl" href="${esc(m[i].url)}" target="_blank" rel="noopener">${day(m[i].created_at)} · ${k(m[i].views)}</a>`).join(" ");
  };
  const section = (title, html, hint) => `<section class="pf-sec"><h3>${esc(title)}</h3>${hint ? `<p class="hint">${esc(hint)}</p>` : ""}${html}</section>`;
  const noReport = () => `<div class="none">No Claude analysis in this record. Press Re-analyze: it uses the stored posts and does not touch X.</div>`;

  // ---- tabs ----
  function overview() {
    const p = data.profile, m = data.metrics, c = m.cadence, r = data.report;
    const stat = (v, l) => `<div class="pf-stat"><b>${v}</b><span>${l}</span></div>`;
    const max = Math.max(...c.hours_utc, 1);
    const hours = c.hours_utc.map((n, h) => `<div class="pf-hour" title="${h}:00 UTC: ${n} posts"><i style="height:${Math.round((n / max) * 100)}%"></i><span>${h % 6 ? "" : h}</span></div>`).join("");
    const types = Object.entries(c.types).map(([t, s]) => `<tr><td>${esc(t)}</td><td class="n">${Math.round(s * 100)}%</td><td class="n">${k(c.median_views_by_type[t])}</td></tr>`).join("");
    const arts = m.articles.map((a) => `<li><a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.title)}</a> <span class="hint">${day(a.created_at)} · ${k(a.views)} views · ${a.followups.length} follow-ups, ${k(a.followup_views)} views</span>
      ${a.followups.length ? `<div class="pf-links">${a.followups.map((f) => `<a class="inl" href="${esc(f.url)}" target="_blank" rel="noopener">${f.kind} · ${k(f.views)}</a>`).join(" ")}</div>` : ""}</li>`).join("");
    const b = m.borrowed;
    const targets = b.top_targets.map(([t, n]) => `@${esc(t)} ×${n}`).join(", ");
    return `
      <div class="pf-who"><b>${esc(p.name)}</b> <span class="hint">@${esc(p.handle)}${p.verified ? " · verified" : ""} · joined ${p.joined ? new Date(p.joined).getFullYear() : "?"}</span><p>${richText(p.bio)}</p>
      ${p.pinned_url ? `<a class="inl" href="${esc(p.pinned_url)}" target="_blank" rel="noopener">pinned post</a>` : ""}</div>
      <div class="pf-stats">${stat(k(p.followers), "followers")}${stat(k(p.following), "following")}${stat(k(p.posts_total), "posts total")}
        ${stat(k(m.median_views_30), "median views, last 30")}${stat(pct(m.median_er), "median engagement")}${stat(m.median_bookmark_ratio ?? "?", "bookmarks / likes")}
        ${stat(m.breakouts, "breakouts, ≥5× median")}${stat(c.per_day, "posts per day")}</div>
      ${r ? section("Summary", r.summary.map((l) => `<p class="pf-line">${esc(l)}</p>`).join("")) : ""}
      ${section("Format mix", `<table class="pf-table"><thead><tr><th>Type</th><th class="n">Share</th><th class="n">Median views</th></tr></thead><tbody>${types}</tbody></table>`, `${c.posts} original posts and ${c.replies} replies over ${c.days} days`)}
      ${section("Posting hours, UTC", `<div class="pf-hours">${hours}</div>`)}
      ${arts ? section("Article chains", `<ul class="pf-list">${arts}</ul>`, "Own quotes, replies and links to the article within 7 days") : ""}
      ${section("Borrowed reach", `<p class="pf-line">${b.count} quotes or replies to accounts with at least ${k(b.threshold_followers)} followers, ${b.breakouts_on_event} of them breakouts.${targets ? ` Top targets: ${targets}.` : ""}</p>
        <p class="pf-line">Breakout rate within 72 h after such a post: ${b.rate_after == null ? "no data" : pct(b.rate_after)} (${b.posts_after} posts). Elsewhere: ${b.rate_other == null ? "no data" : pct(b.rate_other)} (${b.posts_other} posts).</p>`)}`;
  }

  function chart() {
    const pts = data.posts.filter((p) => p.views != null && p.created_at && ["post", "quote", "article", "thread"].includes(p.type))
      .map((p) => ({ ...p, t: +new Date(p.created_at) }));
    if (pts.length < 2) return `<div class="none">Not enough posts for a chart</div>`;
    const W = 680, H = 300, L = 44, R = 10, T = 22, B = 24;
    const t0 = pts[0].t, t1 = pts[pts.length - 1].t;
    const x = (t) => L + ((t - t0) / Math.max(t1 - t0, 1)) * (W - L - R);
    const hi = Math.ceil(Math.log10(Math.max(...pts.map((p) => p.views), 10)));
    const lo = Math.floor(Math.log10(Math.max(Math.min(...pts.map((p) => p.views)), 1)));
    const y = (v) => T + (1 - (Math.log10(Math.max(v, 1)) - lo) / Math.max(hi - lo, 1)) * (H - T - B);
    let grid = "";
    for (let e = lo; e <= hi; e++) grid += `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(10 ** e)}" y2="${y(10 ** e)}"/><text class="axis" x="${L - 6}" y="${y(10 ** e) + 4}" text-anchor="end">${k(10 ** e)}</text>`;
    const ticks = 5;
    for (let i = 0; i < ticks; i++) {
      const t = t0 + ((t1 - t0) * i) / (ticks - 1);
      grid += `<text class="axis" x="${x(t)}" y="${H - 6}" text-anchor="${i === 0 ? "start" : i === ticks - 1 ? "end" : "middle"}">${day(t)}</text>`;
    }
    const bands = data.metrics.phases.filter((ph) => ph.change !== "start").map((ph) => {
      const a = x(Math.max(+new Date(ph.start), t0)), b = x(Math.min(+new Date(ph.end), t1));
      return `<rect class="band ${ph.change}" x="${a}" y="${T}" width="${Math.max(b - a, 2)}" height="${H - T - B}"><title>${esc(ph.change)} ${ph.ratio}×, median ${k(ph.median_views)} views, ${ph.posts} posts (inferred)</title></rect>
        <text class="axis" x="${a + 4}" y="${T - 7}">${ph.change === "up" ? "up" : "down"} ${ph.ratio}×</text>`;
    }).join("");
    const line = (key, cls) => `<path class="${cls}" d="${pts.filter((p) => p[key] != null).map((p, i) => `${i ? "L" : "M"}${x(p.t).toFixed(1)} ${y(p[key]).toFixed(1)}`).join("")}"/>`;
    const dots = pts.filter((p) => !p.breakout).map((p) => `<circle class="dot" cx="${x(p.t).toFixed(1)}" cy="${y(p.views).toFixed(1)}" r="2.5"/>`).join("");
    const marks = pts.filter((p) => p.breakout).map((p) => {
      const cx = x(p.t), cy = y(p.views), s = 5.5;
      return `<path class="breakout" d="M${cx} ${cy - s}L${cx + s} ${cy}L${cx} ${cy + s}L${cx - s} ${cy}Z"/>`;
    }).join("");
    const legend = [["dot", "Post views"], ["med7", "Median, 7 posts"], ["med30", "Median, 30 posts"], ["brk", "Breakout, ≥5× median"], ["bnd", "Inferred phase"]]
      .map(([c, l]) => `<span><i class="lg ${c}"></i>${l}</span>`).join("");
    setTimeout(() => wireChart(pts, x, L, R, W), 0);
    return `<div class="pf-legend">${legend}</div>
      <div class="pf-chart" id="pfChart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Views per post over time on a log scale, with rolling medians, breakouts and inferred phases">
        ${bands}${grid}${dots}${line("median_7", "med7")}${line("median_30", "med30")}${marks}<line id="pfCross" class="cross hidden" y1="${T}" y2="${H - B}"/></svg>
        <div id="pfTip" class="pf-tip hidden"></div></div>`;
  }

  function wireChart(pts, x, L, R, W) {
    const box = $("pfChart");
    if (!box) return;
    const svg = box.querySelector("svg"), tip = $("pfTip"), cross = $("pfCross");
    let cur = null;
    box.onmousemove = (e) => {
      const b = svg.getBoundingClientRect();
      const vx = ((e.clientX - b.left) / b.width) * W;
      cur = pts.reduce((a, p) => Math.abs(x(p.t) - vx) < Math.abs(x(a.t) - vx) ? p : a, pts[0]);
      const cx = x(cur.t);
      cross.setAttribute("x1", cx); cross.setAttribute("x2", cx); cross.classList.remove("hidden");
      tip.innerHTML = `<b>${day(cur.created_at)} · ${esc(cur.type)}${cur.breakout ? " · breakout" : ""}</b><br>${num(cur.views)} views · ${cur.ratio ?? "?"}× median<br><span>${esc((cur.text || "").slice(0, 110))}</span>`;
      tip.classList.remove("hidden");
      const left = (cx / W) * b.width;
      tip.style.left = left > b.width / 2 ? "" : `${left + 12}px`;
      tip.style.right = left > b.width / 2 ? `${b.width - left + 12}px` : "";
    };
    box.onmouseleave = () => { cur = null; tip.classList.add("hidden"); cross.classList.add("hidden"); };
    box.onclick = () => { if (cur) window.open(cur.url, "_blank", "noopener"); };
  }

  function snapshotsBlock() {
    const snaps = data.snapshots || [];
    if (!snaps.length) return "";
    const opts = (sel) => snaps.map((s, i) => `<option value="${i}" ${i === sel ? "selected" : ""}>${new Date(s.ts).toLocaleString([], { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}</option>`).join("");
    return section("Real history: snapshots", snaps.length < 2
      ? `<p class="hint">One snapshot so far: followers ${num(snaps[0].followers)}. Each new scrape adds one, so a real follower history builds up from here.</p>`
      : `<div class="pf-compare"><select id="pfSnapA" aria-label="From snapshot">${opts(0)}</select><span class="hint">to</span><select id="pfSnapB" aria-label="To snapshot">${opts(snaps.length - 1)}</select></div><div id="pfDelta"></div>`);
  }

  function renderDelta() {
    const a = $("pfSnapA"), b = $("pfSnapB");
    if (!a) return;
    const s = data.snapshots, from = s[+a.value], to = s[+b.value];
    const row = (label, key) => {
      const d = from[key] != null && to[key] != null ? to[key] - from[key] : null;
      return `<tr><td>${label}</td><td class="n">${num(from[key])}</td><td class="n">${num(to[key])}</td><td class="n">${d == null ? "?" : (d > 0 ? "+" : "") + num(d)}</td></tr>`;
    };
    $("pfDelta").innerHTML = `<table class="pf-table"><thead><tr><th></th><th class="n">From</th><th class="n">To</th><th class="n">Change</th></tr></thead><tbody>${row("Followers", "followers")}${row("Following", "following")}${row("Posts", "posts_total")}${row("Median views, last 30", "median_views_30")}</tbody></table>`;
    a.onchange = b.onchange = renderDelta;
  }

  function growth() {
    const r = data.report, m = data.metrics;
    const conf = { high: "high", medium: "medium", guess: "guess" };
    const phases = r && r.phases.length ? r.phases.map((ph) => `<article class="pf-phase"><header><b>${day(ph.start)} – ${day(ph.end)}</b><span class="conf ${esc(ph.confidence)}">${conf[ph.confidence] || "guess"}</span></header>
        <p>${esc(ph.changed)}</p><p class="hint">Likely trigger: ${esc(ph.trigger)}</p><div class="pf-links">${postLinks(ph.post_ids)}</div></article>`).join("")
      : m.phases.map((ph) => `<article class="pf-phase"><header><b>${day(ph.start)} – ${day(ph.end)}</b></header><p>${ph.change === "start" ? "Start of data" : `Median ${ph.change} ${ph.ratio}×`}, median ${k(ph.median_views)} views, ${ph.posts} posts</p></article>`).join("");
    return `<p class="pf-note">${icon("triangle-alert")}<span><b>Inference.</b> X does not expose follower history. Phases come from the median views of original posts, not from follower counts.</span></p>
      ${chart()}
      ${section("Growth timeline", phases || `<div class="none">No phases: too few posts</div>`, r ? "Dates, causes and confidence are Claude's reading of the numbers" : "Local median steps only")}
      ${snapshotsBlock()}`;
  }

  function viral() {
    const m = byId(), r = data.report;
    const items = r && r.viral.length ? r.viral.map((v) => ({ v, p: m[v.post_id] })).filter((x) => x.p)
      : [...data.posts].filter((p) => p.ratio != null).sort((a, b) => b.ratio - a.ratio).slice(0, 10).map((p) => ({ v: null, p }));
    if (!items.length) return `<div class="none">No posts with views</div>`;
    setTimeout(() => {
      const box = $("pfViral");
      if (!box) return;
      items.forEach(({ v, p }) => {
        const age_min = (Date.now() - new Date(p.created_at)) / 60000;
        const el = card({ ...p, author: data.profile, age_min, score: `${Math.round(p.ratio)}×`, label: p.breakout ? "hot" : "normal", why: v ? v.why : "", parts: {} });
        el.querySelector(".seen-btn").remove();
        el.querySelector(".score").title = "views vs the rolling median of the previous 30 posts";
        if (v) {
          const facts = [["Hook", v.hook], ["Format", v.format], ["Topic", v.topic], ["Timing", v.timing], ["Borrowed reach", v.borrowed]].filter((f) => f[1]);
          el.querySelector(".body").insertAdjacentHTML("beforebegin", `<dl class="pf-facts">${facts.map(([a, b]) => `<dt>${a}</dt><dd>${esc(b)}</dd>`).join("")}</dl>`);
        }
        box.appendChild(el);
      });
    }, 0);
    return `${r ? "" : `<p class="hint">Top by ratio, without reasons: no Claude analysis in this record.</p>`}<div id="pfViral" class="pf-cards"></div>`;
  }

  function patterns() {
    const r = data.report;
    if (!r) return noReport();
    const list = (t, xs, hint) => xs.length ? section(t, `<ul class="pf-list">${xs.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`, hint) : "";
    return list("Hook types", r.hooks) + list("Opening lines", r.openers, "Templates, not quotes") + list("Post structures", r.structures) + list("CTAs", r.ctas) + list("What consistently flops", r.flops);
  }

  const doneKey = () => `pf-done-${data.profile.handle}-${data.id}`;
  function doneSet() { try { return new Set(JSON.parse(localStorage.getItem(doneKey()) || "[]")); } catch { return new Set(); } }

  function repeat() {
    const r = data.report;
    if (!r) return noReport();
    const done = doneSet();
    const items = r.repeat.map((x, i) => `<li class="pf-check ${done.has(i) ? "done" : ""}"><label><input type="checkbox" data-i="${i}" ${done.has(i) ? "checked" : ""}><span><b>${esc(x.item)}</b><span class="pf-test">Test in one week: ${esc(x.test)}</span></span></label>
      <button class="link pf-copy" data-i="${i}" title="Copy tactic and test" aria-label="Copy tactic and test">${icon("copy")}</button><div class="pf-links">${postLinks(x.post_ids)}</div></li>`).join("");
    const dont = r.dont.map((x) => `<li><b>${esc(x.tactic)}</b><span class="hint"> ${esc(x.why)}</span></li>`).join("");
    setTimeout(() => {
      document.querySelectorAll(".pf-check input").forEach((c) => (c.onchange = () => {
        const s = doneSet();
        c.checked ? s.add(+c.dataset.i) : s.delete(+c.dataset.i);
        try { localStorage.setItem(doneKey(), JSON.stringify([...s])); } catch {}
        c.closest(".pf-check").classList.toggle("done", c.checked);
      }));
      document.querySelectorAll(".pf-copy").forEach((b) => (b.onclick = () => {
        const x = r.repeat[+b.dataset.i];
        navigator.clipboard.writeText(`${x.item}\n${x.test}`).then(() => { b.classList.add("copied"); setTimeout(() => b.classList.remove("copied"), 1200); });
      }));
    }, 0);
    return (items ? section("Repeat on my account", `<ul class="pf-checks">${items}</ul>`, "Tactics and structures only, adapted to About me") : "") + (dont ? section("Don't copy", `<ul class="pf-list">${dont}</ul>`) : "");
  }

  function sorted() {
    const { key, dir } = sort;
    return [...data.posts].sort((a, b) => {
      const x = a[key], y = b[key];
      if (x == null) return 1;
      if (y == null) return -1;
      return (x > y ? 1 : x < y ? -1 : 0) * dir;
    });
  }

  function raw() {
    const cell = (p, key) => {
      if (key === "created_at") return `<a href="${esc(p.url)}" target="_blank" rel="noopener">${esc((p.created_at || "").slice(0, 10))}</a>`;
      if (key === "text") return esc((p.text || "").replace(/\s+/g, " ").slice(0, 120));
      if (key === "er") return p.er == null ? "" : pct(p.er);
      return esc(p[key] == null ? "" : String(p[key]));
    };
    const numeric = new Set(["views", "likes", "replies", "reposts", "quotes", "bookmarks", "er", "ratio"]);
    setTimeout(() => {
      document.querySelectorAll(".pf-raw th button").forEach((b) => (b.onclick = () => {
        sort = { key: b.dataset.k, dir: sort.key === b.dataset.k ? -sort.dir : -1 };
        render();
      }));
      $("pfCsv").onclick = csv;
    }, 0);
    const arrow = (key) => sort.key === key ? (sort.dir > 0 ? " ↑" : " ↓") : "";
    return `<div class="pf-raw-head"><span class="hint">${data.posts.length} posts</span><button id="pfCsv" class="ghost small">${icon("download")} CSV</button></div>
      <div class="pf-raw"><table class="pf-table"><thead><tr>${COLUMNS.map(([key, l]) => `<th class="${numeric.has(key) ? "n" : ""}" aria-sort="${sort.key === key ? (sort.dir > 0 ? "ascending" : "descending") : "none"}"><button class="link" data-k="${key}">${l}${arrow(key)}</button></th>`).join("")}</tr></thead>
      <tbody>${sorted().map((p) => `<tr class="${p.breakout ? "brk" : ""}">${COLUMNS.map(([key]) => `<td class="${numeric.has(key) ? "n" : key === "text" ? "t" : ""}">${cell(p, key)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  }

  function csv() {
    const keys = ["id", "url", "created_at", "type", "media_type", "has_link", "quoted_handle", "quoted_followers", "reply_to_handle", "reply_to_followers", "views", "likes", "replies", "reposts", "quotes", "bookmarks", "er", "bookmark_ratio", "median_7", "median_30", "ratio", "breakout", "text"];
    // leading = + - @ would run as a formula in a spreadsheet: post text is someone else's
    const q = (v) => { let s = v == null ? "" : String(v); if (/^[=+\-@\t\r]/.test(s)) s = "'" + s; return `"${s.replace(/"/g, '""')}"`; };
    const body = [keys.join(","), ...data.posts.map((p) => keys.map((key) => q(p[key])).join(","))].join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([body], { type: "text/csv" }));
    a.download = `${data.profile.handle}-${data.id}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  const RENDER = { overview, growth, viral, patterns, repeat, raw };

  function render() {
    const meta = $("pfMeta"), tabs = $("pfTabs"), body = $("pfBody");
    $("pfRe").disabled = !data;
    if (!data) {
      meta.innerHTML = ""; tabs.innerHTML = "";
      body.innerHTML = `<div class="empty"><h2>No analysis open</h2><p>Type an X handle and press Analyze. It reads up to 300 posts at a human pace, usually a few minutes.</p></div>`;
      return;
    }
    const s = data.stats || {}, c = s.claude;
    const item = (v, l, cls = "") => v == null ? "" : `<span class="${cls}"><b>${v}</b> ${l}</span>`;
    meta.innerHTML = [item(`@${esc(data.profile.handle)}`, day(data.created_at)), item(s.posts, "posts"),
      c ? item(`${k(c.input_tokens)} / ${k(c.output_tokens)}`, "tokens in / out") : "", c ? item(`$${c.cost_usd_equiv.toFixed(2)}`, "at API prices") : "",
      item(dur(s.total_s), "total"), s.reanalyzed_from ? item("re-analysis", "no scraping") : "",
      STATUS[data.status] ? item(STATUS[data.status], "", "error") : "", s.claude_error ? item("Claude failed", "metrics only", "error") : ""].filter(Boolean).join("");
    tabs.innerHTML = "";
    for (const [key, label] of TABS) {
      const b = document.createElement("button");
      b.textContent = label; b.className = key === tab ? "active" : "";
      b.onclick = () => { tab = key; render(); };
      tabs.appendChild(b);
    }
    body.innerHTML = RENDER[tab]();
    if (tab === "growth") renderDelta();
  }

  async function loadHistory(selectId) {
    const list = await api("/api/profiles");
    const sel = $("pfHistory");
    sel.innerHTML = list.length ? list.map((h) => `<optgroup label="@${esc(h.handle)}">${h.analyses.map((a) =>
      `<option value="${esc(h.handle)}/${esc(a.id)}">@${esc(h.handle)} · ${new Date(a.created_at).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })} · ${a.posts} posts${a.has_report ? "" : " · metrics only"}</option>`).join("")}</optgroup>`).join("")
      : `<option value="">No analyzed profiles</option>`;
    sel.disabled = !list.length;
    if (selectId) sel.value = selectId;
    if (sel.value) await open(sel.value); else { data = null; render(); }
  }

  async function open(ref) {
    const [h, id] = ref.split("/");
    data = await api(`/api/profiles/${encodeURIComponent(h)}/analyses/${encodeURIComponent(id)}`);
    $("pfHandle").value = data.profile.handle;
    render();
  }

  window.profilePanel = {
    async onState(s) {
      const job = s.running && s.kind === "profile";
      const busy = s.running || s.login === "waiting" || s.login === "checking";
      $("pfGo").disabled = busy; $("pfRe").disabled = busy || !data;
      $("pfGo").classList.toggle("hidden", job); $("pfStop").classList.toggle("hidden", !job);
      $("pfProgress").classList.toggle("hidden", !job);
      if (job) {
        $("pfStep").textContent = `${s.step || "starting"}…`;
        $("pfBar").style.width = `${Math.round((s.progress || 0.02) * 100)}%`;
        const el = Math.round(Date.now() / 1000 - s.started), left = s.eta_s ? Math.max(s.eta_s - el, 0) : null;
        const fmt = (x) => x < 60 ? `${x}s` : `${Math.floor(x / 60)}m ${String(x % 60).padStart(2, "0")}s`;
        $("pfTiming").textContent = `${Math.round((s.progress || 0) * 100)}% · ${fmt(el)}` + (left != null ? ` · ~${left ? fmt(left) : "almost done"} left` : "");
        $("pfLog").textContent = (s.log || []).slice(-6).join("\n");
      }
      if (wasJob && !job && s.kind === "profile") {
        await loadHistory(s.analysis_id ? `${s.handle}/${s.analysis_id}` : undefined);
        if (s.error && !STATUS[s.error]) alert(s.error);
      }
      wasJob = job;
      // a job in the other section keeps Run and Analyze disabled: show why in the sidebar
      $("navProfiles").querySelector(".nav-busy").classList.toggle("hidden", !job);
      $("navFeed").querySelector(".nav-busy").classList.toggle("hidden", !(s.running && s.kind !== "profile"));
    },
  };

  $("pfForm").onsubmit = (e) => {
    e.preventDefault();
    const handle = $("pfHandle").value.trim();
    if (handle) act(() => post("/api/profiles/analyze", { handle }))();
  };
  $("pfStop").onclick = act(() => post("/api/stop"));
  $("pfRe").onclick = () => { if (data) act(() => post(`/api/profiles/${data.profile.handle}/analyses/${data.id}/reanalyze`))(); };
  $("pfHistory").onchange = (e) => { if (e.target.value) open(e.target.value); };
  loadHistory();
})();
