"""Seed a demo data dir with fictional posts and a finished run, for screenshots and trying the UI.

    X_SCOUT_DATA=./demo-data uv run python scripts/demo.py
    X_SCOUT_DATA=./demo-data uv run x-scout

All accounts and posts below are made up.
"""
import json
import random
from datetime import datetime, timedelta, timezone

from x_scout import db, post_analysis, profile_metrics, profile_store
from x_scout.config import PROFILE_MD, ROOT, SETTINGS_JSON

NOW = datetime.now(timezone.utc)

# (name, handle, followers, age_min, views, likes, replies, reposts, bookmarks, media, text, why, angle, q, score)
DEMO = {
    "AI agents": {
        "hot": [
            ("Mira Okafor", "mira_builds", 18400, 38, 41200, 1210, 164, 233, 610, ["photo"],
             "We put an eval harness in front of every tool call our agent makes.\nFailure rate on prod tickets went from 14% to 3% in two weeks. Here is the setup, and the 3 checks that caught most bugs:",
             "Eval harness on every tool call, failures 14% → 3% in two weeks",
             "Ask which of the 3 checks caught the most; share a tracing-based one", 5, 86),
            ("Theo Lindqvist", "theo_ships", 6200, 52, 9800, 402, 77, 51, 190, [],
             "Hot take: most \"agent frameworks\" are a while loop with retries.\nWe deleted ours, wrote 180 lines, latency dropped 2.4x and debugging became possible again.",
             "Replaced framework with 180-line loop, 2.4x faster, easier to debug",
             "Agree with one caveat: explicit state makes traces readable", 4, 71),
            ("Priya Raman", "priya_ml", 31000, 71, 22600, 540, 98, 88, 300, ["video"],
             "Demo: an MCP server that gives the agent read-only access to Postgres with row limits and a 2s statement timeout. 40 lines. Video below.",
             "Read-only Postgres MCP server with sane guardrails, 40 lines",
             "Mention query allowlists as the next guardrail", 4, 64),
        ],
        "useful": [
            ("Jonas Weber", "jonasw", 2100, 95, 3400, 61, 42, 9, 25, [],
             "Anyone here automated invoice intake? 300 PDFs a month, 3 formats, currently copy-pasting into our accounting tool. Happy to pay for a setup.",
             "Small business asking for paid invoice automation: a direct lead",
             "Outline: extract → validate against PO → export, human review for outliers", 3, 41),
            ("Lena Duarte", "lenaduarte", 12800, 140, 15100, 380, 51, 70, 420, ["photo"],
             "Our agent observability checklist after 6 months in production: span per tool call, input/output hashes, cost per task, replayable traces. Thread on each.",
             "Production observability checklist for agents, concrete and reusable",
             "Add one thing you log that is not on her list", 5, 58),
        ],
        "global": [
            ("Frontier Weekly", "frontierweekly", 412000, 260, 388000, 6100, 720, 1500, 2900, ["photo"],
             "A major lab released a new model with a 1M-token context and native computer use. Benchmarks, pricing and what changed vs the previous version:",
             "New frontier model launch: 1M context, computer use, pricing", "", 4, 77),
            ("Sam Achebe", "samachebe", 88000, 410, 120000, 2300, 610, 310, 800, [],
             "Bank says it will block third-party AI agents from logging into customer accounts. The fight over agent identity has started.",
             "Banks blocking AI agents: the agent-identity debate goes mainstream", "", 4, 52),
            ("Ada Kim", "adakim_research", 54000, 600, 76000, 1800, 240, 420, 1300, [],
             "New study: experts who worked with an AI agent followed its suggestion 86% of the time, even when it was randomly wrong.",
             "Study: experts follow agent suggestions even when wrong", "", 5, 44),
        ],
    },
    "Automation": {
        "hot": [
            ("Rosa Martin", "rosa_ops", 4300, 44, 12400, 510, 96, 70, 340, ["photo"],
             "Our dental clinic was losing 1 in 5 appointments to no-shows. WhatsApp reminders + one-tap reschedule, built in a weekend. No-shows down 22%.",
             "Clinic cut no-shows 22% with WhatsApp reminders, weekend build",
             "Ask about timing; a reminder 2h before often beats 24h", 4, 79),
            ("Kai Brennan", "kaibrennan", 9100, 66, 8700, 260, 48, 40, 150, [],
             "Moved 40 Zaps to self-hosted n8n. Monthly bill: $389 → $14. Full cost breakdown and the 3 things that broke:",
             "40 Zaps to n8n, $389 → $14 a month, with what broke",
             "Share how you handle retries and alerting in n8n", 4, 62),
        ],
        "useful": [
            ("Hannah Cole", "hannahcole_shop", 1300, 120, 2600, 44, 37, 6, 12, [],
             "I spend every Monday morning copying Shopify orders into a spreadsheet for our supplier. 6 hours a week. There has to be a better way?",
             "Shop owner describing a 6h/week manual task: a lead",
             "Shopify webhook → Sheets → auto-email to supplier, about an hour to set up", 3, 38),
            ("Omar Haddad", "omarbuilds", 7600, 200, 11000, 330, 40, 60, 510, ["photo"],
             "Built a nightly job that reconciles Stripe payouts against the bank CSV and only flags mismatches. Saved our accountant 10 hours a month. Diagram:",
             "Stripe vs bank reconciliation bot, 10h/month saved, with diagram",
             "Matching on amount + date window covers most cases; ask about refunds", 5, 55),
        ],
        "global": [
            ("Ops Digest", "opsdigest", 230000, 380, 210000, 3100, 400, 900, 2100, [],
             "A no-code automation platform raised prices for its starter plan by 60%. Thousands of small businesses are now pricing out alternatives.",
             "Major no-code platform price hike pushes users to alternatives", "", 3, 49),
            ("Grace Liu", "graceliu_vc", 96000, 520, 64000, 1400, 310, 220, 700, [],
             "We are still in the autocomplete era of workflow automation. The real money is in boring back-office processes nobody wants to touch.",
             "Investor view: back-office automation is the big untapped market", "", 3, 40),
        ],
    },
    "Crypto infra": {
        "hot": [
            ("Nico Varga", "nico_onchain", 15500, 47, 18800, 620, 88, 140, 520, ["photo"],
             "We open-sourced our trading bot infra: private relays, nonce manager, failed-bundle retries. Architecture diagram and repo below.",
             "Open-sourced bot infra with relays and nonce handling, diagram",
             "Ask how they recover from reorgs without double-sending", 5, 81),
        ],
        "useful": [
            ("Iris Novak", "irisnovak", 3900, 150, 4100, 90, 33, 14, 70, [],
             "Building a Telegram bot that tracks wallet flows and sends a daily digest. Looking for 10 beta testers who watch more than 20 wallets.",
             "Wallet-flow Telegram bot looking for beta testers",
             "Offer feedback; suggest per-wallet digests to avoid alert fatigue", 3, 36),
            ("Ben Okoro", "benokoro_dev", 22000, 260, 30000, 700, 120, 160, 900, [],
             "What changes for wallet devs after the latest Ethereum upgrade: account abstraction for EOAs, batched calls, sponsored gas. Explained with code.",
             "Upgrade explained for wallet devs, with code", "Point out what it unlocks for agent-controlled wallets", 5, 47),
        ],
        "global": [
            ("Chain Report", "chainreport", 510000, 300, 450000, 5200, 900, 1800, 1900, ["photo"],
             "Stablecoin payment volume passed card volume in two LATAM corridors last quarter, per a new industry report.",
             "Stablecoin payments overtake cards in LATAM corridors (report)", "", 4, 58),
        ],
    },
}


