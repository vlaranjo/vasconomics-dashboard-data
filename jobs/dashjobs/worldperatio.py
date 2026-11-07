"""worldperatio.com adapter: plain HTTP, parse detailPE_data (decisions D11 / F9)."""
from __future__ import annotations

import re
from datetime import date

import requests


class ParseError(Exception):
    pass


_BLOCK = re.compile(r"detailPE_data\s*=\s*\[(.*?)\]\s*;", re.S)
_POINT = re.compile(r"Date\.UTC\(\s*(\d{4})\s*,\s*(\d{1,2})\s*,\s*(\d{1,2})\s*\)\s*,\s*(-?[0-9]*\.?[0-9]+)")


def fetch_page(url: str, user_agent: str, timeout: int = 40) -> str:
    r = requests.get(url, headers={"User-Agent": user_agent}, timeout=timeout)
    r.raise_for_status()
    return r.text


def parse_series(html: str) -> list[tuple[str, float]]:
    """Return [("YYYY-MM", value), ...]. Date.UTC months are zero-based, so month = m + 1."""
    m = _BLOCK.search(html)
    if not m:
        raise ParseError("detailPE_data not found")
    pts = _POINT.findall(m.group(1))
    if not pts:
        raise ParseError("detailPE_data has no points")
    return [(f"{int(y):04d}-{int(mo) + 1:02d}", float(v)) for y, mo, _d, v in pts]


def validate_series(series: list[tuple[str, float]], run_date: date, first_point: str | None = None) -> None:
    """Per-index checks (m1-plan section 4). Raises ParseError."""
    if len(series) < 200:
        raise ParseError(f"only {len(series)} points (need at least 200)")
    prev = None
    for ym, v in series:
        y, mo = int(ym[:4]), int(ym[5:7])
        idx = y * 12 + mo
        if prev is not None and idx != prev + 1:
            raise ParseError(f"dates not strictly monthly at {ym}")
        prev = idx
        if not (0 < v < 500):
            raise ParseError(f"value {v} out of range at {ym}")
    ly, lm = int(series[-1][0][:4]), int(series[-1][0][5:7])
    last = date(ly, lm, 1)
    if (run_date - last).days > 45:  # the last point is dated the first of its month
        raise ParseError(f"last point {series[-1][0]} is too old for run date {run_date}")
    if first_point and series[0][0] != first_point:
        raise ParseError(f"first point {series[0][0]} != expected {first_point}")


def averages(series: list[tuple[str, float]]) -> tuple[float, float]:
    vals = [v for _, v in series]
    last120 = vals[-120:]
    return round(sum(last120) / len(last120), 2), round(sum(vals) / len(vals), 2)
