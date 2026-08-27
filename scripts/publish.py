#!/usr/bin/env python3
"""Final step of the daily run.

Reads run/draft.json (written by Claude: the composed Telegram caption, the X
text, the chosen image and a topic label), gets the image file, posts to
Telegram (and optionally X), then appends the record to state/history so the
photo and topic are never reused.

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
from ww2daily import buffer, commons, config, state, telegram, twitter, vk

DRAFT = os.path.join(_bootstrap.RUN_DIR, "draft.json")
CAND_JSON = os.path.join(_bootstrap.RUN_DIR, "candidates.json")
FINAL_IMG = os.path.join(_bootstrap.RUN_DIR, "final_image")


def _load(path: str) -> dict | list:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _resolve_image(chosen: dict) -> str | None:
    """Local image file to publish, or None if nothing could be fetched.

    Cheapest source first: the thumbnail find_photo.py already downloaded (and
    Claude already looked at), then a fresh download of the standard-width
    thumbnail, and only as a last resort the full-resolution original — the one
    Wikimedia throttles."""
    local = chosen.get("local_path")
    if local and os.path.exists(local):
        return local

    urls: list[str] = []
    for url in (commons.photo_url(chosen), chosen.get("image_url")):
        if url and url not in urls:
            urls.append(url)

    for url in urls:
        ext = os.path.splitext(url.split("?")[0])[1] or ".jpg"
        dest = FINAL_IMG + ext
        try:
            return commons.download(url, dest)
        except Exception as exc:
            print(f"Could not download {url[:90]}: {exc}")
    return None


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
        image_path = _resolve_image(chosen)
        if image_path is None:
            print("WARNING: could not fetch the chosen image — "
                  "posting text-only.")

    # --- publish ---
    if image_path:
        telegram.send_photo(image_path, caption)
    else:
        telegram.send_message(caption)  # text-only fallback

    # --- cross-post to X: prefer Buffer webhook (with the Commons image URL),
    # otherwise the X API directly; both are no-ops unless configured. A
    # failure here must never lose the Telegram post that already went out,
    # so cross-posting is best-effort. ---
    x_result = {"skipped": "no_text"}
    if draft.get("post_x"):
        # Prefer the standard-width thumbnail for X (full Commons originals
        # can exceed the platform's image size limit).
        image_url = commons.photo_url(chosen) if chosen else None
        try:
            if buffer.is_enabled():
                x_result = buffer.post(draft["post_x"], image_url)
            else:
                x_result = twitter.post(draft["post_x"], image_path)
        except Exception as exc:
            x_result = {"ok": False, "error": str(exc)}

    # --- cross-post to VK community (Russian text + the same photo file) ---
    try:
        vk_result = vk.post(caption, image_path) if vk.is_enabled() else {"skipped": "vk_disabled"}
    except Exception as exc:
        vk_result = {"ok": False, "error": str(exc)}

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
    print("VK result:", vk_result)


if __name__ == "__main__":
    main()
