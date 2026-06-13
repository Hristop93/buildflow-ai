"""Bulgarian working-day calendar for the schedule.

Statutory terms in ЗУТ are often counted in working days (работни дни), so a
procedure can be marked term_basis='working' and its calendar span is computed
here, skipping weekends and national public holidays (incl. the movable
Orthodox Easter span). Pure calendar-day procedures don't touch this.
"""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache


def orthodox_easter(year: int) -> date:
    """Gregorian date of Orthodox Easter Sunday (valid 1900–2099)."""
    a, b, c = year % 4, year % 7, year % 19
    d = (19 * c + 15) % 30
    e = (2 * a + 4 * b - d + 34) % 7
    month = (d + e + 114) // 31
    day = ((d + e + 114) % 31) + 1
    return date(year, month, day) + timedelta(days=13)  # Julian -> Gregorian


def _fixed_holidays(year: int) -> set[date]:
    return {
        date(year, 1, 1),    # Нова година
        date(year, 3, 3),    # Освобождение
        date(year, 5, 1),    # Ден на труда
        date(year, 5, 6),    # Гергьовден / Ден на храбростта
        date(year, 5, 24),   # Просвета и култура
        date(year, 9, 6),    # Съединение
        date(year, 9, 22),   # Независимост
        date(year, 12, 24),  # Бъдни вечер
        date(year, 12, 25),  # Коледа
        date(year, 12, 26),  # Коледа
    }


@lru_cache(maxsize=None)
def holidays_for_year(year: int) -> frozenset:
    days = _fixed_holidays(year)
    easter = orthodox_easter(year)
    # Велики петък .. Велик понеделник are non-working in BG.
    for offset in (-2, -1, 0, 1):
        days.add(easter + timedelta(days=offset))
    return frozenset(days)


def holidays_in_range(first_year: int, last_year: int) -> set[date]:
    out: set[date] = set()
    for y in range(first_year, last_year + 1):
        out |= holidays_for_year(y)
    return out


def is_working_day(d: date, holidays: set[date]) -> bool:
    return d.weekday() < 5 and d not in holidays


def add_working_days(start: date, n: int, holidays: set[date]) -> date:
    """Return the date `n` working days after `start` (the calendar end of a
    task that occupies n working days). n <= 0 -> start."""
    d = start
    remaining = n
    while remaining > 0:
        d += timedelta(days=1)
        if is_working_day(d, holidays):
            remaining -= 1
    return d
