import json
import random

from x_scout.typer import key_delays, own_reply, sent_from_request


def test_delays_bounds_and_punctuation():
    d = key_delays("a" * 200, random.Random(1))
    assert len(d) == 200 and all(0.04 <= x <= 0.13 + 1.6 for x in d)
    assert sum(x < 0.131 for x in d) > 180  # thinking pauses are rare
    assert key_delays("a.a.", random.Random(2))[1] > key_delays("aaaa", random.Random(2))[1]


def test_sent_from_request():
    body = json.dumps({"variables": {"tweet_text": "ok then", "reply": {"in_reply_to_tweet_id": "42"}}})
    assert sent_from_request(body) == ("ok then", "42")
    assert sent_from_request("not json") == (None, None)


def _tweet(rid, reply_to, name, new_schema=True):
    user = {"core": {"screen_name": name}} if new_schema else {"legacy": {"screen_name": name}}
    return {"rest_id": rid, "core": {"user_results": {"result": user}},
            "legacy": {"in_reply_to_status_id_str": reply_to, "full_text": "x"}}


def test_own_reply_found_in_nested_payload():
    payload = {"data": {"threaded_conversation_with_injections_v2": {"instructions": [{"entries": [
        {"content": {"itemContent": {"tweet_results": {"result": _tweet("1", None, "author")}}}},
        {"content": {"items": [{"item": {"itemContent": {"tweet_results": {"result": _tweet("7", "1", "SentimentGod", False)}}}}]}},
    ]}]}}}
    assert own_reply([payload], "1", "@sentimentGod") == "7"
    assert own_reply([payload], "1", "someoneelse") is None
    assert own_reply([payload], "2", "sentimentGod") is None
    assert own_reply([payload], "1", "") is None
