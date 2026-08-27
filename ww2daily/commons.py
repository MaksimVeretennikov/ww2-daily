"""Wikimedia Commons image search, de-duplication and candidate building.

Two search strategies (mirroring the original make.com flow):
  1. File search   — gsrnamespace=6, query is Claude's `image_prompt`.
  2. Category search — srnamespace=14, query is Claude's `category_prompt`;
     then pull files from the matched categories.

Candidates already used before (tracked by Commons pageid in state) and clearly
post-war images are filtered out. Claude then picks the best fit from what's
left — and, being multimodal, can actually look at the images, not just their
captions."""

import re

from bs4 import BeautifulSoup

from . import config, http

API = "https://commons.wikimedia.org/w/api.php"
_IMAGEINFO = {
    "prop": "imageinfo",
    "iiprop": "url|mime|extmetadata",
    "iiurlwidth": str(config.PHOTO_THUMB_WIDTH),
    "format": "json",
    "origin": "*",
}


def _clean(text: str | None, max_len: int = 300) -> str | None:
    if not text:
        return None
    clean = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
    clean = " ".join(clean.split())
    if len(clean) > max_len:
        clean = clean[:max_len].rsplit(" ", 1)[0]
    return clean or None


def _first_year(text) -> int | None:
    if not text:
        return None
    m = re.search(r"\d{4}", str(text))
    return int(m.group(0)) if m else None


def _page_to_candidate(page: dict) -> dict | None:
    info = (page.get("imageinfo") or [{}])[0]
    meta = info.get("extmetadata", {})
    mime = info.get("mime", "")
    if mime and not mime.startswith("image/"):
        return None
    return {
        "pageid": page.get("pageid"),
        "title": page.get("title"),
        "thumb_url": info.get("thumburl"),
        "image_url": info.get("url"),
        "descriptionurl": info.get("descriptionurl"),
        "year": _first_year(meta.get("DateTimeOriginal", {}).get("value")),
        "description": _clean(meta.get("ImageDescription", {}).get("value")),
        "credit": _clean(meta.get("Artist", {}).get("value"), 120),
        "license": (meta.get("LicenseShortName", {}) or {}).get("value"),
    }


def _search_files(query: str) -> list[dict]:
    params = {
        "action": "query", "generator": "search",
        "gsrnamespace": "6", "gsrlimit": "15",
        "gsrsearch": f"filetype:bitmap {query}", **_IMAGEINFO,
    }
    data = http.get_json(API, params=params)
    pages = (data.get("query") or {}).get("pages", {})
    return list(pages.values())


def _search_categories(query: str, limit_cats: int = 5) -> list[dict]:
    data = http.get_json(API, params={
        "action": "query", "list": "search",
        "srnamespace": "14", "srlimit": "10",
        "srsearch": query, "format": "json", "origin": "*",
    })
    cats = [r["title"] for r in (data.get("query") or {}).get("search", [])]
    pages: list[dict] = []
    for cat in cats[:limit_cats]:
        try:
            data = http.get_json(API, params={
                "action": "query", "generator": "categorymembers",
                "gcmtitle": cat, "gcmtype": "file", "gcmlimit": "15",
                **_IMAGEINFO,
            })
            pages.extend(((data.get("query") or {}).get("pages", {})).values())
        except Exception:
            continue
    return pages


def find_candidates(image_prompt: str,
                    category_prompt: str | None,
                    used_pageids: set) -> list[dict]:
    """Return up to PHOTO_CANDIDATES fresh, archival image candidates."""
    raw: list[dict] = []
    try:
        raw.extend(_search_files(image_prompt))
    except Exception:
        pass
    if category_prompt:
        try:
            raw.extend(_search_categories(category_prompt))
        except Exception:
            pass

    seen, candidates = set(), []
    for page in raw:
        cand = _page_to_candidate(page)
        if not cand or not cand["thumb_url"]:
            continue
        pid = cand["pageid"]
        if pid in used_pageids or pid in seen:
            continue
        if cand["year"] is not None and cand["year"] > config.PHOTO_MAX_YEAR:
            continue
        seen.add(pid)
        candidates.append(cand)
        if len(candidates) >= config.PHOTO_CANDIDATES:
            break
    return candidates


def photo_url(cand: dict) -> str | None:
    """The URL to download when publishing a candidate.

    Prefer the standard-width thumbnail over the full-resolution original:
    Wikimedia serves standard sizes from cache and throttles bulk fetches of
    originals (HTTP 429), which is exactly how a post loses its photo."""
    return cand.get("thumb_url") or cand.get("image_url")


def download(url: str, dest: str) -> str:
    resp = http.get(url)
    resp.raise_for_status()
    with open(dest, "wb") as fh:
        fh.write(resp.content)
    return dest
