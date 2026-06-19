"""Fetch "what happened on this day" facts from several sources.

Every fetcher is defensive: on any error it returns an empty string instead of
raising, so one flaky source never breaks the daily run. The combined material
is handed to Claude, which weighs and cross-checks it when writing the post.

Sources:
  - onwar.com           — concise daily chronology, all theatres (en)
  - ww2db.com           — "today in WW2 history" event list (en)
  - ru.wikipedia.org    — «Хроника Великой Отечественной войны», Eastern Front
                          focus, day-by-day (ru, exists 22 Jun 1941 .. May 1945)
  - en.wikipedia.org    — "Timeline of World War II (YYYY)", all theatres (en)
"""

import re
from html import unescape

from bs4 import BeautifulSoup

from . import http

WIKI_RU_API = "https://ru.wikipedia.org/w/api.php"
WIKI_EN_API = "https://en.wikipedia.org/w/api.php"


def _strip_tags(fragment: str) -> str:
    s = unescape(fragment or "")
    s = re.sub(r"(?is)<[^>]+>", "", s)
    return re.sub(r"\s+", " ", s).strip()


# --- onwar.com ---------------------------------------------------------------

def fetch_onwar(d: dict) -> str:
    """Paragraphs under the <h2>{weekday, Month D, YYYY}</h2> block."""
    try:
        url = f"https://www.onwar.com/wwii/chronology/{d['onwar_yyyymm']}.html"
        html = http.get(url).text
        m = re.search(
            r"(?is)<h2>\s*" + re.escape(d["en_onwar_header"]) +
            r"\s*</h2>(.*?)(?:<hr>|</body>|</html>)",
            html,
        )
        if not m:
            return ""
        paras = re.findall(r"(?is)<p>(.*?)</p>", m.group(1))
        cleaned = [p for p in (_strip_tags(p) for p in paras) if p]
        return "\n\n".join(cleaned)
    except Exception:
        return ""


# --- ww2db.com ---------------------------------------------------------------

def fetch_ww2db(d: dict) -> str:
    """Events for the target calendar day, filtered to the target year."""
    try:
        url = f"https://ww2db.com/event/today/{d['ww2db_slug']}"
        html = http.get(url).text
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text("\n", strip=True)
        # Keep only lines that reference the target year to cut cross-year noise.
        year = str(d["year"])
        lines = [ln for ln in text.splitlines() if year in ln and len(ln) > 30]
        return "\n".join(dict.fromkeys(lines))  # de-dup, preserve order
    except Exception:
        return ""


# --- Wikimedia helpers -------------------------------------------------------

def _wikitext(api: str, title: str) -> str:
    data = http.get_json(api, params={
        "action": "parse", "page": title, "prop": "wikitext",
        "format": "json", "formatversion": "2",
    })
    return data.get("parse", {}).get("wikitext", "") or ""


def _clean_wiki(s: str) -> str:
    """Best-effort wiki markup -> plain text."""
    s = re.sub(r"<ref[^>]*>.*?</ref>", "", s, flags=re.S)
    s = re.sub(r"<ref[^>]*/>", "", s)
    s = re.sub(r"\{\{[^{}]*\}\}", "", s)            # simple templates
    s = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", s)  # links
    s = re.sub(r"'''?", "", s)                       # bold/italics
    s = re.sub(r"<[^>]+>", "", s)                     # stray html
    s = re.sub(r"^[\*#:;]+\s*", "", s, flags=re.M)    # list markers
    return re.sub(r"[ \t]+", " ", s).strip()


# --- ru.wikipedia chronicle --------------------------------------------------

def fetch_ru_chronicle(d: dict) -> str:
    """Section for the day from «Хроника Великой Отечественной войны (месяц)».

    Only exists for the Soviet–German war (from 22 June 1941). Returns "" for
    earlier dates, which is expected and fine.
    """
    try:
        title = f"Хроника Великой Отечественной войны ({d['ru_month_article']})"
        wikitext = _wikitext(WIKI_RU_API, title)
        if not wikitext:
            return ""
        # Day headings look like "== 17 июня ==" (level may vary).
        heading = re.escape(d["ru_day_heading"])
        m = re.search(
            r"(?m)^(={2,})\s*" + heading + r"\s*=+\s*$(.*?)(?=^={2,}\s|\Z)",
            wikitext, flags=re.S,
        )
        if not m:
            return ""
        return _clean_wiki(m.group(2))
    except Exception:
        return ""


# --- en.wikipedia timeline ---------------------------------------------------

def fetch_en_timeline(d: dict) -> str:
    """Rows mentioning the target day from "Timeline of World War II (YYYY)"."""
    try:
        title = f"Timeline of World War II ({d['year']})"
        wikitext = _wikitext(WIKI_EN_API, title)
        if not wikitext:
            return ""
        text = _clean_wiki(wikitext)
        # Timeline tables put the day number in a cell; capture nearby prose.
        wanted = {str(d["day"]), d["en_month"]}
        out = []
        for line in text.splitlines():
            line = line.strip(" |")
            if not line or len(line) < 25:
                continue
            if str(d["day"]) in line and d["en_month"] in line:
                out.append(line)
        return "\n".join(dict.fromkeys(out))[:3000]
    except Exception:
        return ""


# --- aggregate ---------------------------------------------------------------

FETCHERS = {
    "onwar": fetch_onwar,
    "ww2db": fetch_ww2db,
    "ru_chronicle": fetch_ru_chronicle,
    "en_timeline": fetch_en_timeline,
}


def gather(d: dict) -> dict:
    """Run all fetchers. Returns {source: text} plus a combined block."""
    results = {name: fn(d) for name, fn in FETCHERS.items()}
    parts = []
    titles = {
        "onwar": "onwar.com",
        "ww2db": "ww2db.com",
        "ru_chronicle": "Хроника ВОВ (ru.wikipedia)",
        "en_timeline": "Timeline of WWII (en.wikipedia)",
    }
    for name, text in results.items():
        if text:
            parts.append(f"### {titles[name]}\n{text}")
    return {
        "date": d,
        "sources": results,
        "combined": "\n\n".join(parts),
    }
