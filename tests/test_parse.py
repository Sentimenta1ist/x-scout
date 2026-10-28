from x_scout.parse import compact_text, posts_from_search


def _user(handle, followers, new_schema=True):
    if new_schema:
        return {"__typename": "User", "core": {"screen_name": handle, "name": handle.title()},
                "legacy": {"followers_count": followers}, "is_blue_verified": True}
    return {"__typename": "User", "legacy": {"screen_name": handle, "name": handle.title(), "followers_count": followers}}


def _tweet(tid, handle, text, views="1500", new_schema=True, **extra):
    t = {
        "__typename": "Tweet",
        "rest_id": tid,
        "core": {"user_results": {"result": _user(handle, 4200, new_schema)}},
        "views": {"count": views},
        "legacy": {"full_text": text, "created_at": "Wed Oct 28 10:00:00 +0000 2026", "lang": "en",
                   "favorite_count": 40, "reply_count": 5, "retweet_count": 7, "quote_count": 1, "bookmark_count": 9},
    }
    t.update(extra)
    return t


def _entry(eid, result):
    return {"entryId": eid, "content": {"itemContent": {"tweet_results": {"result": result}}}}


def payload(entries):
    return {"data": {"search_by_raw_query": {"search_timeline": {"timeline": {"instructions": [
        {"type": "TimelineAddEntries", "entries": entries}]}}}}}


def test_parses_plain_wrapped_long_and_skips_promoted():
    long = _tweet("2", "bob", "short", note_tweet={"note_tweet_results": {"result": {"text": "full long text"}}})
    entries = [
        _entry("tweet-1", _tweet("1", "alice", "hello https://t.co/x")),
        _entry("tweet-2", {"__typename": "TweetWithVisibilityResults", "tweet": long}),
        _entry("promoted-tweet-3", _tweet("3", "ad", "buy")),
        _entry("tweet-4", _tweet("4", "old", "legacy schema", new_schema=False)),
        {"entryId": "cursor-bottom-1", "content": {"value": "x"}},
    ]
    posts = posts_from_search(payload(entries))
    assert [p["id"] for p in posts] == ["1", "2", "4"]
    a = posts[0]
    assert a["author"] == {"handle": "alice", "name": "Alice", "followers": 4200, "verified": True}
    assert (a["views"], a["likes"], a["replies"], a["reposts"], a["bookmarks"]) == (1500, 40, 5, 7, 9)
    assert a["url"] == "https://x.com/alice/status/1"
    assert a["created_at"].startswith("2026-10-28T10:00:00")
    assert posts[1]["text"] == "full long text"
    assert posts[2]["author"]["handle"] == "old"


def test_retweet_resolves_to_original_and_quote_is_kept():
    orig = _tweet("10", "orig", "original")
    rt = _tweet("11", "rter", "RT @orig: original")
    rt["legacy"]["retweeted_status_result"] = {"result": orig}
    qt = _tweet("12", "quoter", "my take", quoted_status_result={"result": _tweet("13", "src", "source post")})
    posts = posts_from_search(payload([_entry("tweet-11", rt), _entry("tweet-12", qt)]))
    assert posts[0]["id"] == "10"
    assert posts[1]["quoted"] == "@src: source post"


def test_missing_views_is_none():
    t = _tweet("5", "x", "no views")
    del t["views"]
    assert posts_from_search(payload([_entry("tweet-5", t)]))[0]["views"] is None


def test_compact_text():
    assert compact_text("a  b\n\nc https://t.co/abc") == "a b c <link>"
    assert len(compact_text("x" * 500, 100)) == 100
