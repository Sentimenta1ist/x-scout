"""Local metrics for one X account's timeline. Pure functions, no LLM. Posts are oldest first (parse.finalize_timeline)."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median

BREAKOUT_X = 5          # breakout: views >= 5x the rolling median
BASELINE_WINDOW = 30    # posts in the median a post is compared against
MIN_BASELINE = 5        # below this many earlier posts, compare with the first posts of the timeline instead
STEP = 1.5              # a phase changes when the median moves by this factor
BIG_ACCOUNT_X = 5       # "much larger": target has >= 5x the author's followers
AFTER_BORROWED_H = 72
CHAIN_DAYS = 7
MATURE_H = 48           # newer posts are still collecting views, so they don't move the growth phases
ORIGINAL = ("post", "quote", "article", "thread")


def _dt(p):
    return datetime.fromisoformat(p["created_at"])


def is_original(p):
    return p["type"] in ORIGINAL


def rolling_median(values, window):
    """Trailing median including the current value. None values are skipped and yield the last known median."""
    out, buf = [], []
    for v in values:
        if v is not None:
            buf = (buf + [v])[-window:]
        out.append(median(buf) if buf else None)
    return out


def annotate(posts):
    """Per-post copy with er, bookmark_ratio, median_7, median_30, baseline, ratio and breakout.
    The baseline excludes the post itself and comes from original posts only, so a huge post can't raise its own bar
    and low-view replies can't lower it."""
    originals = [p for p in posts if is_original(p) and p.get("views") is not None]
    first = [p["views"] for p in originals[:BASELINE_WINDOW]]
    seen, out = [], []
    m7, m30 = [], []
    for p in posts:
        v = p.get("views")
        q = dict(p)
        likes = p.get("likes") or 0
        q["er"] = round((likes + (p.get("replies") or 0) + (p.get("reposts") or 0) + (p.get("quotes") or 0)) / v, 4) if v else None
        q["bookmark_ratio"] = round((p.get("bookmarks") or 0) / likes, 3) if likes else None
        if v is None:
            q.update(baseline=None, ratio=None, breakout=False)
        else:
            window = seen[-BASELINE_WINDOW:]
            base = median(window) if len(window) >= MIN_BASELINE else (median(first) if len(first) >= MIN_BASELINE else None)
            q["baseline"] = base
            q["ratio"] = round(v / max(base, 1), 2) if base is not None else None
            q["breakout"] = q["ratio"] is not None and q["ratio"] >= BREAKOUT_X
        if is_original(p) and v is not None:
            seen.append(v)
            m7, m30 = (m7 + [v])[-7:], (m30 + [v])[-30:]
        q["median_7"] = median(m7) if m7 else None
        q["median_30"] = median(m30) if m30 else None
        out.append(q)
    return out


def _dated(posts):
    return [p for p in posts if p.get("created_at")]


