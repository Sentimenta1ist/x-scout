# X Scout

Local app that tells you what is happening on X for up to 5 topics. For each topic you get three columns of 3–6 posts:

- **Hot**: young posts that are taking off right now (good to reply early)
- **Global**: the most important posts of the day, to stay informed
- **For me**: what is useful given *your* profile (tools, techniques, leads, people), with a suggested reply angle

How it works:

1. A real Google Chrome with its own profile (Playwright) searches X for each topic, in both the **Top** and **Latest** tabs. It reads X's own search JSON (`SearchTimeline`), not the page, with randomized human-like pauses. Nothing is clicked, liked or posted.
2. Every post gets a local early-virality score (projected views vs age, engagement per view, vs the author's usual reach, acceleration between runs), ported from [x-viral-radar](../x-viral-radar).
3. ~25 candidates per topic go to **one** `claude -p` call as compact one-line rows. Claude picks the three columns and writes a one-line "why" and reply angle.

Token cost per run (3 topics, Sonnet): ~6k input / ~1.5k output tokens, ~15 s. The CLI runs with a short custom system prompt, no tools, no settings and an empty working dir, so Claude Code's own overhead is ~1.5k tokens instead of ~20k.

## Requirements

- macOS / Linux with **Google Chrome** installed
- [uv](https://docs.astral.sh/uv/)
- [Claude Code](https://claude.com/claude-code) CLI, logged in (`claude` on PATH, or set `CLAUDE_BIN` in `.env`)
- An X account. Use a **secondary** account: any automation carries some risk for the account that runs it.

## Run

```bash
./run            # or double-click "X Scout.command" in Finder
```

Opens http://127.0.0.1:8765.

1. **Log in to X**: a Chrome window opens, log in, the window closes itself once you reach the home feed. The session lives in `data/browser-profile` and usually lasts for weeks; re-login when the pill turns red.
2. **Settings**: topics (name + optional X search query with any operators, e.g. `("AI agent" OR agentic) -crypto`), language, how many posts to scrape, model, and **About me** (what Claude uses for the "For me" column).
3. **Run**. A run of 5 topics takes ~5–8 minutes, mostly the paced search. Past runs stay in the dropdown.

**Re-analyze** runs Claude again on a stored run's posts without scraping: useful for tuning the profile or trying another model.

## Volume and safety

Defaults: 30 posts per tab × 2 tabs × topics → up to ~300 posts per run, a handful of search pages with 3–15 s pauses. The run stops immediately on a rate limit (HTTP 429) or a login redirect. Don't run it in a tight loop.

## Data

Everything is local in `data/` (gitignored): `x-scout.db` (posts, metric snapshots, runs), `browser-profile/`, `settings.json`, `profile.md`.

## Dev

```bash
uv run pytest
```

Code map and conventions: `CLAUDE.md`.
