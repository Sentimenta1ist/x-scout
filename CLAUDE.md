# x-scout

Local app: searches X for up to 5 topics through a real Chrome profile (Playwright), scores posts for early virality (ported from github.com/Sentimenta1ist/x-viral-radar `scoring.js`), then one `claude -p` call sorts candidates into three columns per topic: hot / global / useful-for-me. UI is FastAPI + one vanilla-JS page.

- `x_scout/browser.py` Playwright, persistent profile in `data/browser-profile`. Reads X's own `SearchTimeline` GraphQL responses, never the DOM. Keep it human-paced (randomized pauses, few scrolls); stop on 429 or login redirect. No clicks, likes, follows, posting.
- `x_scout/parse.py` GraphQL → flat post dict. X moves fields between schema versions; look up new place first, then legacy.
- `x_scout/scoring.py` pure scoring, tests in `tests/`.
- `x_scout/analyze.py` candidate pre-filter, compact pipe-delimited digest, `claude -p` with a short custom system prompt, `--tools ""`, `--setting-sources ""`, empty cwd. Token economy is a core requirement: measure `usage` after prompt changes.
- `x_scout/pipeline.py` orchestration and live state; `app.py` HTTP API.
- `data/` (gitignored): sqlite db, browser profile, `settings.json`, `profile.md`. Never commit it.
- Tests: `uv run pytest`. Run: `./run`. Demo data: `scripts/demo.py`; README images: `scripts/screenshots.py` against a demo server.
- Re-analyze (UI button / `POST /api/runs/{id}/reanalyze`) re-runs Claude on stored candidates without scraping: use it for prompt tuning.
