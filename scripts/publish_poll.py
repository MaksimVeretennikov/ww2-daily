#!/usr/bin/env python3
"""Publish the daily quiz poll to Telegram.

Reads run/poll.json (written by Claude), shuffles the options so the correct
answer's position is random, sanity-checks the "longest option is the answer"
tell, posts a quiz-mode poll, and records it so future polls don't repeat.

poll.json schema:
{
  "ww2_date": "1941-06-21",
  "theme": "Operation Barbarossa preparations",
  "question": "<= 300 chars>",
  "options": ["...", "...", "...", "..."],   // 2-10, each <= 100 chars
  "correct_index": 2,
  "explanation": "<= 200 chars>"
}
"""

import argparse
import datetime
import json
import os
import random

import _bootstrap  # noqa: F401
from ww2daily import state, telegram

POLL = os.path.join(_bootstrap.RUN_DIR, "poll.json")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--poll", default=POLL)
    ap.add_argument("--force", action="store_true",
                    help="post even if a poll already exists for today")
    args = ap.parse_args()

    with open(args.poll, encoding="utf-8") as fh:
        poll = json.load(fh)

    today = datetime.date.today().isoformat()
    polls = state.load_polls()
    if any(p.get("date") == today for p in polls.get("polls", [])) and not args.force:
        raise SystemExit(f"A poll already exists for {today}. "
                         f"Skipping to avoid a duplicate (use --force).")

    options = list(poll["options"])
    correct_text = options[poll["correct_index"]]

    # Randomise position so the answer is never in a predictable slot.
    random.shuffle(options)
    correct_index = options.index(correct_text)

    # Guard against the classic tell: the longest option being the answer.
    lengths = sorted(len(o) for o in options)
    if len(correct_text) == lengths[-1] and lengths[-1] - lengths[-2] > 12:
        print("WARNING: the correct option is noticeably the longest — "
              "rebalance option lengths so the answer isn't guessable.")

    telegram.send_poll(
        question=poll["question"],
        options=options,
        correct_option_id=correct_index,
        explanation=poll.get("explanation"),
    )

    record = {
        "date": today,
        "ww2_date": poll.get("ww2_date"),
        "theme": poll.get("theme"),
        "question": poll["question"],
        "options": options,
        "correct_index": correct_index,
        "explanation": poll.get("explanation", ""),
    }
    from ww2daily import config
    if not config.DRY_RUN:
        state.append_poll(record)
        print("Recorded poll in", config.POLLS_PATH)
    else:
        print("[DRY_RUN] would record:", json.dumps(record, ensure_ascii=False))


if __name__ == "__main__":
    main()
