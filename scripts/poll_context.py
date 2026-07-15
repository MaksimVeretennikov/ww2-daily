#!/usr/bin/env python3
"""Context builder for the daily quiz poll.

Gives Claude: the channel's current date (today−85), the day's events, what the
channel posted over the last ~2 weeks (so a poll can riff on recent themes from a
fresh angle), and recent poll questions (so it doesn't repeat itself). Writes
run/poll_context.json.
"""

import datetime
import json
import os

import _bootstrap  # noqa: F401
from ww2daily import dates, sources, state

CTX_PATH = os.path.join(_bootstrap.RUN_DIR, "poll_context.json")
RECENT_POST_DAYS = 14


def main() -> None:
    d = dates.target()
    gathered = sources.gather(d)

    cutoff = (datetime.date.today() -
              datetime.timedelta(days=RECENT_POST_DAYS)).isoformat()
    posts = state.load().get("posts", [])
    recent_posts = [
        {
            "date_posted": p.get("date_posted"),
            "ww2_date": p.get("ww2_date"),
            "kind": state.kind_of(p),
            "topic": p.get("topic"),
            "subject": p.get("subject"),
        }
        for p in posts
        if (p.get("date_posted") or "") >= cutoff
    ]

    # The morning daily post for the SAME channel date. The poll must not test
    # facts already stated there — so give the model its full text, not just a
    # label, and flag it explicitly. (This is the overlap that used to slip
    # through: the poll session only ever saw the short `topic` before.)
    todays_morning_post = next(
        (
            {
                "ww2_date": p.get("ww2_date"),
                "topic": p.get("topic"),
                "subject": p.get("subject"),
                "telegram_caption": p.get("telegram_caption"),
                "_note": ("Уже опубликовано СЕГОДНЯ утром. НЕ делай опрос про факт "
                          "или ответ, которые уже названы в этом тексте — тему "
                          "можно затронуть, но проверяемый факт должен быть новым."),
            }
            for p in posts
            if state.kind_of(p) == "daily" and p.get("ww2_date") == d["iso"]
        ),
        None,
    )

    recent_polls = [
        {
            "date": q.get("date") or q.get("date_posted"),
            "question": q.get("question"),
            "theme": q.get("theme") or q.get("topic"),
        }
        for q in state.recent_polls()
    ]

    payload = {
        "date": d,
        "events_today": gathered["combined"],
        "todays_morning_post": todays_morning_post,
        "recent_posts": recent_posts,
        "recent_polls": recent_polls,
    }
    with open(CTX_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    print(f"Channel date: {d['ru_human']} ({d['iso']})")
    print(f"Recent posts (≤{RECENT_POST_DAYS}d): {len(recent_posts)}")
    print("Today's morning post:",
          "found — poll must avoid its facts" if todays_morning_post else "none yet")
    print(f"Known polls for anti-repeat: {len(recent_polls)}")
    print(f"\nWrote {CTX_PATH}")


if __name__ == "__main__":
    main()
