"""Real Chrome (persistent profile) driven by Playwright.

We never parse the DOM: X's own web client requests SearchTimeline GraphQL and we read those JSON responses.
The browser behaves like a person searching: one tab, a few scrolls, randomized pauses, nothing is clicked.
"""
import asyncio
import random
import re
import subprocess
import time
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


def build_queries(topic, lang, exact_window=True):
    """Main query: Top of the last 24h and Latest with some traction. Each extra query (other words for the same
    subject) adds one Top search over the same 24h. min_faves on Top skips posts the candidate filter would drop anyway:
    every page read costs rate limit. since_time is exact; since: (a date) is the fallback and reaches back up to ~46h."""
    q = topic.get("query") or topic["name"]
    lang_op = f" lang:{lang}" if lang else ""
    day_ago = datetime.now(timezone.utc) - timedelta(days=1)
    window = f"since_time:{int(day_ago.timestamp())}" if exact_window else f"since:{day_ago:%Y-%m-%d}"
    out = [
        # most engaged posts of the last day: "what everyone is talking about"
        ("top", f"{q}{lang_op} -filter:replies min_faves:3 {window}"),
        # fresh posts that already got some traction: early risers
        ("live", f"{q}{lang_op} -filter:replies min_faves:5"),
    ]
    for extra in (topic.get("extra") or [])[:3]:
        if extra.strip():
            out.append(("top", f"{extra.strip()}{lang_op} -filter:replies min_faves:3 {window}"))
    return out


def search_count(topics, lang=""):
    return sum(len(build_queries(t, lang)) for t in topics)


def search_plan(topics, lang, exact_window=True):
    """Main searches of every topic first, extra queries after: when the rate limit runs out, the run loses
    extra queries, not whole topics. → [(topic index, query index, mode, query)]"""
    plan = [(i, j, mode, q) for i, t in enumerate(topics) for j, (mode, q) in enumerate(build_queries(t, lang, exact_window))]
    return sorted(plan, key=lambda x: (x[1] >= 2, x[0], x[1]))


MAX_WAIT_S = 16 * 60  # X's search window is 15 minutes


class Budget:
    """X sends x-rate-limit-remaining / -reset on its GraphQL responses. Reading them lets the scrape wait for the
    reset instead of running into a 429."""
    def __init__(self, log, on_wait=lambda left: None, reserve=2):
        self.remaining, self.reset, self.calls, self.waited = None, None, 0, 0
        self.log, self.on_wait, self.reserve = log, on_wait, reserve

    def update(self, headers, code):
        self.calls += 1
        try:
            self.remaining = int(headers.get("x-rate-limit-remaining"))
            self.reset = int(headers.get("x-rate-limit-reset"))
        except (TypeError, ValueError):
            pass
        if code == 429:
            self.remaining = 0

    def wait_s(self, now=None):
        if self.remaining is None or self.remaining > self.reserve or not self.reset:
            return 0
        return max(self.reset - (now or time.time()) + 5, 0)

    async def ensure(self):
        """Sleep until the window resets if the budget is (almost) spent. False if the reset is unknown or too far."""
        if self.remaining is not None and self.remaining <= self.reserve and not self.reset:
            return False
        wait = self.wait_s()
        if not wait:
            return True
        if wait > MAX_WAIT_S:
            return False
        self.log(f"X search limit almost used ({self.calls} requests so far): waiting {round(wait / 60, 1)} min for the reset")
        end = time.time() + wait
        while (left := end - time.time()) > 0:
            self.on_wait(left)
            await asyncio.sleep(min(left, 5))
        self.waited += wait
        self.remaining = None
        return True


async def _search_one(page, mode, query, target, log, budget):
    batch = []
    status = {"code": None}

    async def on_response(resp):
        if "SearchTimeline" not in resp.url:
            return
        status["code"] = resp.status
        budget.update(await resp.all_headers(), resp.status)
        if resp.status != 200:
            return
        try:
            batch.extend(posts_from_search(await resp.json()))
        except Exception:
            pass

    page.on("response", on_response)
    try:
        if not await budget.ensure():
            raise RateLimited()
        url = f"https://x.com/search?q={quote(query)}&src=typed_query" + ("&f=live" if mode == "live" else "")
        await page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(random.uniform(3, 5))
        if "/login" in page.url or "/i/flow" in page.url:
            raise NeedLogin()
        stale = 0
        while len(batch) < target and stale < 3:
            if status["code"] == 429:
                raise RateLimited()
            if budget.wait_s():  # out of budget mid-search: keep this page's posts, the next search waits
                break
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
    return batch, status["code"]


async def scrape(topics, per_mode=40, lang="en", headless=True, log=print, on_step=lambda i, label: None, status=None,
                 on_wait=lambda left: None):
    """Returns {topic_name: [post, ...]} with posts deduped within a topic. Main searches of all topics run first, extra
    queries after. When X's search budget runs out the scrape waits for the reset (up to MAX_WAIT_S); a 429 it can't wait
    out ends the scrape early and keeps what was read (status["rate_limited"] = True), so the run still gets analyzed."""
    status = status if status is not None else {}
    seen = [{} for _ in topics]
    budget = Budget(log, on_wait)
    exact = True
    plan = search_plan(topics, lang)
    async with _lock, async_playwright() as pw:
        ctx = await _context(pw, headless=headless)
        try:
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            for step, (i, j, mode, query) in enumerate(plan):
                topic = topics[i]
                if not exact and mode == "top":
                    query = build_queries(topic, lang, exact_window=False)[j][1]
                tab = "Top" if mode == "top" else "Latest"
                label = f"{tab}, extra query {j - 1}" if j >= 2 else tab
                on_step(step, f"{topic['name']}: {label} ({step + 1}/{len(plan)} searches)")
                log(f"{topic['name']}: searching {mode} — {query}")
                try:
                    batch, code = await _search_one(page, mode, query, per_mode, log, budget)
                except RateLimited:
                    if not any(seen):
                        raise
                    status["rate_limited"] = True
                    log(f"X rate limit (429) at {topic['name']}: stopping the search, analyzing the "
                        f"{sum(len(s) for s in seen)} posts read so far")
                    break
                if exact and step == 0 and mode == "top" and code == 200 and not batch:
                    exact = False  # X ignored since_time: fall back to the date form for the rest of the run
                    log("  since_time returned nothing: using since:<date> for Top searches")
                for p in batch:
                    p.setdefault("found_in", mode)
                    seen[i].setdefault(p["id"], p)
                await asyncio.sleep(random.uniform(4, 8))
        finally:
            await ctx.close()
    for t, sn in zip(topics, seen):
        log(f"{t['name']}: {len(sn)} unique posts")
    log(f"{budget.calls} search requests" + (f", waited {round(budget.waited / 60, 1)} min for the limit reset" if budget.waited else ""))
    status["search_requests"] = budget.calls
    status["waited_s"] = round(budget.waited)
    return {t["name"]: list(s.values()) for t, s in zip(topics, seen) if s or not status.get("rate_limited")}


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
