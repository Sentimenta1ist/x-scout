import json
import random
from datetime import datetime, timedelta, timezone

from x_scout.typer import key_delays, pick_queue, sent_from_request

NOW = datetime(2026, 11, 18, 2, 0, tzinfo=timezone.utc)


def _pick(pid, age_min, views=100000, replies=20, say=("hi there",)):
    return {"id": pid, "url": f"https://x.com/a/status/{pid}", "author": {"handle": "a"}, "text": "t",
            "created_at": (NOW - timedelta(minutes=age_min)).isoformat(), "views": views, "replies": replies,
            "say": list(say)}


def test_delays_bounds_and_punctuation():
    rng = random.Random(1)
    d = key_delays("a" * 200, rng)
    assert len(d) == 200 and all(0.04 <= x <= 0.13 + 1.6 for x in d)
    assert sum(x < 0.131 for x in d) > 180  # thinking pauses are rare
    rng = random.Random(2)
    plain = key_delays("aaaa", rng)
    rng = random.Random(2)
    assert key_delays("a.a.", rng)[1] > plain[1]


def test_queue_filters_cold_seen_and_empty():
    stages = {"big": {"picks": [_pick("1", 30), _pick("2", 300), _pick("3", 30, say=())]},
              "news": {"picks": [_pick("4", 60), _pick("1", 30)]},
              "viral": {"picks": [_pick("9", 10)]}}
    q = pick_queue(stages, sent_ids={"4"}, limit=5, now=NOW)
    assert [i["id"] for i in q] == ["1"]
    assert q[0]["draft"] == "hi there" and q[0]["stage"] == "big"


def test_queue_limit():
    stages = {"big": {"picks": [_pick(str(i), 20) for i in range(10)]}}
    assert len(pick_queue(stages, set(), limit=4, now=NOW)) == 4


def test_sent_from_request():
    body = json.dumps({"variables": {"tweet_text": "ok then", "reply": {"in_reply_to_tweet_id": "42"}}})
    assert sent_from_request(body) == ("ok then", "42")
    assert sent_from_request("not json") == (None, None)
