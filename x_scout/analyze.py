"""Pre-filter scraped posts locally, then one `claude -p` call picks up to 5 posts to reply to and up to 5 to read per topic.

Claude sees one compact line per post (~40 per topic), posts are referenced by a local index instead of
19-digit ids, and the CLI runs with a tiny system prompt, no tools, no settings, empty cwd
(~1.5k tokens of overhead instead of ~20k for a default Claude Code session).
"""
import json
import math
import re
import subprocess

from . import config
from .parse import compact_text

SYSTEM = """You are a strict curator of X (Twitter) posts for one reader. Input: reader profile, then posts grouped by topic.
Post line: n|author|followers|age|views|likes|replies|reposts|bookmarks|score|text
score = local early-virality score 0-100 (velocity vs age and vs author's usual reach). [img]/[vid] = media, QT = quoted post.
For every topic pick up to 5 R posts and up to 5 S posts, best first. Empty or short lists are normal: pick only what clears the bar, never fill a list.
R = a reply here is seen by many and the reader has something concrete to add. Required: younger than 24h, real reach (a post taking off or an author with an audience), and the profile gives him a specific number, failure or trade-off for this exact post.
    An empty thread on a small account is worthless: nobody will read the reply. Few replies is only a plus on a post that already has reach.
    Never R for a topic the profile marks as read-only, for personal updates, day-N build logs or fundraising news.
S = worth reading or saving: the post text itself carries real substance a smart engineer would bookmark: deep explanation, data, postmortem, a new result with specifics.
    You see only the text, not its links: a post that only points to a link, announces a talk, event, guest post or teaser is rejected.
The post must be about the topic name itself. A post that is mainly about AI/agents/LLMs belongs only to an AI topic,
never to Crypto, Games, Computer science etc., even if the text mentions the topic.
Reject: launches that are only marketing, "X is insane"/"you must build these" hype, listicles, course and tool roundups,
promos, giveaways, price talk, rage bait, vague threads with no specifics. Rejected posts never fill a list, even if it stays short.
Output plain text only, no markdown, exactly this format, best first:
# <topic name as given>
R <n> <q> | <gist> | <why> | <angle>
S <n> <q> | <gist> | <why>
q = quality, be strict: 5 rare, would send it to a friend; 4 clearly worth his time; 3 fine but forgettable; 1-2 weak. Most posts are 3 or lower, and only 4-5 are shown. gist: what the post says, 1-2 short sentences in {gist_lang}, so the reader can skip the full text; keep key numbers and names.
why: <=12 words, concrete, no filler. angle (R only): the actual reply text, ready to send, in the language of the post, <=20 words."""


def ranking_system(gist_lang="English"):
    return SYSTEM.replace("{gist_lang}", gist_lang or "English")


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


_JUNK = re.compile(
    r"drop (your|ur|a)\b|giving away|giveaway|airdrop|presale|memecoin|turn (my |on )*notifications"
    r"|\b(follow|like)\b.{0,60}\b(rt|retweet|repost)\b|\b(rt|retweet|repost)\b.{0,30}\b(comment|follow|drop)\b",
    re.IGNORECASE | re.DOTALL)


def is_junk(text):
    return bool(_JUNK.search(text or ""))


def select_candidates(posts, limit=25, max_age_h=36, fresh_h=12):
    """posts carry 'age_min' and 'scored'. Keep a mix: fresh posts worth replying to, early risers, big posts of the day,
    high-engagement niche."""
    pool, dupes = [], set()
    for p in posts:
        if p.get("is_reply") or p.get("age_min") is None or p["age_min"] > max_age_h * 60:
            continue
        if not p.get("views") or p["views"] < 200 or len((p.get("text") or "").strip()) < 15 or is_junk(p["text"]):
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

    fresh = [p for p in pool if p["age_min"] <= fresh_h * 60]
    picked, ids = [], set()
    for subset, key, n in ((fresh, score, limit * 0.4), (pool, score, limit * 0.2), (pool, size, limit * 0.2), (pool, depth, limit)):
        for p in sorted(subset, key=key, reverse=True):
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
            text = compact_text(p["text"], 500)
            if p.get("quoted"):
                text += f" QT {compact_text(p['quoted'], 200)}"
            a = p["author"]
            lines.append("|".join([
                str(n), "@" + a["handle"], _k(a["followers"]), _age(p["age_min"]), _k(p["views"]), _k(p["likes"]),
                _k(p["replies"]), _k(p["reposts"]), _k(p["bookmarks"]), str(p["scored"]["score"]), media + text,
            ]))
        lines.append("")
    return "\n".join(lines), index


QUERY_SYSTEM = """You write X (Twitter) advanced-search queries. Input: reader profile, then topic names, one per line.
For each topic write ONE query that finds substantive posts the reader would care about: use OR-groups of specific terms
and quoted phrases, exclude obvious junk (-giveaway -airdrop, price talk where relevant). Max ~200 characters.
Do not add lang:, filter:, since:, min_faves: (added automatically). Output plain text only, one line per topic:
<topic name as given> => <query>"""


