"""Where the own replies went and what it gave: the post each reply sits under (age, size, crowd), the x-scout stage the post
came from, and X Analytics exports joined by post id. Pure functions; pipeline.reply_report wires them to the stored files.

Built from the 2026-11-17 review of @sentimentGod: the choice of post explained more than topic, style, hour or volume did.
"""
import csv
import io
import json
from datetime import datetime
from statistics import median

from .scoring import DEFAULTS

FIT_MAX_AGE = DEFAULTS["reply_max_age_min"]
FIT_MIN_VIEWS = DEFAULTS["fit_min_views"]
FIT_MAX_CROWD = DEFAULTS["fit_max_crowd"]
FIT_MAX_REPLIES = DEFAULTS["crowd_max_replies"]


def _tweets(responses):
    """Every Tweet object in raw GraphQL responses, by id: the timeline pages carry the posts the replies answer."""
    out = {}

    def walk(o):
        if isinstance(o, dict):
            if o.get("__typename") == "Tweet" and "legacy" in o and o.get("rest_id"):
                out[o["rest_id"]] = o
            elif o.get("__typename") == "TweetWithVisibilityResults" and isinstance(o.get("tweet"), dict):
                walk(o["tweet"])
                return
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(responses)
    return out


def parents(responses):
    """id → {created_at, views, replies, likes} for every tweet seen in the responses."""
    out = {}
    for tid, t in _tweets(responses).items():
        leg = t["legacy"]
        try:
            created = datetime.strptime(leg["created_at"], "%a %b %d %H:%M:%S %z %Y").isoformat()
        except (KeyError, ValueError):
            continue
        views = (t.get("views") or {}).get("count")
        out[tid] = {"created_at": created, "views": int(views) if views else None,
                    "replies": leg.get("reply_count") or 0, "likes": leg.get("favorite_count") or 0}
    return out


def stage_map(runs):
    """post id → x-scout stage it was picked in ("big", "news", ..., "topics"); the first run that showed it wins."""
    out = {}
    for r in sorted(runs, key=lambda r: r["id"]):
        for stage, v in (r.get("stages") or {}).items():
            if isinstance(v, dict):
                for p in v.get("picks") or []:
                    if p.get("id"):
                        out.setdefault(p["id"], stage)
        for t in r.get("result") or []:
            if isinstance(t, dict):
                for p in (t.get("reply") or []) + (t.get("save") or []):
                    if p.get("id"):
                        out.setdefault(p["id"], "topics")
    return out


def _date(s):
    for fmt in ("%a, %b %d, %Y", "%Y-%m-%d", "%b %d, %Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date().isoformat()
        except ValueError:
            pass
    return None


def _int(v):
    try:
        return int(float(v or 0))
    except ValueError:
        return 0


def parse_analytics(text):
    """One X Analytics CSV → ("content", {post id: {...}}) or ("overview", {date: {...}}). Raises ValueError otherwise."""
    rows = list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))
    if not rows:
        raise ValueError("empty CSV")
    cols = set(rows[0])
    num = {"impressions": "Impressions", "likes": "Likes", "engagements": "Engagements", "follows": "New follows",
           "profile_visits": "Profile visits", "replies": "Replies", "bookmarks": "Bookmarks"}
    if "Post id" in cols:
        return "content", {r["Post id"]: {"date": _date(r.get("Date", "")), **{k: _int(r.get(c)) for k, c in num.items()}}
                           for r in rows if r.get("Post id")}
    if "Date" in cols and "Impressions" in cols:
        return "overview", {d: {**{k: _int(r.get(c)) for k, c in num.items()}, "unfollows": _int(r.get("Unfollows"))}
                            for r in rows if (d := _date(r["Date"]))}
    raise ValueError("not an X Analytics export: expected a 'Post id' column (content) or 'Date' + 'Impressions' (overview)")


def merge_analytics(files):
    """[(name, text)] oldest first → {"content": {...}, "overview": {...}, "files": [...]}; later files win per id or day."""
    out = {"content": {}, "overview": {}, "files": []}
    for name, text in files:
        try:
            kind, data = parse_analytics(text)
        except ValueError:
            continue
        out[kind].update(data)
        out["files"].append({"name": name, "kind": kind, "rows": len(data)})
    return out


def fit_why(r):
    why = []
    if r["delay_min"] > FIT_MAX_AGE:
        why.append("older than 3h")
    if r["parent_replies"] >= FIT_MAX_REPLIES:
        why.append("2k+ replies")
    elif r["crowd"] >= FIT_MAX_CROWD:
        why.append("crowded thread")
    if (r["parent_views"] or 0) < FIT_MIN_VIEWS:
        why.append("post under 50k")
    return why


