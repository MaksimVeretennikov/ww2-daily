#!/usr/bin/env python3
"""One-off import of the Airtable poll history into state/polls.json.

Expects a tab-separated (or custom-delimited) export with columns:
  date  question  option1  option2  option3  option4  correct_index  explanation
`date` may be DD.MM.YYYY (as in Airtable) or ISO; `correct_index` is 0-based.

Usage:
  python scripts/import_polls.py --input polls_export.tsv [--delimiter $'\t']
"""

import argparse
import csv
import datetime
import sys

import _bootstrap  # noqa: F401
from ww2daily import state


def parse_date(raw: str) -> str:
    raw = (raw or "").strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return raw  # keep as-is if unrecognised


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--delimiter", default="\t")
    ap.add_argument("--append", action="store_true",
                    help="append to existing polls instead of replacing")
    args = ap.parse_args()

    polls = []
    with open(args.input, encoding="utf-8-sig", newline="") as fh:
        for row in csv.reader(fh, delimiter=args.delimiter):
            if len(row) < 7 or not row[1].strip():
                continue
            options = [c.strip() for c in row[2:6] if c.strip()]
            try:
                correct = int(row[6])
            except (ValueError, IndexError):
                continue
            if not options or not 0 <= correct < len(options):
                continue
            polls.append({
                "date": parse_date(row[0]),
                "ww2_date": None,
                "theme": None,
                "question": row[1].strip(),
                "options": options,
                "correct_index": correct,
                "explanation": (row[7].strip() if len(row) > 7 else ""),
            })

    if not polls:
        sys.exit("No valid rows parsed. Check the delimiter and columns.")

    data = state.load_polls() if args.append else {"polls": []}
    data.setdefault("polls", []).extend(polls)
    state.save_polls(data)
    print(f"Imported {len(polls)} polls -> {state.config.POLLS_PATH} "
          f"(total {len(data['polls'])}).")


if __name__ == "__main__":
    main()
