"""Typing helper: takes reply drafts from a staged run and types them into X's reply box one key at a time.

The owner reads every draft, can edit it, and presses Reply himself: this script never clicks Reply or Post.
Sent replies are caught from X's own CreateTweet response and logged in the `sent` table, so later queues skip
posts that already got a reply and the draft → sent pairs show how the owner edits.

    uv run python -m x_scout.typer              # latest run, 5 replies
    uv run python -m x_scout.typer --run 18 --limit 4
"""
import argparse
import asyncio
import json
import random
from datetime import datetime, timezone

from playwright.async_api import async_playwright

from . import db
from .browser import _context
from .scoring import reply_fit

STAGES = ("big", "news", "trash")  # Viral and Topics replies come too late (2026-11-17 review)
PUNCT = set(".,!?:;")
BOX = '[data-testid="tweetTextarea_0"]'


def key_delays(text, rng=random):
    """Pause after each character, in seconds: 40-130 ms, longer after spaces and punctuation, rare long 'thinking' pauses."""
    out = []
    for ch in text:
        d = rng.uniform(0.04, 0.13)
        if ch == " ":
            d += rng.uniform(0.05, 0.18)
        elif ch in PUNCT or ch == "\n":
            d += rng.uniform(0.15, 0.4)
        if rng.random() < 0.03:
            d += rng.uniform(0.6, 1.6)
        out.append(d)
    return out


def _age_min(created_at, now):
    try:
        t = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    return (now - t).total_seconds() / 60


def pick_queue(stages, sent_ids, limit=5, now=None):
    """Reply drafts from a run's stage picks that still pass the three checks now and got no reply from us yet.
    → [{id, url, author, text, draft, stage, age_min}], best stage first."""
    now = now or datetime.now(timezone.utc)
    out, seen = [], set(sent_ids)
    for stage in STAGES:
        for p in (stages.get(stage) or {}).get("picks") or []:
            pid, says = p.get("id"), [s for s in (p.get("say") or []) if s and s.strip()]
            if not pid or pid in seen or not says:
                continue
            age = _age_min(p.get("created_at"), now)
            if not reply_fit({**p, "age_min": age})["ok"]:
                continue
            seen.add(pid)
            out.append({"id": pid, "url": p.get("url") or f"https://x.com/i/status/{pid}",
                        "author": (p.get("author") or {}).get("handle"), "text": p.get("text") or "",
                        "draft": says[0].strip(), "stage": stage, "age_min": round(age)})
    return out[:limit]


def sent_from_request(post_data):
    """CreateTweet request body → (text, in_reply_to id)."""
    try:
        v = json.loads(post_data or "{}").get("variables") or {}
    except ValueError:
        return None, None
    return v.get("tweet_text"), ((v.get("reply") or {}).get("in_reply_to_tweet_id"))


async def type_text(page, text, rng=random):
    for ch, d in zip(text, key_delays(text, rng)):
        if ch == "\n":
            await page.keyboard.press("Enter")
        else:
            await page.keyboard.type(ch)
        await asyncio.sleep(d)


def _ask(prompt):
    return input(prompt).strip()


async def session(items, run_id, pause=(30, 60)):
    caught = []  # (text, in_reply_to, new id) from CreateTweet

    async def on_response(resp):
        if "/CreateTweet" not in resp.url or resp.status != 200:
            return
        text, reply_to = sent_from_request(resp.request.post_data)
        try:
            new_id = (await resp.json())["data"]["create_tweet"]["tweet_results"]["result"]["rest_id"]
        except Exception:
            new_id = None
        caught.append((text, reply_to, new_id))

    async with async_playwright() as pw:
        ctx = await _context(pw, headless=False)
        try:
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            page.on("response", on_response)
            done = 0
            for n, it in enumerate(items, 1):
                print(f"\n[{n}/{len(items)}] @{it['author']} · {it['age_min']} мин · {it['url']}")
                print("  пост:", it["text"][:200].replace("\n", " "))
                print("  реплай:", it["draft"])
                a = _ask("  Enter — набрать, e — поправить, s — пропустить, q — выход: ").lower()
                if a == "q":
                    break
                if a == "s":
                    db.log_sent(run_id, it, None, "skipped")
                    continue
                text = it["draft"]
                if a == "e":
                    text = _ask("  новый текст: ") or text
                await page.goto(it["url"], wait_until="domcontentloaded")
                await asyncio.sleep(random.uniform(2, 4))
                box = page.locator(BOX).first
                try:
                    await box.wait_for(timeout=15000)
                except Exception:
                    print("  поле ответа не нашлось, пропускаю")
                    db.log_sent(run_id, it, None, "no_box", draft=text)
                    continue
                await box.click()
                await asyncio.sleep(random.uniform(0.5, 1.2))
                caught.clear()
                await type_text(page, text)
                _ask("  набрано. проверь, жми Reply в Chrome, потом Enter здесь: ")
                hit = next((c for c in caught if c[1] == it["id"]), None)
                if hit:
                    db.log_sent(run_id, it, hit[0], "sent", draft=text, sent_id=hit[2])
                    done += 1
                    print("  отправлено и записано")
                    if n < len(items):
                        w = random.uniform(*pause)
                        print(f"  пауза {w:.0f} с")
                        await asyncio.sleep(w)
                else:
                    db.log_sent(run_id, it, None, "not_sent", draft=text)
                    print("  отправки не видно, записал как не отправленный")
            print(f"\nготово: отправлено {done}")
        finally:
            await ctx.close()


def main():
    ap = argparse.ArgumentParser(description="type reply drafts from a run into X, one key at a time")
    ap.add_argument("--run", type=int, help="run id (default: latest)")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--dry", action="store_true", help="only print the queue")
    a = ap.parse_args()
    db.init()
    run_id = a.run or db.latest_run_id()
    run = db.get_run(run_id)
    items = pick_queue(run.get("stages") or {}, db.sent_ids(), a.limit)
    print(f"прогон #{run_id}: в очереди {len(items)}")
    if a.dry or not items:
        for it in items:
            print(f"- @{it['author']} {it['age_min']} мин · {it['draft']}")
        return
    asyncio.run(session(items, run_id))


if __name__ == "__main__":
    main()
