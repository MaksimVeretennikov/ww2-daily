#!/usr/bin/env python3
"""Context builder for the weekly digest «Итог недели».

Covers the 7 days ending on today−85 (Moscow). For each day it gathers source
facts, and it also pulls what the channel actually posted that week from
state/history.json, so the digest is consistent with the week's published posts.
Writes run/week.json.
"""

import datetime
import json
import os

import _bootstrap  # noqa: F401
from ww2daily import dates, sources, state

WEEK_PATH = os.path.join(_bootstrap.RUN_DIR, "week.json")
WINDOW_DAYS = 7


def main() -> None:
    end = dates.target_date()
    start = end - datetime.timedelta(days=WINDOW_DAYS - 1)

    days = []
    for offset in range(WINDOW_DAYS - 1, -1, -1):
        d = dates.describe(end - datetime.timedelta(days=offset))
        gathered = sources.gather(d)
        days.append({
            "date": d,
            "combined": gathered["combined"],
        })

    hist = state.load()
    posted = state.posts_in_ww2_window(start.strftime("%Y-%m-%d"),
                                       end.strftime("%Y-%m-%d"), hist)

    payload = {
        "window": {
            "start": start.strftime("%Y-%m-%d"),
            "end": end.strftime("%Y-%m-%d"),
            "start_human": dates.describe(start)["ru_human"],
            "end_human": dates.describe(end)["ru_human"],
        },
        "days": days,
        "posted_this_week": posted,
        "used_pageids": sorted(state.used_pageids(hist)),
    }
    with open(WEEK_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    print(f"Week: {payload['window']['start_human']} — "
          f"{payload['window']['end_human']}")
    print(f"Days with material: "
          f"{sum(1 for x in days if x['combined'])}/{WINDOW_DAYS}")
    print(f"Posts published this week: {len(posted)}")
    print(f"\nWrote {WEEK_PATH}")


if __name__ == "__main__":
    main()
