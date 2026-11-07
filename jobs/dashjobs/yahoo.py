"""Yahoo adapter: fetch daily history and normalise to [(date, adjclose)]. Kept swappable (decisions D6)."""
from __future__ import annotations

import time
from datetime import date, datetime


class FetchError(Exception):
    pass


def _normalise(df) -> list[tuple[date, float]]:
    import pandas as pd

    if df is None or not hasattr(df, "reset_index") or len(df) == 0:
        return []
    d = df.reset_index()
    col = "adjclose" if "adjclose" in d.columns else "close"
    raw = list(d["date"])
    # Yahoo marks completed daily bars with a plain date; the bar still being traded is appended with a time-of-day stamp.
    stamped = [isinstance(v, datetime) and (v.hour, v.minute, v.second) != (0, 0, 0) for v in raw]
    dt = pd.to_datetime(d["date"], utc=True).dt.tz_convert("Europe/Berlin").dt.date
    keep = [not (i == len(raw) - 1 and stamped[i] and len(raw) > 1 and not stamped[i - 1]) for i in range(len(raw))]
    return [(a, float(b)) for a, b, k in zip(dt, d[col], keep) if k and b == b]


def fetch_history(symbol: str, retries: int = 3, delay: float = 3.0, sleep=time.sleep) -> list[tuple[date, float]]:
    """Daily adjusted closes for one symbol, max history. Retries with a growing delay (Yahoo throttles shared IPs)."""
    from yahooquery import Ticker

    last_err = None
    for attempt in range(1, retries + 1):
        try:
            hist = Ticker(symbol).history(period="max")
            if isinstance(hist, dict) or hist is None:
                raise FetchError(f"{symbol}: {hist}")
            bars = _normalise(hist)
            if bars:
                return bars
            last_err = FetchError(f"{symbol}: empty history")
        except Exception as e:  # noqa: BLE001 - any failure is a retry
            last_err = e
        if attempt < retries:
            sleep(delay * attempt)
    raise FetchError(f"{symbol}: failed after {retries} tries: {last_err}")
