"""Fixtures use fictional accounts."""
import asyncio
from datetime import datetime, timezone

import pytest

from tests.test_profile_parse import module, page, tweet
from x_scout import analyze, browser, pipeline, post_analysis as po
from x_scout.parse import post_detail

SETTINGS = {**pipeline.DEFAULT_SETTINGS, "gist_lang": "Russian"}
REPORT = """VERDICT 2 | Mostly recycled advice.
GIST It says evals matter.
VIRAL Number first | 14% to 3% in the opening line
USEFUL Check tool calls before they run
EMPTY The 3x claim has no source
TAKE Open with the number | Use your own 4% to 61% case
REPEAT adapt | Fits his audience
REPLY say | "same here, the slow part was the queue"
REPLY ask | what broke first when you moved it?
REPLY maybe | wrong kind is ignored
BASE [number before] to [number after] in [time]. here is what changed:
BASE one two three four five six seven eight nine ten
DRAFT the same schema, flattened: tool calls went from 4% to 61%
DRAFT one two three four five six seven eight nine ten
noise line
"""


@pytest.mark.parametrize("raw,key", [("https://x.com/mira/status/123?s=20", "123"), ("https://twitter.com/mira/status/123", "123"), ("https://x.com/mira/article/123", "123"), ("1234567890", "1234567890")])
def test_parse_ref_links(raw, key):
    assert po.parse_ref(raw) == {"key": key, "id": key}


def test_parse_ref_text_and_rejects():
    r = po.parse_ref("  a pasted post that is long enough to read  ")
    assert r["key"].startswith("t") and r["text"] == "a pasted post that is long enough to read"
    assert po.parse_ref("a pasted post that is long enough to read")["key"] == r["key"]
    for bad in ("", "short", "https://example.com/some/long/page/here", "https://x.com/i/article/123"):
        with pytest.raises(ValueError):
            po.parse_ref(bad)


def test_metrics():
    p = {"views": 1000, "likes": 50, "replies": 5, "reposts": 3, "quotes": 2, "bookmarks": 25, "author": {"followers": 500},
         "created_at": "2026-10-28T10:00:00+00:00"}
    m = po.metrics(p, 200, now=datetime(2026, 10, 28, 20, tzinfo=timezone.utc))
    assert (m["er"], m["bookmark_ratio"], m["views_per_follower"], m["vs_median"], m["views_per_h"]) == (0.06, 0.5, 2, 5, 100)
    assert po.metrics({"views": None}) == {}


def test_parse_report_and_copy_guard():
    r = po.parse_report(REPORT, "one two three four five six seven eight nine ten eleven")
    assert (r["score"], r["verdict"], r["gist"], r["repeat"]) == (2, "Mostly recycled advice.", "It says evals matter.", "adapt")
    assert r["viral"] == [{"what": "Number first", "how": "14% to 3% in the opening line"}]
    assert r["useful"] == ["Check tool calls before they run"] and r["empty"] == ["The 3x claim has no source"]
    assert r["draft"] == ["the same schema, flattened: tool calls went from 4% to 61%"] and r["copies_dropped"] == 2
    assert r["replies"] == [{"kind": "say", "text": "same here, the slow part was the queue"}, {"kind": "ask", "text": "what broke first when you moved it?"}]
    assert r["base"] == ["[number before] to [number after] in [time]. here is what changed:"]


def test_post_detail_thread_article_and_missing():
    start = tweet("40")
    part = tweet("41", text="second part", conversation_id_str="40", in_reply_to_status_id_str="40", in_reply_to_user_id_str="1")
    other = tweet("42", handle="stranger", uid="2", conversation_id_str="40", in_reply_to_status_id_str="40", in_reply_to_user_id_str="1")
    p = post_detail([page([module("c", start, part, other)])], "40")
    assert p["type"] == "thread" and [x["text"] for x in p["thread_parts"]] == ["second part"]
    art = tweet("50", article={"article_results": {"result": {"title": "Long read", "content_state": {"blocks": [{"text": "First."}, {"text": "Second."}]}}}})
    assert post_detail([page([module("c", art)])], "50")["text"] == "Long read\n\nFirst.\nSecond."
    assert post_detail([page([module("c", start)])], "999") is None


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(po.config, "POSTS", tmp_path / "posts")
    monkeypatch.setattr(pipeline, "load_profile", lambda: "reader")
    return tmp_path


