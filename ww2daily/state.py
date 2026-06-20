"""Persistent history, committed back to the repo each run.

This file is the channel's memory: it prevents repeated photos (by Commons
pageid) and gives Claude context on recent posts so topics and tone don't
repeat. It lives in git, so the fresh clone at the start of each routine run
already contains everything from previous days."""

import json
import os

from . import config

_DEFAULT = {"posts": []}


def _path() -> str:
    return config.STATE_PATH


def load() -> dict:
    path = _path()
    if not os.path.exists(path):
        return dict(_DEFAULT)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        data.setdefault("posts", [])
        return data
    except Exception:
        return dict(_DEFAULT)


def save(data: dict) -> None:
    path = _path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def used_pageids(data: dict | None = None) -> set:
    data = data or load()
    out = set()
    for p in data.get("posts", []):
        pid = p.get("image_pageid")
        if pid is not None:
            out.add(pid)
    return out


def recent(n: int | None = None, data: dict | None = None) -> list:
    data = data or load()
    posts = data.get("posts", [])
    n = n or config.HISTORY_CONTEXT_POSTS
    return posts[-n:]


def context_digest(n: int | None = None, data: dict | None = None) -> str:
    """Compact human-readable digest of recent posts for the writing prompt."""
    lines = []
    for p in recent(n, data):
        lines.append(
            f"- {p.get('ww2_date', '?')}: {p.get('topic') or p.get('title') or ''}".rstrip()
        )
    return "\n".join(lines)


def append(record: dict, data: dict | None = None) -> dict:
    data = data or load()
    data.setdefault("posts", []).append(record)
    save(data)
    return data


# --- rubric helpers ----------------------------------------------------------

def kind_of(post: dict) -> str:
    """Post type; legacy posts without the field are daily posts."""
    return post.get("kind") or "daily"


def by_kind(kind: str, data: dict | None = None) -> list:
    data = data or load()
    return [p for p in data.get("posts", []) if kind_of(p) == kind]


def featured_subjects(kind: str, data: dict | None = None) -> set:
    """Subjects already covered by a rubric (e.g. people for «Личность»)."""
    return {p.get("subject") for p in by_kind(kind, data) if p.get("subject")}


def featured_by_kind(data: dict | None = None) -> dict:
    """All covered subjects grouped by kind, e.g. {"person": [...], "weapon": [...]}."""
    data = data or load()
    out: dict[str, set] = {}
    for p in data.get("posts", []):
        subj = p.get("subject")
        if subj:
            out.setdefault(kind_of(p), set()).add(subj)
    return {k: sorted(v) for k, v in out.items()}


def recent_by_kind(kind: str, n: int = 12, data: dict | None = None) -> list:
    return by_kind(kind, data)[-n:]


def posts_in_ww2_window(start_iso: str, end_iso: str,
                        data: dict | None = None) -> list:
    """Posts whose ww2_date falls within [start_iso, end_iso] inclusive."""
    data = data or load()
    out = []
    for p in data.get("posts", []):
        d = p.get("ww2_date")
        if d and start_iso <= d <= end_iso:
            out.append(p)
    return out

