"""scrape → score → pick candidates → claude -p per topic → up to 6 posts to reply to and 6 to save per topic."""
import asyncio
import json
import time
from datetime import datetime, timedelta, timezone

from . import analyze, browser, db, post_analysis, profile_analysis, profile_metrics, profile_store, stages as stg
from .config import PROFILE_MD, ROOT, SETTINGS_JSON
from .parse import age_minutes, explore_items, finalize_timeline
from .scoring import project_views, score

DEFAULT_SETTINGS = {
    "topics": [{"name": "AI agents", "query": ""}, {"name": "Automation", "query": ""}],
    "lang": "en",
    "per_mode": 50,          # posts per search tab (Top and Latest) per topic; extra queries read 2/3 of it
    "candidates": 50,        # posts per topic sent to Claude
    "headless": True,
    "model": "sonnet",
    "gist_lang": "English",  # language of the short per-post summary
    # profile analysis
    "profile_max_posts": 300,
    "profile_max_days": 120,
    "profile_max_replies": 60,   # 0 = skip the replies tab
    "profile_model": "sonnet",
    # staged daily run
    "stages": {"news": True, "big": True, "viral": True, "trash": True, "topics": True},
    "big_accounts": [],          # empty = stages.BIG_ACCOUNTS
    "trash_limit": 3,            # trash replies a day; the checklist warns above it
    "topic_extra_queries": False,  # topics stage: main + author searches only, extras cost too much rate limit
    "search_pause": [10, 20],    # seconds between two searches of a staged run
    "own_handle": "sentimentGod",
}
MAX_TOPICS = 10

# live state of the current run, polled by the UI
# kind: "run" (topic search), "profile" or "post"; one job at a time, they share Chrome and Stop
state = {"running": False, "kind": "run", "run_id": None, "step": "", "log": [], "progress": 0.0, "eta_s": None, "started": None,
         "handle": None, "analysis_id": None, "post_key": None, "error": None, "stages": {}}
_task = None  # asyncio task of the current run, for Stop


def stop():
    """Cancel the current run or re-analyze: closes the browser and kills claude -p. Returns False if nothing is running."""
    if not state["running"] or not _task:
        return False
    state["step"] = "stopping"
    analyze.stop_claude()
    _task.cancel()
    return True


def _progress(done, total, step):
    state.update(progress=round(min(done / total, 1), 3), step=step)


def load_settings():
    try:
        return {**DEFAULT_SETTINGS, **json.loads(SETTINGS_JSON.read_text())}
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(DEFAULT_SETTINGS)


def save_settings(s):
    s = {**DEFAULT_SETTINGS, **s}
    s["topics"] = [t for t in s["topics"] if t.get("name", "").strip()][:MAX_TOPICS]
    SETTINGS_JSON.write_text(json.dumps(s, indent=2))
    return s


def load_profile():
    if PROFILE_MD.exists():
        return PROFILE_MD.read_text()
    return (ROOT / "profile.example.md").read_text()


def _log(msg):
    stamp = datetime.now().strftime("%H:%M:%S")
    state["log"].append(f"{stamp} {msg}")
    state["log"] = state["log"][-200:]


def score_posts(posts):
    now = datetime.now(timezone.utc)
    for p in posts:
        p["age_min"] = age_minutes(p, now)
        if p["age_min"] is None or p.get("views") is None:
            p["scored"] = {"score": 0, "label": "low-data", "parts": {}}
            continue
        hist = [project_views(h["views"], h["age_min"]) for h in db.author_history(p["author"]["handle"], p["id"])
                if h["views"] and h["age_min"]]
        prev = db.last_snapshot(p["id"])
        ctx = {"author_projected": hist, "followers": p["author"]["followers"],
               "prev": prev if prev and prev.get("age_min") is not None else None}
        p["scored"] = score({**p, "age_min": p["age_min"]}, ctx)
    return posts


def analyze_candidates(candidates, settings):
    n = sum(len(v) for v in candidates.values())
    _log(f"claude -p ({settings['model']}): {n} posts, one call per topic, {analyze.PARALLEL} at a time")
    result, usage, errors = analyze.rank_topics(load_profile(), candidates, model=settings["model"],
                                                gist_lang=settings["gist_lang"], log=_log)
    _log(f"claude done: in {usage['input_tokens']} / out {usage['output_tokens']} tokens, {usage['duration_s']}s")
    return result, usage, errors