def fake_claude(calls):
    def run(prompt, model=None, system=None, raw=False, **kw):
        calls.append((prompt, model, system))
        return REPORT, {"input_tokens": 9, "output_tokens": 3, "cost_usd_equiv": 0.01, "duration_s": 1}
    return run


def test_pasted_text_never_opens_x_and_can_be_reanalyzed(data, monkeypatch):
    calls = []
    monkeypatch.setattr(browser, "scrape_post", lambda *a, **k: pytest.fail("pasted text must not open X"))
    monkeypatch.setattr(analyze, "run_claude", fake_claude(calls))
    ref = po.parse_ref("a pasted post that is long enough to read")
    asyncio.run(pipeline.analyze_post(ref, SETTINGS))
    assert pipeline.state["kind"] == "post" and pipeline.state["post_key"] == ref["key"] and not pipeline.state["error"]
    assert po.load(ref["key"])["report"]["score"] == 2 and calls[0][1] == "sonnet" and "Russian" in calls[0][2]
    asyncio.run(pipeline.reanalyze_post(ref["key"], SETTINGS))
    assert len(calls) == 2 and po.history()[0]["score"] == 2


def test_link_reads_post_once_and_claude_failure_keeps_it(data, monkeypatch):
    post = post_detail([page([module("c", tweet("40"))])], "40")

    async def scrape(pid, sink, **kw):
        sink["post"], sink["responses"] = post, [{"x": 1}]
        return sink

    def boom(*a, **k):
        raise RuntimeError("no")

    monkeypatch.setattr(browser, "scrape_post", scrape)
    monkeypatch.setattr(analyze, "run_claude", boom)
    asyncio.run(pipeline.analyze_post({"key": "40", "id": "40"}, SETTINGS))
    r = po.load("40")
    assert r["report"] is None and r["stats"]["claude_error"] == "no" and r["post"]["views"] == 500 and pipeline.state["post_key"] == "40"
    assert (data / "posts" / "40.responses.json.gz").exists()


def test_missing_post_and_rate_limit_save_nothing(data, monkeypatch):
    for exc, word in ((LookupError("Post 1: not found"), "not found"), (browser.RateLimited(), "429")):
        async def scrape(pid, sink, exc=exc, **kw):
            raise exc

        monkeypatch.setattr(browser, "scrape_post", scrape)
        monkeypatch.setattr(analyze, "run_claude", lambda *a, **k: pytest.fail("no Claude call"))
        asyncio.run(pipeline.analyze_post({"key": "1", "id": "1"}, SETTINGS))
        assert word in pipeline.state["error"] and po.history() == []


def test_stop_cancels_post_job(data, monkeypatch):
    monkeypatch.setattr(analyze, "stop_claude", lambda: None)

    async def slow(pid, sink, **kw):
        await asyncio.sleep(30)

    monkeypatch.setattr(browser, "scrape_post", slow)

    async def go():
        t = asyncio.create_task(pipeline.analyze_post({"key": "1", "id": "1"}, SETTINGS))
        await asyncio.sleep(0.01)
        assert pipeline.stop()
        await asyncio.wait_for(t, 2)

    asyncio.run(go())
    assert pipeline.state["error"] == "stopped" and not pipeline.state["running"]


@pytest.mark.parametrize("bad", ["../x", "abc", "t123"])
def test_bad_key_rejected(data, bad):
    with pytest.raises(ValueError):
        po.load(bad)
