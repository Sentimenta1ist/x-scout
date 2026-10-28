"""Real Chrome (persistent profile) driven by Playwright.

We never parse the DOM: X's own web client requests SearchTimeline GraphQL and we read those JSON responses.
The browser behaves like a person searching: one tab, a few scrolls, randomized pauses, nothing is clicked.
"""
import asyncio
import random
import re
import subprocess
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from playwright.async_api import async_playwright

from .config import BROWSER_PROFILE
from .parse import posts_from_search

_lock = asyncio.Lock()  # one Chrome per profile dir at a time


class NeedLogin(Exception):
    pass


class RateLimited(Exception):
    pass


def _chrome_ua():
    """Headless Chrome advertises 'HeadlessChrome' in its UA; send the normal desktop UA instead."""
    try:
        out = subprocess.run(
            ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "--version"],
            capture_output=True, text=True, timeout=10,
        ).stdout
        major = re.search(r"(\d+)\.", out).group(1)
        return (f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36")
    except Exception:
        return None


async def _context(pw, headless):
    kwargs = dict(
        user_data_dir=str(BROWSER_PROFILE),
        channel="chrome",
        headless=headless,
        viewport={"width": 1280, "height": 900},
        locale="en-US",
        args=["--disable-blink-features=AutomationControlled"],
    )
    if headless and (ua := _chrome_ua()):
        kwargs["user_agent"] = ua
    try:
        return await pw.chromium.launch_persistent_context(**kwargs)
    except Exception:
        # no system Chrome: fall back to Playwright's bundled Chromium
        kwargs.pop("channel")
        return await pw.chromium.launch_persistent_context(**kwargs)


async def check_login():
    async with _lock, async_playwright() as pw:
        ctx = await _context(pw, headless=True)
        try:
            cookies = await ctx.cookies("https://x.com")
            return any(c["name"] == "auth_token" for c in cookies)
        finally:
            await ctx.close()


async def interactive_login(timeout_s=600):
    """Open a visible window on the login page and wait until the user lands on /home."""
    async with _lock, async_playwright() as pw:
        ctx = await _context(pw, headless=False)
        try:
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            await page.goto("https://x.com/i/flow/login")
            deadline = asyncio.get_event_loop().time() + timeout_s
            while asyncio.get_event_loop().time() < deadline:
                cookies = await ctx.cookies("https://x.com")
                if any(c["name"] == "auth_token" for c in cookies) and "/home" in page.url:
                    await asyncio.sleep(2)
                    return True
                await asyncio.sleep(1.5)
            return False
        finally:
            await ctx.close()


def build_queries(topic, lang):
    q = topic.get("query") or topic["name"]
    lang_op = f" lang:{lang}" if lang else ""
    since = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    return [
        # most engaged posts of the last ~day: "what everyone is talking about"
        ("top", f"{q}{lang_op} -filter:replies since:{since}"),
        # fresh posts that already got some traction: early risers
        ("live", f"{q}{lang_op} -filter:replies min_faves:5"),
    ]


async def _search_one(page, mode, query, target, log):
    batch = []
    status = {"code": None}

    async def on_response(resp):
        if "SearchTimeline" not in resp.url:
            return
        status["code"] = resp.status
        if resp.status != 200:
            return
        try:
            batch.extend(posts_from_search(await resp.json()))
        except Exception:
            pass

    page.on("response", on_response)
    try:
        url = f"https://x.com/search?q={quote(query)}&src=typed_query" + ("&f=live" if mode == "live" else "")
        await page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(random.uniform(3, 5))
        if "/login" in page.url or "/i/flow" in page.url:
            raise NeedLogin()
        stale = 0
        while len(batch) < target and stale < 3:
            if status["code"] == 429:
                raise RateLimited()
            before = len(batch)
            await page.mouse.wheel(0, random.randint(2500, 4000))
            await asyncio.sleep(random.uniform(2.5, 5.5))
            stale = stale + 1 if len(batch) == before else 0
        if status["code"] == 429:
            raise RateLimited()
        if status["code"] is None:
            log(f"  {mode}: X returned no search data (logged out or page changed?)")
    finally:
        page.remove_listener("response", on_response)
    return batch


async def scrape(topics, per_mode=30, lang="en", headless=True, log=print):
    """Returns {topic_name: [post, ...]} with posts deduped within a topic."""
    out = {}
    async with _lock, async_playwright() as pw:
        ctx = await _context(pw, headless=headless)
        try:
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            for i, topic in enumerate(topics):
                if i:
                    await asyncio.sleep(random.uniform(8, 15))
                seen = {}
                for mode, query in build_queries(topic, lang):
                    log(f"{topic['name']}: searching {mode} — {query}")
                    for p in await _search_one(page, mode, query, per_mode, log):
                        p.setdefault("found_in", mode)
                        seen.setdefault(p["id"], p)
                    await asyncio.sleep(random.uniform(4, 8))
                out[topic["name"]] = list(seen.values())
                log(f"{topic['name']}: {len(seen)} unique posts")
        finally:
            await ctx.close()
    return out
