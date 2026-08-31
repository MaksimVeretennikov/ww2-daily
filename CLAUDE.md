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

Besides the morning daily post (09:00) there is an evening rubric every day at
20:00, run by a single second routine. Its skill `rubric-today` reads
`scripts/which_rubric.py` to pick today's rubric by Moscow weekday, then follows
the matching rubric skill. All share this repo and `state/history.json`:

- Mon `rubric-document` («Документ / Дневник») — a real order / communiqué / diary entry;
- Tue `rubric-weapon` («Оружие / Техника») — a recognizable tank/plane/ship/gun;
- Wed `rubric-perspectives` («Двумя глазами») — one event from Soviet and German sources;
- Thu `rubric-photo` («Кадр недели») — one strong archival photo with its story;
- Fri `rubric-numbers` («В цифрах») — one reliable striking statistic;
- Sat `rubric-person` («Личность») — portrait of a recognizable person of the period;
- Sun `weekly-digest` («Итог недели») — recap built from the week's posted history
  plus `scripts/fetch_week.py`.

Every record carries a `kind` (`daily`/`document`/`weapon`/`perspectives`/`photo`/
`numbers`/`person`/`weekly`) and an optional `subject` (person or weapon name),
powering cross-rubric de-duplication. Photo de-dup is by Commons `image_pageid`
across all kinds. `publish.py` refuses to post the same `kind` twice in one day.

## Daily poll

A third routine at 15:00 runs the `daily-poll` skill: one Telegram quiz-mode poll
(single correct answer + explanation) about the period the channel is currently
in. `scripts/poll_context.py` supplies the date, recent posts (~2 weeks) and
recent poll questions; `scripts/publish_poll.py` posts it, shuffles option order
so the answer's position is random, warns if the correct option is the longest
(the classic tell), and records it. Poll memory is `state/polls.json` (seeded once
from Airtable via `scripts/import_polls.py`). The diary "no looking ahead" rule
applies to polls too.

## Conventions

- Python 3.11+. Dependencies in `requirements.txt` (kept minimal: `requests`,
  `beautifulsoup4`; `tweepy` only if X is enabled).
- All date math is anchored to `Europe/Moscow` in `ww2daily/dates.py`.
- Secrets come from environment variables (see `.env.example`); never commit them.
- `run/` holds per-run working files and is git-ignored.
- State (`state/history.json`) is the channel's memory and MUST be committed back
  after each successful post — it powers photo and topic de-duplication. Only a
  photo that actually went out is recorded as used.
- Wikimedia rate-limits image downloads from the shared cloud egress IP (429).
  `publish.py` therefore falls back to letting Telegram fetch the Commons URL
  itself, and drops the italic photo-caption line if a post ends up text-only.
- `DRY_RUN=1` makes the pipeline print instead of posting; use it for testing.

## Setup / operations

See `README.md` for how to create the routine, set environment variables, the
network allowlist and the posting schedule.
