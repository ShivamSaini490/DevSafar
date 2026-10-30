import re
from datetime import date, datetime, time, timedelta, timezone

INDIA_TIME_ZONE = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")

_DATE_WITH_YEAR_FORMATS = (
    "%d %b %Y",
    "%d %B %Y",
    "%b %d %Y",
    "%B %d %Y",
    "%d/%m/%Y",
)
_DATE_WITHOUT_YEAR_FORMATS = ("%d %b", "%d %B", "%b %d", "%B %d")
_DATETIME_WITH_YEAR_FORMATS = tuple(
    f"{date_format} {time_format}"
    for date_format in _DATE_WITH_YEAR_FORMATS
    for time_format in ("%H:%M", "%I:%M %p", "%I %p")
)
_DATETIME_WITHOUT_YEAR_FORMATS = tuple(
    f"{date_format} {time_format}"
    for date_format in _DATE_WITHOUT_YEAR_FORMATS
    for time_format in ("%H:%M", "%I:%M %p", "%I %p")
)


def india_today() -> date:
    return datetime.now(INDIA_TIME_ZONE).date()


def _clean_human_datetime(value: str) -> str:
    cleaned = re.sub(r"(?i)(\d)(st|nd|rd|th)\b", r"\1", value.strip())
    cleaned = re.sub(r"(?i)\s+IST$", "", cleaned)
    return " ".join(cleaned.replace(",", " ").split())


def _roll_forward_year(value: date, *, not_before: date) -> date:
    candidate = value
    while candidate < not_before:
        candidate = candidate.replace(year=candidate.year + 1)
    return candidate


def parse_lenient_date(
    value: str,
    *,
    current_date: date,
    not_before: date | None = None,
) -> date:
    """Parse common model date strings and infer a missing future year."""

    cleaned = _clean_human_datetime(value)
    try:
        return date.fromisoformat(cleaned)
    except ValueError:
        pass
    for date_format in _DATE_WITH_YEAR_FORMATS:
        try:
            return datetime.strptime(cleaned, date_format).date()
        except ValueError:
            continue
    threshold = not_before or current_date
    for date_format in _DATE_WITHOUT_YEAR_FORMATS:
        try:
            parsed = datetime.strptime(cleaned, date_format).date()
        except ValueError:
            continue
        candidate = parsed.replace(year=current_date.year)
        return _roll_forward_year(candidate, not_before=threshold)
    raise ValueError("Unsupported date format")


def parse_lenient_india_datetime(
    value: str,
    *,
    current_date: date,
    not_before: date | None = None,
) -> datetime:
    """Parse common model deadlines and normalize them to Asia/Kolkata."""

    cleaned = _clean_human_datetime(value)
    try:
        return as_india_time(datetime.fromisoformat(cleaned.replace("Z", "+00:00")))
    except ValueError:
        pass
    for datetime_format in _DATETIME_WITH_YEAR_FORMATS:
        try:
            return as_india_time(datetime.strptime(cleaned, datetime_format))
        except ValueError:
            continue
    threshold = not_before or current_date
    for datetime_format in _DATETIME_WITHOUT_YEAR_FORMATS:
        try:
            parsed = datetime.strptime(cleaned, datetime_format)
        except ValueError:
            continue
        candidate = parsed.replace(year=current_date.year)
        candidate_date = _roll_forward_year(candidate.date(), not_before=threshold)
        return as_india_time(candidate.replace(year=candidate_date.year))
    raise ValueError("Unsupported datetime format")


def as_india_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=INDIA_TIME_ZONE)
    return value.astimezone(INDIA_TIME_ZONE)


def at_india_time(value: date, *, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(
        value,
        time(hour=hour, minute=minute),
        tzinfo=INDIA_TIME_ZONE,
    )
