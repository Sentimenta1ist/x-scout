// Staged daily run: one tab per stage (News, Big accounts, Viral, Trash, Topics) and a Checklist.
// Tabs fill up while the run goes on; every card has a "done" box, boxes belong to the run, so a new Run starts clean.
(() => {
  const STAGES = [
    ["news", "News", "post 3 of these today"],
    ["big", "Big accounts", "early replies under big accounts: 2–3"],
    ["viral", "Viral", "formats to repeat: tomorrow's 3 @grok + 3 opinions"],
    ["trash", "Trash", "short replies for volume, stay under the limit"],
    ["topics", "Topics", "what survived your topics"],
  ];
  const LABEL = Object.fromEntries(STAGES.map(([k, l]) => [k, l]));
  const FIELDS = {
    news: [["take", "post"]],
    big: [["say", "say"], ["ask", "ask"]],
    viral: [["grok", "grok"], ["rewrite", "yours"], ["opposite", "quote"], ["opinion", "topic"]],
    trash: [["say", "say"]],
  };
  let active = null;
  let own = null; // {handle, last}

  const checks = () => (current && current.checks) || {};
  const doneIn = (stage) => Object.keys(checks()).filter((k) => k.startsWith(stage + ":"));

  async function setCheck(key, done) {
    const run = current;
    run.checks = await post(`/api/runs/${run.id}/checks`, { key, done });
    window.renderBoard();
  }

  function box(key, title = "done") {
    const lab = document.createElement("label");
    lab.className = "dchk";
    lab.title = title;
    lab.innerHTML = `<input type="checkbox" ${checks()[key] ? "checked" : ""}><span>${title}</span>`;
    lab.querySelector("input").onchange = (e) => setCheck(key, e.target.checked);
    return lab;
  }

  function status(st) {
    if (!st) return "";
    if (st.status === "ready") return `<span class="count">${st.count ?? 0}</span>`;
    if (st.status === "skipped") return `<span class="count">–</span>`;
    if (st.status === "error") return `<span class="count err">!</span>`;
    return `<span class="sdot ${st.status}" title="${esc(st.status)}"></span>`;
  }

  function tabs(run) {
    const nav = $("stageTabs");
    nav.innerHTML = "";
    const st = run.stages || {};
    const shown = STAGES.filter(([k]) => st[k] || k === "topics" && run.result);
    if (!active || (active !== "check" && !shown.find(([k]) => k === active))) {
      active = (shown.find(([k]) => (st[k] || {}).status === "ready") || shown[0] || ["check"])[0];
    }
    for (const [k, label] of shown) {
      const b = document.createElement("button");
      const done = doneIn(k).length;
      b.innerHTML = `${label}${status(st[k])}${done ? `<span class="dn">✓${done}</span>` : ""}`;
      b.className = k === active ? "active" : "";
      b.onclick = () => { active = k; window.renderBoard(); };
      nav.appendChild(b);
    }
    const c = document.createElement("button");
    const [ok, total] = checklistScore(run);
    c.innerHTML = `Checklist<span class="count">${ok}/${total}</span>`;
    c.className = "check-tab" + (active === "check" ? " active" : "");
    c.onclick = () => { active = "check"; window.renderBoard(); };
    nav.appendChild(c);
    return active;
  }

  function drafts(p) {
    const out = [];
    for (const [key, label] of FIELDS[p.stage] || []) {
      const v = p[key];
      for (const t of Array.isArray(v) ? v : v ? [v] : []) out.push([label, t]);
    }
    return out;
  }

  function stageCard(p) {
    const el = document.createElement("article");
    const key = p.key;
    el.className = "fpick dcard" + (checks()[key] ? " seen" : "");
    let meta, url;
    if (p.trend) {
      meta = `<b>trend</b>${p.trend.meta ? ` · ${esc(p.trend.meta)}` : ""}`;
      url = `https://x.com/search?q=${encodeURIComponent(p.trend.name)}&src=trend_click`;
    } else {
      const name = (p.author.name || p.author.handle).replace(/\s*\(.*?\)\s*/g, " ").trim();
      meta = [`<b>${esc(name)}</b>`, `@${esc(p.author.handle)}`, `${k(p.author.followers)} followers`, age(p.age_min),
              `${k(p.views)} views`, `${k(p.replies)} replies`].join(" · ");
      url = p.url;
    }
    const head = p.gist || (p.trend ? p.trend.name : (p.text || "").split("\n")[0].slice(0, 220));
    const list = drafts(p);
    const extra = [p.format ? `<span class="dfmt">${esc(p.format)}</span>` : "", p.repeat ? `<span class="drep">${esc(p.repeat)}</span>` : ""].join("");
    el.innerHTML = `
      <div class="fmeta-row">
        <span class="fwho">${meta}</span>
        ${p.q >= 5 ? `<span class="ftop" title="Claude: do this first">top</span>` : ""}
        ${p.local ? `<span class="ftop warn" title="Claude failed: local order, no drafts">local</span>` : ""}
        <a class="fopen" href="${url}" target="_blank" rel="noopener" title="Open on X">↗</a>
      </div>
      <p class="fgist">${esc(head)}</p>
      ${p.why ? `<p class="fwhy">${esc(p.why)}</p>` : ""}
      ${extra ? `<p class="dline">${extra}</p>` : ""}
      ${list.length ? `<ul class="freplies">${list.map(([kind, t]) => `<li><span class="fkind">${kind}</span><span class="ftext">${esc(t)}</span></li>`).join("")}</ul>` : ""}
      <details class="fmore">
        <summary><span class="fnums">${p.trend ? "" : `${k(p.views)} views · ${k(p.likes)} likes · ${k(p.replies)} replies · ${k(p.bookmarks)} saves`}</span><span class="fopen-label">Breakdown</span></summary>
        ${p.context ? `<div class="fd"><span>What is going on</span><p>${esc(p.context)}</p></div>` : ""}
        ${p.trend ? `<div class="fd"><span>Trend</span><p>${esc(p.trend.name)}${p.trend.context ? ` — ${esc(p.trend.context)}` : ""}</p></div>`
                  : `<div class="fd"><span>Post</span><p class="ftext-full">${richText(p.text)}</p>${p.quoted ? `<p class="fquoted">${richText(p.quoted.slice(0, 600))}</p>` : ""}</div>`}
      </details>`;
    el.querySelectorAll(".freplies li").forEach((li, i) => li.appendChild(copyBtn(list[i][1])));
    el.querySelector(".fmeta-row").insertBefore(box(key), el.querySelector(".fopen"));
    return el;
  }

  function renderStage(run, stage) {
    const board = $("board");
    const st = (run.stages || {})[stage] || {};
    const sub = (STAGES.find(([k2]) => k2 === stage) || [])[2] || "";
    const sec = document.createElement("section");
    sec.className = "fsec";
    const picks = st.picks || [];
    sec.innerHTML = `<h2>${LABEL[stage]}<span class="n">${picks.length}</span><span class="sub">${esc(sub)}</span></h2>`;
    if (st.status && st.status !== "ready") {
      const what = { waiting: "Waiting for its turn.", scraping: "Searching X…", analyzing: "Claude is reading it…", skipped: "Skipped: the run stopped before this stage.", error: "Failed." }[st.status] || st.status;
      sec.insertAdjacentHTML("beforeend", `<p class="fnone">${esc(what)}${st.error ? " " + esc(st.error) : ""}</p>`);
    } else if (!picks.length) {
      sec.insertAdjacentHTML("beforeend", `<p class="fnone">Nothing strong enough in this run.</p>`);
    }
    if (stage === "trash") {
      const limit = (window.settingsCache || {}).trash_limit || 3;
      const n = doneIn("trash").length;
      if (n > limit) sec.insertAdjacentHTML("beforeend", `<p class="fnone warn">${n} trash replies today, limit ${limit}. Stop here.</p>`);
    }
    if (st.error && st.status === "ready") sec.insertAdjacentHTML("beforeend", `<p class="fnone">Claude failed here: local order, no drafts. ${esc(st.error)}</p>`);
    picks.forEach((p) => sec.appendChild(stageCard(p)));
    board.appendChild(sec);
  }

  // ---- checklist ----
  function names(stage) {
    const picks = stage === "topics" ? [] : (((current.stages || {})[stage] || {}).picks || []);
    return doneIn(stage).map((key) => {
      const p = picks.find((x) => x.key === key);
      return p ? (p.author ? "@" + p.author.handle : p.trend ? p.trend.name : key) : key.split(":").pop();
    });
  }

  function items(run) {
    const st = run.stages || {};
    const limit = (window.settingsCache || {}).trash_limit || 3;
    const out = [];
    if (st.news) out.push({ label: "3 posts on hot news, posted today", have: doneIn("news").length, need: 3, who: names("news") });
    out.push({ label: "6 posts for tomorrow in the X scheduler (3 @grok + 3 opinions)", key: "m:plan",
               note: st.viral ? `${doneIn("viral").length} taken from Viral` : "" });
    if (st.big) out.push({ label: "2–3 replies under big accounts", have: doneIn("big").length, need: 2, who: names("big") });
    if (st.trash) out.push({ label: `Trash replies, up to ${limit}`, have: doneIn("trash").length, need: Math.min(2, limit), max: limit, who: names("trash") });
    out.push({ label: "Yesterday's scheduled posts went out", key: "m:yesterday" });
    if (own && own.handle) {
      const days = own.last ? Math.floor((Date.now() - new Date(own.last)) / 864e5) : null;
      if (days == null || days >= 7) out.push({ label: `Weekly: analyze @${own.handle} in Profiles`, key: "m:profile", note: days == null ? "never analyzed" : `last ${days} days ago` });
    }
    ((st.summary || {}).recs || []).forEach((r, i) => out.push({ label: r, key: `rec:${i}`, rec: true }));
    return out;
  }

  function checklistScore(run) {
    const list = items(run);
    const ok = list.filter((it) => it.key ? checks()[it.key] : it.have >= it.need).length;
    return [ok, list.length];
  }

  function renderChecklist(run) {
    const board = $("board");
    const sum = (run.stages || {}).summary;
    if (sum && (sum.lines || []).length) {
      const s = document.createElement("section");
      s.className = "fsec";
      s.innerHTML = `<h2>Today</h2><ul class="dsum">${sum.lines.map((l) => `<li>${esc(l)}</li>`).join("")}</ul>`;
      board.appendChild(s);
    } else if (run.status === "running") {
      board.insertAdjacentHTML("beforeend", `<p class="fnone">The summary comes when the run finishes. The list below fills as you tick cards.</p>`);
    }
    const sec = document.createElement("section");
    sec.className = "fsec";
    sec.innerHTML = `<h2>Checklist</h2>`;
    const ul = document.createElement("ul");
    ul.className = "clist";
    for (const it of items(run)) {
      const li = document.createElement("li");
      if (it.key) {
        li.className = (checks()[it.key] ? "ok" : "") + (it.rec ? " rec" : "");
        li.appendChild(box(it.key, it.rec ? "Claude" : "done"));
        li.insertAdjacentHTML("beforeend", `<span class="cl">${esc(it.label)}${it.note ? ` <i>${esc(it.note)}</i>` : ""}</span>`);
      } else {
        const ok = it.have >= it.need, over = it.max != null && it.have > it.max;
        li.className = ok ? "ok" : "";
        li.innerHTML = `<span class="cnt${over ? " over" : ""}">${it.have}${it.max != null ? "/" + it.max : "/" + it.need}</span>
          <span class="cl">${esc(it.label)}${it.who && it.who.length ? ` <i>${esc(it.who.join(", "))}</i>` : ""}</span>`;
      }
      ul.appendChild(li);
    }
    sec.appendChild(ul);
    board.appendChild(sec);
  }

  window.dayView = {
    // → true when it rendered the board; false → caller renders the topics board
    render(run) {
      $("stageTabs").classList.remove("hidden");
      const stage = tabs(run);
      if (stage === "topics") return false;
      $("tabs").innerHTML = "";
      if (stage === "check") renderChecklist(run); else renderStage(run, stage);
      return true;
    },
    box,
    hide() { $("stageTabs").classList.add("hidden"); $("stageTabs").innerHTML = ""; },
    async loadOwn() { try { own = await api("/api/own"); } catch { own = null; } },
  };
})();
