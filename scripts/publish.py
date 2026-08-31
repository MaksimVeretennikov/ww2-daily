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
import re

import _bootstrap  # noqa: F401
from ww2daily import buffer, commons, config, state, telegram, twitter, vk

DRAFT = os.path.join(_bootstrap.RUN_DIR, "draft.json")
CAND_JSON = os.path.join(_bootstrap.RUN_DIR, "candidates.json")
FINAL_IMG = os.path.join(_bootstrap.RUN_DIR, "final_image")


def _load(path: str) -> dict | list:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


_PHOTO_CAPTION_RE = re.compile(r"\A\s*<i>.*?</i>\s*\n+", re.S)


def _without_photo_caption(caption: str) -> str:
    """The message minus its opening `<i>…</i>` line.

    That line describes the picture, so a post that goes out without one must
    not keep it — a caption for a photo nobody can see reads as a bug."""
    return _PHOTO_CAPTION_RE.sub("", caption, count=1).strip()


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


def _remote_urls(chosen: dict | None) -> list[str]:
    """Commons URLs to offer Telegram, in the order worth trying: the standard
    thumbnail, then a narrower one for files too big to fetch by URL."""
    if not chosen:
        return []
    urls = [u for u in (commons.photo_url(chosen),) if u]
    try:
        smaller = commons.thumb_url(chosen["title"], config.PHOTO_FALLBACK_WIDTH)
    except Exception as exc:
        print("Could not ask Commons for a smaller thumbnail:", exc)
        smaller = None
    if smaller and smaller not in urls:
        urls.append(smaller)
    return urls


def _send_to_telegram(caption: str, image_path: str | None,
                      chosen: dict | None) -> tuple[str, bool]:
    """Publish to Telegram, keeping the photo if there is any way to send one.

    Returns the text actually posted and whether it carried the photo. When our
    own download was throttled we hand Telegram the Commons URL and let its
    servers fetch the file — they are not the ones Wikimedia is rate-limiting.
    Only a refusal from Telegram (as opposed to a network failure, after which
    we cannot know whether the message went out) falls through to the next
    option, so a lost photo can never cost the channel a duplicate post."""
    if image_path:
        telegram.send_photo(image_path, caption)
        return caption, True

    for url in _remote_urls(chosen):
        try:
            telegram.send_photo(url, caption)
            print("Photo sent by URL — Telegram fetched it from Commons.")
            return caption, True
        except telegram.TelegramRejected as exc:
            print(f"Telegram refused to fetch {url[:90]}: {exc}")

    text = _without_photo_caption(caption)
    telegram.send_message(text)
    return text, False


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
            print("WARNING: could not download the chosen image — "
                  "asking Telegram to fetch it from Commons instead.")

    # --- publish ---
    caption, photo_sent = _send_to_telegram(caption, image_path, chosen)
    if chosen and not photo_sent:
        print("WARNING: the post went out text-only; the chosen photo stays "
              "unused and free for a later post.")

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

    # --- cross-post to VK community (Russian text + the same photo file).
    # VK needs the bytes, so a photo Telegram fetched by URL cannot go there:
    # in that case VK gets the text without the photo caption line. ---
    vk_text = caption if image_path else _without_photo_caption(caption)
    try:
        vk_result = vk.post(vk_text, image_path) if vk.is_enabled() \
            else {"skipped": "vk_disabled"}
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
        # Only a photo that actually went out counts as used: a candidate we
        # failed to send must stay available for a future post.
        "image_pageid": chosen.get("pageid") if photo_sent else None,
        "image_title": chosen.get("title") if photo_sent else None,
        "image_url": chosen.get("image_url") if photo_sent else None,
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
