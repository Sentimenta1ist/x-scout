from x_scout.scoring import lifetime_fraction, score


def test_cold_post_is_normal():
    s = score({"views": 120, "likes": 2, "replies": 0, "reposts": 0, "bookmarks": 0, "age_min": 60})
    assert s["label"] == "normal"
    assert s["score"] < 30


def test_too_little_data():
    s = score({"views": 10, "likes": 1, "replies": 0, "reposts": 0, "bookmarks": 0, "age_min": 10})
    assert s["label"] == "low-data"


def test_hot_post():
    s = score(
        {"views": 8000, "likes": 400, "replies": 60, "reposts": 90, "bookmarks": 80, "age_min": 30},
        {"author_projected": [5000, 6000, 4000, 7000], "prev": {"views": 5000, "age_min": 20}},
    )
    assert s["label"] == "hot", s


def test_old_post_not_flagged():
    s = score({"views": 8000, "likes": 400, "replies": 60, "reposts": 90, "bookmarks": 80, "age_min": 900})
    assert s["label"] == "old"


def test_relative_signal_matters():
    t = {"views": 50000, "likes": 500, "replies": 20, "reposts": 30, "bookmarks": 20, "age_min": 120}
    big = score(t, {"author_projected": [90000, 100000, 110000]})
    small = score(t, {"author_projected": [3000, 4000, 5000]})
    assert small["score"] > big["score"]


def test_followers_baseline_without_history():
    t = {"views": 20000, "likes": 300, "replies": 30, "reposts": 40, "bookmarks": 30, "age_min": 60}
    small_acc = score(t, {"followers": 2000})
    huge_acc = score(t, {"followers": 2_000_000})
    assert small_acc["score"] > huge_acc["score"]
    assert "relative" in small_acc["parts"]


def test_lifetime_fraction():
    assert 0.63 < lifetime_fraction(150, 150) < 0.64