def _eta(n_topics):
    """Rough duration from the last finished run, scaled by topic count."""
    for r in db.list_runs(10):
        s = r.get("stats") or {}
        if r["status"] == "done" and s.get("total_s") and r.get("topics"):
            return round(s["total_s"] / len(r["topics"]) * n_topics)
    return 60 * n_topics


async def run(settings):
    global _task
    _task = asyncio.current_task()
    topics = settings["topics"][:MAX_TOPICS]
    state.update(running=True, kind="run", step="starting", log=[], progress=0.0, eta_s=_eta(len(topics)), started=time.time())
    t0 = time.time()
    stats = {}
    run_id = db.create_run(topics)
    state["run_id"] = run_id
    try:
        # an empty query, or a topic that never got extra queries ("extra" absent) → Claude writes them once
        missing = [t for t in topics if not (t.get("query") or "").strip() or "extra" not in t]
        if missing:
            _progress(0, 1, "writing search queries")
            _log(f"writing queries for {', '.join(t['name'] for t in missing)}")
            try:
                queries, usage = await asyncio.to_thread(analyze.generate_queries, load_profile(), missing, settings["model"])
                stats["query_gen"] = usage
            except Exception as e:  # searching with what we have beats failing the run
                _log(f"query writing failed, searching with the current queries: {e}")
                queries = {}
            for t in topics:
                q = queries.get(t["name"])
                if not q:
                    continue
                if q["query"] and not (t.get("query") or "").strip():
                    t["query"] = q["query"]
                    _log(f"{t['name']} => {t['query']}")
                if "extra" not in t:
                    t["extra"] = q["extra"]
                    for e in q["extra"]:
                        _log(f"{t['name']} +> {e}")
            save_settings({**settings, "topics": topics})

        search_topics = []
        for t in topics:
            learned = db.good_authors(t["name"])
            own = [h.lstrip("@") for h in t.get("authors") or []]
            merged = list(dict.fromkeys(own + learned))
            if merged:
                _log(f"{t['name']}: searching {min(len(merged), browser.MAX_AUTHORS)} known authors ({len(own)} yours, {len(learned)} from past picks)")
            search_topics.append({**t, "authors": merged})
        topics = search_topics
        searches = browser.search_count(topics, settings["lang"])
        scrape_status = {}
        # scraping ≈ 85% of the bar, analysis the rest
        scraped = await browser.scrape(
            topics, per_mode=settings["per_mode"], lang=settings["lang"], headless=settings["headless"], log=_log,
            on_step=lambda i, label: _progress(i * 0.85, searches, label), status=scrape_status,
            on_wait=lambda left: state.update(step=f"waiting for X search limit reset, {int(left // 60)}m {int(left % 60):02d}s left"))
        if scrape_status.get("rate_limited"):
            stats["rate_limited"] = True
        stats["search_requests"] = scrape_status.get("search_requests")
        if scrape_status.get("waited_s"):
            stats["rate_wait_s"] = scrape_status["waited_s"]
        stats["scraped"] = sum(len(v) for v in scraped.values())
        stats["scrape_s"] = round(time.time() - t0)

        _progress(0.86, 1, "scoring")
        candidates = {}
        for name, posts in scraped.items():
            score_posts(posts)
            db.save_posts(posts)
            candidates[name] = analyze.select_candidates(posts, limit=settings["candidates"])
            _log(f"{name}: {len(candidates[name])} candidates of {len(posts)}")
        db.save_candidates(run_id, candidates)
        stats["sent"] = sum(len(v) for v in candidates.values())

        _progress(0.88, 1, f"Claude is reading {stats['sent']} posts, topic by topic")
        result, usage, errors = await asyncio.to_thread(analyze_candidates, candidates, settings)
        stats["claude"] = usage
        if errors:
            stats["claude_error"] = "; ".join(f"{k}: {v}" for k, v in errors.items())[:500]
        stats["analyze_s"] = round(time.time() - t0) - stats["scrape_s"]
        stats["total_s"] = round(time.time() - t0)
        db.finish_run(run_id, "done", result, stats)
        _log(f"done in {stats['total_s']}s")
    except asyncio.CancelledError:
        _log("stopped")
        db.finish_run(run_id, "stopped", stats={**stats, "error": "stopped"})
    except browser.NeedLogin:
        _log("X asks to log in: press 'Log in to X' and retry")
        db.finish_run(run_id, "error", stats={**stats, "error": "need_login"})
    except browser.RateLimited:
        _log("X rate limit (429): stopped. Wait an hour before the next run.")
        db.finish_run(run_id, "error", stats={**stats, "error": "rate_limited"})
    except Exception as e:
        _log(f"error: {e!r}")
        db.finish_run(run_id, "error", stats={**stats, "error": str(e)[:500]})
    finally:
        state.update(running=False, step="", progress=1.0)


