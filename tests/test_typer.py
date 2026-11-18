from x_scout import typer as typer_mod


def _typer(monkeypatch):
    calls = []
    monkeypatch.setattr(typer_mod.db, "log_sent", lambda *a, **k: calls.append(("log", a)))
    monkeypatch.setattr(typer_mod.db, "set_check", lambda *a, **k: calls.append(("check", a)))
    return typer_mod.Typer(), calls


ITEM = {"run_id": 1, "id": "42", "key": "big:42", "draft": "hello there", "own_handle": "me"}


def test_queue_take_and_sent(monkeypatch):
    t, calls = _typer(monkeypatch)
    t.queue(dict(ITEM))
    assert t.state["status"] == "queued" and t.take("42")["draft"] == "hello there"
    t.report("42", "waiting", typed="hello there")
    assert t.state["exact"] is True
    assert t.sent("42", "hello there!") is True
    assert t.state["status"] == "sent" and t.take("42") is None
    assert calls[0][1][2] == "hello there!" and calls[1] == ("check", (1, "big:42", True))
    assert t.sent("42", "again") is False


def test_already_and_mismatch(monkeypatch):
    t, calls = _typer(monkeypatch)
    t.queue(dict(ITEM))
    t.report("42", "waiting", typed="бу hello there")
    assert t.state["exact"] is False
    t.report("42", "already")
    assert t.take("42") is None and calls[0][1][3] == "already"
    t.report("42", "bogus")
    assert t.state["status"] == "already"
