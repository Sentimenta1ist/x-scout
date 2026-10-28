from x_scout.analyze import assemble, parse_picks, ranking_system, select_candidates

REPLY = """# AI agents
H 3 4 | автор выпустил MCP-сервер | young MCP post, fast | ask about auth
G 1 5 | крупный запуск | big launch
U 2 3 | ищет, как разбирать счета | lead: invoice automation | offer PDF → sheet flow
junk line
# Crypto
H #9 2 | g | wrong topic index | x
"""


def _post(pid, views=5000, age=60, score=50):
    return {"id": pid, "url": "u", "text": f"post number {pid} with some text", "author": {"handle": "a", "name": "A", "followers": 1000},
            "views": views, "likes": 50, "replies": 5, "reposts": 5, "bookmarks": 5, "age_min": age,
            "scored": {"score": score, "label": "normal", "parts": {}}}


def test_parse_picks():
    d = parse_picks(REPLY)
    agents = d["topics"][0]
    assert agents["topic"] == "AI agents"
    assert agents["hot"] == [{"n": 3, "q": 4, "gist": "автор выпустил MCP-сервер", "why": "young MCP post, fast",
                              "angle": "ask about auth"}]
    assert agents["global"][0] == {"n": 1, "q": 5, "gist": "крупный запуск", "why": "big launch", "angle": ""}
    assert agents["useful"][0]["angle"] == "offer PDF → sheet flow"
    assert d["topics"][1]["hot"][0]["n"] == 9


def test_assemble_maps_index_and_rejects_cross_topic():
    a = [_post("1"), _post("2"), _post("3")]
    c = [_post("9")]
    index = {1: a[0], 2: a[1], 3: a[2], 4: c[0]}
    res = assemble(parse_picks(REPLY), index, {"AI agents": a, "Crypto": c})
    assert [p["id"] for p in res[0]["hot"]] == ["3"]
    assert res[0]["useful"][0]["why"].startswith("lead")
    assert res[0]["hot"][0]["gist"] == "автор выпустил MCP-сервер"
    assert res[1]["hot"] == []  # n=9 not in index → dropped


def test_select_candidates_filters_and_dedupes():
    posts = [_post(str(i), score=i) for i in range(40)]
    posts.append({**_post("dup"), "text": "post number 39 with some text"})  # same text as 39
    posts.append(_post("old", age=60 * 48))
    posts.append(_post("tiny", views=50))
    picked = select_candidates(posts, limit=25)
    ids = {p["id"] for p in picked}
    assert len(picked) == 25
    assert "39" in ids and "dup" not in ids and "old" not in ids and "tiny" not in ids


def test_assemble_keeps_post_in_one_column():
    a = [_post("1"), _post("2")]
    reply = "# T\nH 1 4 | g | a | x\nG 1 4 | g | a again\nG 2 3 | g | b\nU 1 4 | g | a third | y\n"
    res = assemble(parse_picks(reply), {1: a[0], 2: a[1]}, {"T": a})[0]
    assert [p["id"] for p in res["hot"]] == ["1"]
    assert res["useful"] == [] and [p["id"] for p in res["global"]] == ["2"]


def test_ranking_system_sets_gist_language():
    assert "in Russian" in ranking_system("Russian")
    assert "in English" in ranking_system("")
