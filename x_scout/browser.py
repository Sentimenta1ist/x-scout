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
from .parse import post_detail, posts_from_search, profile_from_user, timeline_page

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


async def scrape(topics, per_mode=40, lang="en", headless=True, log=print, on_step=lambda i, label: None):
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
                for j, (mode, query) in enumerate(build_queries(topic, lang)):
                    tab = "Top" if mode == "top" else "Latest"
                    on_step(i * 2 + j, f"{topic['name']}: {tab} (topic {i + 1}/{len(topics)})")
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


_GRAPHQL_OP = re.compile(r"/graphql/[^/]+/(\w+)")
# X renames these operations; older names stay so a rollback or A/B bucket still works
POST_OPS = ("UserOriginalsTimeline", "UserTweets")
REPLY_OPS = ("UserRepliesTimeline", "UserTweetsAndReplies")


def page_reached_cutoff(page_posts, cutoff_iso):
    """Stop paginating once a whole page is older than the cutoff. Uses the page's newest post, because a pinned post
    or an old thread start in a conversation module must not end the scrape early."""
    dates = [p["created_at"] for p in page_posts if p.get("created_at") and not p.get("pinned")]
    return bool(dates) and max(dates) < cutoff_iso


async def _read_timeline(page, url, ops, handle, target, cutoff_iso, sink, log, on_page):
    """Scroll one profile tab, reading only `ops` responses. Everything captured goes to `sink` right away,
    so a Stop or a 429 keeps what was already read."""
    counted = {"own": 0, "stale": 0, "done": False, "status": None, "limited": False}

    async def on_response(resp):
        m = _GRAPHQL_OP.search(resp.url)
        if not m:
            return
        if resp.status == 429:
            counted["limited"] = True
        name = m.group(1)
        if name == "UserByScreenName":
            if resp.status == 200:
                try:
                    data = await resp.json()
                    prof = profile_from_user(data)
                except Exception:
                    return
                if prof and prof["handle"].lower() == handle.lower():
                    sink["profile"] = prof
                    sink["responses"].append({"op": name, "data": data})
                elif sink["profile"] is None and not prof:
                    sink["missing"] = True
            return
        if name not in ops:
            return
        counted["status"] = resp.status
        if resp.status != 200:
            return
        try:
            data = await resp.json()
            pg = timeline_page(data, handle)
        except Exception:
            return
        sink["responses"].append({"op": name, "data": data})
        sink["posts"].extend(pg["posts"])
        sink["accounts"].update(pg["accounts"])
        sink["retweets"] += pg["retweets"]
        counted["own"] += len(pg["posts"])
        if page_reached_cutoff(pg["posts"], cutoff_iso):
            counted["done"] = True
        on_page()

    def check():
        if counted["limited"]:
            raise RateLimited()
        if "/login" in page.url or "/i/flow" in page.url or counted["status"] == 401:
            raise NeedLogin()

    page.on("response", on_response)
    try:
        await page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(random.uniform(3, 6))
        check()
        scrolls = 0
        while counted["own"] < target and not counted["done"] and counted["stale"] < 4:
            before = counted["own"]
            await page.mouse.wheel(0, random.randint(2500, 4000))
            scrolls += 1
            # human pace: 3-7 s between scrolls, a longer 8-15 s break every few
            await asyncio.sleep(random.uniform(8, 15) if scrolls % 6 == 0 else random.uniform(3, 7))
            check()
            counted["stale"] = counted["stale"] + 1 if counted["own"] == before else 0
        if counted["status"] is None:
            log(f"  {ops[0]}: X returned no timeline data (logged out, or X renamed the operation?)")
    finally:
        page.remove_listener("response", on_response)
    return counted["own"]


async def scrape_profile(handle, sink, max_posts=300, max_days=120, max_replies=60, headless=True, log=print,
                         on_progress=lambda phase, n: None):
    """Read one account into `sink`: {"profile", "posts", "accounts", "retweets", "responses"}. Read-only: scrolls and reads JSON.
    Raises NeedLogin / RateLimited / LookupError; what was read before that stays in `sink`."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_days)).isoformat()
    async with _lock, async_playwright() as pw:
        ctx = await _context(pw, headless=headless)
        try:
            if not any(c["name"] == "auth_token" for c in await ctx.cookies("https://x.com")):
                raise NeedLogin()
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            log(f"@{handle}: reading posts (up to {max_posts} or {max_days} days)")
            await _read_timeline(page, f"https://x.com/{handle}", POST_OPS, handle, max_posts, cutoff, sink, log,
                                 lambda: on_progress("posts", len(sink["posts"])))
            if not sink["profile"]:
                raise LookupError(f"@{handle}: account not found or unavailable" if sink.get("missing")
                                  else f"@{handle}: X returned no profile data (logged out or page changed?)")
            own = len(sink["posts"])
            log(f"@{handle}: {own} posts read")
            if max_replies > 0 and not sink["profile"]["protected"]:
                await asyncio.sleep(random.uniform(8, 15))
                log(f"@{handle}: reading replies (up to {max_replies})")
                await _read_timeline(page, f"https://x.com/{handle}/with_replies", REPLY_OPS, handle, max_replies,
                                     cutoff, sink, log, lambda: on_progress("replies", len(sink["posts"]) - own))
        finally:
            await ctx.close()
    return sink


async def scrape_post(post_id, sink, headless=True, log=print):
    """Open one post's page and read it from whatever GraphQL responses carry it. Read-only: a small scroll loads the author's thread.
    Fills sink["post"] and sink["responses"]. Raises NeedLogin / RateLimited / LookupError."""
    payloads, flags = [], {"limited": False}

    async def on_response(resp):
        m = _GRAPHQL_OP.search(resp.url)
        if not m:
            return
        if resp.status == 429:
            flags["limited"] = True
        if resp.status != 200 or "Tweet" not in m.group(1):
            return
        try:
            payloads.append(await resp.json())
        except Exception:
            pass

    async with _lock, async_playwright() as pw:
        ctx = await _context(pw, headless=headless)
        try:
            if not any(c["name"] == "auth_token" for c in await ctx.cookies("https://x.com")):
                raise NeedLogin()
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            page.on("response", on_response)
            log(f"reading post {post_id}")
            await page.goto(f"https://x.com/i/status/{post_id}", wait_until="domcontentloaded")
            for _ in range(5):
                await asyncio.sleep(random.uniform(3, 5))
                if flags["limited"]:
                    raise RateLimited()
                if "/login" in page.url or "/i/flow" in page.url:
                    raise NeedLogin()
                if post_detail(payloads, post_id):
                    break
            await page.mouse.wheel(0, random.randint(800, 1500))
            await asyncio.sleep(random.uniform(3, 5))
        finally:
            await ctx.close()
    sink["responses"] = payloads
    sink["post"] = post_detail(payloads, post_id)
    if not sink["post"]:
        raise LookupError(f"Post {post_id}: not found, deleted, or a retweet. X returned no data for it.")
    return sink
