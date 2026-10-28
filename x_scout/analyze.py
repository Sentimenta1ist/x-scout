"""Pre-filter scraped posts locally, then one `claude -p` call ranks them into three columns per topic.

Token budget is the point: Claude sees ~25 short lines per topic, posts are referenced by a local index
instead of 19-digit ids, and the CLI runs with a tiny system prompt, no tools, no settings, empty cwd
(~1.5k tokens of overhead instead of ~20k for a default Claude Code session).
"""
import json
import math
import re
import subprocess

from . import config
from .parse import compact_text

SYSTEM = """You rank X (Twitter) posts for one reader. Input: reader profile, then posts grouped by topic.
Post line: n|author|followers|age|views|likes|replies|reposts|bookmarks|score|text
score = local early-virality score 0-100 (velocity vs age and vs author's usual reach). [img]/[vid] = media, QT = quoted post.
For every topic pick three lists, 3-6 posts each, best first, only from that topic's posts:
H hot: likely to keep growing fast right now (young, accelerating, high score) AND worth reading; good to reply early.
G global: the most important/popular posts of the day to stay informed (news, launches, big debates). Substance over memes.
U useful: most valuable for the reader given the profile: practical insight, tools, techniques, leads, people worth knowing.
A post may be in several lists. Skip spam, giveaways, engagement bait, shallow hype, ads, off-topic posts.
Output plain text only, no markdown, exactly this format:
# <topic name as given>
H <n> <q> | <why> | <angle>
G <n> <q> | <why>
U <n> <q> | <why> | <angle>
q = depth/quality 1-5. why: <=12 words, concrete, no filler. angle: <=14 words reply direction for the reader; leave empty if a reply makes no sense."""


def _k(n):
    if n is None:
        return "?"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}m".replace(".0m", "m")
    if n >= 1000:
        return f"{n / 1000:.1f}k".replace(".0k", "k")
    return str(n)


def _age(m):
    return f"{m:.0f}m" if m < 60 else f"{m / 60:.1f}h".replace(".0h", "h")


def _norm(text):
    return re.sub(r"\W+", "", (text or "").lower())[:80]


def select_candidates(posts, limit=25, max_age_h=36):
    """posts carry 'age_min' and 'scored'. Keep a mix: early risers, big posts of the day, high-engagement niche."""
    pool, dupes = [], set()
    for p in posts:
        if p.get("is_reply") or p.get("age_min") is None or p["age_min"] > max_age_h * 60:
            continue
        if not p.get("views") or p["views"] < 200 or len((p.get("text") or "").strip()) < 15:
            continue
        key = _norm(p["text"])
        if key in dupes:
            continue
        dupes.add(key)
        pool.append(p)

    def score(p):
        return p["scored"]["score"]

    def size(p):
        return math.log10(max(p["views"], 1)) + 2 * math.log10(max(p["likes"] + 2 * p["reposts"] + 3 * p["replies"], 1))

    def depth(p):
        # bookmarks and replies per view ≈ "worth saving / worth discussing"
        return (2 * p["bookmarks"] + p["replies"]) / p["views"] if p["views"] >= 500 else 0

    picked, ids = [], set()
    for key, n in ((score, limit * 0.45), (size, limit * 0.35), (depth, limit)):
        for p in sorted(pool, key=key, reverse=True):
            if len(picked) >= limit or n <= 0:
                break
            if p["id"] not in ids:
                ids.add(p["id"])
                picked.append(p)
                n -= 1
    return picked


