"""Render README / GitHub Pages screenshots from a running demo server.

    X_SCOUT_DATA=./demo-data uv run python scripts/demo.py
    X_SCOUT_DATA=./demo-data PORT=8798 uv run x-scout   # in another terminal
    uv run python scripts/screenshots.py http://127.0.0.1:8798
"""
import asyncio
import json
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path(__file__).resolve().parent.parent / "docs" / "img"
IDLE = {"running": False, "run_id": 1, "step": "", "log": [], "login": "ok", "progress": 1, "eta_s": None, "started": None}
RUNNING = {"running": True, "run_id": 1, "step": "Automation: Latest (topic 2/3)", "login": "ok", "progress": 0.42,
           "eta_s": 190, "started": time.time() - 78,
           "log": ["02:11:03 AI agents: searching top", "02:11:31 AI agents: searching live", "02:11:58 AI agents: 79 unique posts",
                   "02:12:09 Automation: searching top", "02:12:21 Automation: searching live"]}


async def shot(browser, base, name, scheme, state, width=1440, height=1000, full=False, before=None):
    page = await browser.new_page(viewport={"width": width, "height": height}, color_scheme=scheme, device_scale_factor=2)
    await page.route("**/api/state", lambda r: r.fulfill(content_type="application/json", body=json.dumps(state)))
    await page.goto(base)
    await page.wait_for_timeout(1200)
    if before:
        await before(page)
        await page.wait_for_timeout(600)
    await page.screenshot(path=OUT / f"{name}.png", full_page=full)
    await page.close()


async def main(base):
    OUT.mkdir(parents=True, exist_ok=True)

    async def open_settings(page):
        await page.click("#settingsBtn")

    async def open_log(page):
        await page.click("#logBtn")

    async with async_playwright() as pw:
        b = await pw.chromium.launch(channel="chrome", headless=True)
        await shot(b, base, "board-dark", "dark", IDLE)
        await shot(b, base, "board-light", "light", IDLE)
        await shot(b, base, "running", "dark", RUNNING, height=520, before=open_log)
        await shot(b, base, "settings", "dark", IDLE, height=640, before=open_settings)
        await shot(b, base, "mobile", "dark", IDLE, width=390, height=844)
        await b.close()
    print("written to", OUT)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8798"))
