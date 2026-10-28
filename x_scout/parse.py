"""Turn X GraphQL SearchTimeline responses into flat post dicts.

X moves fields around between schema versions (e.g. screen_name went from user.legacy to user.core),
so every lookup tries the new place first and falls back to the old one.
"""
from datetime import datetime, timezone
import re


def _get(d, *path, default=None):
    for key in path:
        if not isinstance(d, dict):
            return default
        d = d.get(key)
    return default if d is None else d


def _unwrap(result):
    # Tweets with limited visibility come wrapped: {"__typename": "TweetWithVisibilityResults", "tweet": {...}}
    if isinstance(result, dict) and result.get("__typename") == "TweetWithVisibilityResults":
        return result.get("tweet") or {}
    return result or {}


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _user(user_result):
    u = _unwrap(user_result)
    legacy = u.get("legacy") or {}
    core = u.get("core") or {}
    return {
        "handle": core.get("screen_name") or legacy.get("screen_name") or "",
        "name": core.get("name") or legacy.get("name") or "",
        "followers": _int(legacy.get("followers_count")) or _int(_get(u, "relationship_counts", "followers")) or 0,
        "verified": bool(u.get("is_blue_verified") or legacy.get("verified")),
    }


def parse_created(s):
    # "Wed Oct 28 10:00:00 +0000 2026"
    try:
        return datetime.strptime(s, "%a %b %d %H:%M:%S %z %Y")
    except (TypeError, ValueError):
        return None


def tweet_from_result(result):
    t = _unwrap(result)
    if t.get("__typename") not in (None, "Tweet") or not t.get("legacy"):
        return None
    legacy = t["legacy"]
    if legacy.get("retweeted_status_result"):
        # a plain retweet: score the original instead
        return tweet_from_result(_get(legacy, "retweeted_status_result", "result"))

    text = _get(t, "note_tweet", "note_tweet_results", "result", "text") or legacy.get("full_text") or ""
    created = parse_created(legacy.get("created_at"))
    user = _user(_get(t, "core", "user_results", "result"))
    media = [m.get("type") for m in _get(legacy, "extended_entities", "media", default=[])]
    quoted = _unwrap(_get(t, "quoted_status_result", "result"))
    quoted_text = None
    if quoted.get("legacy"):
        qu = _user(_get(quoted, "core", "user_results", "result"))
        quoted_text = f"@{qu['handle']}: {quoted['legacy'].get('full_text', '')}"

    tid = t.get("rest_id") or legacy.get("id_str")
    return {
        "id": tid,
        "url": f"https://x.com/{user['handle'] or 'i'}/status/{tid}",
        "text": text,
        "lang": legacy.get("lang"),
        "created_at": created.isoformat() if created else None,
        "author": user,
        "views": _int(_get(t, "views", "count")),
        "likes": _int(legacy.get("favorite_count")) or 0,
        "replies": _int(legacy.get("reply_count")) or 0,
        "reposts": _int(legacy.get("retweet_count")) or 0,
        "quotes": _int(legacy.get("quote_count")) or 0,
        "bookmarks": _int(legacy.get("bookmark_count")) or 0,
        "is_reply": bool(legacy.get("in_reply_to_status_id_str")),
        "media": media,
        "quoted": quoted_text,
    }


def _walk_entries(obj):
    """Yield every timeline entry in a SearchTimeline payload, wherever the instruction nesting puts it."""
    instructions = _get(obj, "data", "search_by_raw_query", "search_timeline", "timeline", "instructions", default=[])
    for ins in instructions:
        for e in ins.get("entries") or []:
            yield e
        if ins.get("entry"):
            yield ins["entry"]
        for item in ins.get("moduleItems") or []:
            yield item


def posts_from_search(payload):
    out = []
    for entry in _walk_entries(payload):
        entry_id = entry.get("entryId", "")
        if entry_id.startswith(("promoted", "cursor")):
            continue
        content = entry.get("content") or entry.get("item") or {}
        candidates = []
        if _get(content, "itemContent", "tweet_results"):
            candidates.append(content["itemContent"])
        for item in content.get("items") or []:  # conversation / module entries
            ic = _get(item, "item", "itemContent")
            if ic:
                candidates.append(ic)
        for ic in candidates:
            if ic.get("promotedMetadata"):
                continue
            p = tweet_from_result(_get(ic, "tweet_results", "result"))
            if p and p["id"]:
                out.append(p)
    return out


_URL = re.compile(r"https?://\S+")
_WS = re.compile(r"\s+")


def compact_text(text, limit=280):
    t = _WS.sub(" ", _URL.sub("<link>", text or "")).strip()
    return t if len(t) <= limit else t[: limit - 1] + "…"


def age_minutes(post, now=None):
    if not post.get("created_at"):
        return None
    now = now or datetime.now(timezone.utc)
    return max((now - datetime.fromisoformat(post["created_at"])).total_seconds() / 60, 0)
