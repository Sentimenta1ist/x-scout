"""Fixtures use fictional accounts."""
from x_scout.browser import page_reached_cutoff
from x_scout.parse import finalize_timeline, profile_from_user, timeline_page


def user(handle="mira_builds", followers=1000):
    return {"__typename": "User", "core": {"screen_name": handle, "name": handle.title()}, "legacy": {"followers_count": followers}}


def tweet(tid, handle="mira_builds", text="hello there", uid="1", followers=1000, date="Wed Oct 28 10:00:00 +0000 2026", **legacy):
    extra = {k: legacy.pop(k) for k in ("article", "quoted_status_result", "note_tweet", "card") if k in legacy}
    return {"__typename": "Tweet", "rest_id": tid, "core": {"user_results": {"result": user(handle, followers)}}, "views": {"count": "500"},
            "legacy": {"full_text": text, "created_at": date, "user_id_str": uid, "conversation_id_str": tid, "favorite_count": 10,
                       "reply_count": 1, "retweet_count": 2, "quote_count": 3, "bookmark_count": 4, **legacy}, **extra}


def entry(eid, t):
    return {"entryId": eid, "content": {"itemContent": {"tweet_results": {"result": t}}}}


def module(eid, *ts):
    return {"entryId": eid, "content": {"items": [{"item": {"itemContent": {"tweet_results": {"result": t}}}} for t in ts]}}


def page(entries, pin=None, key="timeline"):
    ins = [{"type": "TimelineAddEntries", "entries": entries}]
    if pin:
        ins.insert(0, {"type": "TimelinePinEntry", "entry": pin})
    return {"data": {"user": {"result": {key: {"timeline": {"instructions": ins}}}}}}


def test_profile_new_and_legacy_schema():
    new = {"data": {"user": {"result": {"core": {"screen_name": "Mira", "name": "Mira O", "created_at": "Wed Oct 28 10:00:00 +0000 2020"},
                                        "is_blue_verified": True, "profile_bio": {"description": "builds things"},
                                        "legacy": {"followers_count": 1200, "friends_count": 50, "statuses_count": 900, "pinned_tweet_ids_str": ["7"]}}}}}
    p = profile_from_user(new)
    assert (p["handle"], p["followers"], p["following"], p["posts_total"], p["bio"], p["verified"], p["pinned_id"]) == ("Mira", 1200, 50, 900, "builds things", True, "7")
    assert p["joined"].startswith("2020-10-28")
    old = {"data": {"user": {"result": {"legacy": {"screen_name": "Old", "name": "O", "description": "bio", "followers_count": 3, "created_at": "Wed Oct 28 10:00:00 +0000 2020"}}}}}
    assert profile_from_user(old)["bio"] == "bio"
    assert profile_from_user({"data": {"user": {"result": {"__typename": "UserUnavailable"}}}}) is None
    assert profile_from_user({"data": {}}) is None


def test_profile_current_schema_without_legacy():
    p = profile_from_user({"data": {"user": {"result": {
        "core": {"screen_name": "Mira", "name": "Mira O", "created_at": "Wed Oct 28 10:00:00 +0000 2020"}, "is_blue_verified": True,
        "profile_bio": {"description": "bio"}, "relationship_counts": {"followers": 4063, "following": 12}, "tweet_counts": {"tweets": 321},
        "pinned_items": {"tweet_ids_str": ["7"]}, "privacy": {"protected": False}}}}})
    assert (p["followers"], p["following"], p["posts_total"], p["pinned_id"], p["protected"]) == (4063, 12, 321, "7", False)


def test_article_card_is_not_an_external_link():
    t = tweet("4", article={"article_results": {"result": {"rest_id": "99", "title": "T"}}}, card={"rest_id": "c"})
    assert not timeline_page(page([entry("tweet-4", t)]), "mira_builds")["posts"][0]["has_link"]