async def reanalyze(run_id, settings):
    """Run Claude again on a stored run's candidates (no scraping). For prompt/model tuning."""
    global _task
    _task = asyncio.current_task()
    src = db.get_run(run_id)
    if not src or not src.get("candidates"):
        raise ValueError("run has no stored candidates")
    state.update(running=True, kind="run", step="Claude is ranking stored posts", log=[], progress=0.5, eta_s=60, started=time.time())
    new_id = db.create_run(src["topics"])
    state["run_id"] = new_id
    try:
        db.save_candidates(new_id, src["candidates"])
        t0 = time.time()
        result, usage, errors = await asyncio.to_thread(analyze_candidates, src["candidates"], settings)
        prev = src.get("stats") or {}
        stats = {"claude": usage, "reanalyzed_from": run_id, "scraped": prev.get("scraped"),
                 "sent": sum(len(v) for v in src["candidates"].values()), "total_s": round(time.time() - t0)}
        if errors:
            stats["claude_error"] = "; ".join(f"{k}: {v}" for k, v in errors.items())[:500]
        db.finish_run(new_id, "done", result, stats)
        _log("done")
    except asyncio.CancelledError:
        _log("stopped")
        db.finish_run(new_id, "stopped", stats={"error": "stopped"})
    except Exception as e:
        _log(f"error: {e!r}")
        db.finish_run(new_id, "error", stats={"error": str(e)[:500]})
    finally:
        state.update(running=False, step="", progress=1.0)


# ---- staged daily run: News → Big → Viral → Trash → Topics ----

def _stage_state(run_id, stage, **fields):
    state["stages"] = {**state.get("stages", {}), stage: {**state.get("stages", {}).get(stage, {}), **fields}}
    db.update_stage(run_id, stage, **fields)


def _enabled(settings):
    on = settings.get("stages") or {}
    out = [s for s in stg.ORDER if on.get(s, True)]
    if "topics" in out and not settings.get("topics"):
        out.remove("topics")
    return out


def analyze_stage(stage, posts, trends, settings):
    """One claude -p for a stage → (picks, usage). Claude failing → local fallback, the tab still fills."""
    prompt, index = stg.digest(load_profile(), posts, trends)
    text, usage = analyze.run_claude(prompt, model=settings["model"], system=stg.system(stage, settings["gist_lang"]), raw=True)
    _log(f"{stg.LABELS[stage]}: claude in {usage['input_tokens']} / out {usage['output_tokens']} tokens, {usage['duration_s']}s")
    return stg.assemble(stage, stg.parse(text), index), usage


def _analyze_stage_job(run_id, stage, posts, trends, settings):
    try:
        picks, usage = analyze_stage(stage, posts, trends, settings)
        _stage_state(run_id, stage, status="ready", picks=picks, count=len(picks), usage=usage)
    except Exception as e:
        if analyze._stopped.is_set():
            raise
        _log(f"{stg.LABELS[stage]}: claude failed, local order shown: {e}")
        picks = stg.fallback(stage, posts)
        _stage_state(run_id, stage, status="ready", picks=picks, count=len(picks), error=str(e)[:300])


