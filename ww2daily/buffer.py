"""Cross-post to X via the user's Buffer, by calling a small make.com webhook.

Why a webhook and not Buffer's API directly: Buffer's media-capable REST API is
closed to new app registrations, and the new GraphQL beta can't attach media
yet. make.com, however, holds a grandfathered Buffer app, so the reliable free
path for "X post with photo" is a tiny make scenario:

    Webhook  ->  Buffer: Create Status (text + media.picture = image_url)

This module just POSTs {"text": ..., "image_url": ...} to that webhook. The image
is a public Wikimedia Commons URL, so no extra hosting is needed.
"""

from urllib.parse import quote

from . import config, http


def _image_proxy(url: str) -> str:
    """Re-serve the image through the free wsrv.nl CDN.

    Buffer fetches the image URL itself, and Wikimedia blocks Buffer's fetcher
    (hence "image not valid"). wsrv.nl downloads the source server-side and
    serves Buffer a clean JPEG from its own CDN — no Dropbox/hosting needed.
    """
    if not url:
        return url
    bare = url.split("://", 1)[-1]  # wsrv adds the scheme itself
    return f"https://wsrv.nl/?url={quote(bare, safe='')}&output=jpg&w=1600"


def is_enabled() -> bool:
    return bool(config.BUFFER_WEBHOOK_URL)


def post(text: str, image_url: str | None = None) -> dict:
    if not is_enabled():
        return {"ok": False, "skipped": "buffer_webhook_not_configured"}
    if not text:
        return {"ok": False, "skipped": "no_text"}

    payload = {"text": text, "image_url": _image_proxy(image_url) if image_url else ""}
    if config.DRY_RUN:
        print(f"[DRY_RUN] Buffer webhook -> {config.BUFFER_WEBHOOK_URL}\n{payload}")
        return {"ok": True, "dry_run": True}

    resp = http.session().post(config.BUFFER_WEBHOOK_URL, json=payload,
                               timeout=config.HTTP_TIMEOUT)
    resp.raise_for_status()
    return {"ok": True, "status": resp.status_code}
