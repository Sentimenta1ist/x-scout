"""Typing helper behind the "type" button on reply drafts.

One visible Chrome on the app's profile stays open between clicks. A click opens the post, checks the thread for a
reply from the own account (then it stops and the card is ticked), clicks the reply box and types the draft one key at
a time: 40-130 ms per key, longer after spaces and punctuation, a rare long pause, Enter for a line break. The owner
reads it, edits it if he wants and presses Reply himself: nothing here clicks Reply or Post. X's own CreateTweet
response is caught and logged in the `sent` table (draft, sent text with his edits, ids) and ticks the card.
It has its own Chrome profile (TYPER_PROFILE, one login), so it works while a Run is searching in the main one.
The window closes after IDLE_S without clicks.
"""
import asyncio
import json
import random
import re

from playwright.async_api import async_playwright

from . import browser, db
from .config import TYPER_PROFILE

PUNCT = set(".,!?:;")
BOX = '[data-testid="tweetTextarea_0"]'
IDLE_S = 15 * 60
_GRAPHQL_OP = re.compile(r"/graphql/[^/]+/(\w+)")


def key_delays(text, rng=random):
    """Pause after each character, in seconds."""
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


def sent_from_request(post_data):
    """CreateTweet request body → (text, in_reply_to id)."""
    try:
        v = json.loads(post_data or "{}").get("variables") or {}
    except ValueError:
        return None, None
    return v.get("tweet_text"), (v.get("reply") or {}).get("in_reply_to_tweet_id")


def _screen_name(t):
    u = ((t.get("core") or {}).get("user_results") or {}).get("result") or {}
    return (u.get("core") or {}).get("screen_name") or (u.get("legacy") or {}).get("screen_name")


def own_reply(payloads, post_id, handle):
    """Id of a reply by `handle` to `post_id` found anywhere in TweetDetail responses, else None."""
    handle = (handle or "").lstrip("@").lower()
    if not handle:
        return None
    stack = list(payloads)
    while stack:
        x = stack.pop()
        if isinstance(x, list):
            stack.extend(x)
        elif isinstance(x, dict):
            leg = x.get("legacy")
            if (isinstance(leg, dict) and leg.get("in_reply_to_status_id_str") == str(post_id)
                    and (_screen_name(x) or "").lower() == handle):
                return x.get("rest_id") or leg.get("id_str") or True
            stack.extend(x.values())
    return None


class Typer:
    def __init__(self):
        self.state = {"status": "idle"}  # idle | opening | login | typing | waiting | sent | already | error
        self._pw = self._ctx = self.page = None
        self._payloads, self._item = [], None
        self._idle = None

    async def _open(self):
        if self._ctx:
            return
        try:
            self._pw = await async_playwright().start()
            self._ctx = await browser._context(self._pw, headless=False, profile=TYPER_PROFILE)
            self.page = self._ctx.pages[0] if self._ctx.pages else await self._ctx.new_page()
            self.page.on("response", self._on_response)
        except BaseException:
            await self.close()
            raise

    async def close(self):
        try:
            if self._ctx:
                await self._ctx.close()
            if self._pw:
                await self._pw.stop()
        except Exception:
            pass
        finally:
            self._ctx = self._pw = self.page = None
            if self.state.get("status") not in ("sent", "already", "error"):
                self.state = {"status": "idle"}

    async def _on_response(self, resp):
        m = _GRAPHQL_OP.search(resp.url)
        if not m or resp.status != 200:
            return
        op = m.group(1)
        if op == "CreateTweet" and self._item:
            text, reply_to = sent_from_request(resp.request.post_data)
            it = self._item
            if reply_to != it["id"]:
                return
            try:
                new_id = (await resp.json())["data"]["create_tweet"]["tweet_results"]["result"]["rest_id"]
            except Exception:
                new_id = None
            db.log_sent(it["run_id"], it, text, "sent", sent_id=new_id)
            if it.get("key"):
                db.set_check(it["run_id"], it["key"], True)
            self._item = None
            self.state = {"status": "sent", "id": it["id"], "key": it.get("key")}
        elif "Tweet" in op:
            try:
                self._payloads.append(await resp.json())
            except Exception:
                pass

    def _touch(self):
        if self._idle:
            self._idle.cancel()
        self._idle = asyncio.get_event_loop().call_later(IDLE_S, lambda: asyncio.ensure_future(self.close()))

    async def type_reply(self, item, own_handle):
        """item: {run_id, id, url, key, stage, author, draft}."""
        self._touch()
        self.state = {"status": "opening", "id": item["id"], "key": item.get("key")}
        try:
            await self._open()
            if not any(c["name"] == "auth_token" for c in await self._ctx.cookies("https://x.com")):
                await self.page.goto("https://x.com/i/flow/login")
                await self.page.bring_to_front()
                self.state = {"status": "login", "id": item["id"], "key": item.get("key")}
                return
            self._payloads, self._item = [], None
            await self.page.goto(item["url"], wait_until="domcontentloaded")
            box = self.page.locator(BOX).first
            await box.wait_for(timeout=20000)
            await asyncio.sleep(random.uniform(1.5, 3))
            if mine := own_reply(self._payloads, item["id"], own_handle):
                db.log_sent(item["run_id"], item, None, "already", sent_id=mine if isinstance(mine, str) else None)
                if item.get("key"):
                    db.set_check(item["run_id"], item["key"], True)
                self.state = {"status": "already", "id": item["id"], "key": item.get("key")}
                return
            await self.page.bring_to_front()
            await box.click()
            await asyncio.sleep(random.uniform(0.5, 1.2))
            self.state = {"status": "typing", "id": item["id"], "key": item.get("key")}
            self._item = {**item}
            text = item["draft"]
            for ch, d in zip(text, key_delays(text)):
                if ch == "\n":
                    await self.page.keyboard.press("Enter")
                else:
                    await self.page.keyboard.type(ch)
                await asyncio.sleep(d)
            if self.state.get("status") == "typing":
                self.state = {"status": "waiting", "id": item["id"], "key": item.get("key")}
        except Exception as e:
            self._item = None
            self.state = {"status": "error", "id": item["id"], "key": item.get("key"), "error": str(e)[:200]}


typer = Typer()
