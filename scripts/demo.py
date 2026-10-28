"""Seed a demo data dir with fictional posts and a finished run, for screenshots and trying the UI.

    X_SCOUT_DATA=./demo-data uv run python scripts/demo.py
    X_SCOUT_DATA=./demo-data uv run x-scout

All accounts and posts below are made up.
"""
import json
from datetime import datetime, timedelta, timezone

from x_scout import db
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
    SETTINGS_JSON.write_text(json.dumps({"topics": topics}, indent=2))
    PROFILE_MD.write_text((ROOT / "profile.example.md").read_text())
    print(f"demo run #{run_id} written")


if __name__ == "__main__":
    main()
