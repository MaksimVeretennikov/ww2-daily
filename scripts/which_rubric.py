#!/usr/bin/env python3
"""Tells the evening routine which rubric to run today (by Moscow weekday).

Prints the rubric, the skill to follow, and the `kind` to record. The dispatcher
skill reads this and then follows the corresponding rubric skill.
"""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import _bootstrap  # noqa: F401
from ww2daily import config

# weekday(): Monday=0 .. Sunday=6
SCHEDULE = {
    0: ("Документ / Дневник", "rubric-document", "document"),
    1: ("Оружие / Техника",   "rubric-weapon",   "weapon"),
    2: ("Двумя глазами",       "rubric-perspectives", "perspectives"),
    3: ("Кадр недели",         "rubric-photo",    "photo"),
    4: ("В цифрах",            "rubric-numbers",  "numbers"),
    5: ("Личность",            "rubric-person",   "person"),
    6: ("Итог недели",         "weekly-digest",   "weekly"),
}


def main() -> None:
    now = datetime.now(ZoneInfo(config.TIMEZONE))
    name, skill, kind = SCHEDULE[now.weekday()]
    info = {
        "weekday": now.strftime("%A"),
        "rubric": name,
        "skill": skill,
        "skill_path": f".claude/skills/{skill}/SKILL.md",
        "kind": kind,
    }
    print(json.dumps(info, ensure_ascii=False, indent=2))
    print(f"\nСегодня ({info['weekday']}) рубрика: {name}")
    print(f"Следуй навыку: {info['skill_path']}")


if __name__ == "__main__":
    main()