def rows(posts, parent_by_id, stage_of=None, content=None):
    """Own replies with what they sit under. Views prefer the X Analytics impressions when the export has the post."""
    stage_of, content = stage_of or {}, content or {}
    out = []
    for p in posts:
        if p.get("type") != "reply" or p.get("self_reply"):
            continue
        par = parent_by_id.get(p.get("reply_to_id"))
        if not par or not par.get("views") or not p.get("created_at"):
            continue
        delay = (datetime.fromisoformat(p["created_at"]) - datetime.fromisoformat(par["created_at"])).total_seconds() / 60
        a = content.get(p["id"]) or {}
        r = {"id": p["id"], "url": p.get("url"), "text": p.get("text"), "created_at": p["created_at"], "to": p.get("reply_to_handle"),
             "views": a.get("impressions", p.get("views") or 0), "likes": a.get("likes", p.get("likes") or 0),
             "profile_visits": a.get("profile_visits"), "follows": a.get("follows"),
             "delay_min": round(delay), "parent_views": par["views"], "parent_replies": par["replies"],
             "crowd": round(par["replies"] / max(par["views"], 5000) * 10_000, 1), "stage": stage_of.get(p.get("reply_to_id"), "manual")}
        r["why"] = fit_why(r)
        r["fit"] = not r["why"]
        out.append(r)
    return out


def _group(label, rs):
    v = [r["views"] for r in rs]
    pv = [r["profile_visits"] for r in rs if r["profile_visits"] is not None]
    return {"label": label, "n": len(rs), "median_views": round(median(v)) if v else 0,
            "share_1k": round(sum(x >= 1000 for x in v) / len(v), 3) if v else 0,
            "share_under_50": round(sum(x < 50 for x in v) / len(v), 3) if v else 0,
            "views": sum(v), "profile_visits": sum(pv) if pv else None}


def _buckets(rs, key, edges, labels):
    return [_group(l, [r for r in rs if a <= r[key] < b]) for (a, b), l in zip(zip(edges, edges[1:]), labels)]


STAGE_ORDER = ["big", "trash", "news", "viral", "topics", "manual"]


def summarize(rs, overview=None, days=21):
    """Tables for the Profiles 'Replies' tab. Empty rs → None."""
    if not rs:
        return None
    inf = float("inf")
    stages = [_group(s, [r for r in rs if r["stage"] == s]) for s in STAGE_ORDER if any(r["stage"] == s for r in rs)]
    out = {
        "replies": len(rs),
        "fit": [_group("passes the 3 checks", [r for r in rs if r["fit"]]), _group("fails", [r for r in rs if not r["fit"]])],
        "delay": _buckets(rs, "delay_min", [0, 60, 180, 480, 1440, inf], ["under 1h", "1–3h", "3–8h", "8–24h", "over a day"]),
        "parent_views": _buckets(rs, "parent_views", [0, 50_000, 200_000, 1_000_000, 5_000_000, inf], ["under 50k", "50–200k", "200k–1M", "1–5M", "5M+"]),
        "crowd": _buckets(rs, "crowd", [0, 3, 10, inf], ["under 3", "3–10", "10+"]),
        "stages": stages,
        "fail_reasons": sorted(((w, sum(w in r["why"] for r in rs)) for w in {w for r in rs for w in r["why"]}), key=lambda x: -x[1]),
        "worst": sorted([r for r in rs if not r["fit"]], key=lambda r: r["views"])[:8],
        "daily": [],
    }
    by_day = {}
    for r in rs:
        by_day.setdefault(r["created_at"][:10], []).append(r)
    dates = sorted(set(by_day) | set(overview or {}))[-days:]
    for d in dates:
        day_rs, o = by_day.get(d, []), (overview or {}).get(d, {})
        out["daily"].append({"date": d, "replies": len(day_rs), "fit": sum(r["fit"] for r in day_rs),
                             "median_views": round(median([r["views"] for r in day_rs])) if day_rs else None,
                             "impressions": o.get("impressions"), "profile_visits": o.get("profile_visits"),
                             "follows": o.get("follows"), "unfollows": o.get("unfollows")})
    return out


def load_runs_json(rows_):
    """sqlite rows of runs → dicts with parsed stages/result."""
    out = []
    for r in rows_:
        try:
            out.append({"id": r["id"], "stages": json.loads(r["stages"] or "{}"), "result": json.loads(r["result"] or "[]")})
        except (TypeError, json.JSONDecodeError):
            continue
    return out
