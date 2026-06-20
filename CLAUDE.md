# CLAUDE.md

Repository for the **«Дневник Второй Мировой»** Telegram channel
([@ww2_dnevnik](https://t.me/ww2_dnevnik)). Every day it publishes what happened
in WWII exactly 85 years ago, with an archival photo.

## How it runs

A daily **Claude routine** (scheduled cloud session, Opus 4.8, max effort) runs
the skill in `.claude/skills/daily-post/`. The session:

1. runs `scripts/fetch_sources.py` to gather facts for "today − 85 years";
2. writes the post, photo caption and X text itself (this is the creative part —
   done by Claude, not by an external API);
3. runs `scripts/find_photo.py` to get de-duplicated Commons candidates, then
   **looks at the images** and picks the best one;
4. runs `scripts/publish.py` to post to Telegram (and optionally X);
5. commits the updated `state/history.json` so the next run remembers it.

Deterministic plumbing lives in the `ww2daily/` package; judgement (writing,
photo choice) is the model's. The full daily procedure and the writing rules are
in the skill — follow it when running the routine.

## Rubrics

Besides the daily post there are weekly rubrics, each its own routine and skill,
sharing this repo and `state/history.json`:

- `rubric-person` («Личность») — portrait of a person tied to the period (Tue, Sat);
- `rubric-photo` («Кадр недели») — one strong archival photo with its story (Thu);
- `weekly-digest` («Итог недели») — recap of the week, built from the week's posted
  history plus `scripts/fetch_week.py` (Sun).

Every published record carries a `kind` (`daily`/`person`/`photo`/`weekly`) and an
optional `subject` (e.g. the person's name), which power cross-rubric
de-duplication. Photo de-dup is by Commons `image_pageid` across all kinds.

## Conventions

- Python 3.11+. Dependencies in `requirements.txt` (kept minimal: `requests`,
  `beautifulsoup4`; `tweepy` only if X is enabled).
- All date math is anchored to `Europe/Moscow` in `ww2daily/dates.py`.
- Secrets come from environment variables (see `.env.example`); never commit them.
- `run/` holds per-run working files and is git-ignored.
- State (`state/history.json`) is the channel's memory and MUST be committed back
  after each successful post — it powers photo and topic de-duplication.
- `DRY_RUN=1` makes the pipeline print instead of posting; use it for testing.

## Setup / operations

See `README.md` for how to create the routine, set environment variables, the
network allowlist and the posting schedule.
