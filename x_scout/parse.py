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


# ---- profile analysis: UserByScreenName and the profile timelines ----

def _find_instructions(obj, depth=0):
    """X nests timelines differently per schema (timeline_v2, timeline, ...): find the 'instructions' list wherever it is."""
    if not isinstance(obj, dict) or depth > 8:
        return []
    if isinstance(obj.get("instructions"), list):
        return obj["instructions"]
    for v in obj.values():
        if found := _find_instructions(v, depth + 1):
            return found
    return []


def _item_contents(entry):
    content = entry.get("content") or entry.get("item") or {}
    if _get(content, "itemContent", "tweet_results"):
        yield content["itemContent"]
    for item in content.get("items") or []:
        ic = _get(item, "item", "itemContent")
        if ic and ic.get("tweet_results"):
            yield ic


def profile_from_user(payload):
    """UserByScreenName JSON → profile dict, or None if the account does not exist / is unavailable."""
    u = _unwrap(_get(payload, "data", "user", "result") or _get(payload, "data", "user_result", "result"))
    legacy, core = u.get("legacy") or {}, u.get("core") or {}
    handle = core.get("screen_name") or legacy.get("screen_name")
    if not handle:
        return None
    created = parse_created(core.get("created_at") or legacy.get("created_at"))
    pinned = _get(u, "pinned_items", "tweet_ids_str") or legacy.get("pinned_tweet_ids_str") or []
    return {
        "handle": handle,
        "name": core.get("name") or legacy.get("name") or handle,
        "bio": _get(u, "profile_bio", "description") or legacy.get("description") or "",
        "followers": _int(legacy.get("followers_count")) or _int(_get(u, "relationship_counts", "followers")) or 0,
        "following": _int(legacy.get("friends_count")) or _int(_get(u, "relationship_counts", "following")) or 0,
        "posts_total": _int(legacy.get("statuses_count")) or _int(_get(u, "tweet_counts", "tweets")) or 0,
        "joined": created.isoformat() if created else None,
        "verified": bool(u.get("is_blue_verified") or legacy.get("verified")),
        "protected": bool(legacy.get("protected") or _get(u, "privacy", "protected")),
        "pinned_id": pinned[0] if pinned else None,
    }


_STATUS_URL = re.compile(r"(?:x|twitter)\.com/(?:\w+/status(?:es)?|i/(?:web/status|article))/(\d+)", re.IGNORECASE)


def _urls(t, legacy):
    entities = legacy.get("entities") or {}
    urls = [u.get("expanded_url") or "" for u in entities.get("urls") or []]
    urls += [u.get("expanded_url") or "" for u in _get(t, "note_tweet", "note_tweet_results", "result", "entity_set", "urls", default=[])]
    return [u for u in urls if u]


def _media_type(media):
    if "video" in media:
        return "video"
    if "animated_gif" in media:
        return "gif"
    return "photo" if "photo" in media else "none"


def profile_post(result):
    """One timeline tweet → flat post with the fields profile analysis needs. Plain retweets return None."""
    t = _unwrap(result)
    legacy = t.get("legacy") or {}
    if legacy.get("retweeted_status_result"):
        return None
    p = tweet_from_result(t)
    if not p or not p["id"]:
        return None
    article = _get(t, "article", "article_results", "result") or {}
    urls = _urls(t, legacy)
    linked_ids = [m.group(1) for u in urls if (m := _STATUS_URL.search(u))]
    quoted = _unwrap(_get(t, "quoted_status_result", "result"))
    qu = _user(_get(quoted, "core", "user_results", "result")) if quoted.get("legacy") else {}
    reply_to = legacy.get("in_reply_to_status_id_str")
    self_reply = bool(reply_to) and legacy.get("in_reply_to_user_id_str") == legacy.get("user_id_str")
    if article:
        title, preview = article.get("title") or "", article.get("preview_text") or ""
        p["text"] = f"{title}\n\n{preview}".strip() or p["text"]
    if article:
        kind = "article"
    elif reply_to:
        kind = "reply"
    elif qu:
        kind = "quote"
    else:
        kind = "post"
    p.update(
        type=kind,
        media_type=_media_type(p["media"]),
        has_link=(bool(t.get("card")) and not article) or any(not _STATUS_URL.search(u) for u in urls),
        linked_ids=linked_ids,
        conversation_id=legacy.get("conversation_id_str"),
        self_thread_id=_get(legacy, "self_thread", "id_str"),
        reply_to_id=reply_to,
        reply_to_handle=legacy.get("in_reply_to_screen_name"),
        reply_to_followers=None,
        self_reply=self_reply,
        quoted_id=quoted.get("rest_id") or legacy.get("quoted_status_id_str"),
        quoted_handle=qu.get("handle"),
        quoted_followers=qu.get("followers"),
        article_id=article.get("rest_id"),
        article_title=article.get("title"),
        pinned=False,
    )
    return p


def timeline_page(payload, handle):
    """A profile timeline response (posts or replies tab) → {"posts": own posts, "accounts": {lower handle: followers}, "retweets": n}.
    Parents shown in conversation modules are not kept as posts, but give us the follower count of who was replied to."""
    handle = handle.lower()
    posts, accounts, retweets = [], {}, 0
    for ins in _find_instructions(payload):
        pin = ins.get("type") == "TimelinePinEntry"
        entries = list(ins.get("entries") or []) + list(ins.get("moduleItems") or [])
        if ins.get("entry"):
            entries.append(ins["entry"])
        for entry in entries:
            if entry.get("entryId", "").startswith(("promoted", "cursor", "who-to-follow")):
                continue
            for ic in _item_contents(entry):
                if ic.get("promotedMetadata"):
                    continue
                raw = _get(ic, "tweet_results", "result")
                t = _unwrap(raw)
                author = _user(_get(t, "core", "user_results", "result"))
                if author["handle"]:
                    accounts[author["handle"].lower()] = author["followers"]
                if author["handle"].lower() != handle:
                    continue
                if (t.get("legacy") or {}).get("retweeted_status_result"):
                    retweets += 1
                    continue
                p = profile_post(t)
                if p:
                    p["pinned"] = pin
                    if p.get("quoted_handle"):
                        accounts[p["quoted_handle"].lower()] = p["quoted_followers"]
                    posts.append(p)
    return {"posts": posts, "accounts": accounts, "retweets": retweets}


def finalize_timeline(posts, accounts):
    """Dedupe (a post can come from both tabs), mark thread starts, fill reply targets' followers. Oldest first."""
    by_id = {}
    for p in posts:
        by_id[p["id"]] = {**by_id.get(p["id"], {}), **p, "pinned": p["pinned"] or by_id.get(p["id"], {}).get("pinned", False)}
    self_threads = {p["conversation_id"] for p in by_id.values() if p["self_reply"]}
    for p in by_id.values():
        if p["type"] in ("post", "quote") and (p["id"] in self_threads or p.get("self_thread_id") == p["id"]):
            p["type"] = "thread"
        if p.get("reply_to_handle"):
            p["reply_to_followers"] = accounts.get(p["reply_to_handle"].lower())
    return sorted(by_id.values(), key=lambda p: p["created_at"] or "")
