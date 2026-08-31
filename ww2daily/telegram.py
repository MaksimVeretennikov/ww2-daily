"""Telegram Bot API publishing.

We post the photo and the text as a single message: a photo with an HTML
caption. The caption is `<i>{photo_caption}</i>` + blank line + post body, and
must stay within Telegram's 1024-character caption limit."""

from . import config, http


class TelegramRejected(RuntimeError):
    """Telegram received the request and refused it.

    Distinct from a network failure, where we cannot tell whether the message
    went out: only a rejection is safe to recover from by sending something
    else instead."""


def _result(resp) -> dict:
    """The API payload, or TelegramRejected if Telegram refused the request."""
    if 400 <= resp.status_code < 500:
        raise TelegramRejected(f"HTTP {resp.status_code}: {resp.text[:300]}")
    resp.raise_for_status()
    payload = resp.json()
    if not payload.get("ok"):
        raise TelegramRejected(f"Telegram error: {payload}")
    return payload


def build_caption(photo_caption: str, post_body: str) -> str:
    photo_caption = (photo_caption or "").strip()
    post_body = (post_body or "").strip()
    if photo_caption:
        return f"<i>{photo_caption}</i>\n\n{post_body}"
    return post_body


def _api(method: str) -> str:
    return f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/{method}"


def send_photo(photo: str, caption: str,
               channel: str | None = None) -> dict:
    """Send a photo with an HTML caption: a local file, or an http(s) URL.

    Passing a URL hands the download to Telegram's own servers — which is how a
    post keeps its picture when Wikimedia is throttling our egress IP."""
    channel = channel or config.TELEGRAM_CHANNEL
    if len(caption) > config.TG_CAPTION_HARD_CAP:
        raise ValueError(
            f"Caption is {len(caption)} chars, over Telegram's "
            f"{config.TG_CAPTION_HARD_CAP} limit. Shorten the post or caption."
        )
    if config.DRY_RUN:
        print(f"[DRY_RUN] sendPhoto -> {channel}\nphoto: {photo}\n"
              f"caption ({len(caption)} chars):\n{caption}")
        return {"ok": True, "dry_run": True}

    data = {"chat_id": channel, "caption": caption, "parse_mode": "HTML"}
    if photo.startswith(("http://", "https://")):
        resp = http.session().post(
            _api("sendPhoto"),
            data={**data, "photo": photo},
            timeout=config.HTTP_TIMEOUT,
        )
    else:
        with open(photo, "rb") as fh:
            resp = http.session().post(
                _api("sendPhoto"),
                data=data,
                files={"photo": fh},
                timeout=config.HTTP_TIMEOUT,
            )
    return _result(resp)


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
    return _result(resp)


def send_poll(question: str, options: list[str], correct_option_id: int,
              explanation: str | None = None, channel: str | None = None,
              is_anonymous: bool = True) -> dict:
    """Send a quiz-mode poll (one correct answer + explanation)."""
    import json as _json

    channel = channel or config.TELEGRAM_CHANNEL
    if len(question) > config.POLL_QUESTION_MAX:
        raise ValueError(f"Poll question is {len(question)} chars, over "
                         f"{config.POLL_QUESTION_MAX}.")
    if not 2 <= len(options) <= 10:
        raise ValueError("A poll needs between 2 and 10 options.")
    for o in options:
        if len(o) > config.POLL_OPTION_MAX:
            raise ValueError(f"Option '{o[:30]}…' is {len(o)} chars, over "
                             f"{config.POLL_OPTION_MAX}.")
    if explanation and len(explanation) > config.POLL_EXPLANATION_MAX:
        raise ValueError(f"Explanation is {len(explanation)} chars, over "
                         f"{config.POLL_EXPLANATION_MAX}.")
    if not 0 <= correct_option_id < len(options):
        raise ValueError("correct_option_id is out of range.")

    if config.DRY_RUN:
        print(f"[DRY_RUN] sendPoll(quiz) -> {channel}\nQ: {question}")
        for i, o in enumerate(options):
            print(f"  {'*' if i == correct_option_id else ' '} {o}")
        print(f"explanation: {explanation}")
        return {"ok": True, "dry_run": True}

    data = {
        "chat_id": channel,
        "question": question,
        # Bot API 7.0+ expects InputPollOption objects.
        "options": _json.dumps([{"text": o} for o in options], ensure_ascii=False),
        "type": "quiz",
        "correct_option_id": correct_option_id,
        "is_anonymous": is_anonymous,
    }
    if explanation:
        data["explanation"] = explanation
    resp = http.session().post(_api("sendPoll"), data=data,
                               timeout=config.HTTP_TIMEOUT)
    return _result(resp)
