import asyncio
from datetime import datetime, timezone

from x_scout import analyze, db, pipeline, stages
from x_scout.parse import explore_items


def post(i, age=30, views=10_000, likes=50, replies=5, followers=100_000, text=None, is_reply=False):
    return {"id": str(i), "url": f"https://x.com/a/status/{i}", "text": text or f"post number {i} about ai and jobs",
            "created_at": None, "author": {"handle": f"a{i}", "name": "A", "followers": followers}, "views": views,
            "likes": likes, "replies": replies, "reposts": 1, "quotes": 0, "bookmarks": 2, "media": [], "quoted": None,
            "is_reply": is_reply, "age_min": age, "scored": {"score": 10, "label": "low", "parts": {}}}


def test_every_stage_has_queries_with_a_window():
    now = datetime(2026, 11, 4, tzinfo=timezone.utc)
    for st in ("news", "big", "viral", "trash"):
        qs = stages.queries(st, {"lang": "en"}, now)
        assert qs and all("since_time:" in q and "-filter:replies" in q for _, q, _ in qs)
    big = stages.queries("big", {"lang": "en", "big_accounts": [f"@h{i}" for i in range(40)]}, now)
    assert sum(q.startswith("(from:") for _, q, _ in big) == 2  # 30 handles max, 15 per query
    assert not stages.queries("viral", {"lang": ""}, now)[0][1].startswith("-")


def test_select_keeps_fresh_posts_of_the_right_size():
    posts = [post(1, age=60, followers=500_000), post(2, age=400, followers=500_000), post(3, age=30, followers=5_000),
             post(4, age=30, followers=500_000, is_reply=True)]
    assert [p["id"] for p in stages.select("big", posts)] == ["1"]
    assert [p["id"] for p in stages.select("trash", posts)] == ["3"]


def test_select_drops_duplicate_texts():
    posts = [post(1, text="Same text here"), post(2, text="same text here!")]
    assert len(stages.select("news", posts)) == 1


def test_parse_and_assemble_posts_and_trends():
    text = """P 2 5
GIST two
TAKE first take
TAKE second take
P t1 4
GIST a trend
P 9 5
GIST unknown index
P 1 2
GIST too weak
P 2 4
GIST repeat"""
    picks = stages.parse(text)
    _, index = stages.digest("me", [post(1), post(2)], [{"name": "Big Story", "context": "c", "meta": "10k posts"}])
    cards = stages.assemble("news", picks, index)
    assert [c["key"] for c in cards] == ["news:2", "news:t:bigstory"]
    assert cards[0]["take"] == ["first take", "second take"] and cards[0]["q"] == 5 and cards[0]["stage"] == "news"


def test_assemble_keeps_two_own_posts_per_stage():
    _, index = stages.digest("me", [post(1), post(2)])
    news = stages.assemble("news", [{"n": "1", "q": 5, "take": ["a", "b"], "say": ["r1"]},
                                    {"n": "2", "q": 4, "take": ["c"], "say": ["r2"]}], index)
    assert [c["take"] for c in news] == [["a", "b"], []] and [c["say"] for c in news] == [["r1"], ["r2"]]
    viral = stages.assemble("viral", [{"n": "1", "q": 5, "take": [], "say": [], "rewrite": "x", "opposite": "y"},
                                      {"n": "2", "q": 4, "take": [], "say": [], "rewrite": "z"}], index)
    assert viral[0]["rewrite"] == "x" and viral[0]["opposite"] == "y" and "rewrite" not in viral[1]


def test_summary_parse():
    s = stages.parse_summary("SUMMARY AI layoffs dominate\n- REC: post on the layoffs story first\nnoise")
    assert s == {"lines": ["AI layoffs dominate"], "recs": ["post on the layoffs story first"]}


def test_explore_items_reads_trends_and_posts():
    payload = {"data": {"timeline": {"instructions": [{"entries": [
        {"content": {"itemContent": {"__typename": "TimelineTrend", "name": "OpenAI", "trend_metadata": {"domain_context": "Technology"},
                                     "social_context": {"text": "120K posts"}}}},
        {"content": {"itemContent": {"tweet_results": {"result": {"__typename": "Tweet", "rest_id": "77",
            "core": {"user_results": {"result": {"legacy": {"screen_name": "x", "followers_count": 5}}}},
            "legacy": {"full_text": "hello", "created_at": "Wed Oct 28 10:00:00 +0000 2026", "favorite_count": 1}}}}}},
    ]}]}}}
    out = explore_items([{"op": "GenericTimelineById", "data": payload}])
    assert out["trends"][0]["name"] == "OpenAI" and out["trends"][0]["context"] == "120K posts"
    assert [p["id"] for p in out["posts"]] == ["77"]


