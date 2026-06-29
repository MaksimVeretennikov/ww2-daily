#!/usr/bin/env python3
"""Recover the channel's memory when it scatters across per-session branches.

Each scheduled routine runs in its own cloud session. If a routine lacks
permission to push straight to `main`, it falls back to its per-session
`claude/*` branch (see README §8), and that day's record never reaches `main`.
The result: evening rubrics and polls end up stranded on different branches and
the next run can't see them, breaking topic/photo/poll de-duplication.

This script unions `state/history.json` and `state/polls.json` from EVERY ref
(all local + remote branches and the working tree), de-duplicates, and rewrites
the two files in place. It is strictly additive: it refuses to write if the
result would drop any record currently committed on `main`.

Usage:
    git fetch origin --prune
    python3 scripts/consolidate_state.py            # writes state/, prints report
    python3 scripts/consolidate_state.py --check    # report only, no write
    git add state/ && git commit -m "state: consolidate" && git push origin HEAD:main
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY = "state/history.json"
POLLS = "state/polls.json"

# Records confirmed to be dev/test runs (e.g. a DRY_RUN during skill
# development) that were never published to the channel. Keyed exactly like
# `_hist_key`: (date_posted, kind, subject). Add an entry only when you are sure
# the post never went to the channel — when in doubt, keep it (de-dup safety).
EXCLUDE_HISTORY: set[tuple] = set()


def _sh(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=REPO, capture_output=True, text=True)


def _refs() -> list[str]:
    out = _sh("git", "for-each-ref", "--format=%(refname:short)",
              "refs/heads", "refs/remotes").stdout
    return [r.strip() for r in out.splitlines() if r.strip() and "HEAD" not in r]


def _load_ref(ref: str, path: str):
    r = _sh("git", "show", f"{ref}:{path}")
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def _load_worktree(path: str):
    p = os.path.join(REPO, path)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def _payloads(path: str):
    yield "WORKTREE", _load_worktree(path)
    for ref in _refs():
        yield ref, _load_ref(ref, path)


# ---- history -------------------------------------------------------------
def _hist_key(r: dict) -> tuple:
    return (r.get("date_posted") or "", r.get("kind") or "daily",
            (r.get("subject") or "").strip())


def _hist_richness(r: dict) -> tuple:
    return (1 if r.get("image_pageid") else 0, len(r.get("telegram_caption") or ""))


def _daypart(r: dict) -> int:
    return 0 if (r.get("kind") or "daily") == "daily" else 1  # morning before evening


def consolidate_history():
    best: dict[tuple, dict] = {}
    for ref, data in _payloads(HISTORY):
        if not data:
            continue
        for r in data.get("posts", []):
            k = _hist_key(r)
            if k in EXCLUDE_HISTORY:
                continue
            if k not in best or _hist_richness(r) > _hist_richness(best[k]):
                best[k] = r
    records = sorted(best.values(),
                     key=lambda r: (r.get("date_posted") or "", _daypart(r)))
    return records


# ---- polls ---------------------------------------------------------------
def _poll_key(r: dict) -> tuple:
    return (r.get("date") or "", (r.get("question") or "").strip())


def consolidate_polls():
    best: dict[tuple, dict] = {}
    for ref, data in _payloads(POLLS):
        if not data:
            continue
        for r in data.get("polls", []):
            k = _poll_key(r)
            if k not in best or len(json.dumps(r, ensure_ascii=False)) > \
                    len(json.dumps(best[k], ensure_ascii=False)):
                best[k] = r
    return sorted(best.values(), key=lambda r: (r.get("date") or ""))


def _guard_no_loss(new_records, key_fn, on_main, label):
    """Refuse to proceed if any record on `main` is absent from the new set
    (other than deliberately excluded ones)."""
    new_keys = {key_fn(r) for r in new_records}
    missing = [key_fn(r) for r in on_main
               if key_fn(r) not in new_keys and key_fn(r) not in EXCLUDE_HISTORY]
    if missing:
        raise SystemExit(f"ABORT: {label} on main would lose records: {missing}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="report only; do not write the files")
    args = ap.parse_args()

    history = consolidate_history()
    polls = consolidate_polls()

    main_hist = (_load_ref("origin/main", HISTORY) or {}).get("posts", [])
    main_polls = (_load_ref("origin/main", POLLS) or {}).get("polls", [])
    _guard_no_loss(history, _hist_key, main_hist, "history")
    _guard_no_loss(polls, _poll_key, main_polls, "polls")

    print(f"history: {len(main_hist)} on main -> {len(history)} consolidated")
    print(f"polls:   {len(main_polls)} on main -> {len(polls)} consolidated")

    if args.check:
        print("(--check: nothing written)")
        return

    for path, payload in ((HISTORY, {"posts": history}), (POLLS, {"polls": polls})):
        with open(os.path.join(REPO, path), "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    print("wrote", HISTORY, "and", POLLS)


if __name__ == "__main__":
    main()