def cadence(posts):
    posts = _dated(posts)
    originals = [p for p in posts if is_original(p)]
    if not posts:
        return {"posts": 0, "replies": 0, "days": 0, "per_day": 0, "per_week": [], "hours_utc": [0] * 24, "types": {}, "median_views_by_type": {}}
    days = max((_dt(posts[-1]) - _dt(posts[0])).total_seconds() / 86400, 1)
    hours = [0] * 24
    weeks = Counter()
    for p in originals:
        d = _dt(p)
        hours[d.hour] += 1
        weeks[(d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")] += 1
    types = Counter(p["type"] for p in posts)
    by_type = defaultdict(list)
    for p in posts:
        if p.get("views") is not None:
            by_type[p["type"]].append(p["views"])
    return {
        "posts": len(originals),
        "replies": len(posts) - len(originals),
        "days": round(days, 1),
        "per_day": round(len(originals) / days, 2),
        "per_week": [{"week": w, "posts": weeks[w]} for w in sorted(weeks)],
        "hours_utc": hours,
        "types": {k: round(v / len(posts), 3) for k, v in types.most_common()},
        "median_views_by_type": {k: median(v) for k, v in by_type.items()},
    }


def article_chains(posts, days=CHAIN_DAYS):
    """For each article: own quotes of it, replies under it and posts linking to it within the next `days` days."""
    posts = _dated(posts)
    chains = []
    for a in posts:
        if a["type"] != "article":
            continue
        ids = {a["id"], a.get("article_id")} - {None}
        start, end = _dt(a), _dt(a) + timedelta(days=days)
        follow = []
        for p in posts:
            if p["id"] == a["id"] or not start < _dt(p) <= end:
                continue
            if p.get("quoted_id") in ids:
                kind = "quote"
            elif p.get("reply_to_id") in ids or p.get("conversation_id") == a["id"]:
                kind = "reply"
            elif ids & set(p.get("linked_ids") or []):
                kind = "link"
            else:
                continue
            follow.append({"id": p["id"], "url": p["url"], "kind": kind, "created_at": p["created_at"], "views": p.get("views")})
        chains.append({"id": a["id"], "url": a["url"], "title": a.get("article_title") or a["text"][:80],
                       "created_at": a["created_at"], "views": a.get("views"), "followups": follow,
                       "followup_views": sum(f["views"] or 0 for f in follow)})
    return chains


def borrowed_reach(posts, followers, big_x=BIG_ACCOUNT_X, after_h=AFTER_BORROWED_H):
    """Quotes of and replies to accounts >= big_x times the author's size, and whether breakouts follow them.
    Needs annotate() output. Compares the breakout rate in the `after_h` hours after such a post with the rate elsewhere."""
    posts = _dated(posts)
    threshold = max(followers, 1) * big_x
    events = []
    for p in posts:
        if p.get("quoted_handle") and (p.get("quoted_followers") or 0) >= threshold:
            target, size, how = p["quoted_handle"], p["quoted_followers"], "quote"
        elif p["type"] == "reply" and not p.get("self_reply") and (p.get("reply_to_followers") or 0) >= threshold:
            target, size, how = p["reply_to_handle"], p["reply_to_followers"], "reply"
        else:
            continue
        events.append({"id": p["id"], "url": p["url"], "created_at": p["created_at"], "how": how, "target": target,
                       "target_followers": size, "views": p.get("views"), "ratio": p.get("ratio"), "breakout": p.get("breakout", False)})
    event_ids = {e["id"] for e in events}
    times = [_dt(p) for p in posts if p["id"] in event_ids]
    after, other = [], []
    for p in posts:
        if not is_original(p) or p["id"] in event_ids or p.get("views") is None:
            continue
        d = _dt(p)
        (after if any(timedelta(0) < d - t <= timedelta(hours=after_h) for t in times) else other).append(p)
    rate = lambda xs: round(sum(1 for p in xs if p.get("breakout")) / len(xs), 3) if xs else None
    return {
        "threshold_followers": threshold,
        "count": len(events),
        "breakouts_on_event": sum(1 for e in events if e["breakout"]),
        "posts_after": len(after), "rate_after": rate(after),
        "posts_other": len(other), "rate_other": rate(other),
        "top_targets": Counter(e["target"] for e in events).most_common(8),
        "events": sorted(events, key=lambda e: e["views"] or 0, reverse=True)[:30],
    }


def growth_phases(posts, now=None, step=STEP):
    """Follower history isn't available, so phases are inferred from the median views of original posts in 7-day bins.
    A new phase starts when the next two bins' median differs from the current phase's median by `step`.
    Posts younger than MATURE_H are left out: they are still collecting views."""
    now = now or datetime.now(timezone.utc)
    usable = [p for p in _dated(posts) if is_original(p) and p.get("views") is not None
              and (now - _dt(p)).total_seconds() >= MATURE_H * 3600]
    if not usable:
        return []
    start = _dt(usable[0])
    bins = defaultdict(list)
    for p in usable:
        bins[(_dt(p) - start).days // 7].append(p)
    keys = sorted(bins)
    phases, cur = [], {"bins": [keys[0]], "change": "start", "ratio": None}
    views = lambda bs: [p["views"] for b in bs for p in bins[b]]
    i = 1
    while i < len(keys):
        ahead = keys[i:i + 2]
        base = max(median(views(cur["bins"])), 1)
        # both next bins must cross the step on their own: one loud week, or a week straddling the change, is not a phase
        ratios = [median(views([b])) / base for b in ahead]
        up, down = all(x >= step for x in ratios), all(x <= 1 / step for x in ratios)
        if len(ahead) == 2 and len(views(ahead)) >= 3 and len(cur["bins"]) >= 2 and (up or down):
            r = median(views(ahead)) / base
            phases.append(cur)
            cur = {"bins": ahead, "change": "up" if up else "down", "ratio": round(r, 2)}
            i += 2
        else:
            cur["bins"].append(keys[i])
            i += 1
    phases.append(cur)
    out = []
    for ph in phases:
        ps = [p for b in ph["bins"] for p in bins[b]]
        out.append({"start": min(p["created_at"] for p in ps), "end": max(p["created_at"] for p in ps), "posts": len(ps),
                    "median_views": median(p["views"] for p in ps), "change": ph["change"], "ratio": ph["ratio"]})
    return out


def compute(posts, profile, now=None):
    """Everything local for one scrape → (annotated posts, metrics)."""
    rows = annotate(posts)
    originals = [p for p in rows if is_original(p) and p.get("views") is not None]
    breakouts = [p for p in rows if p["breakout"]]
    er = [p["er"] for p in originals if p["er"] is not None]
    bm = [p["bookmark_ratio"] for p in originals if p["bookmark_ratio"] is not None]
    last = originals[-1] if originals else {}
    return rows, {
        "median_views": median(p["views"] for p in originals) if originals else None,
        "median_views_7": last.get("median_7"),
        "median_views_30": last.get("median_30"),
        "median_er": round(median(er), 4) if er else None,
        "median_bookmark_ratio": round(median(bm), 3) if bm else None,
        "breakouts": len(breakouts),
        "cadence": cadence(rows),
        "articles": article_chains(rows),
        "borrowed": borrowed_reach(rows, profile.get("followers") or 0),
        "phases": growth_phases(rows, now),
    }


def snapshot(profile, metrics, scrape_id, ts):
    return {"scrape_id": scrape_id, "ts": ts, "followers": profile.get("followers"), "following": profile.get("following"),
            "posts_total": profile.get("posts_total"), "median_views_30": metrics.get("median_views_30")}