def test_db_stage_and_checks(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db.init()
    db.init()  # migrations are idempotent
    rid = db.create_run([])
    db.set_kind(rid, "day")
    db.update_stage(rid, "news", status="scraping")
    db.update_stage(rid, "news", status="ready", count=2)
    assert db.set_check(rid, "news:1", True) == {"news:1": True}
    assert db.set_check(rid, "news:1", False) == {}
    db.finish_run(rid, "done", None, {})
    r = db.get_run(rid)
    assert r["kind"] == "day" and r["stages"]["news"] == {"status": "ready", "count": 2} and r["status"] == "done"
    assert db.set_check(999, "x", True) is None


def test_session_reads_radar_posts_in_batches(tmp_path, monkeypatch):
    import time as _t
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db.init()
    monkeypatch.setattr(db, "author_history", lambda *a, **k: [])
    monkeypatch.setattr(db, "last_snapshot", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "BATCH_SIZE", 1)
    monkeypatch.setattr(pipeline, "BATCH_MAX", 1)
    pipeline.FEED.clear()
    now_ms = _t.time() * 1000
    pipeline.feed_add([
        {"id": str(i), "handle": f"a{i}", "created": now_ms - 40 * 60000, "text": f"fresh post number {i} taking off", "views": 30000, "replies": 5, "likes": 900}
        for i in (1, 2)])
    prompts = []

    def fake_claude(prompt, model=None, system=None, raw=False, timeout=600):
        if "end-of-run brief" in system:
            return "SUMMARY quiet day\nREC reply more", {"input_tokens": 1, "output_tokens": 1, "cost_usd_equiv": 0, "duration_s": 0}
        prompts.append(prompt)
        pipeline.session["finish"] = True  # he presses Finish while Claude reads the first batch
        return "P 1 5\nGIST g\nSAY s\nTAKE t", {"input_tokens": 1, "output_tokens": 1, "cost_usd_equiv": 0, "duration_s": 0}

    monkeypatch.setattr(analyze, "run_claude", fake_claude)
    asyncio.run(pipeline.run_session({**pipeline.DEFAULT_SETTINGS}))
    r = db.get_run(db.latest_run_id())
    assert r["kind"] == "day" and r["status"] == "done" and r["stats"]["batches"] == 2
    assert len(prompts) == 2 and "COVERED" in prompts[1]  # the second batch knows what the first one covered
    feed = r["stages"]["feed"]
    assert feed["status"] == "ready" and {p["id"] for p in feed["picks"]} == {"1", "2"}
    assert feed["picks"][0]["take"] == ["t"] and r["stages"]["summary"]["recs"] == ["reply more"]
    pipeline.FEED.clear()


def test_search_hints_turn_scraper_queries_into_links():
    from datetime import datetime, timezone
    h = pipeline.search_hints({**pipeline.DEFAULT_SETTINGS, "big_accounts": ["@karpathy"]}, now=datetime(2026, 11, 22, tzinfo=timezone.utc))
    assert h["searches"] and all("since_time" not in q["query"] for q in h["searches"])
    assert any("within_time:12h" in q["query"] for q in h["searches"])
    assert any(q["mode"] == "Latest" and q["url"].endswith("&f=live") for q in h["searches"])
    assert h["accounts"] == [{"handle": "karpathy", "url": "https://x.com/karpathy"}]


def test_feed_checks_are_looser_than_search_checks():
    from x_scout.scoring import FEED_FIT, reply_fit
    mid = {"views": 4000, "replies": 3, "age_min": 40}  # heading to ~17-25k
    p = {"views": 6000, "replies": 8, "age_min": 40, "id": "9", "text": "a mid post taking off now", "author": {"handle": "a"}}
    assert not reply_fit(p)["ok"] and reply_fit(p, FEED_FIT)["ok"]
    assert reply_fit(mid)["why"] == ["won't reach 50k"]


def test_select_ranks_by_reply_value_and_news_window_is_6h():
    fresh = post(1, age=20, views=30_000, replies=10, followers=500_000)
    peaked = post(2, age=170, views=900_000, replies=1800, followers=500_000)  # 20 replies per 10k views: drowned
    assert [p["id"] for p in stages.select("big", [peaked, fresh])] == ["1"]  # crowded threads never reach Claude
    assert [p["id"] for p in stages.select("news", [post(3, age=8 * 60), post(4, age=60)])] == ["4"]


def test_reply_fit_and_crowd_per_view():
    from x_scout.scoring import reply_fit, reply_value
    fresh = {"views": 40_000, "replies": 8, "age_min": 40}
    assert reply_fit(fresh)["ok"]
    assert reply_fit({**fresh, "age_min": 200})["why"] == ["older than 3h"]
    assert "crowded thread" in reply_fit({**fresh, "replies": 80})["why"]
    assert "2k+ replies" in reply_fit({"views": 5_000_000, "replies": 2500, "age_min": 60})["why"]
    assert "won't reach 50k" in reply_fit({"views": 900, "replies": 0, "age_min": 100})["why"]
    # same raw reply count, ten times the audience: the big post is the quieter thread
    assert reply_value({"views": 400_000, "replies": 100, "age_min": 60})["crowd"] > reply_value({"views": 40_000, "replies": 100, "age_min": 60})["crowd"]
    assert reply_value({"views": 5_000_000, "replies": 2500, "age_min": 60})["score"] == 0


def test_trash_needs_a_post_heading_somewhere_and_cards_carry_fit():
    small = post(1, age=60, views=900, replies=1, followers=5000)
    rising = post(2, age=30, views=6000, replies=2, followers=50_000)
    assert [p["id"] for p in stages.select("trash", [small, rising])] == ["2"]
    cards = stages.assemble("big", [{"n": "1", "q": 4, "take": [], "say": ["x"]}], {"1": rising})
    assert cards[0]["fit"]["ok"] is False and cards[0]["fit"]["why"] == ["won't reach 50k"]


def test_more_pool_fresh_unpicked_unsent_from_runs():
    from datetime import datetime, timedelta, timezone
    from x_scout.stages import covered_lines, more_pool
    now = datetime(2026, 11, 18, 3, 0, tzinfo=timezone.utc)

    def c(pid, age, views=60000, replies=10, text="a real post about something"):
        return {"id": pid, "created_at": (now - timedelta(minutes=age)).isoformat(), "views": views,
                "replies": replies, "text": text, "author": {"handle": "a", "followers": 100000}}

    cur = {"big": {"cands": [c("1", 30), c("2", 30), c("3", 400)]}, "news": {"cands": [c("4", 60, replies=500)]}}
    old = {"big": {"cands": [c("1", 30), c("5", 90)]}, "trash": {"cands": [c("6", 20)]}}
    pool = more_pool([cur, old], picked_ids={"2"}, sent_ids={"6"}, now=now)
    assert {p["id"] for p in pool} == {"1", "5"}  # 2 picked, 3 old, 4 crowded, 6 sent
    assert all(abs(p["age_min"] - 30) < 1 or abs(p["age_min"] - 90) < 1 for p in pool)
    assert covered_lines([{"gist": "outages"}])[0] == "COVERED:" and covered_lines([]) == []


def test_feed_posts_from_radar_go_through_the_reply_checks(monkeypatch):
    import time as _t
    from x_scout import db, pipeline
    monkeypatch.setattr(db, "author_history", lambda *a, **k: [])  # no real db in tests (CI has none)
    monkeypatch.setattr(db, "last_snapshot", lambda *a, **k: None)
    pipeline.FEED.clear()
    now_ms = _t.time() * 1000
    kept = pipeline.feed_add([
        {"id": "11", "handle": "a", "created": now_ms - 40 * 60000, "text": "fresh post taking off fast", "views": 30000, "replies": 5, "likes": 900},
        {"id": "12", "handle": "b", "created": now_ms - 5 * 3600000, "text": "old post from this morning", "views": 900000, "replies": 50},
        {"id": "x", "handle": "c", "created": now_ms, "text": "bad id"},
    ])
    assert kept == 2 and pipeline.FEED["11"]["url"] == "https://x.com/a/status/11"
    posts = pipeline.score_posts([{k: v for k, v in p.items() if k != "_got"} for p in pipeline.FEED.values()])
    assert [p["id"] for p in stages.select("feed", posts)] == ["11"]
    pipeline.FEED.clear()
