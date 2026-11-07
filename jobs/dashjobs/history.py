"""Chart series published for the front end. Pure functions, no I/O. Only INDEXED levels are published, never prices.

Rebased chart (`history/<section>.json`)
  - One series per fund: levels indexed to 100 at the series' first point. The page re-bases to the chosen period.
  - Window: from the last close on or before the 10Y calendar anchor (or the fund's first close, if younger) to the last close.
  - Points: every trading day from the 1Y start; for older dates the last close of each ISO week. The start bar of the 3Y, 5Y
    and 10Y look-backs is always kept, so a period starts on exactly the bar the heatmap uses (same anchor rule).

Indicator chart (`indicators/<section>.json`)
  - Computed on the adjusted close over trading days, on the fund's full history, then cut to the last two years.
  - level (indexed to 100 at the window start), 50- and 200-day simple moving averages (same index), 14-day RSI with Wilder's smoothing.
"""
from __future__ import annotations

import math
from bisect import bisect_right
from datetime import date

from .lookback import anchor_for

EPOCH_ORDINAL = date(1970, 1, 1).toordinal()
RSI_PERIOD = 14


def epoch_day(d: date) -> int:
    return d.toordinal() - EPOCH_ORDINAL


def _r(x: float) -> float:
    """Level precision: 2 decimals, 3 below 10 (keeps the end-point within 0.05 pp of the heatmap figure)."""
    return round(x, 2 if abs(x) >= 10 else 3)


def sma(values: list[float], n: int) -> list[float | None]:
    """Simple moving average over n trading rows; None until n rows exist. (TA-Lib MA/SMA.)"""
    out: list[float | None] = [None] * len(values)
    if n <= 0 or len(values) < n:
        return out
    s = sum(values[:n])
    out[n - 1] = s / n
    for i in range(n, len(values)):
        s += values[i] - values[i - n]
        out[i] = s / n
    return out


def rsi_wilder(values: list[float], n: int = RSI_PERIOD) -> list[float | None]:
    """RSI with Wilder's smoothing, as TA-Lib's RSI: the first average gain/loss is the simple mean of the first n changes
    (so the first value sits at index n); after that avg = (previous * (n - 1) + current) / n. RSI = 100 * gain / (gain + loss).
    One deliberate difference: when gain + loss is exactly zero (no movement at all) TA-Lib returns 0; this returns None
    (RSI is undefined for a flat series, and 0 would read as 'oversold')."""
    out: list[float | None] = [None] * len(values)
    if len(values) <= n:
        return out
    gain = loss = 0.0
    for i in range(1, n + 1):
        ch = values[i] - values[i - 1]
        gain += max(ch, 0.0)
        loss += max(-ch, 0.0)
    gain /= n
    loss /= n

    def val() -> float | None:
        tot = gain + loss
        return None if tot == 0 else 100.0 * gain / tot

    out[n] = val()
    for i in range(n + 1, len(values)):
        ch = values[i] - values[i - 1]
        gain = (gain * (n - 1) + max(ch, 0.0)) / n
        loss = (loss * (n - 1) + max(-ch, 0.0)) / n
        out[i] = val()
    return out


def _start_index(dates: list[date], end: date, key: str) -> int:
    """Index of the last close on or before the key's calendar anchor; 0 if the series starts after the anchor."""
    return max(bisect_right(dates, anchor_for(end, key)) - 1, 0)


def history_points(bars: list[tuple[date, float]]) -> dict:
    """bars: cleaned, ascending. Returns {"d": [epoch days], "v": [levels]}."""
    dates = [d for d, _ in bars]
    closes = [c for _, c in bars]
    n = len(bars)
    end = dates[-1]
    i0 = _start_index(dates, end, "10Y")
    i1 = max(_start_index(dates, end, "1Y"), i0)
    keep = set(range(i1, n))
    week_last: dict[tuple[int, int], int] = {}
    for i in range(i0, i1):
        iso = dates[i].isocalendar()
        week_last[(iso[0], iso[1])] = i
    keep |= set(week_last.values())
    for key in ("3Y", "5Y", "10Y"):
        if dates[0] <= anchor_for(end, key):
            keep.add(_start_index(dates, end, key))
    keep.add(i0)
    idx = sorted(keep)
    base = closes[i0]
    return {"d": [epoch_day(dates[i]) for i in idx], "v": [_r(100.0 * closes[i] / base) for i in idx]}


def indicator_points(bars: list[tuple[date, float]], years_key: str = "2Y") -> dict:
    """bars: cleaned, ascending, FULL history. Returns the last `years_key` of daily level / MA50 / MA200 / RSI14."""
    dates = [d for d, _ in bars]
    closes = [c for _, c in bars]
    ma50, ma200, rsi = sma(closes, 50), sma(closes, 200), rsi_wilder(closes, RSI_PERIOD)
    i0 = _start_index(dates, dates[-1], years_key)
    k = 100.0 / closes[i0]

    def lv(x):
        return None if x is None else _r(x * k)

    rng = range(i0, len(bars))
    return {
        "d": [epoch_day(dates[i]) for i in rng],
        "p": [_r(closes[i] * k) for i in rng],
        "ma50": [lv(ma50[i]) for i in rng],
        "ma200": [lv(ma200[i]) for i in rng],
        "rsi": [None if rsi[i] is None else round(rsi[i], 1) for i in rng],
    }


def finite(x) -> bool:
    return x is None or (isinstance(x, (int, float)) and math.isfinite(x))
