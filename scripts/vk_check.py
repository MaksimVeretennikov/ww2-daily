#!/usr/bin/env python3
"""One-off check of the VK cross-post setup: is the token a user token, does it
carry the right scopes, is its owner an admin of VK_GROUP_ID, can it upload
wall photos. Posts nothing.

    VK_ACCESS_TOKEN=... VK_GROUP_ID=... python scripts/vk_check.py
"""

import _bootstrap  # noqa: F401
from ww2daily import vk


def main() -> None:
    problems = vk.check()
    if problems:
        print("\nVK setup problems:")
        for p in problems:
            print(" -", p)
        raise SystemExit(1)
    print("\nVK setup OK: posts, photos and polls will cross-post.")


if __name__ == "__main__":
    main()
