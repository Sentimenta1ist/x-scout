import threading
import time

from x_scout import analyze
from x_scout.analyze import MAX_PER_COLUMN, assemble, is_junk, parse_picks, ranking_system, select_candidates

REPLY = """# AI agents
R 3 4 | автор выпустил MCP-сервер | young MCP post, fast | ask about auth
S 1 5 | разбор архитектуры | real numbers
junk line
H 2 3 | old format | ignored | x
# Crypto
R #9 2 | g | wrong topic index | x
"""


def _post(pid, views=5000, age=60, score=50, label="normal"):
    return {"id": pid, "url": "u", "text": f"post number {pid} with some text", "author": {"handle": "a", "name": "A", "followers": 1000},
            "views": views, "likes": 50, "replies": 5, "reposts": 5, "bookmarks": 5, "age_min": age,
            "scored": {"score": score, "label": label, "parts": {}}}


def test_parse_picks():
    d = parse_picks(REPLY)
    agents = d["topics"][0]
    assert agents["topic"] == "AI agents"
    assert agents["reply"] == [{"n": 3, "q": 4, "gist": "автор выпустил MCP-сервер", "why": "young MCP post, fast",
                                "angle": "ask about auth"}]
    assert agents["save"] == [{"n": 1, "q": 5, "gist": "разбор архитектуры", "why": "real numbers", "angle": ""}]
    assert d["topics"][1]["reply"][0]["n"] == 9


def test_assemble_maps_index_and_rejects_cross_topic():
    a = [_post("1"), _post("2"), _post("3")]
    c = [_post("9")]
    index = {1: a[0], 2: a[1], 3: a[2], 4: c[0]}
    res = assemble(parse_picks(REPLY), index, {"AI agents": a, "Crypto": c})
    assert [p["id"] for p in res[0]["reply"]] == ["3"]
    assert [p["id"] for p in res[0]["save"]] == ["1"]
    assert res[0]["reply"][0]["gist"] == "автор выпустил MCP-сервер"
    assert res[1]["reply"] == []  # n=9 not in index → dropped


def test_assemble_keeps_post_in_one_column_and_drops_save_angle():
    a = [_post("1"), _post("2")]
    reply = "# T\nR 1 4 | g | a | x\nS 1 4 | g | a again\nS 2 4 | g | b | stray angle\n"
    res = assemble(parse_picks(reply), {1: a[0], 2: a[1]}, {"T": a})[0]
    assert [p["id"] for p in res["reply"]] == ["1"]
    assert [p["id"] for p in res["save"]] == ["2"]
    assert res["save"][0]["angle"] == ""


def test_assemble_caps_each_column_separately():
    a = [_post(str(i)) for i in range(1, 15)]
    reply = "# T\n" + "".join(f"R {i} 4 | g | w | x\n" for i in range(1, 8)) + "".join(f"S {i} 4 | g | w\n" for i in range(8, 15))
    res = assemble(parse_picks(reply), {i + 1: p for i, p in enumerate(a)}, {"T": a})[0]
    assert len(res["reply"]) == MAX_PER_COLUMN and len(res["save"]) == MAX_PER_COLUMN


def test_assemble_moves_old_reply_pick_to_save():
    a = [_post("old", age=25 * 60), _post("new", age=60)]
    res = assemble(parse_picks("# T\nR 1 4 | g | w | x\nR 2 4 | g | w | x\n"), {1: a[0], 2: a[1]}, {"T": a})[0]
    assert [p["id"] for p in res["reply"]] == ["new"]
    assert [p["id"] for p in res["save"]] == ["old"] and res["save"][0]["angle"] == ""


def test_assemble_drops_weak_picks_and_moves_reply_without_reach_to_save():
    big, small_author, no_views = _post("1"), _post("2"), _post("3", views=300)
    small_author["author"] = {**small_author["author"], "followers": 67}
    no_views["scored"] = {**no_views["scored"], "projected": 400}
    weak = _post("4")
    a = [big, small_author, no_views, weak]
    res = assemble(parse_picks("# T\nR 1 4 | g | w | x\nR 2 5 | g | w | x\nR 3 4 | g | w | x\nR 4 3 | g | w | x\nS 4 2 | g | w\n"),
                   {i + 1: p for i, p in enumerate(a)}, {"T": a})[0]
    assert [p["id"] for p in res["reply"]] == ["1"]
    assert [p["id"] for p in res["save"]] == ["2", "3"] and all(p["angle"] == "" for p in res["save"])


def test_young_post_of_real_author_qualifies_by_projected_views():
    p = _post("1", views=400)
    p["scored"] = {**p["scored"], "projected": 3000}
    res = assemble(parse_picks("# T\nR 1 4 | g | w | x\n"), {1: p}, {"T": [p]})[0]
    assert [x["id"] for x in res["reply"]] == ["1"]


def test_is_junk():
    for text in ("Giving away 5x $100 in sol! 1.Follow @x 2. Like & RT this post", "Drop your $SOLANA address",
                 "I want to send some $sol to 5 people that turn my notifications on", "$500 for 5 people who retweet and comment"):
        assert is_junk(text), text
    for text in ("The exploit drained the wallet in two blocks", "We dropped the index and latency fell", "Follow-up on the Postgres postmortem"):
        assert not is_junk(text), text


def test_select_candidates_keeps_room_for_fresh_posts():
    old = [_post(f"o{i}", age=20 * 60, score=90) for i in range(40)]
    fresh = [_post(f"f{i}", age=60, score=10) for i in range(40)]
    picked = select_candidates(old + fresh, limit=20)
    assert sum(p["id"].startswith("f") for p in picked) >= 8


def test_select_candidates_filters_and_dedupes():
    posts = [_post(str(i), score=i) for i in range(40)]
    posts.append({**_post("dup"), "text": "post number 39 with some text"})  # same text as 39
    posts.append(_post("old", age=60 * 48))
    posts.append(_post("tiny", views=50))
    picked = select_candidates(posts, limit=25)
    ids = {p["id"] for p in picked}
    assert len(picked) == 25
    assert "39" in ids and "dup" not in ids and "old" not in ids and "tiny" not in ids


def test_ranking_system_sets_gist_language():
    assert "in Russian" in ranking_system("Russian")
    assert "in English" in ranking_system("")


def test_stop_claude_kills_the_running_call(tmp_path, monkeypatch):
    fake = tmp_path / "claude"
    fake.write_text("#!/bin/sh\nexec sleep 30\n")
    fake.chmod(0o755)
    monkeypatch.setattr(analyze.config, "claude_bin", lambda: str(fake))
    monkeypatch.setattr(analyze.config, "CLAUDE_CWD", tmp_path)
    errors = []

    def call():
        try:
            analyze.run_claude("x", model="m")
        except RuntimeError as e:
            errors.append(str(e))

    t = threading.Thread(target=call)
    t.start()
    while analyze._proc is None:
        time.sleep(0.01)
    analyze.stop_claude()
    t.join(5)
    assert not t.is_alive() and "failed" in errors[0]
