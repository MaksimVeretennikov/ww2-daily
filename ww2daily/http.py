"""Shared HTTP session with a polite User-Agent, sane timeouts and retries.

Wikimedia rate-limits the shared egress IP that cloud sessions go out through:
requests come back as HTTP 429 with a `Retry-After` of several minutes. The
throttling window is short in practice, so a couple of backed-off retries turn
a lost photo into a slightly slower run."""

import time

import requests

from . import config

_session: requests.Session | None = None

# Statuses worth retrying: rate limiting and transient server/proxy errors.
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})

# Seconds left for waiting, shared by every request in this process: a burst of
# throttling should cost a run a couple of minutes, not stall it outright.
_budget = config.HTTP_RETRY_BUDGET


def session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({"User-Agent": config.USER_AGENT})
    return _session


def _wait_for(resp: requests.Response, fallback: float) -> float:
    """How long to sleep before the next attempt.

    Honour `Retry-After` when the server sends one, but cap it: Wikimedia
    answers with 600 seconds, and no daily run should stall for ten minutes."""
    raw = resp.headers.get("Retry-After")
    if raw:
        try:
            return min(float(raw), config.HTTP_RETRY_MAX_WAIT)
        except ValueError:
            pass  # HTTP-date form — use our own backoff instead
    return fallback


def get(url: str, **kwargs) -> requests.Response:
    global _budget
    kwargs.setdefault("timeout", config.HTTP_TIMEOUT)
    backoff = config.HTTP_BACKOFF
    resp: requests.Response | None = None
    last_exc: Exception | None = None

    for attempt in range(config.HTTP_RETRIES + 1):
        resp, last_exc = None, None
        try:
            resp = session().get(url, **kwargs)
        except requests.RequestException as exc:  # timeout, reset connection…
            last_exc = exc
        if resp is not None and resp.status_code not in RETRY_STATUS:
            return resp
        if attempt == config.HTTP_RETRIES:
            break
        reason = f"HTTP {resp.status_code}" if resp is not None \
            else type(last_exc).__name__
        delay = _wait_for(resp, backoff) if resp is not None else backoff
        if delay > _budget:
            print(f"  {reason} from {url[:90]} — retry budget spent, giving up")
            break
        _budget -= delay
        print(f"  {reason} from {url[:90]} — retrying in {delay:.0f}s "
              f"({attempt + 1}/{config.HTTP_RETRIES})")
        time.sleep(delay)
        backoff = min(backoff * 2, config.HTTP_RETRY_MAX_WAIT)

    if resp is not None:
        return resp  # out of retries: let the caller's raise_for_status speak
    raise last_exc


def get_json(url: str, **kwargs) -> dict:
    resp = get(url, **kwargs)
    resp.raise_for_status()
    return resp.json()
