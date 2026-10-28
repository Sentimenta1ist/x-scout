"""Early-virality score, ported from x-viral-radar/scoring.js. Pure functions.

Differences from the extension:
- search results carry the author's follower count, so the "vs author" signal works from day one:
  if we have < 3 past posts of the author, the baseline is followers * FOLLOWER_VIEW_RATIO (an assumption).
- acceleration uses the snapshot from a previous run, if the same post was seen before.
"""
import math
from statistics import median

DEFAULTS = {
    "tau": 150,  # minutes: views accumulate as 1 - exp(-t / tau). Assumption, calibrate.
    "hot_score": 70,
    "rising_score": 45,
    "min_views": 30,
    "max_age_min": 360,
    "weights": {"reply": 3, "repost": 2, "like": 1, "bookmark": 2},
}
# Typical post reaches ~15% of follower count in views. Rough assumption, only used without author history.
FOLLOWER_VIEW_RATIO = 0.15


def clamp(x, lo=0.0, hi=100.0):
    return min(hi, max(lo, x))


def lifetime_fraction(age_min, tau):
    return 1 - math.exp(-max(age_min, 1) / tau)


def project_views(views, age_min, cfg=DEFAULTS):
    # fraction floored to avoid wild jumps for very young posts
    return views / max(lifetime_fraction(age_min, cfg["tau"]), 0.15)


def score(tweet, ctx=None, cfg=None):
    """tweet: {views, likes, replies, reposts, bookmarks, age_min}
    ctx: {author_projected: [float], followers: int, prev: {views, age_min} | None}"""
    ctx = ctx or {}
    cfg = {**DEFAULTS, **(cfg or {})}
    views, age = tweet.get("views"), tweet.get("age_min")
    if views is None or age is None or views < cfg["min_views"] or age < 2:
        return {"score": 0, "label": "low-data", "parts": {}, "projected": None, "vpm": None, "er": None}

    projected = project_views(views, age, cfg)
    vpm = views / age
    w = cfg["weights"]
    eng = (w["reply"] * tweet.get("replies", 0) + w["repost"] * tweet.get("reposts", 0)
           + w["like"] * tweet.get("likes", 0) + w["bookmark"] * tweet.get("bookmarks", 0))
    er = eng / views

    parts = {}
    # 1k projected -> 0, 500k -> 100 (log scale)
    parts["size"] = clamp(math.log10(projected / 1000) / math.log10(500) * 100)
    # weighted engagement per view: 1% -> 0, 6% -> 100
    parts["engagement"] = clamp((er - 0.01) / 0.05 * 100)

    weights = {"size": 0.35, "engagement": 0.2, "relative": 0.25, "acceleration": 0.2}
    hist = ctx.get("author_projected") or []
    base = median(hist) if len(hist) >= 3 else None
    if base is None and ctx.get("followers"):
        base = max(ctx["followers"] * FOLLOWER_VIEW_RATIO, 100)
        weights["relative"] = 0.15  # weaker evidence than real history
    if base:
        # 1x author's normal -> 0, 8x -> 100
        parts["relative"] = clamp(math.log2(projected / base) / 3 * 100)

    prev = ctx.get("prev")
    if prev and age - prev["age_min"] >= 2 and views > prev["views"]:
        dt = age - prev["age_min"]
        recent = (views - prev["views"]) / dt
        tau = cfg["tau"]
        # instantaneous / average rate expected from the decay model at this age
        expected = (math.exp(-age / tau) / tau) / (lifetime_fraction(age, tau) / age)
        ratio = recent / (vpm * expected)
        parts["acceleration"] = clamp(50 + 50 * math.log2(ratio))

    total_w = sum(weights[k] for k in parts)
    raw = sum(parts[k] * weights[k] for k in parts) / total_w
    confidence = clamp(views / 300, 0, 1) * (1 if age >= 5 else 0.6)
    total = raw * (0.5 + 0.5 * confidence)

    label = "hot" if total >= cfg["hot_score"] else "rising" if total >= cfg["rising_score"] else "normal"
    if age > cfg["max_age_min"]:
        label = "old"
    return {"score": round(total), "label": label, "parts": {k: round(v) for k, v in parts.items()},
            "projected": round(projected), "vpm": round(vpm, 1), "er": round(er, 4)}