def digest(profile, by_topic):
    """by_topic: {topic: [candidate posts]} → (prompt text, index → post)."""
    lines = ["PROFILE:", profile.strip(), ""]
    index, n = {}, 0
    for topic, posts in by_topic.items():
        lines.append(f"## TOPIC: {topic}")
        for p in posts:
            n += 1
            index[n] = p
            media = "".join(f"[{'vid' if m in ('video', 'animated_gif') else 'img'}]" for m in sorted(set(p.get("media") or [])))
            text = compact_text(p["text"], 280)
            if p.get("quoted"):
                text += f" QT {compact_text(p['quoted'], 120)}"
            a = p["author"]
            lines.append("|".join([
                str(n), "@" + a["handle"], _k(a["followers"]), _age(p["age_min"]), _k(p["views"]), _k(p["likes"]),
                _k(p["replies"]), _k(p["reposts"]), _k(p["bookmarks"]), str(p["scored"]["score"]), media + text,
            ]))
        lines.append("")
    return "\n".join(lines), index


def run_claude(prompt, model=None, timeout=600):
    cmd = [
        config.claude_bin(), "-p",
        "--model", model or config.CLAUDE_MODEL,
        "--system-prompt", SYSTEM,
        "--tools", "",
        "--strict-mcp-config",
        "--setting-sources", "",
        "--no-session-persistence",
        "--output-format", "json",
    ]
    proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, cwd=config.CLAUDE_CWD)
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"claude -p failed (exit {proc.returncode}): {(proc.stderr or proc.stdout)[-800:]}")
    if out.get("is_error"):
        raise RuntimeError(f"claude -p error: {out.get('result')}")
    data = parse_picks(out.get("result") or "")
    u = out.get("usage") or {}
    usage = {
        "input_tokens": u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0),
        "output_tokens": u.get("output_tokens", 0),
        "cost_usd_equiv": round(out.get("total_cost_usd") or 0, 4),
        "duration_s": round((out.get("duration_ms") or 0) / 1000, 1),
    }
    return data, usage


_PICK = re.compile(r"^([HGU])\s+#?(\d+)\s+(\d)?\s*\|?\s*(.*)$")
_COL = {"H": "hot", "G": "global", "U": "useful"}


def parse_picks(text):
    """Line format from SYSTEM → {"topics": [{"topic", "hot": [{n, q, why, angle}], ...}]}.
    Plain lines instead of --json-schema: structured output costs a second model turn that re-reads the whole prompt."""
    topics, cur = [], None
    for raw in text.splitlines():
        line = raw.strip().strip("`")
        if line.startswith("#"):
            cur = {"topic": line.lstrip("#").strip(), "hot": [], "global": [], "useful": []}
            topics.append(cur)
            continue
        m = _PICK.match(line)
        if not m or cur is None:
            continue
        col, n, q, rest = m.groups()
        fields = [f.strip() for f in rest.split("|")]
        cur[_COL[col]].append({"n": int(n), "q": int(q) if q else None, "why": fields[0] if fields else "",
                               "angle": fields[1] if len(fields) > 1 else ""})
    return {"topics": topics}


def assemble(claude_data, index, topics):
    """Map Claude's picks (by local index) back to full posts. Drops picks that point outside the topic."""
    by_name = {t["topic"].strip().lower(): t for t in claude_data.get("topics", [])}
    result = []
    for name, posts in topics.items():
        allowed = {id(p) for p in posts}
        t = by_name.get(name.lower(), {})
        cols = {}
        for col in ("hot", "global", "useful"):
            seen, items = set(), []
            for pick in t.get(col, []):
                p = index.get(pick.get("n"))
                if not p or id(p) not in allowed or p["id"] in seen:
                    continue
                seen.add(p["id"])
                items.append({**slim(p), "why": pick.get("why", ""), "angle": pick.get("angle") or "", "q": pick.get("q")})
            cols[col] = items[:7]
        result.append({"topic": name, "candidates": len(posts), **cols})
    return result


def slim(p):
    keep = ("id", "url", "text", "created_at", "author", "views", "likes", "replies", "reposts", "quotes",
            "bookmarks", "media", "quoted", "age_min", "found_in")
    return {**{k: p.get(k) for k in keep}, "score": p["scored"]["score"], "label": p["scored"]["label"],
            "parts": p["scored"]["parts"]}