def generate_queries(profile, names, model=None):
    """Empty topic query → one Claude call writes queries for all such topics. Returns ({name: query}, usage)."""
    text, usage = run_claude(f"PROFILE:\n{profile.strip()}\n\nTOPICS:\n" + "\n".join(names), model=model,
                             system=QUERY_SYSTEM, raw=True)
    out = {}
    for line in text.splitlines():
        if "=>" in line:
            name, q = (x.strip().strip("`") for x in line.split("=>", 1))
            match = next((n for n in names if n.lower() == name.lower()), None)
            if match and q:
                out[match] = q
    return out, usage


_proc = None  # the running `claude -p`, so Stop can end it instead of letting it spend tokens


def stop_claude():
    if _proc:
        _proc.kill()


def run_claude(prompt, model=None, timeout=600, system=None, raw=False):
    cmd = [
        config.claude_bin(), "-p",
        "--model", model or config.CLAUDE_MODEL,
        "--system-prompt", system or ranking_system(),
        "--tools", "",
        "--strict-mcp-config",
        "--setting-sources", "",
        "--no-session-persistence",
        "--output-format", "json",
    ]
    global _proc
    proc = _proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                    cwd=config.CLAUDE_CWD)
    try:
        stdout, stderr = proc.communicate(prompt, timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise RuntimeError(f"claude -p timed out after {timeout}s")
    finally:
        _proc = None
    try:
        out = json.loads(stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"claude -p failed (exit {proc.returncode}): {(stderr or stdout)[-800:]}")
    if out.get("is_error"):
        raise RuntimeError(f"claude -p error: {out.get('result')}")
    data = (out.get("result") or "") if raw else parse_picks(out.get("result") or "")
    u = out.get("usage") or {}
    usage = {
        "input_tokens": u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0),
        "output_tokens": u.get("output_tokens", 0),
        "cost_usd_equiv": round(out.get("total_cost_usd") or 0, 4),
        "duration_s": round((out.get("duration_ms") or 0) / 1000, 1),
    }
    return data, usage


_PICK = re.compile(r"^([RS])\s+#?(\d+)\s+(\d)?\s*\|?\s*(.*)$")
_COL = {"R": "reply", "S": "save"}
MAX_PER_COLUMN = 5
REPLY_MAX_AGE_H = 24
MIN_Q = 4                 # weaker picks are never shown: an empty column beats a filler post
REPLY_MIN_FOLLOWERS = 1000
REPLY_MIN_VIEWS = 1000
REPLY_MIN_PROJECTED = 2500  # a very young post can qualify by projected views


def parse_picks(text):
    """Line format from SYSTEM → {"topics": [{"topic", "reply": [{n, q, gist, why, angle}], "save": [...]}]}.
    Plain lines instead of --json-schema: structured output costs a second model turn that re-reads the whole prompt."""
    topics, cur = [], None
    for raw in text.splitlines():
        line = raw.strip().strip("`")
        if line.startswith("#"):
            cur = {"topic": line.lstrip("#").strip(), "reply": [], "save": []}
            topics.append(cur)
            continue
        m = _PICK.match(line)
        if not m or cur is None:
            continue
        col, n, q, rest = m.groups()
        fields = [f.strip() for f in rest.split("|")]
        fields += [""] * (3 - len(fields))
        cur[_COL[col]].append({"n": int(n), "q": int(q) if q else None, "gist": fields[0], "why": fields[1],
                               "angle": fields[2]})
    return {"topics": topics}


def has_reply_reach(p):
    """A reply is worth writing only where people will see it."""
    if p["author"]["followers"] < REPLY_MIN_FOLLOWERS:
        return False
    return (p.get("views") or 0) >= REPLY_MIN_VIEWS or (p["scored"].get("projected") or 0) >= REPLY_MIN_PROJECTED


def assemble(claude_data, index, topics):
    """Map Claude's picks (by local index) back to full posts, in Claude's order. A post lands in one column only,
    picks from another topic or under MIN_Q are dropped, at most MAX_PER_COLUMN per column. A reply pick that is older than
    REPLY_MAX_AGE_H or has no reach moves to "save": still may be a good read, but not worth a reply."""
    by_name = {t["topic"].strip().lower(): t for t in claude_data.get("topics", [])}
    result = []
    for name, posts in topics.items():
        allowed = {id(p) for p in posts}
        t = by_name.get(name.lower(), {})
        cols, seen = {"reply": [], "save": []}, set()
        for picked_col in ("reply", "save"):
            for pick in t.get(picked_col, []):
                p = index.get(pick.get("n"))
                if not p or id(p) not in allowed or p["id"] in seen or (pick.get("q") is not None and pick["q"] < MIN_Q):
                    continue
                too_old = (p.get("age_min") or 0) > REPLY_MAX_AGE_H * 60
                col = "save" if picked_col == "reply" and (too_old or not has_reply_reach(p)) else picked_col
                if len(cols[col]) >= MAX_PER_COLUMN:
                    continue
                seen.add(p["id"])
                cols[col].append({**slim(p), "gist": pick.get("gist", ""), "why": pick.get("why", ""),
                                  "angle": (pick.get("angle") or "") if col == "reply" else "", "q": pick.get("q")})
        result.append({"topic": name, "candidates": len(posts), **cols})
    return result


def slim(p):
    keep = ("id", "url", "text", "created_at", "author", "views", "likes", "replies", "reposts", "quotes",
            "bookmarks", "media", "quoted", "age_min", "found_in")
    return {**{k: p.get(k) for k in keep}, "score": p["scored"]["score"], "label": p["scored"]["label"],
            "parts": p["scored"]["parts"]}
