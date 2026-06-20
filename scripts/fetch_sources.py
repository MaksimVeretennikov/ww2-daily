#!/usr/bin/env python3
"""Step 1 of the daily run.

Computes the target date (today minus 85 years, Moscow time), gathers facts
from every source, and writes run/facts.json together with the recent-history
context Claude needs to avoid repeating topics. Also prints a readable summary.
"""

import json
import os

import _bootstrap  # noqa: F401  (sets up sys.path + run/ dir)
from ww2daily import dates, sources, state

FACTS_PATH = os.path.join(_bootstrap.RUN_DIR, "facts.json")


def main() -> None:
    d = dates.target()
    gathered = sources.gather(d)
    hist = state.load()

    payload = {
        "date": d,
        "sources": gathered["sources"],
        "combined": gathered["combined"],
        "history_digest": state.context_digest(data=hist),
        "used_pageids": sorted(state.used_pageids(hist)),
        "recent_posts": state.recent(data=hist),
        "featured_people": sorted(state.featured_subjects("person", hist)),
        "featured": state.featured_by_kind(hist),
    }
    with open(FACTS_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    print(f"Target date: {d['ru_human']} ({d['iso']})")
    print(f"Sources with material: "
          f"{[k for k, v in gathered['sources'].items() if v]}")
    print(f"Combined facts length: {len(gathered['combined'])} chars")
    print(f"History: {len(payload['recent_posts'])} recent posts, "
          f"{len(payload['used_pageids'])} used photos")
    print(f"\nWrote {FACTS_PATH}")
    if not gathered["combined"]:
        print("\nWARNING: no source returned material for this date.")


if __name__ == "__main__":
    main()
