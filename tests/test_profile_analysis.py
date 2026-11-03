import asyncio
from pathlib import Path

import pytest

from x_scout import analyze, browser, pipeline, profile_analysis as pa, profile_store as store
from x_scout.profile_metrics import compute
from tests.test_profile_metrics import post

PROFILE = {"handle": "mira_builds", "name": "Mira", "bio": "builds", "followers": 1000, "following": 10, "posts_total": 50, "joined": "2020-01-01T00:00:00+00:00", "verified": False}
REPORT = """Some preamble
SUMMARY Builder of small tools.
**SUMMARY** Audience: engineers.
PHASE 2026-08-01..2026-08-20 | HIGH | Moved to long posts | First article | 1, 2
PHASE 2026-08-21..2026-09-01 | maybe | x | y | 999
PHASE no dates | high | x | y | 1
VIRAL 1 | Number first | Post, short | Evals | Morning | - | Concrete number
VIRAL 1 | dupe | a | b | c | d | e
VIRAL 999 | ghost | a | b | c | d | e
HOOK Number first
OPENER We [did X] and [metric] moved
STRUCTURE Claim, proof, link
CTA Ask for a case
FLOP Plain links: median 40
REPEAT Share one failure a week | Post 3, compare median views | 2
REPEAT Copied one | one two three four five six seven eight nine ten | 1
DONT Giveaways | Needs reach, risks a ban
"""


def rows():
    r, m = compute([post(i, views=100 + i) for i in range(10)] + [post(10, views=5000, text=None)], PROFILE)
    return r, m


def test_parse_report_lines():
    r = pa.parse_report(REPORT)
    assert r["summary"] == ["Builder of small tools.", "Audience: engineers."]
    assert [(p["start"], p["confidence"], p["ns"]) for p in r["phases"]] == [("2026-08-01", "high", [1, 2]), ("2026-08-21", "guess", [999])]
    assert r["viral"][0] == {"n": 1, "hook": "Number first", "format": "Post, short", "topic": "Evals", "timing": "Morning", "borrowed": "", "why": "Concrete number"}
    assert r["openers"] == ["We [did X] and [metric] moved"] and r["flops"] == ["Plain links: median 40"]
    assert r["dont"] == [{"tactic": "Giveaways", "why": "Needs reach, risks a ban"}]


def test_resolve_maps_indexes_dedupes_and_drops_copied_text():
    report = pa.parse_report(REPORT)
    posts = [{"id": "a", "text": "one two three four five six seven eight nine ten"}, {"id": "b", "text": "other"}]
    out = pa.resolve(report, {1: posts[0], 2: posts[1]}, posts)
    assert [v["post_id"] for v in out["viral"]] == ["a"]
    assert out["phases"][0]["post_ids"] == ["a", "b"] and out["phases"][1]["post_ids"] == []
    assert [x["item"] for x in out["repeat"]] == ["Share one failure a week"] and out["copies_dropped"] == 1


def test_leftover_row_numbers_become_dates():
    report = pa.parse_report("FLOP n1 flopped, n99 unknown, none here\nREPEAT Do x like n1 | Test | 1")
    p = {"id": "a", "text": "x", "created_at": "2026-10-29T14:00:00+00:00", "views": 12700}
    out = pa.resolve(report, {1: p}, [p])
    assert out["flops"] == ["10-29 (12.7k) flopped, n99 unknown, none here"]
    assert out["repeat"][0] == {"item": "Do x like 10-29 (12.7k)", "test": "Test", "post_ids": ["a"]}


def test_digest_has_reader_metrics_top_and_typical():
    r, m = rows()
    prompt, index = pa.digest("I build automation.", PROFILE, m, r)
    assert "I build automation." in prompt and "@mira_builds" in prompt and "METRICS:" in prompt and "TYPICAL:" in prompt
    assert index[1]["id"] == "10"  # the 5000-view post ranks first
    assert len(index) == len({p["id"] for p in index.values()})
    assert "\n1|2026-" in prompt


def test_select_rows_limits():
    r, _ = compute([post(i, views=100) for i in range(100)], PROFILE)
    top, typical = pa.select_rows(r, top_n=40, typical_n=20)
    assert len(top) == 40 and len(typical) == 20 and not {p["id"] for p in top} & {p["id"] for p in typical}


@pytest.mark.parametrize("raw,want", [("@Mira_B", "Mira_B"), (" mira ", "mira"), ("https://x.com/mira/status/1", "mira"), ("https://twitter.com/mira", "mira")])
def test_clean_handle(raw, want):
    assert store.clean_handle(raw) == want


@pytest.mark.parametrize("raw", ["", "../etc", "a/b", "way_too_long_handle_here", "a b", None])
def test_clean_handle_rejects(raw):
    with pytest.raises(ValueError):
        store.clean_handle(raw)


def _sink_scrape(sink_posts, exc=None):
    async def fake(handle, sink, **kw):
        sink["profile"] = dict(PROFILE)
        sink["posts"].extend(sink_posts)
        if exc:
            raise exc
        return sink
    return fake


def _full(p):
    return {"pinned": False, "self_reply": False, "conversation_id": p["id"], **p}


