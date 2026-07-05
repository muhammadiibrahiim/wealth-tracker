"""
Utility functions for date handling, formatting, and slug generation
"""
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from decimal import Decimal, ROUND_HALF_UP
import re


def normalize_slug(name: str) -> str:
    """
    Normalize asset name to slug for uniqueness checks
    Lowercase, strip spaces, replace spaces with hyphens
    """
    slug = name.strip().lower()
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[-\s]+', '-', slug)
    return slug.strip('-')


def parse_year_month(year_month: str) -> date:
    """
    Parse YYYY-MM string to date object (first day of month)
    """
    try:
        dt = datetime.strptime(year_month, "%Y-%m")
        return date(dt.year, dt.month, 1)
    except ValueError:
        raise ValueError(f"Invalid year_month format: {year_month}. Expected YYYY-MM")


def format_year_month(dt: date) -> str:
    """
    Format date to YYYY-MM string
    """
    return dt.strftime("%Y-%m")


def prev_year_month(year_month: str) -> str:
    """
    Get the previous month as YYYY-MM string
    """
    dt = parse_year_month(year_month)
    prev_dt = dt - relativedelta(months=1)
    return format_year_month(prev_dt)


def next_year_month(year_month: str) -> str:
    """
    Get the next month as YYYY-MM string
    """
    dt = parse_year_month(year_month)
    next_dt = dt + relativedelta(months=1)
    return format_year_month(next_dt)


def get_current_year_month() -> str:
    """
    Get current month as YYYY-MM string
    """
    return format_year_month(date.today())


def month_diff(start: str, end: str) -> int:
    """
    Calculate number of months between two year-month strings (inclusive of start, exclusive of end)
    """
    start_dt = parse_year_month(start)
    end_dt = parse_year_month(end)
    return (end_dt.year - start_dt.year) * 12 + (end_dt.month - start_dt.month)


def quantize_decimal(value: Decimal | float, places: int = 2) -> Decimal:
    """
    Quantize decimal to specified decimal places
    """
    if isinstance(value, float):
        value = Decimal(str(value))
    quantizer = Decimal(10) ** -places
    return value.quantize(quantizer, rounding=ROUND_HALF_UP)


def format_currency(value: Decimal | float) -> str:
    """
    Format value as currency string (PKR)
    """
    if isinstance(value, float):
        value = Decimal(str(value))
    value = quantize_decimal(value)
    return f"Rs {value:,.2f}"


def format_delta(value: Decimal | float) -> str:
    """
    Format delta with sign and currency (PKR)
    """
    if isinstance(value, float):
        value = Decimal(str(value))
    value = quantize_decimal(value)
    sign = "+" if value >= 0 else ""
    return f"{sign}Rs {value:,.2f}"


def months_in_range(start: str | None, end: str | None) -> list[str]:
    """
    Generate list of year-month strings in range [start, end] inclusive
    If start or end is None, return empty list (caller should handle)
    """
    if start is None or end is None:
        return []
    
    result = []
    current = start
    end_dt = parse_year_month(end)
    
    while True:
        current_dt = parse_year_month(current)
        if current_dt > end_dt:
            break
        result.append(current)
        current = next_year_month(current)
    
    return result
