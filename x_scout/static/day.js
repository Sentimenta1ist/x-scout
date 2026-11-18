// Staged daily run: one tab per stage (News, Big accounts, Viral, Trash, Topics) and a Checklist.
// Tabs fill up while the run goes on; every card has a "done" box, boxes belong to the run, so a new Run starts clean.
(() => {
  const STAGES = [
    ["news", "News", "at most 1 own post a day; reply here only while the post is under 3h"],
    ["big", "Big accounts", "the main source: reply while the post is under 3h and the thread is quiet"],
    ["viral", "Viral", "formats to learn from, too old to reply under"],
    ["trash", "Trash", "replies under smaller posts that are taking off, stay under the limit"],
    ["topics", "Topics", "what survived your topics"],
  ];
  const LABEL = Object.fromEntries(STAGES.map(([k, l]) => [k, l]));
  const FIELDS = {
    news: [["say", "say"], ["take", "post"]],
    big: [["say", "say"], ["ask", "ask"]],
    viral: [["grok", "grok"], ["rewrite", "yours"], ["opposite", "quote"], ["opinion", "topic"]],
    trash: [["say", "say"]],
  };
  // the three checks before a reply (scoring.reply_fit); age is recomputed from created_at: a card cools while you read
  const REPLY_STAGES = new Set(["news", "big", "trash"]);
  const ageNow = (p) => p.created_at ? (Date.now() - Date.parse(p.created_at)) / 60000 : p.age_min;
  function coldWhy(p) {
    if (p.trend) return [];
    const why = p.fit ? p.fit.why.filter((w) => w !== "older than 3h") : [];  // runs before 2026-11-17 have no fit: age only
    const a = ageNow(p);
    if (a == null || a > 180) why.unshift("older than 3h");
    return why;
  }
  const RUN_STALE_MIN = 180;
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
    lab.innerHTML = `<input type="checkbox" ${checks()[key] ? "checked" : ""}>${title ? `<span>${title}</span>` : ""}`;
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
      meta = [`<b>${esc(name)}</b>`, `@${esc(p.author.handle)}`, `${k(p.author.followers)} followers`, `${age(ageNow(p))} ago`,
              `${k(p.views)} views`, `${k(p.replies)} replies`, p.fit ? `${p.fit.crowd}/10k` : ""].filter(Boolean).join(" · ");
      url = p.url;
    }
    const head = p.gist || (p.trend ? p.trend.name : (p.text || "").split("\n")[0].slice(0, 220));
    const list = drafts(p);
    const cold = coldWhy(p);
    const hideDrafts = cold.length && REPLY_STAGES.has(p.stage);
    if (hideDrafts) el.classList.add("cold");
    const isReply = ([kind]) => kind === "say" || kind === "ask";
    const ul = (l) => l.length ? `<ul class="freplies">${l.map(([kind, t]) => `<li><span class="fkind">${kind}</span><span class="ftext">${esc(t)}</span></li>`).join("")}</ul>` : "";
    const draftList = ul(list);
    const extra = [p.format ? `<span class="dfmt">${esc(p.format)}</span>` : "", p.repeat ? `<span class="drep">${esc(p.repeat)}</span>` : ""].join("");
    el.innerHTML = `
      <div class="fmeta-row">
        <span class="fwho">${meta}</span>
        ${p.q >= 5 ? `<span class="ftop" title="Claude: do this first">top</span>` : ""}
        ${p.local ? `<span class="ftop warn" title="Claude failed: local order, no drafts">local</span>` : ""}
        ${cold.length ? `<span class="ftop warn" title="${esc(cold.join(", "))}">${REPLY_STAGES.has(p.stage) ? "cold" : "too late to reply"}</span>` : ""}
        <a class="fopen" href="${url}" target="_blank" rel="noopener" title="Open on X">↗</a>
      </div>
      <p class="fgist">${esc(head)}</p>
      ${p.why ? `<p class="fwhy">${esc(p.why)}</p>` : ""}
      ${extra ? `<p class="dline">${extra}</p>` : ""}
      ${hideDrafts ? (list.some(isReply) ? `<details class="fcold"><summary>${esc(cold.join(" · "))}: replies hidden</summary>${ul(list.filter(isReply))}</details>` : `<p class="fnone">${esc(cold.join(" · "))}</p>`) + ul(list.filter((d) => !isReply(d))) : draftList}
      <details class="fmore">
        <summary><span class="fnums">${p.trend ? "" : `${k(p.views)} views · ${k(p.likes)} likes · ${k(p.replies)} replies · ${k(p.bookmarks)} saves`}</span><span class="fopen-label">Breakdown</span></summary>
        ${p.context ? `<div class="fd"><span>What is going on</span><p>${esc(p.context)}</p></div>` : ""}
        ${p.trend ? `<div class="fd"><span>Trend</span><p>${esc(p.trend.name)}${p.trend.context ? ` — ${esc(p.trend.context)}` : ""}</p></div>`
                  : `<div class="fd"><span>Post</span><p class="ftext-full">${richText(p.text)}</p>${p.quoted ? `<p class="fquoted">${richText(p.quoted.slice(0, 600))}</p>` : ""}</div>`}
      </details>`;
    const shown = hideDrafts ? [...list.filter(isReply), ...list.filter((d) => !isReply(d))] : list;
    el.querySelectorAll(".freplies li").forEach((li, i) => {
      li.appendChild(copyBtn(shown[i][1]));
      if (REPLY_STAGES.has(p.stage) && !p.trend && isReply(shown[i])) li.appendChild(typeBtn(p, li));
    });
    el.querySelector(".fmeta-row").insertBefore(box(key), el.querySelector(".fopen"));
    return el;
  }

  // ---- type: the draft (edited in place) is typed into X key by key, the owner presses Reply ----
  const TYPE_LABEL = { queued: "opening…", typing: "typing…", waiting: "press Reply in that tab", sent: "sent ✓", already: "already replied ✓", error: "failed" };
  let typing = null;  // {key, status}

  function typeBtn(p, li) {
    const t = li.querySelector(".ftext");
    t.contentEditable = "plaintext-only";
    t.spellcheck = false;
    t.title = "Edit before typing";
    const b = document.createElement("button");
    b.className = "ftype";
    b.textContent = typing && typing.key === p.key ? (TYPE_LABEL[typing.status] || "type") : "type";
    b.title = "Opens the post in a new tab; the x-scout typer extension types this draft, you press Reply";
    b.onclick = async (e) => {
      e.stopPropagation();
      const tab = window.open("about:blank", "_blank");  // opened inside the click, so it is not blocked as a popup
      try {
        const r = await post("/api/type", { run_id: current.id, id: p.id, url: p.url, key: p.key, stage: p.stage,
                                            author: p.author.handle, draft: t.innerText.trim() });
        tab.location = r.url + "#xscout";
        typing = { key: p.key, status: "queued" };
        b.textContent = TYPE_LABEL.queued;
        pollType(b, Date.now());
      } catch (err) { tab && tab.close(); b.textContent = "failed"; b.title = String(err); }
    };
    return b;
  }

  async function pollType(b, t0) {
    let s;
    try { s = await api("/api/type"); } catch { return; }
    typing = { key: s.key, status: s.status };
    b.textContent = TYPE_LABEL[s.status] || "type";
    if (s.error) b.title = s.error;
    if (s.status === "waiting" && s.exact === false) { b.textContent = "check the text in that tab"; b.title = `in the box: ${s.typed || ""}`; }
    if (s.status === "queued" && Date.now() - t0 > 30000) { b.textContent = "no extension?"; b.title = "Load extension/ in chrome://extensions (Load unpacked)"; return; }
    if (s.status === "sent" || s.status === "already") {
      current.checks = (await api(`/api/runs/${current.id}`)).checks;
      typing = null;
      window.renderBoard();
      return;
    }
    if (s.status !== "error" && Date.now() - t0 < 20 * 60000) setTimeout(() => pollType(b, t0), 1500);
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
    if (REPLY_STAGES.has(stage) && picks.length) {
      const ref = run.finished_at || run.started_at;
      const mins = ref ? (Date.now() - Date.parse(ref)) / 60000 : 0;
      if (mins > RUN_STALE_MIN) sec.insertAdjacentHTML("beforeend", `<p class="fnone warn">This run is ${age(mins)} old: these posts have cooled. Press Run for fresh ones.</p>`);
    }
    // cold cards sink to the bottom, Claude's order stays within each group
    const order = REPLY_STAGES.has(stage) ? [...picks].sort((a, b) => (coldWhy(a).length > 0) - (coldWhy(b).length > 0)) : picks;
    order.forEach((p) => sec.appendChild(stageCard(p)));
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
    const replies = ["big", "trash", "news"].reduce((n, s) => n + doneIn(s).length, 0);
    out.push({ label: "Replies in sessions of 8–10, each under a post < 3h with a quiet thread", have: replies, need: 8 });
    if (st.big) out.push({ label: "From Big accounts", have: doneIn("big").length, need: 5, who: names("big") });
    if (st.trash) out.push({ label: `Trash replies, up to ${limit}`, have: doneIn("trash").length, need: Math.min(2, limit), max: limit, who: names("trash") });
    out.push({ label: "At most 1 own post today (quote only on a big-event day)", key: "m:post" });
    out.push({ label: "Stop rule: two days in a row with a median under 60 views per reply → back to 20–25 a day", key: "m:stop" });
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
        if (it.rec) li.title = "Claude's recommendation";
        const b = box(it.key, "");
        b.classList.add("cbox");
        li.appendChild(b);
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
