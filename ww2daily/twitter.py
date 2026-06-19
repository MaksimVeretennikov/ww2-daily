"""Optional X (Twitter) cross-posting.

Disabled by default (X_ENABLED=0). When enabled, posts the short English text
with the same photo via the X API v2 using tweepy. As of 2026 the API is
pay-per-use (~$0.01/post, a few cents a month at one post/day), with a one-time
$10 starter credit — so daily posting is effectively free. tweepy is only
imported when this path is actually used, so it stays an optional dependency."""

from . import config


def is_enabled() -> bool:
    creds = config.X_CREDENTIALS
    required = ("api_key", "api_secret", "access_token", "access_token_secret")
    return config.X_ENABLED and all(creds[k] for k in required)


def post(text: str, photo_path: str | None = None) -> dict:
    if not is_enabled():
        return {"ok": False, "skipped": "x_disabled_or_unconfigured"}
    if config.DRY_RUN:
        print(f"[DRY_RUN] X post ({len(text)} chars):\n{text}\nphoto: {photo_path}")
        return {"ok": True, "dry_run": True}

    import tweepy  # imported lazily; optional dependency

    creds = config.X_CREDENTIALS
    client = tweepy.Client(
        consumer_key=creds["api_key"],
        consumer_secret=creds["api_secret"],
        access_token=creds["access_token"],
        access_token_secret=creds["access_token_secret"],
    )
    media_ids = None
    if photo_path:
        auth = tweepy.OAuth1UserHandler(
            creds["api_key"], creds["api_secret"],
            creds["access_token"], creds["access_token_secret"],
        )
        api_v1 = tweepy.API(auth)
        media = api_v1.media_upload(photo_path)
        media_ids = [media.media_id]
    resp = client.create_tweet(text=text, media_ids=media_ids)
    return {"ok": True, "id": resp.data.get("id")}
