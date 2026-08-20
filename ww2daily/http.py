"""Shared HTTP session with a polite User-Agent and sane timeouts."""

import time

import requests

from . import config

_session: requests.Session | None = None

# Wikimedia rate-limits by IP, and the routine shares one with other traffic,
# so 429 is routine and transient rather than a real failure.
_RETRY_STATUSES = (429, 500, 502, 503, 504)


def session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({"User-Agent": config.USER_AGENT})
    return _session


def get(url: str, **kwargs) -> requests.Response:
    kwargs.setdefault("timeout", config.HTTP_TIMEOUT)
    delay = config.HTTP_RETRY_BASE_DELAY
    for attempt in range(config.HTTP_RETRIES):
        resp = session().get(url, **kwargs)
        if resp.status_code not in _RETRY_STATUSES:
            return resp
        if attempt == config.HTTP_RETRIES - 1:
            return resp
        time.sleep(delay)
        delay *= 2
    return resp


def get_json(url: str, **kwargs) -> dict:
    resp = get(url, **kwargs)
    resp.raise_for_status()
    return resp.json()
