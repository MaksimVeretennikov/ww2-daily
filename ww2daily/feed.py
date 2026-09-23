"""RSS feed of the channel's posts, for VK's built-in RSS import (and Дзен).

VK communities can import an RSS feed («Управление → Дополнительно → RSS →
Импорт в сообщество»): VK polls the feed and publishes new items on the wall
with their pictures. That needs no user token at all, which is what makes it
the way photos reach VK — a community key cannot upload wall photos.

How VK imports (checked on a real community, September 2026): the post text
is the item's `description` with every HTML tag stripped and NOT turned into
line breaks, so the description is plain text with real newlines; the picture
is neither `<enclosure>` nor `<img>` but the Open Graph image of the page the
item LINKS to — VK renders a link card under the text. So every post gets its
own little page in `docs/p/` with og:image pointing at the photo in
`docs/img/` (VK cannot fetch pictures from Wikimedia, so the routine keeps the
file it already downloaded). GitHub Pages serves all of it. Only records that
carry a `feed_image` key — i.e. published since the feed exists — are listed,
so enabling the import never floods the wall with history. Everything is
rebuilt from state/history.json, so the feed is as reproducible as the rest
of state/.
"""

import datetime
import html
import os
import re
import shutil
import zoneinfo
from xml.sax.saxutils import escape

from . import config, dates

KIND_LABELS = {
    "daily": "Дневник",
    "document": "Документ",
    "weapon": "Оружие и техника",
    "perspectives": "Двумя глазами",
    "photo": "Кадр недели",
    "numbers": "В цифрах",
    "person": "Личность",
    "weekly": "Итог недели",
}
# Local publication hour by kind: morning post 09:00, everything else 20:00.
KIND_HOUR = {"daily": 9}


def _tz():
    return zoneinfo.ZoneInfo(config.TIMEZONE)


def image_name(record: dict) -> str:
    return f"{record.get('date_posted')}-{record.get('kind') or 'daily'}.jpg"


def stage_image(image_path: str, record: dict) -> str | None:
    """Copy the published picture into docs/img/ and return its feed path."""
    if not image_path or not os.path.exists(image_path):
        return None
    rel = os.path.join(config.FEED_IMG_DIR, image_name(record))
    os.makedirs(os.path.dirname(rel), exist_ok=True)
    shutil.copyfile(image_path, rel)
    return os.path.relpath(rel, os.path.dirname(config.FEED_PATH))


