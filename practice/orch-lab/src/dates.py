def is_leap_year(year: int) -> bool:
    # Planted bug: ignores the 100/400 rule (1900 is not a leap year, 2000 is).
    return year % 4 == 0


def days_in_month(year: int, month: int) -> int:
    if month == 2:
        return 29 if is_leap_year(year) else 28
    return 30 if month in (4, 6, 9, 11) else 31
