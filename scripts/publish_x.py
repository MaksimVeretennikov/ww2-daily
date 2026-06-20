#!/usr/bin/env python3
"""Send ONLY the X cross-post (Buffer webhook), without touching Telegram.

Two uses:
  1. Make's custom webhook shows "Data structure not determined yet" until it
     receives one request — run this once to teach it the {text, image_url} shape.
  2. Test the X/Buffer path end to end without publishing to the Telegram channel.

Usage:
  python scripts/publish_x.py --text "Test post" --image-url "https://…/photo.jpg"
  python scripts/publish_x.py            # falls back to run/draft.json + candidates
"""

import argparse
import json
import os

import _bootstrap  # noqa: F401
from ww2daily import buffer, twitter

DRAFT = os.path.join(_bootstrap.RUN_DIR, "draft.json")
CAND = os.path.join(_bootstrap.RUN_DIR, "candidates.json")


def _from_draft() -> tuple[str | None, str | None]:
    if not os.path.exists(DRAFT):
        return None, None
    with open(DRAFT, encoding="utf-8") as fh:
        draft = json.load(fh)
    text = draft.get("post_x")
    image_url = None
    idx = draft.get("image_index", -1)
    if idx is not None and idx >= 0 and os.path.exists(CAND):
        with open(CAND, encoding="utf-8") as fh:
            cands = json.load(fh)
        chosen = next((c for c in cands if c.get("index") == idx), None)
        if chosen:
            image_url = chosen.get("thumb_url") or chosen.get("image_url")
    return text, image_url


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text")
    ap.add_argument("--image-url")
    args = ap.parse_args()

    text, image_url = args.text, args.image_url
    if not text:
        text, image_url = _from_draft()
    if not text:
        raise SystemExit("No text. Pass --text or write run/draft.json with post_x.")

    if buffer.is_enabled():
        print("Buffer webhook:", buffer.post(text, image_url))
    elif twitter.is_enabled():
        print("NOTE: X API path uploads a local file, not a URL — use the full "
              "pipeline (publish.py) to test it. Nothing sent.")
    else:
        raise SystemExit("X is not configured (set BUFFER_WEBHOOK_URL or X_* keys).")


if __name__ == "__main__":
    main()