def _ru_date(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        y, m, d = (int(x) for x in iso.split("-"))
        return f"{d} {dates.RU_MONTHS_GENITIVE[m - 1]} {y}"
    except (ValueError, IndexError):
        return iso


def _pub_date(record: dict) -> str:
    kind = record.get("kind") or "daily"
    day = datetime.date.fromisoformat(record["date_posted"])
    dt = datetime.datetime.combine(day, datetime.time(KIND_HOUR.get(kind, 20)),
                                   tzinfo=_tz())
    return dt.strftime("%a, %d %b %Y %H:%M:%S %z")


def _title(record: dict) -> str:
    kind = record.get("kind") or "daily"
    label = KIND_LABELS.get(kind, kind)
    when = _ru_date(record.get("ww2_date"))
    subject = record.get("subject")
    if kind == "daily":
        return when or label
    if subject:
        return f"{label}: {subject}"
    return f"{label} — {when}" if when else label


_TAG_RE = re.compile(r"</?(i|b|u|s|a|code|pre|tg-spoiler|span)[^>]*>")


def _plain_text(text: str) -> str:
    """Telegram HTML → plain text with real newlines (VK drops tags, keeps
    newlines)."""
    plain = html.unescape(_TAG_RE.sub("", text or "")).strip()
    paras = [p.strip() for p in re.split(r"\n\s*\n", plain) if p.strip()]
    return "\n\n".join(paras)


def page_name(record: dict) -> str:
    return f"{record.get('date_posted')}-{record.get('kind') or 'daily'}.html"


def _page_html(record: dict, base_url: str) -> str:
    """A tiny public page per post: Open Graph tags for the link card VK (and
    Telegram, and messengers) render, then the post itself and a way to the
    channel."""
    title = _title(record)
    text = _plain_text(record.get("telegram_caption", ""))
    img = record.get("feed_image")
    img_url = base_url + img if img else ""
    first = text.split("\n\n")[0] if text else ""
    desc = html.escape(first[:200])
    og_img = ""
    if img_url:
        og_img = (f'<meta property="og:image" content="{html.escape(img_url)}">\n'
                  f'<meta name="twitter:image" content="{html.escape(img_url)}">\n'
                  '<meta name="twitter:card" content="summary_large_image">\n')
    paras = "".join(f"<p>{html.escape(p).replace(chr(10), '<br>')}</p>"
                    for p in text.split("\n\n") if p)
    figure = f'<img src="{html.escape(img_url)}" alt="">' if img_url else ""
    return f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<title>{html.escape(title)} — {html.escape(config.FEED_TITLE)}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta property="og:type" content="article">
<meta property="og:site_name" content="{html.escape(config.FEED_TITLE)}">
<meta property="og:title" content="{html.escape(title)}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{html.escape(base_url + 'p/' + page_name(record))}">
{og_img}<meta name="description" content="{desc}">
<style>body{{font-family:Georgia,serif;max-width:40em;margin:2em auto;padding:0 1em;line-height:1.55}}img{{max-width:100%;height:auto}}a{{color:#1a5fb4}}</style>
</head><body>
<p><a href="../">{html.escape(config.FEED_TITLE)}</a></p>
<h1>{html.escape(title)}</h1>
{figure}
{paras}
<p><a href="{html.escape(config.FEED_LINK)}">Читать канал в Telegram →</a></p>
</body></html>
"""


def _item(record: dict, base_url: str) -> str:
    guid = f"ww2daily:{record.get('date_posted')}:{record.get('kind') or 'daily'}"
    if record.get("feed_rev"):
        guid += f":{record['feed_rev']}"     # re-issue an item VK already took
    body = _plain_text(record.get("telegram_caption", ""))
    img = record.get("feed_image")
    img_url = base_url + img if img else None
    page_url = base_url + "p/" + page_name(record)
    parts = [
        f"<title>{escape(_title(record))}</title>",
        f"<link>{escape(page_url)}</link>",
        f'<guid isPermaLink="false">{escape(guid)}</guid>',
        f"<pubDate>{_pub_date(record)}</pubDate>",
        f"<description><![CDATA[{body}]]></description>",
    ]
    if img_url:
        length = 0
        local = os.path.join(os.path.dirname(config.FEED_PATH), img)
        if os.path.exists(local):
            length = os.path.getsize(local)
        parts.append(f'<enclosure url="{escape(img_url, {chr(34): "&quot;"})}" '
                     f'type="image/jpeg" length="{length}"/>')
    return "<item>" + "".join(parts) + "</item>"


def render(posts: list[dict]) -> str:
    base_url = config.FEED_BASE_URL.rstrip("/") + "/"
    items = [p for p in posts if "feed_image" in p and p.get("telegram_caption")]
    items = [_item(p, base_url) for p in items[-config.FEED_MAX_ITEMS:][::-1]]
    now = datetime.datetime.now(_tz()).strftime("%a, %d %b %Y %H:%M:%S %z")
    head = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n<channel>\n'
        f"<title>{escape(config.FEED_TITLE)}</title>\n"
        f"<link>{escape(config.FEED_LINK)}</link>\n"
        f"<description>{escape(config.FEED_DESCRIPTION)}</description>\n"
        "<language>ru</language>\n"
        f"<lastBuildDate>{now}</lastBuildDate>\n"
        f'<atom:link href="{escape(base_url + os.path.basename(config.FEED_PATH))}" '
        'rel="self" type="application/rss+xml"/>\n'
    )
    return head + "\n".join(items) + "\n</channel>\n</rss>\n"


def write(posts: list[dict]) -> str:
    docs = os.path.dirname(config.FEED_PATH) or "."
    os.makedirs(os.path.join(docs, "p"), exist_ok=True)
    base_url = config.FEED_BASE_URL.rstrip("/") + "/"
    for record in posts:
        if "feed_image" in record and record.get("telegram_caption"):
            with open(os.path.join(docs, "p", page_name(record)), "w",
                      encoding="utf-8") as fh:
                fh.write(_page_html(record, base_url))
    with open(config.FEED_PATH, "w", encoding="utf-8") as fh:
        fh.write(render(posts))
    return config.FEED_PATH