async def _scrape_stage(session, stage, settings, log):
    """→ (posts, trends) for one stage. Searches that fail on 429 end the stage early with what was read."""
    posts, trends = {}, []
    if stage == "news":
        try:
            payloads = await session.explore()
            found = explore_items(payloads)
            trends = found["trends"][:20]
            for p in found["posts"]:
                posts.setdefault(p["id"], p)
            log(f"News: Explore gave {len(trends)} trends and {len(found['posts'])} posts")
            if not trends and not found["posts"]:
                log("  Explore → News returned nothing readable: search only (X may have renamed it)")
        except browser.RateLimited:
            raise
        except browser.NeedLogin:
            raise
        except Exception as e:
            log(f"  Explore failed, search only: {e}")
    for mode, query, target in stg.queries(stage, settings):
        log(f"{stg.LABELS[stage]}: searching {mode} — {query}")
        try:
            batch, _ = await session.search(mode, query, target)
        except browser.RateLimited:
            if not posts and not trends:
                raise
            log(f"{stg.LABELS[stage]}: X rate limit (429), keeping {len(posts)} posts")
            break
        for p in batch:
            posts.setdefault(p["id"], p)
    return list(posts.values()), trends


async def _topics_stage(session, run_id, settings, stats):
    """The old topic search as the last stage: main + author searches (extras only if enabled), then the topic analysis."""
    topics = settings["topics"][:MAX_TOPICS]
    missing = [t for t in topics if not (t.get("query") or "").strip()]
    if missing:
        try:
            queries, usage = await asyncio.to_thread(analyze.generate_queries, load_profile(), missing, settings["model"])
            stats["query_gen"] = usage
            for t in topics:
                q = queries.get(t["name"])
                if q and q["query"] and not (t.get("query") or "").strip():
                    t["query"] = q["query"]
                    t.setdefault("extra", q["extra"])
            save_settings({**settings, "topics": topics})
        except Exception as e:
            _log(f"query writing failed, searching with the current queries: {e}")
    search_topics = [{**t, "authors": list(dict.fromkeys([h.lstrip("@") for h in t.get("authors") or []] + db.good_authors(t["name"])))}
                     for t in topics if (t.get("query") or "").strip()]
    kinds = None if settings.get("topic_extra_queries") else ("main", "authors")
    status = {}
    scraped = await browser.scrape_topics(session, search_topics, per_mode=settings["per_mode"], lang=settings["lang"],
                                          on_step=lambda i, label: state.update(step=f"Topics: {label}"), status=status, kinds=kinds)
    candidates = {}
    for name, posts in scraped.items():
        score_posts(posts)
        db.save_posts(posts)
        candidates[name] = analyze.select_candidates(posts, limit=settings["candidates"])
    db.save_candidates(run_id, candidates)
    return candidates, sum(len(v) for v in scraped.values())


def _topics_analysis(run_id, candidates, settings):
    try:
        result, usage, errors = analyze_candidates(candidates, settings)
        n = sum(len(t.get("reply") or []) + len(t.get("save") or []) for t in result)
        with db.conn() as c:
            c.execute("update runs set result=? where id=?", (json.dumps(result), run_id))
        _stage_state(run_id, "topics", status="ready", count=n, usage=usage, **({"error": "; ".join(errors.values())[:300]} if errors else {}))
        return result
    except Exception as e:
        if analyze._stopped.is_set():
            raise
        _log(f"Topics: claude failed: {e}")
        _stage_state(run_id, "topics", status="error", error=str(e)[:300])
        return None


def _summary(run_id, topics_result, settings):
    src = db.get_run(run_id) or {}
    digest = stg.summary_digest(src.get("stages") or {}, topics_result)
    if not digest.strip():
        return None, None
    text, usage = analyze.run_claude(digest, model=settings["model"], system=stg.SUMMARY_SYSTEM.replace("{gist_lang}", settings["gist_lang"]), raw=True)
    return stg.parse_summary(text), usage


def _day_eta(settings):
    for r in db.list_runs(10):
        st = r.get("stats") or {}
        if r["status"] == "done" and r.get("kind") == "day" and st.get("total_s"):
            return st["total_s"]
    return 30 * 60


