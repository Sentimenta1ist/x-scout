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


def test_day_run_fills_stages_in_order(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db.init()
    seen = []

    class FakeSession:
        def __init__(self, *a, **k):
            self.budget = type("B", (), {"calls": 3, "waited": 0})()
            self.log = lambda m: None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *e):
            pass

        async def explore(self):
            return []

        async def search(self, mode, query, target):
            seen.append(query)
            return [post(len(seen), age=20, followers=150_000)], 200

    monkeypatch.setattr(pipeline.browser, "Session", FakeSession)
    monkeypatch.setattr(pipeline, "score_posts", lambda posts: posts)
    monkeypatch.setattr(db, "save_posts", lambda posts: None)

    def fake_claude(prompt, model=None, system=None, raw=False, timeout=600):
        if "end-of-run brief" in system:
            return "SUMMARY hot day\nREC do the news", {"input_tokens": 1, "output_tokens": 1, "cost_usd_equiv": 0, "duration_s": 0}
        return "P 1 5\nGIST g\nSAY s", {"input_tokens": 1, "output_tokens": 1, "cost_usd_equiv": 0, "duration_s": 0}

    monkeypatch.setattr(analyze, "run_claude", fake_claude)
    settings = {**pipeline.DEFAULT_SETTINGS, "topics": [], "stages": {"news": True, "big": True, "viral": False, "trash": True}}
    asyncio.run(pipeline.run_day(settings))
    r = db.get_run(db.latest_run_id())
    assert r["kind"] == "day" and r["status"] == "done"
    assert set(r["stages"]) == {"news", "big", "trash", "summary"}
    assert all(r["stages"][s]["status"] == "ready" for s in ("news", "big", "trash"))
    assert r["stages"]["summary"]["recs"] == ["do the news"]
