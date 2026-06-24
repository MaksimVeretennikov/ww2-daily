"""Commit and push state files back to the repo from inside a publish script.

The daily routines run in an ephemeral cloud container that is cloned fresh each
time. The channel's memory (post history, poll history) only survives if it is
PUSHED back after each post — a commit that never reaches the remote is lost
when the container is reclaimed. Relying on a manual "now commit and push" step
in the skill is fragile: if the model skips it, or the push fails silently, the
next run starts blind and can repeat a topic or a poll question.

`persist()` makes that step part of publishing itself: right after a record is
appended, it stages the state file, commits it, and pushes. Failures are loud
but non-fatal — the post is already out, so we warn and let the skill's manual
step act as a backstop rather than crashing.
"""

import subprocess

from ww2daily import config


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
    )


def persist(path: str, message: str, push_ref: str | None = None) -> bool:
    """Stage, commit and push `path`. Returns True if it reached the remote.

    No-ops (returns True) when STATE_AUTOCOMMIT is off or in DRY_RUN — the
    caller's manual git step stays in charge in those modes.
    """
    if config.DRY_RUN or not config.STATE_AUTOCOMMIT:
        return True

    push_ref = push_ref or config.STATE_PUSH_REF

    add = _run(["add", path])
    if add.returncode != 0:
        print(f"WARNING: could not stage {path}: {add.stderr.strip()}")
        return False

    # Nothing staged (already committed) → treat as success, still try to push.
    if _run(["diff", "--cached", "--quiet", "--", path]).returncode != 0:
        commit = _run(["commit", "-m", message, "--", path])
        if commit.returncode != 0:
            print(f"WARNING: could not commit {path}: {commit.stderr.strip()}")
            return False

    push = _run(["push", "origin", f"HEAD:{push_ref}"])
    if push.returncode != 0:
        print(f"WARNING: committed {path} locally but push to "
              f"'{push_ref}' failed: {push.stderr.strip()}\n"
              f"         Push it manually or the next run will not see it.")
        return False

    print(f"Committed and pushed {path} to '{push_ref}'.")
    return True
