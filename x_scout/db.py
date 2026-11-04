import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import DB_PATH

SCHEMA = """
create table if not exists posts (
  id text primary key,
  author text not null,
  data text not null,           -- latest parsed post json
  first_seen text not null
);
create table if not exists snapshots (
  post_id text not null,
  ts text not null,
  views integer, likes integer, replies integer, reposts integer, bookmarks integer,
  age_min real
);
create index if not exists snapshots_post on snapshots(post_id, ts);
create table if not exists runs (
  id integer primary key autoincrement,
  started_at text not null,
  finished_at text,
  status text not null,         -- running | done | error
  topics text not null,         -- json list
  result text,                  -- json: per-topic columns with full post data
  stats text,                   -- json: counts, tokens, cost, timings
  candidates text               -- json: {topic: [posts]} sent to Claude, lets us re-run analysis without scraping
);
"""


def now_iso():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


# columns added after the first release: (name, type); init() adds the missing ones
MIGRATIONS = [("kind", "text"), ("stages", "text"), ("checks", "text")]
_stage_lock = threading.Lock()  # stage results are written from the run loop and from Claude threads


def init():
    with conn() as c:
        c.executescript(SCHEMA)
        have = {r["name"] for r in c.execute("pragma table_info(runs)")}
        for name, typ in MIGRATIONS:
            if name not in have:
                c.execute(f"alter table runs add column {name} {typ}")


def set_kind(run_id, kind):
    with conn() as c:
        c.execute("update runs set kind=? where id=?", (kind, run_id))


def update_stage(run_id, stage, **fields):
    """Merge fields into runs.stages[stage] (json). Returns the whole stages dict."""
    with _stage_lock, conn() as c:
        r = c.execute("select stages from runs where id=?", (run_id,)).fetchone()
        stages = json.loads(r["stages"]) if r and r["stages"] else {}
        stages.setdefault(stage, {}).update(fields)
        c.execute("update runs set stages=? where id=?", (json.dumps(stages), run_id))
        return stages


def set_check(run_id, key, done):
    """Checklist / card checkbox of one run: {key: true}. Unchecked keys are removed."""
    with _stage_lock, conn() as c:
        r = c.execute("select checks from runs where id=?", (run_id,)).fetchone()
        if r is None:
            return None
        checks = json.loads(r["checks"]) if r["checks"] else {}
        if done:
            checks[key] = True
        else:
            checks.pop(key, None)
        c.execute("update runs set checks=? where id=?", (json.dumps(checks), run_id))
        return checks


def last_snapshot(post_id):
    with conn() as c:
        r = c.execute("select views, age_min from snapshots where post_id=? order by ts desc limit 1", (post_id,)).fetchone()
        return dict(r) if r else None


def author_history(handle, exclude_id, limit=20):
    """Last known (views, age) of the author's other posts, for the 'vs author' baseline."""
    with conn() as c:
        rows = c.execute(
            """select s.views, s.age_min from posts p
               join snapshots s on s.post_id = p.id
               where p.author = ? and p.id != ?
               and s.ts = (select max(ts) from snapshots where post_id = p.id)
               order by p.first_seen desc limit ?""",
            (handle, exclude_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def save_posts(posts):
    ts = now_iso()
    with conn() as c:
        for p in posts:
            c.execute(
                "insert into posts(id, author, data, first_seen) values(?,?,?,?) "
                "on conflict(id) do update set data=excluded.data",
                (p["id"], p["author"]["handle"], json.dumps(p), ts),
            )
            if p.get("views") is not None:
                c.execute(
                    "insert into snapshots values(?,?,?,?,?,?,?,?)",
                    (p["id"], ts, p["views"], p["likes"], p["replies"], p["reposts"], p["bookmarks"], p.get("age_min")),
                )


def create_run(topics):
    with conn() as c:
        cur = c.execute("insert into runs(started_at, status, topics) values(?,?,?)", (now_iso(), "running", json.dumps(topics)))
        return cur.lastrowid


def save_candidates(run_id, candidates):
    with conn() as c:
        c.execute("update runs set candidates=? where id=?", (json.dumps(candidates), run_id))


def finish_run(run_id, status, result=None, stats=None):
    with conn() as c:
        c.execute(
            "update runs set finished_at=?, status=?, result=coalesce(?, result), stats=? where id=?",
            (now_iso(), status, json.dumps(result) if result is not None else None, json.dumps(stats or {}), run_id),
        )


def _run_row(r):
    d = dict(r)
    for k in ("topics", "result", "stats", "candidates", "stages", "checks"):
        if k not in d:
            continue
        d[k] = json.loads(d[k]) if d[k] else None
    return d


def list_runs(limit=30):
    with conn() as c:
        rows = c.execute("select id, started_at, finished_at, status, topics, stats, kind from runs order by id desc limit ?", (limit,)).fetchall()
        return [_run_row(dict(r)) for r in rows]


def get_run(run_id):
    with conn() as c:
        r = c.execute("select * from runs where id=?", (run_id,)).fetchone()
        return _run_row(r) if r else None


def latest_run_id():
    with conn() as c:
        r = c.execute("select id from runs where status='done' order by id desc limit 1").fetchone()
        return r["id"] if r else None


def mark_stale_runs():
    """A server restart kills in-flight runs; don't leave them 'running' forever."""
    with conn() as c:
        c.execute("update runs set status='error', stats=json_object('error','interrupted') where status='running'")


def good_authors(topic, limit=15, runs=40, min_followers=1000):
    """Authors whose posts Claude picked at q >= 4 under this topic in recent runs, most picked first.
    Fed back into search as from: queries: on niche topics good posts come from people, not keywords."""
    counts = {}
    with conn() as c:
        rows = c.execute("select result from runs where status='done' and result is not null order by id desc limit ?", (runs,)).fetchall()
    for (result,) in rows:
        for t in json.loads(result) or []:
            if t.get("topic", "").lower() != topic.lower():
                continue
            for col in ("reply", "save"):
                for p in t.get(col) or []:
                    a = p.get("author") or {}
                    if (p.get("q") or 0) >= 4 and (a.get("followers") or 0) >= min_followers and a.get("handle"):
                        counts[a["handle"]] = counts.get(a["handle"], 0) + 1
    return [h for h, _ in sorted(counts.items(), key=lambda x: -x[1])][:limit]
