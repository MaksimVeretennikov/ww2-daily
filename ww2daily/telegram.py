"""Telegram Bot API publishing.

We post the photo and the text as a single message: a photo with an HTML
caption. The caption is `<i>{photo_caption}</i>` + blank line + post body, and
must stay within Telegram's 1024-character caption limit."""

from . import config, http


def build_caption(photo_caption: str, post_body: str) -> str:
    photo_caption = (photo_caption or "").strip()
    post_body = (post_body or "").strip()
    if photo_caption:
        return f"<i>{photo_caption}</i>\n\n{post_body}"
    return post_body


def _api(method: str) -> str:
    return f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/{method}"


def send_photo(photo_path: str, caption: str,
               channel: str | None = None) -> dict:
    """Send a local photo file with an HTML caption to the channel."""
    channel = channel or config.TELEGRAM_CHANNEL
    if len(caption) > config.TG_CAPTION_HARD_CAP:
        raise ValueError(
            f"Caption is {len(caption)} chars, over Telegram's "
            f"{config.TG_CAPTION_HARD_CAP} limit. Shorten the post or caption."
        )
    if config.DRY_RUN:
        print(f"[DRY_RUN] sendPhoto -> {channel}\nphoto: {photo_path}\n"
              f"caption ({len(caption)} chars):\n{caption}")
        return {"ok": True, "dry_run": True}

    with open(photo_path, "rb") as fh:
        resp = http.session().post(
            _api("sendPhoto"),
            data={"chat_id": channel, "caption": caption, "parse_mode": "HTML"},
            files={"photo": fh},
            timeout=config.HTTP_TIMEOUT,
        )
    resp.raise_for_status()
    payload = resp.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram error: {payload}")
    return payload


def send_message(text: str, channel: str | None = None) -> dict:
    """Plain text fallback (e.g. if no suitable photo was found)."""
    channel = channel or config.TELEGRAM_CHANNEL
    if config.DRY_RUN:
        print(f"[DRY_RUN] sendMessage -> {channel}\n{text}")
        return {"ok": True, "dry_run": True}
    resp = http.session().post(
        _api("sendMessage"),
        data={"chat_id": channel, "text": text, "parse_mode": "HTML"},
        timeout=config.HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram error: {payload}")
    return payload
