import asyncio

from x_scout import browser
from x_scout.browser import Budget, build_queries, search_plan


def test_plan_runs_main_searches_of_all_topics_before_extras():
    topics = [{"name": "A", "query": "a", "extra": ["a1", "a2"]}, {"name": "B", "query": "b"}, {"name": "C", "query": "c", "extra": ["c1"]}]
    plan = [(i, j) for i, j, _, _, _ in search_plan(topics, "en")]
    assert plan == [(0, 0), (0, 1), (1, 0), (1, 1), (2, 0), (2, 1), (0, 2), (0, 3), (2, 2)]


def test_author_search_runs_after_main_and_before_extras():
    topics = [{"name": "A", "query": "a", "extra": ["a1"], "authors": ["@x", "y", "x"]}, {"name": "B", "query": "b"}]
    plan = search_plan(topics, "en")
    assert [k for _, _, k, _, _ in plan] == ["main", "main", "main", "main", "authors", "extra"]
    q = plan[4][4]
    assert q.startswith("(from:x OR from:y)") and "since_time:" in q


def test_queries_use_an_exact_day_and_skip_dead_posts():
    q = build_queries({"name": "A", "query": "a", "extra": ["b"]}, "en")
    assert "since_time:" in q[0][2] and "min_faves:3" in q[0][2] and "since_time:" in q[2][2]
    assert "since:" in build_queries({"name": "A", "query": "a"}, "en", exact_window=False)[0][2]


def test_budget_waits_for_reset_only_when_almost_spent():
    b = Budget(lambda m: None)
    b.update({"x-rate-limit-remaining": "40", "x-rate-limit-reset": "1000"}, 200)
    assert b.wait_s(now=900) == 0
    b.update({"x-rate-limit-remaining": "1", "x-rate-limit-reset": "1000"}, 200)
    assert b.wait_s(now=900) == 105
    b.update({}, 429)  # no headers on the 429: the last known reset still applies
    assert b.remaining == 0 and b.wait_s(now=990) == 15 and b.calls == 3


def test_budget_gives_up_when_reset_is_unknown_or_too_far(monkeypatch):
    b = Budget(lambda m: None)
    b.update({}, 429)
    assert asyncio.run(b.ensure()) is False
    b.update({"x-rate-limit-remaining": "0", "x-rate-limit-reset": str(10**12)}, 200)
    assert asyncio.run(b.ensure()) is False


def test_budget_sleeps_until_reset(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(browser.time, "time", lambda: clock["t"])

    async def fake_sleep(s):
        clock["t"] += s

    monkeypatch.setattr(browser.asyncio, "sleep", fake_sleep)
    waits = []
    b = Budget(lambda m: None, on_wait=waits.append)
    b.update({"x-rate-limit-remaining": "0", "x-rate-limit-reset": "1060"}, 200)
    assert asyncio.run(b.ensure()) is True
    assert clock["t"] >= 1065 and b.remaining is None and waits[0] == 65
