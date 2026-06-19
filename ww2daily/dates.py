"""Date math for the "exactly N years ago" anchor.

Everything is computed in the channel's timezone so the day flips at local
midnight, and Russian month names are produced without relying on system
locale (which is unreliable in minimal containers)."""

from datetime import datetime
from zoneinfo import ZoneInfo

from . import config

# Russian month names. Nominative is used for Wikipedia article titles
# ("июнь 1941 года"); genitive for day headings and human display ("17 июня").
RU_MONTHS_NOMINATIVE = [
    "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
]
RU_MONTHS_GENITIVE = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]
EN_MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
EN_WEEKDAYS = [
    "Monday", "Tuesday", "Wednesday", "Thursday",
    "Friday", "Saturday", "Sunday",
]


def _subtract_years(d: datetime, years: int) -> datetime:
    """Subtract whole years, clamping Feb 29 -> Feb 28 when needed."""
    try:
        return d.replace(year=d.year - years)
    except ValueError:
        return d.replace(year=d.year - years, day=28)


def target_date(now: datetime | None = None) -> datetime:
    """The historical date the post is about: today minus YEARS_BACK, in TZ."""
    tz = ZoneInfo(config.TIMEZONE)
    now = now.astimezone(tz) if now else datetime.now(tz)
    return _subtract_years(now, config.YEARS_BACK)


def describe(d: datetime) -> dict:
    """All date representations the pipeline needs, in one dict."""
    m = d.month - 1
    return {
        "year": d.year,
        "month": d.month,
        "day": d.day,
        # 1941
        "iso": d.strftime("%Y-%m-%d"),
        # 17.06.1941
        "ru_dotted": d.strftime("%d.%m.%Y"),
        # 17 июня 1941 — for the bold header in the post
        "ru_human": f"{d.day} {RU_MONTHS_GENITIVE[m]} {d.year}",
        # июнь 1941 года — ru.wikipedia chronicle article title fragment
        "ru_month_article": f"{RU_MONTHS_NOMINATIVE[m]} {d.year} года",
        # 17 июня — day heading inside the ru.wikipedia chronicle
        "ru_day_heading": f"{d.day} {RU_MONTHS_GENITIVE[m]}",
        # Tuesday, June 17, 1941 — onwar.com day header
        "en_onwar_header": f"{EN_WEEKDAYS[d.weekday()]}, {EN_MONTHS[m]} {d.day}, {d.year}",
        # 194106 — onwar.com chronology page slug
        "onwar_yyyymm": d.strftime("%Y%m"),
        # 06/17/1941 — ww2db event/today slug
        "ww2db_slug": d.strftime("%m/%d/%Y"),
        # English month + year for the en.wikipedia timeline article
        "en_month": EN_MONTHS[m],
    }


def target() -> dict:
    """Convenience: describe(target_date())."""
    return describe(target_date())
