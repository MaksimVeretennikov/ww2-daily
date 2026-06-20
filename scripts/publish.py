#!/usr/bin/env python3
"""Final step of the daily run.

Reads run/draft.json (written by Claude: the composed Telegram caption, the X
text, the chosen image and a topic label), downloads the full-resolution image,
posts to Telegram (and optionally X), then appends the record to state/history
so the photo and topic are never reused.

draft.json schema:
{
  "ww2_date": "1941-06-17",
  "topic": "Hitler fixes the date for Barbarossa",
  "image_index": 0,            // index into run/candidates.json, or -1 for none
  "telegram_caption": "<full HTML message, <= 1024 chars>",
  "post_x": "<= 260 chars english, or empty to skip X>"
}
"""

import argparse
import datetime
import json
import os

import _bootstrap  # noqa: F401
from ww2daily import commons, config, state, telegram, twitter

DRAFT = os.path.join(_bootstrap.RUN_DIR, "draft.json")
CAND_JSON = os.path.join(_bootstrap.RUN_DIR, "candidates.json")
FINAL_IMG = os.path.join(_bootstrap.RUN_DIR, "final_image")


def _load(path: str) -> dict | list:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--draft", default=DRAFT)
    ap.add_argument("--force", action="store_true",
                    help="post even if a record of this kind already exists today")
    args = ap.parse_args()

    draft = _load(args.draft)
    caption = draft["telegram_caption"].strip()
    idx = draft.get("image_index", -1)
    kind = draft.get("kind", "daily")

    # Idempotency guard: never publish the same kind twice on the same calendar
    # day (protects against a manual run colliding with the scheduled one).
    today = datetime.date.today().isoformat()
    already = [p for p in state.load().get("posts", [])
               if p.get("date_posted") == today and state.kind_of(p) == kind]
    if already and not args.force:
        raise SystemExit(
            f"A '{kind}' post already exists for {today} "
            f"(subject: {already[-1].get('subject') or already[-1].get('topic')}). "
            f"Skipping to avoid a duplicate. Re-run with --force to override."
        )

    chosen = None
    image_path = None
    if idx is not None and idx >= 0:
        candidates = _load(CAND_JSON)
        chosen = next((c for c in candidates if c.get("index") == idx), None)
        if chosen is None:
            raise SystemExit(f"image_index {idx} not found in candidates.json")
        url = chosen.get("image_url") or chosen.get("thumb_url")
        ext = os.path.splitext(url.split("?")[0])[1] or ".jpg"
        image_path = FINAL_IMG + ext
        try:
            commons.download(url, image_path)
        except Exception:
            image_path = chosen.get("local_path")  # fall back to thumbnail

    # --- publish ---
    if image_path:
        telegram.send_photo(image_path, caption)
    else:
        telegram.send_message(caption)  # text-only fallback

    x_result = {"skipped": "no_text"}
    if draft.get("post_x"):
        x_result = twitter.post(draft["post_x"], image_path)

    # --- remember ---
    record = {
        "date_posted": datetime.date.today().isoformat(),
        "kind": draft.get("kind", "daily"),
        "subject": draft.get("subject"),
        "ww2_date": draft.get("ww2_date"),
        "topic": draft.get("topic"),
        "telegram_caption": caption,
        "post_x": draft.get("post_x", ""),
        "image_pageid": chosen.get("pageid") if chosen else None,
        "image_title": chosen.get("title") if chosen else None,
        "image_url": chosen.get("image_url") if chosen else None,
    }
    if not config.DRY_RUN:
        state.append(record)
        print("Appended record to", config.STATE_PATH)
    else:
        print("[DRY_RUN] would append:", json.dumps(record, ensure_ascii=False))

    print("Telegram caption length:", len(caption))
    print("X result:", x_result)


if __name__ == "__main__":
    main()