SETTINGS = {**pipeline.DEFAULT_SETTINGS, "gist_lang": "Russian"}


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(store.config, "PROFILES", tmp_path / "profiles")
    monkeypatch.setattr(pipeline, "load_profile", lambda: "reader")
    return tmp_path


def _recent(i, **kw):
    from datetime import datetime, timedelta, timezone
    return _full({**post(i, **kw), "created_at": (datetime.now(timezone.utc) - timedelta(days=30 - i)).isoformat()})


def test_end_to_end_with_fake_browser_and_claude_then_reanalyze(data, monkeypatch):
    calls = []

    def fake_claude(prompt, model=None, system=None, raw=False, **kw):
        calls.append((model, system))
        return "SUMMARY ok\nVIRAL 1 | h | f | t | w | - | why", {"input_tokens": 10, "output_tokens": 5, "cost_usd_equiv": 0.01, "duration_s": 1}

    monkeypatch.setattr(browser, "scrape_profile", _sink_scrape([_recent(i) for i in range(8)]))
    monkeypatch.setattr(analyze, "run_claude", fake_claude)
    asyncio.run(pipeline.analyze_profile("mira_builds", SETTINGS))
    assert pipeline.state["kind"] == "profile" and not pipeline.state["running"] and not pipeline.state["error"]
    first = pipeline.state["analysis_id"]
    a = store.load_analysis("mira_builds", first)
    assert a["report"]["summary"] == ["ok"] and a["stats"]["claude"]["input_tokens"] == 10 and len(a["posts"]) == 8
    assert calls[0][0] == "sonnet" and "Russian" in calls[0][1]
    assert len(store.snapshots("mira_builds")) == 1

    # re-analysis reads the stored scrape: the browser must not be touched
    monkeypatch.setattr(browser, "scrape_profile", None)
    monkeypatch.setattr(store, "new_id", lambda: "20991231-000000")
    asyncio.run(pipeline.reanalyze_profile("mira_builds", first, SETTINGS))
    b = store.load_analysis("mira_builds", "20991231-000000")
    assert b["stats"]["reanalyzed_from"] == first and b["scrape_id"] == a["scrape_id"]
    assert len(calls) == 2 and len(store.snapshots("mira_builds")) == 1
    h = store.history()
    assert h[0]["handle"] == "mira_builds" and len(h[0]["analyses"]) == 2


def test_rate_limit_keeps_partial_data_without_claude(data, monkeypatch):
    monkeypatch.setattr(browser, "scrape_profile", _sink_scrape([_recent(0)], browser.RateLimited()))
    monkeypatch.setattr(analyze, "run_claude", lambda *a, **k: pytest.fail("no Claude call after a 429"))
    asyncio.run(pipeline.analyze_profile("mira_builds", SETTINGS))
    assert pipeline.state["error"] == "rate_limited"
    a = store.load_analysis("mira_builds", pipeline.state["analysis_id"])
    assert a["status"] == "rate_limited" and a["report"] is None and len(a["posts"]) == 1


def test_claude_failure_keeps_metrics(data, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no")

    monkeypatch.setattr(browser, "scrape_profile", _sink_scrape([_recent(i) for i in range(6)]))
    monkeypatch.setattr(analyze, "run_claude", boom)
    asyncio.run(pipeline.analyze_profile("mira_builds", SETTINGS))
    a = store.load_analysis("mira_builds", pipeline.state["analysis_id"])
    assert a["report"] is None and a["stats"]["claude_error"] == "no" and a["metrics"]["median_views"] == 100


def test_stop_during_scrape(data, monkeypatch):
    monkeypatch.setattr(analyze, "stop_claude", lambda: None)

    async def slow(handle, sink, **kw):
        sink["profile"] = dict(PROFILE)
        sink["posts"].append(_recent(0))
        await asyncio.sleep(30)

    monkeypatch.setattr(browser, "scrape_profile", slow)

    async def go():
        t = asyncio.create_task(pipeline.analyze_profile("mira_builds", SETTINGS))
        await asyncio.sleep(0.01)
        assert pipeline.stop()
        await asyncio.wait_for(t, 2)

    asyncio.run(go())
    assert pipeline.state["error"] == "stopped" and not pipeline.state["running"]
    assert store.load_analysis("mira_builds", pipeline.state["analysis_id"])["status"] == "stopped"


def test_no_posts_means_no_claude_call(data, monkeypatch):
    monkeypatch.setattr(browser, "scrape_profile", _sink_scrape([]))
    monkeypatch.setattr(analyze, "run_claude", lambda *a, **k: pytest.fail("no Claude call without posts"))
    asyncio.run(pipeline.analyze_profile("mira_builds", SETTINGS))
    assert "no posts" in pipeline.state["error"] and len(store.snapshots("mira_builds")) == 1


def test_unknown_account_saves_nothing(data, monkeypatch):
    async def missing(handle, sink, **kw):
        raise LookupError("@ghost: account not found")

    monkeypatch.setattr(browser, "scrape_profile", missing)
    asyncio.run(pipeline.analyze_profile("ghost", SETTINGS))
    assert "not found" in pipeline.state["error"] and store.history() == []
    assert not Path(data / "profiles").exists()