async def run_day(settings):
    """One button: stages scrape one after another through one Chrome; each stage's Claude call runs while the next stage
    is scraped, so tabs fill up in order. Stop / 429 / lost login keep the stages already analyzed."""
    global _task
    _task = asyncio.current_task()
    analyze._stopped.clear()
    order = _enabled(settings)
    state.update(running=True, kind="run", step="opening X", log=[], progress=0.0, eta_s=_day_eta(settings), started=time.time(), stages={})
    t0 = time.time()
    stats = {"stages": order}
    run_id = db.create_run(settings.get("topics") or [])
    db.set_kind(run_id, "day")
    state["run_id"] = run_id
    for st in order:
        _stage_state(run_id, st, status="waiting")
    jobs, topics_job = [], None
    try:
        pause = tuple(settings.get("search_pause") or (10, 20))
        on_wait = lambda left: state.update(step=f"waiting for X search limit reset, {int(left // 60)}m {int(left % 60):02d}s left")
        async with browser.Session(settings["headless"], _log, on_wait, pause=pause) as session:
            for i, st in enumerate(order):
                state.update(progress=round(i / (len(order) + 1), 3), step=f"{stg.LABELS[st]}: searching")
                _stage_state(run_id, st, status="scraping")
                if st == "topics":
                    candidates, scraped = await _topics_stage(session, run_id, settings, stats)
                    _stage_state(run_id, st, status="analyzing", scraped=scraped)
                    topics_job = asyncio.create_task(asyncio.to_thread(_topics_analysis, run_id, candidates, settings))
                    continue
                posts, trends = await _scrape_stage(session, st, settings, _log)
                score_posts(posts)
                db.save_posts(posts)
                cands = stg.select(st, posts, settings)
                _log(f"{stg.LABELS[st]}: {len(cands)} candidates of {len(posts)}" + (f", {len(trends)} trends" if trends else ""))
                if not cands and not trends:
                    _stage_state(run_id, st, status="ready", picks=[], count=0, scraped=len(posts))
                    continue
                _stage_state(run_id, st, status="analyzing", scraped=len(posts), cands=[analyze.slim(p) for p in cands], trends=trends)
                jobs.append(asyncio.create_task(asyncio.to_thread(_analyze_stage_job, run_id, st, cands, trends, settings)))
            stats["search_requests"] = session.budget.calls
            stats["rate_wait_s"] = round(session.budget.waited)
        state.update(progress=round(len(order) / (len(order) + 1), 3), step="Claude is finishing the last tabs")
        await asyncio.gather(*jobs)
        topics_result = await topics_job if topics_job else None
        state.update(step="Claude is writing the summary")
        try:
            summary, usage = await asyncio.to_thread(_summary, run_id, topics_result, settings)
            if summary:
                db.update_stage(run_id, "summary", **summary, usage=usage)
        except Exception as e:
            if analyze._stopped.is_set():
                raise
            _log(f"summary failed: {e}")
        stats["total_s"] = round(time.time() - t0)
        db.finish_run(run_id, "done", topics_result, stats)
        _log(f"done in {stats['total_s'] // 60}m {stats['total_s'] % 60}s")
    except BaseException as e:
        if isinstance(e, asyncio.CancelledError):
            analyze.stop_claude()
            status, msg = "stopped", "stopped"
        elif isinstance(e, browser.NeedLogin):
            status, msg = "error", "X asks to log in: press 'Log in to X' and retry"
        elif isinstance(e, browser.RateLimited):
            status, msg = "error", "X rate limit (429): stopped. Wait an hour before the next run."
        elif isinstance(e, Exception):
            status, msg = "error", f"error: {e!r}"
        else:
            raise
        _log(msg)
        pending = jobs + ([topics_job] if topics_job else [])
        if status == "stopped":
            for j in pending:
                j.cancel()
        elif pending:  # X stopped the scrape: stages already handed to Claude still finish
            state.update(step="X stopped the search: Claude finishes the stages already read")
            await asyncio.gather(*pending, return_exceptions=True)
        for st, v in ((db.get_run(run_id) or {}).get("stages") or {}).items():
            if isinstance(v, dict) and v.get("status") in ("waiting", "scraping", "analyzing"):
                db.update_stage(run_id, st, status="skipped")
        stats["total_s"] = round(time.time() - t0)
        db.finish_run(run_id, status, None, {**stats, "error": "stopped" if status == "stopped" else msg})
    finally:
        state.update(running=False, step="", progress=1.0)


