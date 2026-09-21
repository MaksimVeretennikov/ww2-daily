#!/usr/bin/env python3
"""Publish the daily quiz poll to Telegram.

Reads run/poll.json (written by Claude), shuffles the options so the correct
answer's position is random, sanity-checks the "longest option is the answer"
tell, posts a quiz-mode poll, and records it so future polls don't repeat.

If VK is configured, the same poll also goes to the VK community. VK has no
quiz mode, so there it is a plain poll, and the previous poll's answer (with
the explanation) is revealed as a community comment under that earlier post —
so every VK poll gets its answer a day later.

poll.json schema:
{
  "ww2_date": "1941-06-21",
  "theme": "Operation Barbarossa preparations",
  "question": "<= 300 chars>",
  "options": ["...", "...", "...", "..."],   // 2-10, each <= 100 chars
  "correct_index": 2,
  "explanation": "<= 200 chars>"
}
"""

import argparse
import datetime
import json
import os
import random
import re

import _bootstrap  # noqa: F401
from ww2daily import config, state, telegram, vk

POLL = os.path.join(_bootstrap.RUN_DIR, "poll.json")


def _content_words(text: str) -> set[str]:
    """Significant word stems (length >= 5, tags stripped, de-cased)."""
    if not text:
        return set()
    plain = re.sub(r"<[^>]+>", " ", text)
    words = re.findall(r"[0-9A-Za-zА-Яа-яЁё]{5,}", plain.lower())
    # Compare on a 5-char prefix so ru inflections (Флёров/Флёрова) still match.
    return {w[:5] for w in words}


def _overlap_warning(poll: dict) -> str | None:
    """Deterministic backstop against overlap with the SAME channel-date morning
    post. Fires when either (a) the poll is centred on the same event — the
    question shares many distinctive terms with the post — or (b) the correct
    answer's substance already appears in the post."""
    ww2 = poll.get("ww2_date")
    post = next(
        (p for p in state.load().get("posts", [])
         if state.kind_of(p) == "daily" and p.get("ww2_date") == ww2),
        None,
    )
    if not post:
        return None
    post_words = _content_words(post.get("telegram_caption", ""))
    if not post_words:
        return None

    # (a) Question centred on the morning post's event.
    q_hit = _content_words(poll.get("question", "")) & post_words
    if len(q_hit) >= 4:
        return ("the question is built around the same event as today's morning "
                f"post (shared terms: {', '.join(sorted(q_hit))}). Subscribers "
                "just read it. Ask about a different event/detail of the period.")

    # (b) Answer substance lifted straight from the post.
    answer_words = _content_words(poll["options"][poll["correct_index"]])
    a_hit = answer_words & post_words
    if answer_words and len(a_hit) >= max(2, round(0.6 * len(answer_words))):
        return ("the correct answer's key terms "
                f"({', '.join(sorted(a_hit))}) already appear in today's morning "
                "post — the poll tests a fact subscribers just read. "
                "Pick a fact NOT stated in that post.")
    return None


VK_POLL_INTRO = "Викторина. Верный ответ и пояснение — завтра в комментариях."


def _reveal_previous_vk_answer(polls: dict) -> dict:
    """Post yesterday's answer under yesterday's VK poll post (if any).

    Whatever happens here must not stop today's poll: a failure is reported
    and the reveal is retried on the next run."""
    pending = [p for p in polls.get("polls", [])
               if p.get("vk_post_id") and not p.get("vk_answer_revealed")]
    if not pending:
        return {"skipped": "nothing_to_reveal"}
    prev = pending[-1]
    answer = prev["options"][prev["correct_index"]]
    text = f"Верный ответ: {answer}"
    if prev.get("explanation"):
        text += f"\n\n{prev['explanation']}"
    try:
        result = vk.reveal_answer(prev["vk_post_id"], text)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    if result.get("ok") and not config.DRY_RUN:
        prev["vk_answer_revealed"] = True
        state.save_polls(polls)
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--poll", default=POLL)
    ap.add_argument("--force", action="store_true",
                    help="post even if a poll already exists for today")
    args = ap.parse_args()

    with open(args.poll, encoding="utf-8") as fh:
        poll = json.load(fh)

    today = datetime.date.today().isoformat()
    polls = state.load_polls()
    if any(p.get("date") == today for p in polls.get("polls", [])) and not args.force:
        raise SystemExit(f"A poll already exists for {today}. "
                         f"Skipping to avoid a duplicate (use --force).")

    options = list(poll["options"])
    correct_text = options[poll["correct_index"]]

    # Randomise position so the answer is never in a predictable slot.
    random.shuffle(options)
    correct_index = options.index(correct_text)

    # Guard against the classic tell: the longest option being the answer.
    lengths = sorted(len(o) for o in options)
    if len(correct_text) == lengths[-1] and lengths[-1] - lengths[-2] > 12:
        print("WARNING: the correct option is noticeably the longest — "
              "rebalance option lengths so the answer isn't guessable.")

    # Guard against overlap with the same-day morning post (subscribers just
    # read it — quizzing its facts is a give-away and feels repetitive).
    overlap = _overlap_warning(poll)
    if overlap:
        print("WARNING:", overlap)

    telegram.send_poll(
        question=poll["question"],
        options=options,
        correct_option_id=correct_index,
        explanation=poll.get("explanation"),
    )

    # --- VK: reveal yesterday's answer, then mirror today's poll. Best-effort:
    # the Telegram poll already went out and must be recorded regardless. ---
    vk_reveal = vk_result = {"skipped": "vk_disabled"}
    if vk.is_enabled():
        vk_reveal = _reveal_previous_vk_answer(polls)
        try:
            vk_result = vk.post_poll(poll["question"], options, VK_POLL_INTRO)
        except Exception as exc:
            vk_result = {"ok": False, "error": str(exc)}

    record = {
        "date": today,
        "ww2_date": poll.get("ww2_date"),
        "theme": poll.get("theme"),
        "question": poll["question"],
        "options": options,
        "correct_index": correct_index,
        "explanation": poll.get("explanation", ""),
    }
    if vk_result.get("post_id"):
        record["vk_post_id"] = vk_result["post_id"]
        record["vk_poll_id"] = vk_result.get("poll_id")
    if not config.DRY_RUN:
        state.append_poll(record, polls)
        print("Recorded poll in", config.POLLS_PATH)
    else:
        print("[DRY_RUN] would record:", json.dumps(record, ensure_ascii=False))
    print("VK reveal:", vk_reveal)
    print("VK result:", vk_result)


if __name__ == "__main__":
    main()
