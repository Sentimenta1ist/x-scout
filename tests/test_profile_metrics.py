from datetime import datetime, timedelta, timezone

from x_scout.profile_metrics import annotate, article_chains, borrowed_reach, cadence, compute, growth_phases, rolling_median

T0 = datetime(2026, 8, 3, 12, tzinfo=timezone.utc)


def post(i, views=100, type="post", hours=None, **kw):
    t = T0 + timedelta(hours=hours if hours is not None else i * 24)
    return {"id": str(i), "url": f"https://x.com/m/status/{i}", "created_at": t.isoformat(), "text": f"post {i}", "type": type, "views": views,
            "likes": 10, "replies": 1, "reposts": 2, "quotes": 3, "bookmarks": 5, **kw}


def test_rolling_median_window_and_gaps():
    assert rolling_median([1, 2, 3, 100], 3) == [1, 1.5, 2, 3]
    assert rolling_median([None, 4, None, 6], 7) == [None, 4, 4, 5]


def test_engagement_and_bookmark_ratio():
    q = annotate([post(0, views=1000)])[0]
    assert q["er"] == 0.016 and q["bookmark_ratio"] == 0.5
    assert annotate([post(0, views=None)])[0]["er"] is None


def test_breakout_at_exactly_5x_and_own_views_excluded():
    posts = [post(i) for i in range(10)] + [post(10, views=500), post(11, views=499)]
    rows = annotate(posts)
    assert rows[10]["ratio"] == 5 and rows[10]["breakout"]
    assert not rows[11]["breakout"]
    assert not any(r["breakout"] for r in rows[:10])


def test_early_post_uses_first_posts_as_baseline():
    rows = annotate([post(0, views=5000)] + [post(i) for i in range(1, 8)])
    assert rows[0]["baseline"] == 100 and rows[0]["breakout"]


def test_replies_do_not_lower_baseline_and_can_break_out():
    posts = [post(i) for i in range(6)] + [post(i, views=1, type="reply") for i in range(6, 40)]
    posts.append(post(40, views=200))
    assert annotate(posts)[-1]["baseline"] == 100
    assert annotate([post(i) for i in range(6)] + [post(6, views=900, type="reply")])[-1]["breakout"]


def test_too_few_posts_have_no_ratio():
    assert annotate([post(0), post(1)])[1]["ratio"] is None


def test_article_chain_groups_quote_reply_link_within_7_days():
    posts = [
        post(0, type="article", article_id="A9", article_title="Deep dive", views=5000, hours=0),
        post(1, type="quote", quoted_id="0", views=700, hours=24),
        post(2, type="reply", reply_to_id="0", self_reply=True, views=50, hours=30),
        post(3, linked_ids=["A9"], views=300, hours=48),
        post(4, views=999, hours=50),                                  # unrelated
        post(5, type="quote", quoted_id="0", views=111, hours=24 * 8),  # too late
    ]
    chain = article_chains(posts)[0]
    assert [(f["id"], f["kind"]) for f in chain["followups"]] == [("1", "quote"), ("2", "reply"), ("3", "link")]
    assert chain["followup_views"] == 1050 and chain["title"] == "Deep dive"


def test_borrowed_reach_events_and_rates():
    posts = annotate([post(i, hours=i * 200) for i in range(6)] + [
        post(6, type="quote", quoted_handle="big", quoted_followers=50000, hours=6 * 200),
        post(7, views=900, hours=6 * 200 + 24),  # breakout right after
        post(8, type="reply", reply_to_handle="big", reply_to_followers=50000, views=50, hours=8 * 200),
        post(9, type="reply", reply_to_handle="small", reply_to_followers=10, hours=9 * 200),
        post(10, type="reply", self_reply=True, reply_to_handle="me", reply_to_followers=50000, hours=10 * 200),
    ])
    b = borrowed_reach(posts, followers=1000)
    assert b["count"] == 2 and {e["how"] for e in b["events"]} == {"quote", "reply"}
    assert b["rate_after"] == 1 and b["posts_after"] == 1
    assert b["rate_other"] == 0
    assert b["top_targets"] == [("big", 2)]


def test_cadence():
    c = cadence(annotate([post(0, hours=0), post(1, type="article", hours=24), post(2, type="reply", hours=48)]))
    assert (c["posts"], c["replies"], c["days"], c["per_day"]) == (2, 1, 2, 1)
    assert c["hours_utc"][12] == 2 and c["types"]["article"] == round(1 / 3, 3)
    assert c["median_views_by_type"]["post"] == 100


def test_growth_phases_mark_step_up_and_ignore_immature_posts():
    posts = [post(i, views=100, hours=i * 24) for i in range(21)] + [post(100 + i, views=400, hours=(21 + i) * 24) for i in range(21)]
    now = T0 + timedelta(days=60)
    phases = growth_phases(posts, now=now)
    assert [p["change"] for p in phases] == ["start", "up"]
    assert phases[0]["median_views"] == 100 and phases[1]["median_views"] == 400 and phases[1]["ratio"] == 4
    assert phases[1]["start"].startswith("2026-08-24")
    flat = [post(i, hours=i * 24) for i in range(30)]
    assert [p["change"] for p in growth_phases(flat, now=now)] == ["start"]
    fresh = posts + [post(500, views=9, hours=42 * 24)]
    assert growth_phases(fresh, now=T0 + timedelta(days=43)) == growth_phases(posts, now=now)


def test_one_loud_week_is_not_a_phase():
    posts = [post(i, hours=i * 24) for i in range(14)] + [post(20, views=5000, hours=14 * 24)] + [post(30 + i, hours=(21 + i) * 24) for i in range(14)]
    assert [p["change"] for p in growth_phases(posts, now=T0 + timedelta(days=60))] == ["start"]


def test_compute_handles_empty_timeline():
    rows, m = compute([], {"followers": 10})
    assert rows == [] and m["median_views"] is None and m["phases"] == [] and m["articles"] == []