async def reanalyze_day(run_id, settings):
    """Claude again on every stage of a stored day run (stored candidates and trends, no scraping). For prompt tuning."""
    global _task
    _task = asyncio.current_task()
    analyze._stopped.clear()
    src = db.get_run(run_id)
    state.update(running=True, kind="run", step="Claude is re-reading stored stages", log=[], progress=0.3, eta_s=120, started=time.time(), stages={})
    new_id = db.create_run(src.get("topics") or [])
    db.set_kind(new_id, "day")
    state["run_id"] = new_id
    t0 = time.time()
    try:
        jobs = []
        for st, v in (src.get("stages") or {}).items():
            if st == "summary" or not isinstance(v, dict):
                continue
            if st == "topics":
                continue
            cands = v.get("cands") or []
            if not cands and not v.get("trends"):
                _stage_state(new_id, st, status="ready", picks=[], count=0)
                continue
            for p in cands:  # slim() needs the scored block back
                p.setdefault("scored", {"score": p.get("score", 0), "label": p.get("label", ""), "parts": p.get("parts", {})})
            _stage_state(new_id, st, status="analyzing", cands=v.get("cands"), trends=v.get("trends"))
            jobs.append(asyncio.to_thread(_analyze_stage_job, new_id, st, cands, v.get("trends") or [], settings))
        topics_result = None
        if src.get("candidates"):
            db.save_candidates(new_id, src["candidates"])
            _stage_state(new_id, "topics", status="analyzing")
            jobs.append(asyncio.to_thread(_topics_analysis, new_id, src["candidates"], settings))
        results = await asyncio.gather(*jobs)
        if src.get("candidates"):
            topics_result = results[-1]
        summary, usage = await asyncio.to_thread(_summary, new_id, topics_result, settings)
        if summary:
            db.update_stage(new_id, "summary", **summary, usage=usage)
        db.finish_run(new_id, "done", topics_result, {"reanalyzed_from": run_id, "total_s": round(time.time() - t0)})
        _log("done")
    except asyncio.CancelledError:
        _log("stopped")
        db.finish_run(new_id, "stopped", stats={"error": "stopped"})
    except Exception as e:
        _log(f"error: {e!r}")
        db.finish_run(new_id, "error", stats={"error": str(e)[:500]})
    finally:
        state.update(running=False, step="", progress=1.0)


# ---- profile analysis ----

def _profile_eta(settings):
    """~18 posts per scroll page at ~6 s a page, plus the replies tab and one Claude call."""
    pages = (settings["profile_max_posts"] + settings["profile_max_replies"]) / 18
    return round(pages * 6 + 90)


def _build_analysis(handle, scrape_id, scrape, settings, status):
    """Local metrics, optionally one Claude call. Claude failing keeps the metrics: the tabs still work and Re-analyze can retry."""
    rows, metrics = profile_metrics.compute(scrape["posts"], scrape["profile"])
    return {"id": profile_store.new_id(), "scrape_id": scrape_id, "created_at": db.now_iso(), "status": status,
            "profile": scrape["profile"], "metrics": metrics, "posts": rows, "report": None,
            "stats": {"posts": len(rows), "scrape_s": scrape.get("scrape_s")}}


def _claude_report(analysis, settings):
    prompt, index = profile_analysis.digest(load_profile(), analysis["profile"], analysis["metrics"], analysis["posts"])
    system = profile_analysis.system_prompt(settings["gist_lang"])
    _log(f"claude -p ({settings['profile_model']}): {len(index)} posts, ~{len(prompt) // 4} tokens of input")
    text, usage = analyze.run_claude(prompt, model=settings["profile_model"], system=system, raw=True)
    _log(f"claude done: in {usage['input_tokens']} / out {usage['output_tokens']} tokens, {usage['duration_s']}s")
    report = profile_analysis.resolve(profile_analysis.parse_report(text), index, analysis["posts"])
    if report["copies_dropped"]:
        _log(f"dropped {report['copies_dropped']} items that repeated text of a post")
    return report, usage


def _analyze_step(analysis, settings, t0):
    try:
        analysis["report"], analysis["stats"]["claude"] = _claude_report(analysis, settings)
    except Exception as e:
        _log(f"claude failed, metrics are kept, use Re-analyze: {e}")
        analysis["stats"]["claude_error"] = str(e)[:500]
    analysis["stats"]["total_s"] = round(time.time() - t0)


def _finish_profile(handle, analysis_id=None, error=None):
    state.update(running=False, step="", progress=1.0, analysis_id=analysis_id, error=error)


