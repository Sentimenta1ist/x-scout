"""scrape → score → pick candidates → claude -p → up to 5 posts to reply to and 5 to save per topic."""
import asyncio
import json
import time
from datetime import datetime, timedelta, timezone

from . import analyze, browser, db, post_analysis, profile_analysis, profile_metrics, profile_store
from .config import PROFILE_MD, ROOT, SETTINGS_JSON
from .parse import age_minutes, finalize_timeline
from .scoring import project_views, score

DEFAULT_SETTINGS = {
    "topics": [{"name": "AI agents", "query": ""}, {"name": "Automation", "query": ""}],
    "lang": "en",
    "per_mode": 40,          # posts per search tab (Top and Latest) per topic
    "candidates": 40,        # posts per topic sent to Claude
    "headless": True,
    "model": "sonnet",
    "gist_lang": "English",  # language of the short per-post summary
    # profile analysis
    "profile_max_posts": 300,
    "profile_max_days": 120,
    "profile_max_replies": 60,   # 0 = skip the replies tab
    "profile_model": "sonnet",
}
MAX_TOPICS = 5

# live state of the current run, polled by the UI
# kind: "run" (topic search), "profile" or "post"; one job at a time, they share Chrome and Stop
state = {"running": False, "kind": "run", "run_id": None, "step": "", "log": [], "progress": 0.0, "eta_s": None, "started": None,
         "handle": None, "analysis_id": None, "post_key": None, "error": None}
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


def fallback_columns(candidates):
    """Used when Claude fails: top posts by local score under "save", so the run still shows something."""
    out = []
    for name, posts in candidates.items():
        top = sorted(posts, key=lambda p: p["scored"]["score"], reverse=True)[:analyze.MAX_PER_COLUMN]
        out.append({"topic": name, "candidates": len(posts), "reply": [],
                    "save": [{**analyze.slim(p), "why": "", "angle": "", "q": None} for p in top]})
    return out


def analyze_candidates(candidates, settings):
    prompt, index = analyze.digest(load_profile(), candidates)
    _log(f"claude -p ({settings['model']}): {sum(len(v) for v in candidates.values())} posts, ~{len(prompt) // 4} tokens of input")
    data, usage = analyze.run_claude(prompt, model=settings["model"], system=analyze.ranking_system(settings["gist_lang"]))
    _log(f"claude done: in {usage['input_tokens']} / out {usage['output_tokens']} tokens, {usage['duration_s']}s")
    return analyze.assemble(data, index, candidates), usage


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
        missing = [t["name"] for t in topics if not (t.get("query") or "").strip()]
        if missing:
            _progress(0, 1, "writing search queries")
            _log(f"no query for {', '.join(missing)}: asking Claude to write them")
            queries, usage = await asyncio.to_thread(analyze.generate_queries, load_profile(), missing, settings["model"])
            stats["query_gen"] = usage
            for t in topics:
                if t["name"] in queries:
                    t["query"] = queries[t["name"]]
                    _log(f"{t['name']} => {t['query']}")
            save_settings({**settings, "topics": topics})

        searches = len(topics) * 2
        # scraping ≈ 85% of the bar, analysis the rest
        scraped = await browser.scrape(
            topics, per_mode=settings["per_mode"], lang=settings["lang"], headless=settings["headless"], log=_log,
            on_step=lambda i, label: _progress(i * 0.85, searches, label))
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

        _progress(0.88, 1, f"Claude is ranking {stats['sent']} posts")
        try:
            result, usage = await asyncio.to_thread(analyze_candidates, candidates, settings)
            stats["claude"] = usage
        except Exception as e:  # keep the scrape, show local ranking
            _log(f"claude failed, showing local ranking: {e}")
            result, stats["claude_error"] = fallback_columns(candidates), str(e)[:500]
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
    state.update(running=True, kind="run", step="Claude is ranking stored posts", log=[], progress=0.5, eta_s=20, started=time.time())
    new_id = db.create_run(src["topics"])
    state["run_id"] = new_id
    try:
        db.save_candidates(new_id, src["candidates"])
        result, usage = await asyncio.to_thread(analyze_candidates, src["candidates"], settings)
        prev = src.get("stats") or {}
        db.finish_run(new_id, "done", result, {"claude": usage, "reanalyzed_from": run_id, "scraped": prev.get("scraped"),
                                               "sent": sum(len(v) for v in src["candidates"].values()),
                                               "total_s": usage["duration_s"]})
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
