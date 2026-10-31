import asyncio

from x_scout import analyze, browser, db, pipeline


def test_stop_cancels_run_and_marks_it_stopped(monkeypatch):
    finished = []
    monkeypatch.setattr(db, "create_run", lambda topics: 1)
    monkeypatch.setattr(db, "list_runs", lambda n: [])
    monkeypatch.setattr(db, "finish_run", lambda run_id, status, result=None, stats=None: finished.append(status))
    monkeypatch.setattr(analyze, "stop_claude", lambda: None)

    async def slow_scrape(*a, **k):
        await asyncio.sleep(30)

    monkeypatch.setattr(browser, "scrape", slow_scrape)

    async def go():
        task = asyncio.create_task(pipeline.run({**pipeline.DEFAULT_SETTINGS, "topics": [{"name": "T", "query": "q"}]}))
        await asyncio.sleep(0.01)
        assert pipeline.state["running"] and pipeline.stop()
        await asyncio.wait_for(task, 2)

    asyncio.run(go())
    assert finished == ["stopped"] and not pipeline.state["running"] and not pipeline.stop()