async def analyze_profile(handle, settings):
    """Scrape one account → metrics → one Claude call. Stop, 429 or a lost session keep what was read, without the Claude call."""
    global _task
    _task = asyncio.current_task()
    state.update(running=True, kind="profile", handle=handle, analysis_id=None, error=None, run_id=None, step="opening X", log=[],
                 progress=0.0, eta_s=_profile_eta(settings), started=time.time())
    t0 = time.time()
    scrape_id = profile_store.new_id()
    sink = {"profile": None, "posts": [], "accounts": {}, "retweets": 0, "responses": []}
    max_posts, max_replies = settings["profile_max_posts"], settings["profile_max_replies"]
    total = max(max_posts + max_replies, 1)

    def on_progress(tab, n):
        done = n if tab == "posts" else max_posts + n
        _progress(min(done, total) * 0.85, total, f"@{handle}: {n} {tab}")

    def keep(status):
        """Save what the scrape got: scrape file, snapshot and a metrics-only analysis. Returns the analysis or None."""
        if not sink["profile"]:
            return None
        posts = finalize_timeline(sink["posts"], sink["accounts"])
        cutoff = (datetime.now(timezone.utc) - timedelta(days=settings["profile_max_days"])).isoformat()
        pinned = next((p for p in posts if p["pinned"]), None)
        profile = {**sink["profile"], "pinned_text": pinned["text"] if pinned else None, "pinned_url": pinned["url"] if pinned else None}
        posts = [p for p in posts if (p["created_at"] or "") >= cutoff]
        scrape = {"id": scrape_id, "scraped_at": db.now_iso(), "status": status, "profile": profile, "posts": posts,
                  "retweets": sink["retweets"], "accounts": sink["accounts"], "scrape_s": round(time.time() - t0)}
        profile_store.save_scrape(handle, scrape_id, scrape, sink["responses"])
        analysis = _build_analysis(handle, scrape_id, scrape, settings, status)
        profile_store.add_snapshot(handle, profile_metrics.snapshot(profile, analysis["metrics"], scrape_id, scrape["scraped_at"]))
        return analysis

    def partial(status, message):
        _log(message)
        a = keep(status)
        if a and not a["posts"]:
            a = None  # the snapshot is saved, but an empty record would only clutter history
        if a:
            a["stats"]["total_s"] = round(time.time() - t0)
            profile_store.save_analysis(handle, a)
            _log(f"kept {a['stats']['posts']} posts: Re-analyze runs Claude on them without scraping")
        _finish_profile(handle, a["id"] if a else None, status)

    try:
        await browser.scrape_profile(handle, sink, max_posts=max_posts, max_days=settings["profile_max_days"], max_replies=max_replies,
                                     headless=settings["headless"], log=_log, on_progress=on_progress)
        if not sink["posts"]:  # nothing to analyze: keep the snapshot, don't pay for a Claude call
            keep("empty")
            raise LookupError(f"@{handle}: X returned no posts (private, empty, or X renamed the timeline operation?)")
        analysis = keep("done")
        _progress(0.87, 1, f"Claude is analyzing @{handle}")
        await asyncio.to_thread(_analyze_step, analysis, settings, t0)
        profile_store.save_analysis(handle, analysis)
        _log(f"done in {analysis['stats']['total_s']}s")
        _finish_profile(handle, analysis["id"])
    except asyncio.CancelledError:
        partial("stopped", "stopped")
    except browser.NeedLogin:
        partial("need_login", "X asks to log in: press 'Log in to X' and retry")
    except browser.RateLimited:
        partial("rate_limited", "X rate limit (429): stopped. Wait an hour before the next run.")
    except LookupError as e:
        _log(str(e))
        _finish_profile(handle, error=str(e))
    except Exception as e:
        _log(f"error: {e!r}")
        _finish_profile(handle, error=str(e)[:500])


async def reanalyze_profile(handle, analysis_id, settings):
    """Metrics and Claude again on the stored scrape of an analysis. No X traffic."""
    global _task
    _task = asyncio.current_task()
    src = profile_store.load_analysis(handle, analysis_id)
    state.update(running=True, kind="profile", handle=handle, analysis_id=None, error=None, run_id=None, log=[], progress=0.5,
                 step=f"Claude is analyzing @{handle}", eta_s=90, started=time.time())
    t0 = time.time()
    try:
        scrape = profile_store.load_scrape(handle, src["scrape_id"])
        analysis = _build_analysis(handle, src["scrape_id"], scrape, settings, "done")
        analysis["stats"]["reanalyzed_from"] = analysis_id
        await asyncio.to_thread(_analyze_step, analysis, settings, t0)
        profile_store.save_analysis(handle, analysis)
        _log("done")
        _finish_profile(handle, analysis["id"])
    except asyncio.CancelledError:
        _log("stopped")
        _finish_profile(handle, error="stopped")
    except Exception as e:
        _log(f"error: {e!r}")
        _finish_profile(handle, error=str(e)[:500])


