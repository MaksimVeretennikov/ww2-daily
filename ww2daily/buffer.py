"""Cross-post to X via the user's Buffer, by calling a small make.com webhook.

Why a webhook and not Buffer's API directly: Buffer's media-capable REST API is
closed to new app registrations, and the new GraphQL beta can't attach media
yet. make.com, however, holds a grandfathered Buffer app, so the reliable free
path for "X post with photo" is a tiny make scenario:

    Webhook  ->  Buffer: Create Status (text + media.picture = image_url)

This module just POSTs {"text": ..., "image_url": ...} to that webhook. The image
is a public Wikimedia Commons URL, so no extra hosting is needed.
"""

from . import config, http


def is_enabled() -> bool:
    return bool(config.BUFFER_WEBHOOK_URL)


def post(text: str, image_url: str | None = None) -> dict:
    if not is_enabled():
        return {"ok": False, "skipped": "buffer_webhook_not_configured"}
    if not text:
        return {"ok": False, "skipped": "no_text"}

    payload = {"text": text, "image_url": image_url or ""}
    if config.DRY_RUN:
        print(f"[DRY_RUN] Buffer webhook -> {config.BUFFER_WEBHOOK_URL}\n{payload}")
        return {"ok": True, "dry_run": True}

    resp = http.session().post(config.BUFFER_WEBHOOK_URL, json=payload,
                               timeout=config.HTTP_TIMEOUT)
    resp.raise_for_status()
    return {"ok": True, "status": resp.status_code}
