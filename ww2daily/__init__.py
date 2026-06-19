"""WW2 daily — pipeline for the «Дневник Второй Мировой» Telegram channel.

The intelligent parts (writing the post, the photo caption and choosing the
best image) are done by Claude inside the daily routine session. These modules
provide the deterministic plumbing: date math, source fetching, Wikimedia
Commons search with de-duplication, publishing and persistent state.
"""

__all__ = [
    "config",
    "dates",
    "sources",
    "commons",
    "telegram",
    "twitter",
    "state",
]