def test_timeline_types_and_fields():
    art = tweet("4", text="https://t.co/a", article={"article_results": {"result": {"rest_id": "99", "title": "Long read", "preview_text": "Preview"}}})
    qt = tweet("2", text="my take", quoted_status_result={"result": tweet("20", handle="big_lab", followers=500000, uid="9")},
               quoted_status_id_str="20")
    media = tweet("3", extended_entities={"media": [{"type": "video"}]},
                  entities={"urls": [{"expanded_url": "https://example.com/x"}]})
    selflink = tweet("5", entities={"urls": [{"expanded_url": "https://x.com/i/article/99"}]})
    pg = timeline_page(page([entry("tweet-1", tweet("1")), entry("tweet-2", qt), entry("tweet-3", media), entry("tweet-4", art), entry("tweet-5", selflink),
                             entry("promoted-tweet-6", tweet("6")), entry("cursor-bottom-0", {})]), "MIRA_builds")
    posts = {p["id"]: p for p in pg["posts"]}
    assert sorted(posts) == ["1", "2", "3", "4", "5"]
    assert posts["1"]["type"] == "post" and posts["1"]["media_type"] == "none" and not posts["1"]["has_link"]
    assert (posts["2"]["type"], posts["2"]["quoted_handle"], posts["2"]["quoted_followers"], posts["2"]["quoted_id"]) == ("quote", "big_lab", 500000, "20")
    assert posts["3"]["media_type"] == "video" and posts["3"]["has_link"]
    assert posts["4"]["type"] == "article" and posts["4"]["text"] == "Long read\n\nPreview" and posts["4"]["article_id"] == "99"
    assert posts["5"]["linked_ids"] == ["99"] and not posts["5"]["has_link"]
    assert (posts["1"]["views"], posts["1"]["quotes"], posts["1"]["bookmarks"]) == (500, 3, 4)
    assert pg["accounts"]["big_lab"] == 500000


def test_retweets_skipped_pinned_flagged_other_schema():
    rt = tweet("11", legacy_rt=None)
    rt["legacy"]["retweeted_status_result"] = {"result": tweet("12", handle="other", uid="2")}
    pg = timeline_page(page([entry("tweet-11", rt)], pin=entry("tweet-9", tweet("9")), key="timeline_v2"), "mira_builds")
    assert [(p["id"], p["pinned"]) for p in pg["posts"]] == [("9", True)]
    assert pg["retweets"] == 1


def test_replies_threads_and_reply_target_followers():
    parent = tweet("30", handle="big_lab", followers=900000, uid="9")
    reply = tweet("31", conversation_id_str="30", in_reply_to_status_id_str="30", in_reply_to_user_id_str="9", in_reply_to_screen_name="big_lab")
    start = tweet("40", date="Wed Oct 28 09:00:00 +0000 2026")
    part = tweet("41", conversation_id_str="40", in_reply_to_status_id_str="40", in_reply_to_user_id_str="1", in_reply_to_screen_name="mira_builds")
    pg = timeline_page(page([module("profile-conversation-1", parent, reply), module("profile-conversation-2", start, part)]), "mira_builds")
    assert {p["id"] for p in pg["posts"]} == {"31", "40", "41"}  # parent of another account gives followers, not a post
    posts = {p["id"]: p for p in finalize_timeline(pg["posts"] + pg["posts"], pg["accounts"])}
    assert posts["31"]["type"] == "reply" and posts["31"]["reply_to_followers"] == 900000 and not posts["31"]["self_reply"]
    assert posts["40"]["type"] == "thread"
    assert posts["41"]["type"] == "reply" and posts["41"]["self_reply"]
    assert len(posts) == 3


def test_finalize_sorts_oldest_first():
    pg = timeline_page(page([entry("tweet-2", tweet("2", date="Thu Oct 29 10:00:00 +0000 2026")), entry("tweet-1", tweet("1"))]), "mira_builds")
    assert [p["id"] for p in finalize_timeline(pg["posts"], {})] == ["1", "2"]


def test_cutoff_uses_newest_non_pinned():
    old = {"created_at": "2026-01-01T00:00:00+00:00", "pinned": False}
    new = {"created_at": "2026-10-01T00:00:00+00:00", "pinned": False}
    pinned_old = {**old, "pinned": True}
    cutoff = "2026-06-01T00:00:00+00:00"
    assert page_reached_cutoff([old], cutoff)
    assert not page_reached_cutoff([old, new], cutoff)
    assert not page_reached_cutoff([pinned_old], cutoff)  # pinned alone says nothing
    assert not page_reached_cutoff([], cutoff)
