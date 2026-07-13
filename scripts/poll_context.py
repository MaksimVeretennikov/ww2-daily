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
# Posts this fresh (including today's morning post) are off-limits as the
# source of a poll's answer — subscribers just read them.
FRESH_POST_DAYS = 3


def main() -> None:
    d = dates.target()
    gathered = sources.gather(d)

    today = datetime.date.today()
    cutoff = (today - datetime.timedelta(days=RECENT_POST_DAYS)).isoformat()
    fresh_cutoff = (today - datetime.timedelta(days=FRESH_POST_DAYS)).isoformat()
    recent_posts = [
        {
            "date_posted": p.get("date_posted"),
            "ww2_date": p.get("ww2_date"),
            "kind": state.kind_of(p),
            "topic": p.get("topic"),
            "subject": p.get("subject"),
            "too_fresh_for_poll": (p.get("date_posted") or "") >= fresh_cutoff,
        }
        for p in state.load().get("posts", [])
        if (p.get("date_posted") or "") >= cutoff
    ]

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
        "recent_posts": recent_posts,
        "recent_polls": recent_polls,
    }
    with open(CTX_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    print(f"Channel date: {d['ru_human']} ({d['iso']})")
    n_fresh = sum(1 for p in recent_posts if p["too_fresh_for_poll"])
    print(f"Recent posts (≤{RECENT_POST_DAYS}d): {len(recent_posts)}, "
          f"of which too fresh to source a poll answer (≤{FRESH_POST_DAYS}d): "
          f"{n_fresh}")
    print(f"Known polls for anti-repeat: {len(recent_polls)}")
    print(f"\nWrote {CTX_PATH}")


if __name__ == "__main__":
    main()
