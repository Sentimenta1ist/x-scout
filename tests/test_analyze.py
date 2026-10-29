from x_scout.analyze import MAX_PER_TOPIC, assemble, parse_picks, ranking_system, select_candidates

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
    reply = "# T\nR 1 4 | g | a | x\nS 1 4 | g | a again\nS 2 3 | g | b | stray angle\n"
    res = assemble(parse_picks(reply), {1: a[0], 2: a[1]}, {"T": a})[0]
    assert [p["id"] for p in res["reply"]] == ["1"]
    assert [p["id"] for p in res["save"]] == ["2"]
    assert res["save"][0]["angle"] == ""


def test_assemble_caps_posts_per_topic():
    a = [_post(str(i)) for i in range(1, 9)]
    reply = "# T\n" + "".join(f"R {i} 3 | g | w | x\n" for i in range(1, 4)) + "".join(f"S {i} 3 | g | w\n" for i in range(4, 9))
    res = assemble(parse_picks(reply), {i + 1: p for i, p in enumerate(a)}, {"T": a})[0]
    assert len(res["reply"]) == 3 and len(res["save"]) == MAX_PER_TOPIC - 3


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
