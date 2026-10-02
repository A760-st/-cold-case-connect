from dataclasses import dataclass
from datetime import date
import calendar
import re


@dataclass(frozen=True)
class ParsedDate:
    start: date | None
    end: date | None
    precision: str
    text: str


MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
MONTHS.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})
MONTH_RX = r"(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"


def parse_date(text: str | None) -> ParsedDate:
    raw = (text or "").strip()
    if not raw:
        return ParsedDate(None, None, "UNKNOWN", "")
    approximate = bool(re.search(r"\b(around|about|approximately|approx\.?|early|mid|late)\b", raw, re.I))
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", raw)
    if m:
        try:
            d = date(*map(int, m.groups()))
            return ParsedDate(d, d, "EXACT", raw)
        except ValueError: pass
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", raw)
    if m:
        try:
            d = date(int(m[3]), int(m[2]), int(m[1]))
            return ParsedDate(d, d, "EXACT", raw)
        except ValueError: pass
    m = re.search(rf"\b({MONTH_RX})\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", raw, re.I)
    if not m:
        m = re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({MONTH_RX}),?\s+(\d{{4}})\b", raw, re.I)
        if m:
            day, mon, year = int(m[1]), MONTHS[m[2].lower()[:3]], int(m[3])
        else: day = mon = year = None
    else: mon, day, year = MONTHS[m[1].lower()[:3]], int(m[2]), int(m[3])
    if day:
        try:
            d = date(year, mon, day)
            return ParsedDate(d, d, "APPROXIMATE" if approximate else "EXACT", raw)
        except ValueError: pass
    # Explicit day ranges within one month, e.g. April 10-15, 2026.
    m = re.search(rf"\b({MONTH_RX})\s+(\d{{1,2}})\s*[-–]\s*(\d{{1,2}}),?\s+(\d{{4}})\b", raw, re.I)
    if m:
        try:
            lo = date(int(m[4]), MONTHS[m[1].lower()[:3]], int(m[2])); hi = date(int(m[4]), lo.month, int(m[3]))
            return ParsedDate(lo, hi, "RANGE", raw) if hi >= lo else ParsedDate(None, None, "UNKNOWN", raw)
        except ValueError: pass
    m = re.search(rf"\b({MONTH_RX})\s+(\d{{4}})\b", raw, re.I)
    if m:
        year, month = int(m[2]), MONTHS[m[1].lower()[:3]]
        lo = date(year, month, 1); hi = date(year, month, calendar.monthrange(year, month)[1])
        if approximate:
            phrase = re.search(r"\b(early|mid|late)\b", raw, re.I)
            if phrase:
                p = phrase.group(1).lower()
                if p == "early": lo, hi = date(year, month, 1), date(year, month, min(10, calendar.monthrange(year, month)[1]))
                elif p == "mid": lo, hi = date(year, month, 11), date(year, month, min(20, calendar.monthrange(year, month)[1]))
                else: lo, hi = date(year, month, 21), date(year, month, calendar.monthrange(year, month)[1])
            return ParsedDate(lo, hi, "APPROXIMATE", raw)
        return ParsedDate(lo, hi, "MONTH", raw)
    m = re.search(r"\b(\d{4})\b", raw)
    if m:
        year = int(m[1])
        if 1000 <= year <= 9999:
            return ParsedDate(date(year, 1, 1), date(year, 12, 31), "YEAR", raw)
    return ParsedDate(None, None, "UNKNOWN", raw)
