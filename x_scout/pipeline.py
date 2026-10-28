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
    "per_mode": 30,          # posts per search tab (Top and Latest) per topic
    "candidates": 25,        # posts per topic sent to Claude
    "headless": True,
    "model": "sonnet",
}
MAX_TOPICS = 5

# live state of the current run, polled by the UI
state = {"running": False, "run_id": None, "step": "", "log": []}


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
    data, usage = analyze.run_claude(prompt, model=settings["model"])
    _log(f"claude done: in {usage['input_tokens']} / out {usage['output_tokens']} tokens, {usage['duration_s']}s")
    return analyze.assemble(data, index, candidates), usage


async def run(settings):
    state.update(running=True, step="scraping", log=[])
    topics = settings["topics"][:MAX_TOPICS]
    run_id = db.create_run(topics)
    state["run_id"] = run_id
    t0 = time.time()
    stats = {}
    try:
        scraped = await browser.scrape(topics, per_mode=settings["per_mode"], lang=settings["lang"],
                                       headless=settings["headless"], log=_log)
        stats["scraped"] = sum(len(v) for v in scraped.values())
        stats["scrape_s"] = round(time.time() - t0)

        state["step"] = "scoring"
        candidates = {}
        for name, posts in scraped.items():
            score_posts(posts)
            db.save_posts(posts)
            candidates[name] = analyze.select_candidates(posts, limit=settings["candidates"])
            _log(f"{name}: {len(candidates[name])} candidates of {len(posts)}")
        db.save_candidates(run_id, candidates)

        state["step"] = "analyzing"
        try:
            result, usage = await asyncio.to_thread(analyze_candidates, candidates, settings)
            stats["claude"] = usage
        except Exception as e:  # keep the scrape, show local ranking
            _log(f"claude failed, showing local ranking: {e}")
            result, stats["claude_error"] = fallback_columns(candidates), str(e)[:500]
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
        state.update(running=False, step="")


async def reanalyze(run_id, settings):
    """Run Claude again on a stored run's candidates (no scraping). For prompt/model tuning."""
    src = db.get_run(run_id)
    if not src or not src.get("candidates"):
        raise ValueError("run has no stored candidates")
    state.update(running=True, step="analyzing", log=[])
    new_id = db.create_run(src["topics"])
    state["run_id"] = new_id
    try:
        db.save_candidates(new_id, src["candidates"])
        result, usage = await asyncio.to_thread(analyze_candidates, src["candidates"], settings)
        db.finish_run(new_id, "done", result, {"claude": usage, "reanalyzed_from": run_id,
                                               "scraped": src["stats"].get("scraped") if src.get("stats") else None})
        _log("done")
    except Exception as e:
        _log(f"error: {e!r}")
        db.finish_run(new_id, "error", stats={"error": str(e)[:500]})
    finally:
        state.update(running=False, step="")
