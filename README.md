<div align="center">

# X Scout

**Your daily X briefing for up to 5 topics: what is taking off, what everyone talks about, and what is useful to *you*. Runs locally, ranked by Claude.**

[![tests](https://github.com/Sentimenta1ist/x-scout/actions/workflows/test.yml/badge.svg)](https://github.com/Sentimenta1ist/x-scout/actions/workflows/test.yml)
![python](https://img.shields.io/badge/python-3.12+-3776ab)
![license](https://img.shields.io/badge/license-MIT-green)

[Website](https://sentimenta1ist.github.io/x-scout/) · [How it works](#how-it-works) · [Quick start](#quick-start) · [Token cost](#token-cost)

<img src="docs/img/board-dark.png" alt="X Scout board for the AI agents topic" width="100%">

</div>

## Why

Scrolling X to find posts worth reading or replying to eats an hour a day. Browser agents that scroll and screenshot the feed are slow and burn ~1.5k tokens per screenshot. X Scout does the reading for you:

1. searches X for your topics in a real browser, the way a person would;
2. scores every post for early virality locally, for free;
3. sends only the best ~40 candidates per topic to **one** `claude -p` call as compact text;
4. shows up to 5 posts to reply to and up to 5 to read per topic. Junk never fills a column.

| Column | What lands there |
|---|---|
| **Reply** | Fresh posts with reach where *you* can add something concrete, based on a short profile you write. Comes with a suggested reply angle. |
| **Read** | Posts with real substance worth reading or saving: deep dives, data, postmortems, genuinely new tools. |

Every card has Claude's one-line take, a 1–2 sentence summary of the post (in a language you pick), a 1–5 depth rating, the post metrics and a link to open it on X. Reply cards also get a **reply angle** (copy button).

## Features

- **Up to 5 topics**, each with an optional X search query (`OR`, quotes, `-exclude`, `from:` …). Leave it empty and Claude writes one from the topic name and your profile.
- **Real Chrome, no DOM scraping.** Playwright drives your installed Google Chrome with its own profile and reads X's own search JSON. Human-paced: randomized pauses, a few scrolls, nothing is clicked. Stops on a rate limit or a login prompt.
- **Local virality score** (0–100): projected views from age, engagement per view, reach vs the author's usual level (from history, or from followers on day one), and acceleration between runs.
- **One Claude call per run**, tuned for tokens (see [Token cost](#token-cost)).
- **Progress bar with ETA**, run summary (posts, tokens, time), run history, **Re-analyze** to rerun Claude on stored posts without scraping.
- **"Seen" marks**, light and dark theme, works on a phone-width window.
- Everything stays on your machine: SQLite, browser profile and settings live in `data/`.

## Profile analysis

Open **Profiles**, type an X handle, press **Analyze**. You get a breakdown of that account: which posts went viral and why, how its reach grew, and what you can repeat on your own account. Read-only, same pace and stop rules as search.

<table>
<tr>
<td width="50%"><img src="docs/img/profile-growth.png" alt="Growth tab: views per post, rolling medians, breakouts and inferred phases"></td>
<td width="50%"><img src="docs/img/profile-repeat.png" alt="Repeat for me tab: a checklist of tactics with a one-week test for each"></td>
</tr>
</table>

| Tab | What is there |
|---|---|
| **Overview** | Bio, key numbers, Claude's summary, format mix, posting hours, article chains, borrowed reach |
| **Growth** | Views per post on a log scale, 7- and 30-post medians, breakouts, phases with confidence, snapshot comparison |
| **Viral posts** | Top 10 with link, numbers and why each worked |
| **Patterns** | Hooks, opening lines as templates, structures, CTAs, what flops |
| **Repeat for me** | 5–8 tactics adapted to your About me, each with a one-week test; plus what not to copy |
| **Raw** | Sortable table of every post, CSV export |

- **Scrape:** up to 300 posts or 120 days, whichever comes first, plus up to 60 replies. All three limits are in Settings. Takes a few minutes.
- **Metrics are local.** A breakout is a post with at least 5× the median views of the previous 30 original posts.
- **Growth is inference.** X does not expose follower history, so phases come from steps in the views median and are labeled as such. Every scrape saves a snapshot (followers, following, posts), so a real history builds up and any two snapshots can be compared.
- **One `claude -p` call** (Sonnet by default) on the metrics, the top ~40 posts by breakout ratio and ~20 typical ones. It suggests structures and tactics, never copied text; items that repeat 8+ words of a post are dropped.
- **Stop, a 429 or a lost session keep what was read**, without calling Claude. **Re-analyze** runs Claude on stored posts with no X traffic.

## Screens

<table>
<tr>
<td width="50%"><img src="docs/img/running.png" alt="Run in progress with progress bar, ETA and log"></td>
<td width="50%"><img src="docs/img/settings.png" alt="Settings: topics, queries, scraping limits, model and About me profile"></td>
</tr>
<tr>
<td align="center"><sub>A run in progress</sub></td>
<td align="center"><sub>Topics, limits and your profile</sub></td>
</tr>
</table>

## How it works

```mermaid
flowchart LR
    A[Topics + queries] --> B[Chrome via Playwright<br/>X search: Top + Latest]
    B -->|SearchTimeline JSON| C[Parse + dedupe]
    C --> D[Local virality score<br/>+ author history]
    D --> E[Top ~40 per topic<br/>one line per post]
    E --> F["claude -p (Sonnet)<br/>one call per run"]
    F --> G[Reply · Read, up to 5 each<br/>why + reply angle]
    D --> H[(SQLite: posts,<br/>snapshots, runs)]
    H -.->|acceleration next run| D
```

What Claude actually receives per post:

```
12|@mira_builds|18.4k|38m|41.2k|1.2k|164|233|610|86|[img]We put an eval harness in front of every tool call…
```

Posts are referenced by a local index (`12`), not by 19-digit IDs, and Claude answers in a compact line format:

```
# AI agents
H 12 5 | Eval harness on every tool call, failures 14% → 3% | Ask which check caught the most
```

## Quick start

Requirements: macOS or Linux, **Google Chrome**, [uv](https://docs.astral.sh/uv/), and [Claude Code](https://claude.com/claude-code) logged in (`claude` on PATH).

```bash
git clone https://github.com/Sentimenta1ist/x-scout.git
cd x-scout
./run                 # on macOS you can also double-click "X Scout.command"
```

The app opens at http://127.0.0.1:8765.

1. **Log in to X.** A Chrome window opens; log in and it closes itself once you reach the home feed. The session is stored in `data/browser-profile` and lasts for months. Use a **secondary account**: any automation carries some risk for the account that runs it.
2. **Settings.** Add up to 5 topics, write a few lines in **About me** (what you do, what is useful, what is noise). See [`profile.example.md`](profile.example.md).
3. **Run.** 3 topics take ~3 minutes, mostly paced search.

Try the UI without an X account, using made-up demo data:

```bash
X_SCOUT_DATA=./demo-data uv run python scripts/demo.py
X_SCOUT_DATA=./demo-data uv run x-scout
```

## Settings

| Setting | Default | What it does |
|---|---|---|
| Topics | — | Up to 5. Name is shown in the UI, query goes to X search. Empty query → Claude writes one. |
| Language | `en` | `lang:` filter; empty = any language. |
| Posts per tab | 40 | Posts collected from **Top** and from **Latest** for each topic. |
| Candidates per topic | 40 | How many of the best-scored posts go to Claude. Main token knob. |
| Model | `sonnet` | `haiku` is cheaper, `opus` is more thorough. |
| Summary language | `English` | Language of the short per-post summary, e.g. `Russian`. |
| Headless | on | Turn off to watch the browser work. |
| Profile analysis limits | 300 posts, 120 days, 60 replies | How far back the Profiles panel reads. Replies `0` skips that tab. |

Optional `.env` (see [`.env.example`](.env.example)): `PORT`, `CLAUDE_BIN`, `CLAUDE_MODEL`, `X_SCOUT_DATA`.

## Token cost

`claude -p` runs with a short custom system prompt, `--tools ""`, `--setting-sources ""` and an empty working directory, so Claude Code's own overhead is ~1.5k tokens instead of ~20k for a default session. The answer is plain lines rather than `--json-schema`: structured output costs a second model turn that re-reads the whole prompt.

Measured on 3 topics × 25 posts with Sonnet:

| Output format | Input tokens | Output tokens | Time |
|---|---|---|---|
| `--json-schema` | 15.0k | 4.9k | 33 s |
| line format (used) | 6.0k | 1.6k | 15 s |

With the default 40 candidates per topic, a 3-topic run is ~20k input / ~2k output tokens. The run summary shows the exact numbers for every run.

## Volume and safety

- Defaults: 2 search tabs × 40 posts × topics, i.e. up to ~240 posts for 3 topics, with 3–15 s randomized pauses between pages and searches.
- The run stops at the first HTTP 429 or login redirect. Runs start only when you press **Run**: there is no background crawling.
- Nothing is ever liked, followed, posted or clicked.

## Data and privacy

Everything is local and gitignored, in `data/`:

| File | Contents |
|---|---|
| `x-scout.db` | Posts, metric snapshots (for acceleration and author baselines), runs |
| `browser-profile/` | The Chrome profile with your X session |
| `settings.json`, `profile.md` | Your topics and About me |
| `profiles/<handle>/` | Scrapes (parsed posts + raw X JSON, gzipped), analyses, `snapshots.jsonl` |

The only network traffic is Chrome talking to x.com and the Claude CLI talking to Anthropic.

## Development

```bash
uv run pytest                                   # parsers, scoring, candidate selection, profile metrics, reply parsing
uv run python scripts/screenshots.py <url>      # re-render docs/img from a running demo server
```

```
x_scout/
  browser.py    Playwright, persistent profile, search + response capture
  parse.py      SearchTimeline and profile JSON → flat posts (handles X schema variants)
  scoring.py    virality score (ported from x-viral-radar)
  analyze.py    candidate selection, compact digest, claude -p, reply parsing
  pipeline.py   run orchestration, progress, settings
  profile_metrics.py   profile analysis: breakouts, medians, cadence, article chains, phases
  profile_analysis.py  profile analysis: digest, claude -p prompt, reply parsing
  profile_store.py     data/profiles/<handle>/ files
  app.py        FastAPI API + static UI
  static/       index.html, app.js, profile.js, style.css (no build step)
```

The scoring model comes from [x-viral-radar](https://github.com/Sentimenta1ist/x-viral-radar), a Chrome extension that badges posts in your own feed.

## FAQ

**Can it work without logging in?** No. X search requires an account. The session is saved, so you log in once and it lasts for months.

**Why not the official X API?** Search access is expensive for a personal tool. A third-party API backend could be added as an alternative to Chrome later.

**Does it need an Anthropic API key?** No. It uses your logged-in Claude Code CLI.

## License

[MIT](LICENSE). Not affiliated with X Corp. or Anthropic.
