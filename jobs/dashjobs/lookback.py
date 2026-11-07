"""D7 lookback rule (decisions.md D7 / F7). Pure functions, no I/O.

- End = the instrument's last close in the run (never "today").
- 1D = previous trading row.
- 1W = end - 7 calendar days; 1M/3M/6M = end - n calendar months; 1Y..10Y = end - n calendar years.
- Month/year arithmetic clamps to the last day of the month (relativedelta does this).
- Start = last close ON OR BEFORE the anchor.
- If the first close is after the anchor: n/a (status "na_young") with a since-launch return.
- A bar only counts once it is COMPLETED (see `last_completed_date`): never a live quote.
- Stale: last close 2 OR MORE business days (Mon-Fri, no holiday calendar) behind the section's latest.
"""
from __future__ import annotations

import math
from bisect import bisect_right
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable

from dateutil.relativedelta import relativedelta

LOOKBACKS = ["1D", "1W", "1M", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "10Y"]

_SPAN = {
    "1W": relativedelta(days=7),
    "1M": relativedelta(months=1),
    "3M": relativedelta(months=3),
    "6M": relativedelta(months=6),
    "1Y": relativedelta(years=1),
    "2Y": relativedelta(years=2),
    "3Y": relativedelta(years=3),
    "5Y": relativedelta(years=5),
    "10Y": relativedelta(years=10),
}

STALE_BUSINESS_DAYS = 2  # "2 or more" (decisions F7)


def clean_bars(bars: Iterable[tuple[date, float]], run_date: date | None = None) -> list[tuple[date, float]]:
    """Sort by date, keep the last bar per date, drop non-finite / non-positive closes and bars after run_date."""
    by_date: dict[date, float] = {}
    for d, c in bars:
        try:
            c = float(c)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(c) or c <= 0:
            continue
        if run_date is not None and d > run_date:
            continue
        by_date[d] = c
    return sorted(by_date.items())


def anchor_for(end: date, key: str) -> date:
    return end - _SPAN[key]


def _pct(end_close: float, start_close: float) -> float:
    return round((end_close / start_close - 1.0) * 100.0, 2)


def compute_returns(bars: list[tuple[date, float]]) -> dict:
    """bars: cleaned, ascending. Returns {lookback: {value, start, status[, since_launch]}}."""
    out: dict = {}
    n = len(bars)
    if n == 0:
        return {k: {"value": None, "start": None, "status": "na_missing"} for k in LOOKBACKS}
    dates = [d for d, _ in bars]
    closes = [c for _, c in bars]
    end_d, end_c = dates[-1], closes[-1]
    first_d, first_c = dates[0], closes[0]
    since = None
    if n >= 2:
        since = {"value": _pct(end_c, first_c), "start": first_d.isoformat()}
    for key in LOOKBACKS:
        if key == "1D":
            if n >= 2:
                out[key] = {"value": _pct(end_c, closes[-2]), "start": dates[-2].isoformat(), "status": "ok"}
            else:
                out[key] = {"value": None, "start": None, "status": "na_missing"}
            continue
        anchor = anchor_for(end_d, key)
        if first_d > anchor:
            cell = {"value": None, "start": None, "status": "na_young"}
            if since is not None:
                cell["since_launch"] = dict(since)
            out[key] = cell
            continue
        i = bisect_right(dates, anchor) - 1  # last close on or before the anchor
        out[key] = {"value": _pct(end_c, closes[i]), "start": dates[i].isoformat(), "status": "ok"}
    return out


def business_days_behind(last_close: date, latest: date) -> int:
    """Mon-Fri days after last_close up to and including latest. 29 Oct vs 2 Nov -> Fri 30, Mon 2 = 2."""
    if last_close >= latest:
        return 0
    n = 0
    d = last_close
    while d < latest:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def is_stale_close(last_close: date, section_latest: date) -> bool:
    return business_days_behind(last_close, section_latest) >= STALE_BUSINESS_DAYS


# ---- completed bars (decisions: "Completed daily bars", 7 Nov 2026) --------------------------------------------------
FUND_BAR_COMPLETE_UTC_HOUR = 17     # every fund line trades on Xetra, Borsa Italiana or Euronext, all closed by 16:45 UTC at the latest
SCHEDULED_RUN_UTC = time(22, 37)    # a run described only by its date is taken to be the scheduled evening run


def _last_sunday(year: int, month: int) -> date:
    d = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
    return d - timedelta(days=(d.weekday() + 1) % 7)


def london_date(now_utc: datetime) -> date:
    """Calendar date in London (BST from 01:00 UTC on the last Sunday of March to 01:00 UTC on the last Sunday of October).
    Computed by hand so the job does not depend on a time-zone database."""
    y = now_utc.year
    start = datetime.combine(_last_sunday(y, 3), time(1), tzinfo=timezone.utc)
    end = datetime.combine(_last_sunday(y, 10), time(1), tzinfo=timezone.utc)
    return (now_utc + timedelta(hours=1)).date() if start <= now_utc < end else now_utc.date()


def last_completed_date(kind: str, today: date, now: datetime | None = None) -> date:
    """The latest bar date that may be used: a bar is COMPLETED when its trading day is over.

    - Fund (exchange-traded) bars: the day's bar is complete once the run is at or after 17:00 UTC (all closes are earlier);
      before that, only yesterday's bar.
    - FX bars: Yahoo's daily FX bar is a London calendar day (hourly bars run 00:00 to 23:00 London time). It is complete only
      after London midnight, so the latest usable bar is the one before the run's London date. Friday's bar therefore arrives
      with the Saturday repair run.
    - Yahoo also appends a live quote as a bar stamped with a time of day; that is removed in `yahoo._normalise` and, by
      this rule, would in any case be dated today and excluded for FX.
    `now` is the run time; when it does not fall on `today` (tests, backfills), the run is taken to be the 22:37 UTC evening run of `today`."""
    if now is None or now.astimezone(timezone.utc).date() != today:
        ref = datetime.combine(today, SCHEDULED_RUN_UTC, tzinfo=timezone.utc)
    else:
        ref = now.astimezone(timezone.utc)
    if kind == "fx":
        return london_date(ref) - timedelta(days=1)
    return ref.date() if ref.hour >= FUND_BAR_COMPLETE_UTC_HOUR else ref.date() - timedelta(days=1)