def post(topic, i, row):
    name, handle, fol, age, views, likes, replies, reposts, bms, media, text, why, angle, q, score = row
    pid = f"demo-{topic[:3].lower()}-{i}"
    label = "hot" if score >= 70 else "rising" if score >= 45 else "normal"
    return {
        "id": pid, "url": f"https://x.com/{handle}/status/{pid}", "text": text,
        "created_at": (NOW - timedelta(minutes=age)).isoformat(),
        "author": {"handle": handle, "name": name, "followers": fol, "verified": False},
        "views": views, "likes": likes, "replies": replies, "reposts": reposts, "quotes": 0, "bookmarks": bms,
        "media": media, "quoted": None, "age_min": age, "found_in": "live",
        "score": score, "label": label, "parts": {}, "why": why, "angle": angle, "q": q,
    }


PROFILE_DEMO = {"handle": "mira_builds", "name": "Mira Okafor", "bio": "Ships small agents for boring back-office work. Notes on evals and failures.",
                "followers": 18400, "following": 410, "posts_total": 3120, "joined": "2021-03-14T09:00:00+00:00", "verified": True,
                "protected": False, "pinned_id": None, "pinned_text": None, "pinned_url": None}
HOOKS = ["We put an eval harness in front of every tool call.", "Three failures from last week, with the logs.", "A 180-line loop replaced our framework.",
         "What I would not automate again.", "Invoice intake: the numbers after 30 days.", "Why our agent got slower after the fix."]


