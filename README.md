# job-bot

A semi-automated job-search assistant. It pulls listings from public job-board
APIs, scores each one against your background with Claude, writes a tailored
resume and cover letter for the good matches, and helps you track applications.
**You** review everything and click submit. Built for QA / SDET / DevOps roles
first; per-user job titles, locations and companies make it work for any field.

```
fetch (public job APIs) -> filter (free) -> rank (free) -> score (Haiku) -> tailor (Sonnet)
      -> guardrail checks -> PDF packet -> you review -> apply (pre-fill, you submit)
```

Use it from the command line or from a local website (`python -m jobbot web`,
see [Dashboard](#dashboard-local-website)).

The point is fewer, better, truthful applications, not volume. The AI can't
invent experience: guardrails in code (not just the prompt) keep every resume
tied to facts you wrote yourself.

## Setup

Requires Python 3.10+ (tested on 3.13) and an [Anthropic API key](https://console.anthropic.com).

```bash
git clone <this repo> job-bot && cd job-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

cp .env.example .env                    # paste your ANTHROPIC_API_KEY
cp profile.example.yaml profile.yaml    # then replace with YOUR background
```

> **macOS note:** if `python3 -m venv` fails inside `ensurepip` (seen with
> Homebrew Python 3.14 on macOS 26.2, a libexpat mismatch), use uv's
> self-contained Python instead:
> `brew install uv && uv venv --python 3.13 .venv && uv pip install --python .venv -r requirements.txt`

**`profile.yaml` is the only source of truth the AI may use.** Write real
bullets for each job, list only skills you actually have, and put any metrics
under `extra_facts`. The AI can only use numbers that appear there.
`profile.yaml`, `.env`, `jobs.db`, `output/` and `.browser-profile/` are all
gitignored, so your personal data stays local.

## Smoke test

```bash
python -m unittest discover -s tests -t . -v     # 26 offline tests, no API key needed
python -m jobbot ping                            # checks your API key + model IDs
python -m jobbot check-boards                    # which company slugs in config.yaml work
```

Remove `BAD` slugs from `config.yaml` and add companies you like. Find a
company's slug from its careers URL: `job-boards.greenhouse.io/<slug>`,
`jobs.lever.co/<slug>`, `jobs.ashbyhq.com/<slug>`.

## Dashboard (local website)

Everything can be done from a local web page instead of the command line.

**Start it** (after the setup above), from a terminal:

```bash
cd job-bot                   # the project folder
source .venv/bin/activate
python -m jobbot web
```

Then open **http://localhost:8000** in your browser. Leave that terminal open
while you use the dashboard; press **Ctrl+C** in it to stop the server.

- Use another port with `python -m jobbot web --port 8080` (then open
  http://localhost:8080). Do this if you see "Address already in use".
- The server only listens on your own machine (127.0.0.1); nobody else on
  your network can open it.
- Closing the browser tab doesn't stop the server, and stopping the server
  doesn't lose anything: all data lives in `jobs.db` and `output/`.

The dashboard covers everything below:
prospects with score, reasons, concerns and the "check before submitting" list,
the resume PDF, copy buttons for the cover letter and screening answers, an
**Open application** button per job, **Pre-fill in automated browser**, and
Applied / Interview / Offer / Rejected / Skip buttons with notes. **Run job
search** shows live progress, and you get a macOS notification when a run ends.

### Browser extension (hosted)

Pre-fill in your own Chrome, also for jobs found via Himalayas and other job
sites: download it from **Settings → Browser extension**, load it unpacked, click
**Connect**. See [`extension/README.md`](extension/README.md).

### Tracking applications

Every application gets details (applied date, salary, contact, next step,
follow-up date, notes) and a timeline: status changes are logged
automatically and you can add entries like "recruiter screen went well".
Follow-ups that are due are highlighted. Applications you made outside
job-bot can be added with **+ Add application**, or from the CLI:

```bash
python -m jobbot add "Initech" "Senior SDET" --date 2026-09-01 --url https://... --salary "$130K"
python -m jobbot mark 42 interview --note "Onsite Thu"   # also logged on the timeline
```

## Daily use (CLI)

```bash
python -m jobbot run        # fetch + score + tailor (well under $1/day of API usage)
python -m jobbot review     # list packets, best first
python -m jobbot apply      # opens the best job's form, pre-filled
```

Each packet in `output/<id>-<company>-<title>/` contains:

| file | what |
|---|---|
| `REVIEW.md` | score, reasons, concerns, **checklist of things to verify** |
| `*_Resume.pdf` | tailored one-page resume |
| `*_Cover_Letter.pdf` / `.txt` | cover letter |
| `answers.md` | drafts for "why this role" style questions |

`apply` opens a Chrome window and fills name, email, phone, LinkedIn/GitHub,
resume and cover letter. Then it waits: fill in anything left (work
authorization, EEO, custom questions), **submit it yourself**, and answer `y`
in the terminal. If a page shows a human-verification check first, pass it and
press `r` to re-run the pre-fill.

| ATS | pre-fill |
|---|---|
| Greenhouse | works (opens the official embed form, which skips company-site redirects) |
| Lever | works |
| Ashby | fills, but Ashby's spam filter may reject submissions from an automated browser. Apply from your normal browser using the packet files. |

Other commands:

```bash
python -m jobbot apply 42                    # a specific job
python -m jobbot mark 42 applied             # record an application made outside `apply`
python -m jobbot mark 42 interview --note "recruiter call Tue"
python -m jobbot status                      # pipeline counts
python -m jobbot export                      # tracker.csv for Numbers/Sheets
```

## Job sources

All public APIs, no scraping or logins:

| kind | sources |
|---|---|
| company boards (listed in `config.yaml`) | Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee |
| keyword / feed search (any field) | [Himalayas](https://himalayas.app) remote jobs (one search per job title), [Jobicy](https://jobicy.com) (newest US remote jobs), Remotive |
| with a free key in `.env` (optional) | [The Muse](https://www.themuse.com/developers/api/v2/apps) (`MUSE_API_KEY`), [Adzuna](https://developer.adzuna.com/signup) (`ADZUNA_APP_ID`, `ADZUNA_APP_KEY`; short descriptions only) |

Aggregator listings keep their original link and are labeled "via Himalayas" /
"via Jobicy", as their terms ask. Before any paid scoring, queued jobs are
ranked for free against your profile, so the best matches are scored first and
the per-run cap (`max_score_per_run`) only defers the least relevant ones.

## Guardrails (enforced in code, not just the prompt)

- Company names, titles and dates come from `profile.yaml`, never from the model.
- Skills the model lists are filtered to your `skills` list.
- Numbers and well-known tools that aren't in your profile are flagged in `REVIEW.md`.
- Work-authorization, sponsorship, salary, EEO and legal questions are never answered.
- The bot never clicks submit. `daily_apply_limit` caps applications per day.
- Only public job-board APIs are used. No LinkedIn/Indeed automation (it violates
  their terms and gets accounts banned).

## How it works

| module | role |
|---|---|
| `jobbot/sources.py` | Greenhouse, Lever, Ashby and Remotive public APIs |
| `jobbot/filters.py` | free regex title/location filter before any paid call |
| `jobbot/score.py` | fit score 0-100 with Claude Haiku |
| `jobbot/tailor.py` | resume + cover letter with Claude Sonnet, then `validate()` guardrails |
| `jobbot/llm.py` | Anthropic Messages API via `requests`, JSON via structured outputs |
| `jobbot/render.py` | HTML -> PDF with Playwright |
| `jobbot/apply.py` | headed browser pre-fill, never submits |
| `jobbot/db.py` | SQLite tracker (`jobs.db`) |

## Tuning

Everything is in `config.yaml`: `min_score`, title include/exclude patterns,
per-run caps, company slugs, `provider` (claude or grok) and models. To run it
every morning, add a cron job for `python -m jobbot run`. Scoring and tailoring
are safe to automate; applying stays manual.
