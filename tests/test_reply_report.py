from x_scout import reply_report as rr


def tweet(tid, created, views, replies):
    return {"__typename": "Tweet", "rest_id": tid, "views": {"count": str(views)},
            "legacy": {"created_at": created, "reply_count": replies, "favorite_count": 3}}


def own(pid, to, created, views=100):
    return {"id": pid, "type": "reply", "self_reply": False, "reply_to_id": to, "reply_to_handle": "big",
            "created_at": created, "views": views, "likes": 1, "url": f"u/{pid}", "text": "@big hi there"}


def test_parents_rows_and_fit():
    responses = [{"data": {"x": [tweet("p1", "Mon Nov 16 19:00:00 +0000 2026", 300_000, 40),
                                 {"__typename": "TweetWithVisibilityResults", "tweet": tweet("p2", "Sun Nov 15 10:00:00 +0000 2026", 20_000, 900)}]}}]
    par = rr.parents(responses)
    assert par["p1"]["views"] == 300_000 and par["p2"]["replies"] == 900
    posts = [own("r1", "p1", "2026-11-16T19:30:00+00:00", 2000), own("r2", "p2", "2026-11-16T10:00:00+00:00", 9),
             {"id": "s", "type": "reply", "self_reply": True, "reply_to_id": "p1"}]
    rows = rr.rows(posts, par, {"p1": "big"}, {"r1": {"impressions": 2100, "likes": 5, "profile_visits": 4, "follows": 1}})
    a, b = rows
    assert a["fit"] and a["stage"] == "big" and a["delay_min"] == 30 and a["views"] == 2100 and a["profile_visits"] == 4
    assert b["why"] == ["older than 3h", "crowded thread", "post under 50k"] and b["stage"] == "manual"
    s = rr.summarize(rows)
    assert s["fit"][0]["n"] == 1 and s["fit"][0]["median_views"] == 2100 and s["stages"][0]["label"] == "big"


def test_analytics_csv_kinds():
    content = "Post id,Date,Post text,Impressions,Likes,Engagements,New follows,Profile visits\n123,\"Mon, Nov 16, 2026\",hi,50,1,2,0,1\n"
    kind, data = rr.parse_analytics("﻿" + content)
    assert kind == "content" and data["123"]["impressions"] == 50 and data["123"]["date"] == "2026-11-16"
    overview = "Date,Impressions,Likes,Engagements,New follows,Unfollows,Profile visits\n\"Sun, Nov 15, 2026\",26481,90,130,8,0,27\n"
    kind, data = rr.parse_analytics(overview)
    assert kind == "overview" and data["2026-11-15"]["follows"] == 8 and data["2026-11-15"]["profile_visits"] == 27
    merged = rr.merge_analytics([("a.csv", content), ("b.csv", overview), ("bad.csv", "x,y\n1,2\n")])
    assert [f["kind"] for f in merged["files"]] == ["content", "overview"]


def test_stage_map_first_run_wins():
    runs = [{"id": 2, "stages": {"trash": {"picks": [{"id": "a"}]}}, "result": []},
            {"id": 1, "stages": {"big": {"picks": [{"id": "a"}]}}, "result": [{"topic": "T", "reply": [{"id": "b"}], "save": []}]}]
    assert rr.stage_map(runs) == {"a": "big", "b": "topics"}