# ---- one pasted post ----

def _post_report(record, settings):
    prompt = post_analysis.digest(load_profile(), record["post"], record["metrics"])
    _log(f"claude -p ({settings['profile_model']}): ~{len(prompt) // 4} tokens of input")
    text, usage = analyze.run_claude(prompt, model=settings["profile_model"], system=post_analysis.system_prompt(settings["gist_lang"]), raw=True)
    _log(f"claude done: in {usage['input_tokens']} / out {usage['output_tokens']} tokens, {usage['duration_s']}s")
    return post_analysis.parse_report(text, record["post"].get("text")), usage


async def _post_claude_step(record, settings, t0):
    """The post is saved first, so a failed or stopped Claude call can be retried without opening X again."""
    post_analysis.save(record)
    state.update(progress=0.5, step="Claude is reading the post")
    try:
        record["report"], record["stats"]["claude"] = await asyncio.to_thread(_post_report, record, settings)
        record["stats"].pop("claude_error", None)
    except Exception as e:
        _log(f"claude failed, the post is kept, use Re-analyze: {e}")
        record["stats"]["claude_error"] = str(e)[:500]
    record["stats"]["total_s"] = round(time.time() - t0)
    post_analysis.save(record)


def _author_median(post):
    handle = (post.get("author") or {}).get("handle")
    if not handle:
        return None
    try:
        snaps = profile_store.snapshots(handle)
    except ValueError:
        return None
    return snaps[-1].get("median_views_30") if snaps else None


async def analyze_post(ref, settings):
    """ref from post_analysis.parse_ref. A link opens X once; pasted text doesn't touch X."""
    global _task
    _task = asyncio.current_task()
    state.update(running=True, kind="post", post_key=None, analysis_id=None, error=None, run_id=None, log=[], progress=0.1,
                 step="opening the post" if ref.get("id") else "Claude is reading the post", eta_s=75 if ref.get("id") else 50, started=time.time())
    t0 = time.time()
    sink = {"post": None, "responses": []}
    try:
        if ref.get("id"):
            await browser.scrape_post(ref["id"], sink, headless=settings["headless"], log=_log)
            post = sink["post"]
        else:
            post = {"id": None, "text": ref["text"], "views": None}
        record = {"key": ref["key"], "created_at": db.now_iso(), "post": post, "metrics": post_analysis.metrics(post, _author_median(post)),
                  "report": None, "stats": {}}
        post_analysis.save(record, sink["responses"])
        await _post_claude_step(record, settings, t0)
        _log(f"done in {record['stats']['total_s']}s")
        state.update(post_key=ref["key"])
    except asyncio.CancelledError:
        _log("stopped")
        state.update(error="stopped")
    except browser.NeedLogin:
        _log("X asks to log in")
        state.update(error="X asks to log in: press 'Log in to X' and retry")
    except browser.RateLimited:
        _log("X rate limit (429): stopped")
        state.update(error="X rate limit (429). Wait an hour before the next run.")
    except Exception as e:
        _log(f"error: {e}")
        state.update(error=str(e)[:500])
    finally:
        state.update(running=False, step="", progress=1.0)


async def reanalyze_post(key, settings):
    """Claude again on the stored post. No X traffic."""
    global _task
    _task = asyncio.current_task()
    state.update(running=True, kind="post", post_key=None, analysis_id=None, error=None, run_id=None, log=[], progress=0.5,
                 step="Claude is reading the post", eta_s=50, started=time.time())
    t0 = time.time()
    try:
        record = post_analysis.load(key)
        await _post_claude_step(record, settings, t0)
        state.update(post_key=key)
    except asyncio.CancelledError:
        _log("stopped")
        state.update(error="stopped")
    except Exception as e:
        _log(f"error: {e}")
        state.update(error=str(e)[:500])
    finally:
        state.update(running=False, step="", progress=1.0)
