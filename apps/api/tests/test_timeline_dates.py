from datetime import date
from app.timeline.date_parser import parse_date

def test_exact_dates_and_multiple_formats():
    for value, expected in [("2026-04-17",date(2026,4,17)),("17/04/2026",date(2026,4,17)),("April 17, 2026",date(2026,4,17)),("17 April 2026",date(2026,4,17))]:
        result=parse_date(value);assert result.start==expected and result.end==expected and result.precision=="EXACT" and result.text==value

def test_month_and_year_preserve_precision():
    month=parse_date("April 2026");assert (month.start,month.end,month.precision)==(date(2026,4,1),date(2026,4,30),"MONTH")
    year=parse_date("2026");assert (year.start,year.end,year.precision)==(date(2026,1,1),date(2026,12,31),"YEAR")

def test_ranges_and_approximate_phrases_are_not_promoted_to_exact():
    span=parse_date("April 10-15, 2026");assert (span.start,span.end,span.precision)==(date(2026,4,10),date(2026,4,15),"RANGE")
    approx=parse_date("around April 2026");assert approx.precision=="APPROXIMATE" and approx.start==date(2026,4,1) and approx.end==date(2026,4,30)
    late=parse_date("late April 2026");assert late.precision=="APPROXIMATE" and late.start==date(2026,4,21)

def test_unknown_date_is_never_invented():
    result=parse_date("recently");assert result.start is None and result.end is None and result.precision=="UNKNOWN" and result.text=="recently"
