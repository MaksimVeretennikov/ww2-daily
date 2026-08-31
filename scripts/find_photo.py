#!/usr/bin/env python3
"""Step 3 of the daily run (after Claude has written the draft + image queries).

Queries Wikimedia Commons with Claude's image/category prompts, filters out
already-used and post-war images, downloads thumbnails of the survivors into
run/candidates/, and writes run/candidates.json. Claude then looks at the
thumbnails and picks the best fit.

Usage:
  python scripts/find_photo.py --image-prompt "Narvik battle 1940 ship" \
      [--category-prompt "Battle of Narvik 1940"]
"""

import argparse
import json
import os

import _bootstrap  # noqa: F401
from ww2daily import commons, http, state

CAND_DIR = os.path.join(_bootstrap.RUN_DIR, "candidates")
CAND_JSON = os.path.join(_bootstrap.RUN_DIR, "candidates.json")


def _fetch_preview(cand: dict) -> None:
    """Download the candidate's thumbnail into run/candidates/ so Claude can
    look at it. Records the failure instead of raising: one refused preview
    must not cost the run its other candidates."""
    ext = os.path.splitext(cand["thumb_url"].split("?")[0])[1] or ".jpg"
    local = os.path.join(CAND_DIR, f"cand_{cand['index']}{ext}")
    try:
        commons.download(cand["thumb_url"], local)
        cand["local_path"] = local
        cand.pop("download_error", None)
    except Exception as exc:
        cand["local_path"] = None
        cand["download_error"] = str(exc)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image-prompt", required=True)
    ap.add_argument("--category-prompt", default=None)
    args = ap.parse_args()

    os.makedirs(CAND_DIR, exist_ok=True)
    used = state.used_pageids()
    cands = commons.find_candidates(args.image_prompt, args.category_prompt, used)

    for i, c in enumerate(cands):
        c["index"] = i
        _fetch_preview(c)

    # Wikimedia throttles the shared egress IP of cloud sessions in bursts, so
    # previews it refused a moment ago often arrive on a second pass — and a
    # preview Claude cannot look at is a photo chosen blind.
    missing = [c for c in cands if not c.get("local_path")]
    if missing:
        print(f"Retrying {len(missing)} preview(s) Wikimedia refused…")
        http.reset_budget()
        for c in missing:
            _fetch_preview(c)

    with open(CAND_JSON, "w", encoding="utf-8") as fh:
        json.dump(cands, fh, ensure_ascii=False, indent=2)

    print(f"Found {len(cands)} candidate(s) (excluding {len(used)} used).")
    for c in cands:
        print(f"  [{c['index']}] {c['title']} "
              f"({c.get('year')}) -> {c.get('local_path')}")
        if c.get("description"):
            print(f"       {c['description'][:120]}")
    print(f"\nWrote {CAND_JSON}")
    if not cands:
        print("\nWARNING: no fresh candidates. Broaden the image prompt and retry.")
    elif all(not c.get("local_path") for c in cands):
        print("\nWARNING: Wikimedia refused every preview (rate limiting), so "
              "there is nothing to look at. Pick by title/description and "
              "publish anyway: publish.py falls back to letting Telegram fetch "
              "the file from Commons itself.")


if __name__ == "__main__":
    main()
