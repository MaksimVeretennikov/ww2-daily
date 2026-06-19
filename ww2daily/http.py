"""Shared HTTP session with a polite User-Agent and sane timeouts."""

import requests

from . import config

_session: requests.Session | None = None


def session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({"User-Agent": config.USER_AGENT})
    return _session


def get(url: str, **kwargs) -> requests.Response:
    kwargs.setdefault("timeout", config.HTTP_TIMEOUT)
    return session().get(url, **kwargs)


def get_json(url: str, **kwargs) -> dict:
    resp = get(url, **kwargs)
    resp.raise_for_status()
    return resp.json()