def demo_profile():
    """A fictional account: 110 days, a median that steps up twice, a few breakouts and one article chain."""
    rnd = random.Random(7)
    posts, n = [], 0
    for d in range(110, 2, -1):
        for _ in range(rnd.choice((0, 1, 1, 2))):
            n += 1
            base = 900 if d > 70 else 2600 if d > 30 else 6800
            hit = rnd.random() < 0.06
            views = int(base * rnd.uniform(0.5, 1.6) * (rnd.uniform(6, 14) if hit else 1))
            kind = rnd.choices(("post", "quote", "thread"), (7, 2, 1))[0]
            likes = int(views * rnd.uniform(0.008, 0.03))
            t = NOW - timedelta(days=d, hours=rnd.randint(0, 20))
            post = {"id": f"p{n}", "url": f"https://x.com/mira_builds/status/p{n}", "created_at": t.isoformat(), "text": rnd.choice(HOOKS), "type": kind,
                    "media_type": rnd.choice(("none", "none", "photo", "video")), "has_link": rnd.random() < 0.2, "views": views, "likes": likes,
                    "replies": likes // 8, "reposts": likes // 6, "quotes": likes // 20, "bookmarks": int(likes * rnd.uniform(0.2, 0.9)), "self_reply": False}
            if kind == "quote":
                post.update(quoted_id=f"q{n}", quoted_handle="frontierweekly", quoted_followers=412000)
            posts.append(post)
    posts.sort(key=lambda p: p["created_at"])
    art = posts[len(posts) // 2]
    art.update(type="article", article_id="a1", article_title="How we test agents before a client sees them", views=art["views"] * 12)
    q = posts[len(posts) // 2 + 1]
    q.update(type="quote", quoted_id=art["id"], quoted_handle="mira_builds", quoted_followers=18400)
    return posts


def demo_report(rows):
    top = sorted((p for p in rows if p["ratio"]), key=lambda p: p["ratio"], reverse=True)
    phases = profile_metrics.growth_phases(rows)
    conf = ["guess", "medium", "high"]
    return {
        "summary": ["Fictional builder writing about agents in production for small businesses.", "Audience: engineers and operators; the median has stepped up twice.",
                    "Mid-size account growing through specific failure stories."],
        "phases": [{"start": ph["start"][:10], "end": ph["end"][:10], "confidence": conf[min(i, 2)], "changed": "Moved from opinions to posts with numbers and logs.",
                    "trigger": "A long article followed by quotes of it.", "post_ids": [p["id"] for p in top[i:i + 2]]} for i, ph in enumerate(phases)],
        "viral": [{"post_id": p["id"], "hook": "Number in the first line", "format": "Short post with a screenshot", "topic": "Agent evals", "timing": "Weekday morning UTC", "borrowed": "",
                   "why": "A concrete before-and-after anyone building agents can check."} for p in top[:10]],
        "hooks": ["Before and after number", "Failure confession with a log"], "openers": ["We [changed X] and [metric] moved from [A] to [B]."],
        "structures": ["Claim, proof screenshot, what to copy"], "ctas": ["Ask for one similar case"], "flops": ["Bare links: median far below typical"],
        "repeat": [{"item": "Publish one automation failure with the number that exposed it", "test": "Three posts this week; compare median views with the last 30.", "post_ids": [top[0]["id"]]},
                   {"item": "Write one long piece, then quote it twice with new angles", "test": "One article, two quotes in 7 days; count profile visits.", "post_ids": [top[1]["id"]]},
                   {"item": "Open with the client's manual hours, not the tool", "test": "Two posts; compare replies from business owners.", "post_ids": []}],
        "dont": [{"tactic": "Giveaways for reposts", "why": "Attracts the wrong audience and risks a ban."}], "copies_dropped": 0,
    }


def seed_profile():
    rows, metrics = profile_metrics.compute(demo_profile(), PROFILE_DEMO)
    handle, ts = PROFILE_DEMO["handle"], NOW.isoformat()
    profile_store.add_snapshot(handle, {"scrape_id": "20260901-090000", "ts": (NOW - timedelta(days=30)).isoformat(), "followers": 16100, "following": 402, "posts_total": 3060, "median_views_30": 2500})
    profile_store.add_snapshot(handle, profile_metrics.snapshot(PROFILE_DEMO, metrics, "20261001-090000", ts))
    profile_store.save_scrape(handle, "20261001-090000", {"id": "20261001-090000", "scraped_at": ts, "status": "done", "profile": PROFILE_DEMO, "posts": demo_profile(), "scrape_s": 214})
    profile_store.save_analysis(handle, {"id": "20261001-090500", "scrape_id": "20261001-090000", "created_at": ts, "status": "done", "profile": PROFILE_DEMO, "metrics": metrics, "posts": rows, "report": demo_report(rows),
                                         "stats": {"posts": len(rows), "scrape_s": 214, "total_s": 262, "claude": {"input_tokens": 14200, "output_tokens": 3100, "cost_usd_equiv": 0.09, "duration_s": 47}}})


def seed_post():
    post = {"id": "demo1", "url": "https://x.com/kaibrennan/status/demo1", "type": "post", "media_type": "photo", "created_at": (NOW - timedelta(hours=30)).isoformat(),
            "text": "Moved 40 Zaps to self-hosted n8n. Monthly bill: $389 → $14. Full cost breakdown and the 3 things that broke:", "media": ["photo"], "quoted": None,
            "author": {"handle": "kaibrennan", "name": "Kai Brennan", "followers": 9100, "verified": False},
            "views": 86000, "likes": 1260, "replies": 148, "reposts": 170, "quotes": 22, "bookmarks": 1540}
    post_analysis.save({"key": "1000000000000000001", "created_at": NOW.isoformat(), "post": post, "metrics": post_analysis.metrics(post, 7200), "stats": {"total_s": 24, "claude": {"input_tokens": 4200, "output_tokens": 900, "cost_usd_equiv": 0.03, "duration_s": 15}},
                        "report": {"score": 4, "verdict": "Worth reading: real numbers and what failed, unusual for a migration post.", "gist": "A move from Zapier to self-hosted n8n cut the bill 28 times; retries, alerting and OAuth renewals broke.",
                                   "useful": ["Add retries and alerting before migrating: both are built into Zapier and missing by default in n8n.", "Compare the bill with the hours of upkeep, not the bill alone."], "empty": ["The $14 leaves out his time for maintenance.", "The savings are not verified: no invoice is shown."],
                                   "viral": [{"what": "Before and after in the first line", "how": "$389 → $14 needs no explanation."}, {"what": "Saveable format", "how": "1.2 bookmarks per like: people keep it for later."}],
                                   "take": [{"what": "What broke as the promise", "how": "Announce the failures in the first line of your own migration story."}, {"what": "One number per claim", "how": "Use your own 54 s in queue vs 7 s of work."}],
                                   "repeat": "adapt", "repeat_why": "The structure fits, but use a process you really automated.",
                                   "replies": [{"kind": "say", "text": "the bill is the easy part. who gets paged when a run fails at 3am?"}, {"kind": "say", "text": "retries were the first thing that bit me too"},
                                               {"kind": "ask", "text": "what broke first, and how did you notice?"}, {"kind": "ask", "text": "how many hours a month does the upkeep take now?"}],
                                   "base": ["moved [N] [old tool things] to [new tool]. monthly bill: [before] → [after].", "full cost breakdown and the [N] things that broke:"], "draft": ["we automated a weekly report for a client: 6 hours down to 20 minutes.", "here is what it cost and the 3 things that broke:"], "copies_dropped": 0}})


# Staged daily run: made-up accounts and stories, same shape as runs.stages from pipeline.run_day.
DAY = {
    "news": [
        ("Ledger Daily", "ledgerdaily", 840000, 95, 412000, 6100, 410, 300, ["photo"],
         "Northwind Software cuts 18% of staff and offers 6 months of pay, a $10k fund to start a company, and lets people keep their laptops.",
         "Northwind cuts 18% of staff with a generous package; replies are split between 'classy' and 'still a layoff'.",
         "Layoffs plus a nice package: the fear-of-replacement crowd and the 'good employer' crowd argue in the same thread.",
         ["we're at the stage where people applaud how nicely they got fired", "6 months of pay is generous. it's also 6 months to find a job while every company cuts at once", "a $10k fund to start your own thing is the new severance"], 5),
        ("Market Pulse", "marketpulse_hq", 1200000, 140, 268000, 3400, 220, 150, [],
         "AI chip stocks fall 6% in early trading after two large data center projects were paused.",
         "AI chip stocks drop after two data center projects are paused.",
         "Money, the bubble question and jobs in one line. Easy to have an opinion.",
         ["two paused projects and the whole ai trade shakes. how solid was 'infinite demand' really", "honest question: slow pop or just a tuesday?"], 4),
        ("Civic Wire", "civicwire", 390000, 60, 88000, 2100, 130, 60, ["photo"],
         "Voters in 21 of 24 towns approved limits on new data centers this week.",
         "21 of 24 local votes restrict new data centers.",
         "The AI backlash shows up at the ballot box, not on X. Fresh, few replies yet.",
         ["the election won't slow down ai models. it'll slow down the buildings they run in", "ai companies sold to ceos and forgot towns get a vote"], 4),
    ],
    "big": [
        ("Tech Ticker", "techticker", 2100000, 35, 21000, 380, 31, 90, [],
         "Orbital Cloud offers voluntary exits to staff in four countries. Only its AI research unit is exempt.",
         "Orbital Cloud pays staff to leave; only the AI unit is exempt.",
         "Big account, 35 minutes old, 31 replies: an early reply here gets seen.",
         ["the exemption list is the whole map of where the jobs are going"], ["would you take a month per year, or bet on the next round?"], 5),
        ("Dana Reyes", "danareyes", 650000, 50, 14000, 290, 22, 40, [],
         "Poll: 58% say AI will hurt society more than help. 74% don't want a data center nearby.",
         "Poll: most people expect AI to do more harm than good.",
         "Numbers everyone wants to comment on, replies still thin.",
         ["most of the 58% used a chatbot this week"], ["do people hate ai, or what their boss plans to do with it?"], 4),
    ],
    "viral": [
        ("Sam Ortiz", "samortiz_dev", 3800, 1400, 5200000, 24000, 2300, 3100, [],
         "Can I ask a dumb tech question? Why do file paths on Windows use backslashes?",
         "A 'dumb' everyday tech question: why Windows uses backslashes.",
         "5.2M views from a 3.8k account: everyone knows a bit of the answer and wants to show it.",
         "'dumb tech question' + an everyday software riddle", "yes, every couple of days: a riddle half the feed can answer",
         "Hey @grok, dumb question: why do arrays start at 0 when every human counts from 1? who decided that",
         "can i ask a dumb dev question. why is localhost 127.0.0.1 and not something simple", "what dumb question about my job did i stop asking years ago?", 5),
        ("Jo Park", "jopark", 7100, 2600, 610000, 47000, 400, 2900, [],
         "startup idea: a factory that makes RAM",
         "One-line 'startup idea' about RAM prices.",
         "47k likes on 7k followers: an obvious joke that hits a real pain of the AI boom.",
         "'startup idea:' + something absurdly obvious", "yes, as an evening one-liner",
         "Hey @grok, who actually makes money in the AI boom: labs, GPU makers, power plants or course sellers? pick one",
         "startup idea: a job ai can't do", "what boring business wins the AI gold rush?", 4),
    ],
    "trash": [
        ("Nia Cole", "niacole_", 33000, 12, 1100, 31, 8, 4, [],
         "Gen Z can't find jobs so they pivot to trading. What's your plan B? Genuinely asking",
         "", "", ["plan b should be a skill people pay for, not a chart"], 4),
        ("Ravi Menon", "ravimenon", 98000, 9, 1700, 27, 14, 2, [],
         "smart work is more important than hard work", "", "", ["smart work is just hard work you did earlier"], 4),
    ],
}
SUMMARY = {
    "lines": ["Layoff wave: Northwind cuts 18% with a generous package, Orbital Cloud pays staff to leave and keeps only its AI unit.",
              "Backlash: polls and local votes go against data centers; AI chip stocks dip on paused projects."],
    "recs": ["Post today: Northwind + Orbital Cloud in one post, ending with a two-option question.",
             "Reply in the first hour under @techticker, where replies are still under 40.",
             "Tomorrow: 'startup idea:' one-liner in the evening, the 'dumb tech question' format in the morning."],
}


def day_pick(stage, i, row):
    if stage in ("news",):
        name, handle, fol, age, views, likes, replies, bms, media, text, gist, why, take, q = row
        extra = {"take": take}
    elif stage == "big":
        name, handle, fol, age, views, likes, replies, bms, media, text, gist, why, say, ask, q = row
        extra = {"say": say, "ask": ask[0]}
    elif stage == "viral":
        name, handle, fol, age, views, likes, replies, bms, media, text, gist, why, fmt, rep, grok, rewrite, opinion, q = row
        extra = {"format": fmt, "repeat": rep, "grok": grok, "rewrite": rewrite, "opinion": opinion}
    else:
        name, handle, fol, age, views, likes, replies, bms, media, text, gist, why, say, q = row
        extra = {"say": say}
    pid = f"demo-{stage}-{i}"
    p = {"id": pid, "url": f"https://x.com/{handle}/status/{pid}", "text": text,
         "created_at": (NOW - timedelta(minutes=age)).isoformat(),
         "author": {"handle": handle, "name": name, "followers": fol, "verified": True},
         "views": views, "likes": likes, "replies": replies, "reposts": 0, "quotes": 0, "bookmarks": bms,
         "media": media, "quoted": None, "age_min": age, "found_in": None, "score": 60, "label": "rising", "parts": {},
         "key": f"{stage}:{pid}", "take": [], "say": [], "q": q, "stage": stage}
    if gist:
        p["gist"] = gist
    if why:
        p["why"] = why
    p.update(extra)
    return p


def seed_day(topics_result):
    run_id = db.create_run([])
    db.set_kind(run_id, "day")
    usage = {"input_tokens": 6500, "output_tokens": 2600, "cost_usd_equiv": 0.11, "duration_s": 38.0}
    for stage, rows in DAY.items():
        picks = [day_pick(stage, i, r) for i, r in enumerate(rows, 1)]
        db.update_stage(run_id, stage, status="ready", scraped=len(rows) * 30, picks=picks, count=len(picks), usage=usage)
    db.update_stage(run_id, "topics", status="ready", scraped=236, count=sum(len(v) for t in topics_result for v in t.values() if isinstance(v, list)), usage=usage)
    db.update_stage(run_id, "summary", **SUMMARY, usage=usage)
    db.set_check(run_id, "news:demo-news-1", True)
    db.set_check(run_id, "big:demo-big-1", True)
    db.finish_run(run_id, "done", topics_result, {"stages": ["news", "big", "viral", "trash", "topics"], "search_requests": 41, "rate_wait_s": 0, "total_s": 769})
    return run_id


def main():
    db.init()
    topics = [{"name": t, "query": ""} for t in DEMO]
    result, i = [], 0
    for topic, cols in DEMO.items():
        entry = {"topic": topic, "candidates": 40}
        for col, rows in cols.items():
            entry[col] = []
            for row in rows:
                i += 1
                entry[col].append(post(topic, i, row))
        result.append(entry)
    run_id = db.create_run(topics)
    db.finish_run(run_id, "done", result, {
        "scraped": 236, "sent": 120, "scrape_s": 171, "analyze_s": 19, "total_s": 190,
        "claude": {"input_tokens": 21400, "output_tokens": 1900, "cost_usd_equiv": 0.09, "duration_s": 18.4},
    })
    day_id = seed_day(result)
    SETTINGS_JSON.write_text(json.dumps({"topics": topics, "own_handle": "mira_builds"}, indent=2))
    PROFILE_MD.write_text((ROOT / "profile.example.md").read_text())
    seed_profile()
    seed_post()
    print(f"demo runs #{run_id}, #{day_id} (daily) and profile @{PROFILE_DEMO['handle']} written")


if __name__ == "__main__":
    main()
