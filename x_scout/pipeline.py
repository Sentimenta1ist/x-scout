"""scrape → score → pick candidates → claude -p → three columns per topic."""
import asyncio
import json
import time
from datetime import datetime, timezone

from . import analyze, browser, db
from .config import PROFILE_MD, ROOT, SETTINGS_JSON
from .parse import age_minutes
from .scoring import project_views, score

DEFAULT_SETTINGS = {
    "topics": [{"name": "AI agents", "query": ""}, {"name": "Automation", "query": ""}],
    "lang": "en",
    "per_mode": 40,          # posts per search tab (Top and Latest) per topic
    "candidates": 40,        # posts per topic sent to Claude
    "headless": True,
    "model": "sonnet",
    "gist_lang": "English",  # language of the short per-post summary
}
MAX_TOPICS = 5

# live state of the current run, polled by the UI
state = {"running": False, "run_id": None, "step": "", "log": [], "progress": 0.0, "eta_s": None, "started": None}


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
    """Used when Claude fails: columns by local numbers only, so the run still shows something."""
    out = []
    for name, posts in candidates.items():
        hot = sorted([p for p in posts if p["age_min"] <= 360], key=lambda p: p["scored"]["score"], reverse=True)[:5]
        big = sorted(posts, key=lambda p: p["views"], reverse=True)[:5]
        out.append({"topic": name, "candidates": len(posts),
                    "hot": [{**analyze.slim(p), "why": "", "angle": "", "q": None} for p in hot],
                    "global": [{**analyze.slim(p), "why": "", "angle": "", "q": None} for p in big],
                    "useful": []})
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
    topics = settings["topics"][:MAX_TOPICS]
    state.update(running=True, step="starting", log=[], progress=0.0, eta_s=_eta(len(topics)), started=time.time())
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
    src = db.get_run(run_id)
    if not src or not src.get("candidates"):
        raise ValueError("run has no stored candidates")
    state.update(running=True, step="Claude is ranking stored posts", log=[], progress=0.5, eta_s=20, started=time.time())
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
    except Exception as e:
        _log(f"error: {e!r}")
        db.finish_run(new_id, "error", stats={"error": str(e)[:500]})
    finally:
        state.update(running=False, step="", progress=1.0)
