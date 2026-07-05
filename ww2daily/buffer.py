"""Cross-post to X via the user's Buffer, by calling a small make.com webhook.

Why a webhook and not Buffer's API directly: Buffer's media-capable REST API is
closed to new app registrations, and the new GraphQL beta can't attach media
yet. make.com, however, holds a grandfathered Buffer app, so the reliable free
path for "X post with photo" is a tiny make scenario:

    Webhook  ->  Buffer: Create Status (text + media.picture = image_url)

This module just POSTs {"text": ..., "image_url": ...} to that webhook. Buffer
then fetches that URL itself and attaches it to the X post — so the URL must be
publicly fetchable *by Buffer's fetcher* and return real image bytes.
"""

from urllib.parse import quote

from . import config, http


def _image_proxy(url: str) -> str:
    """Re-serve the image through the free wsrv.nl CDN as a plain ``.jpg``.

    Two things break Buffer's own fetch of a raw Commons URL:

    * Wikimedia blocks Buffer's fetcher by User-Agent (``upload.wikimedia.org``
      returns 403 to bot/empty UAs, 200 only to browser-like ones), so Buffer
      reports "The provided image does not appear to be valid".
    * Buffer/make also sniff the URL and reject links that don't look like a
      direct image file ("Invalid URL in parameter 'picture'").

    wsrv.nl downloads the source server-side (with its own UA) and serves a clean
    JPEG from its CDN. We put ``/image.jpg`` in the path so the URL ends in a
    real image extension, force ``output=jpg`` and cap the width so the result
    stays well under X's 5 MB image limit.
    """
    if not url:
        return url
    bare = url.split("://", 1)[-1]  # wsrv adds the scheme itself
    return (f"https://wsrv.nl/image.jpg?url={quote(bare, safe='')}"
            f"&output=jpg&w=1600&q=85")


def _warm(url: str, attempts: int = 2) -> bool:
    """Fetch the proxied URL ourselves so it is a warm CDN cache HIT for Buffer,
    and confirm it really returns image bytes.

    Buffer's fetch of a *cold* wsrv URL can time out while wsrv pulls and
    reprocesses the original from Wikimedia — that surfaces as the intermittent
    "image does not appear to be valid" 400. Warming turns Buffer's fetch into a
    fast cache HIT and lets us detect a genuinely broken image here (and fall
    back to a text-only post) instead of letting Buffer reject the whole update.
    """
    for _ in range(max(1, attempts)):
        try:
            resp = http.get(url)
            ctype = resp.headers.get("Content-Type", "")
            if resp.status_code == 200 and ctype.startswith("image/") and resp.content:
                return True
        except Exception:
            pass
    return False


def is_enabled() -> bool:
    return bool(config.BUFFER_WEBHOOK_URL)


def post(text: str, image_url: str | None = None) -> dict:
    if not is_enabled():
        return {"ok": False, "skipped": "buffer_webhook_not_configured"}
    if not text:
        return {"ok": False, "skipped": "no_text"}

    proxied = ""
    if image_url:
        proxied = _image_proxy(image_url)
        # Warm + validate the proxy before handing the URL to Buffer. If it can't
        # serve a valid image, drop it and post text-only rather than letting the
        # whole X cross-post fail with a 400.
        if not config.DRY_RUN and not _warm(proxied):
            proxied = ""

    payload = {"text": text, "image_url": proxied}
    if config.DRY_RUN:
        print(f"[DRY_RUN] Buffer webhook -> {config.BUFFER_WEBHOOK_URL}\n{payload}")
        return {"ok": True, "dry_run": True}

    # A webhook/Buffer error must not crash the daily run (Telegram has already
    # posted and history still needs saving), so report it instead of raising.
    try:
        resp = http.session().post(config.BUFFER_WEBHOOK_URL, json=payload,
                                   timeout=config.HTTP_TIMEOUT)
        resp.raise_for_status()
    except Exception as exc:
        return {"ok": False, "error": str(exc), "image": bool(proxied)}
    return {"ok": True, "status": resp.status_code, "image": bool(proxied)}
