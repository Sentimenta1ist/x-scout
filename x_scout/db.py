import json
import sqlite3
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


def init():
    with conn() as c:
        c.executescript(SCHEMA)


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
            "update runs set finished_at=?, status=?, result=?, stats=? where id=?",
            (now_iso(), status, json.dumps(result) if result is not None else None, json.dumps(stats or {}), run_id),
        )


def _run_row(r):
    d = dict(r)
    for k in ("topics", "result", "stats", "candidates"):
        if k not in d:
            continue
        d[k] = json.loads(d[k]) if d[k] else None
    return d


def list_runs(limit=30):
    with conn() as c:
        rows = c.execute("select id, started_at, finished_at, status, topics, stats from runs order by id desc limit ?", (limit,)).fetchall()
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
