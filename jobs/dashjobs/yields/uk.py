"""United Kingdom: Bank of England nominal spot curve (GLC). 6M, 1Y, 3Y, 5Y, 10Y, 30Y daily. 1M and 3M are not published
by the Bank; the DMO Treasury bill tenders sit behind bot protection (docs/yield-sources.md), so those stay empty."""
from __future__ import annotations

import io
import zipfile
from datetime import date, datetime

from .core import Raw, Series, window_start

META = {
    "code": "uk", "name": "United Kingdom", "source": "Bank of England, nominal spot curve (GLC)",
    "source_url": "https://www.bankofengland.co.uk/statistics/yield-curves",
    "terms": "Bank of England database: re-use for non-commercial purposes; credit 'Source: Bank of England'.",
}
LATEST = "https://www.bankofengland.co.uk/-/media/boe/files/statistics/yield-curves/latest-yield-curve-data.zip"
HISTORY = "https://www.bankofengland.co.uk/-/media/boe/files/statistics/yield-curves/glcnominalddata.zip"
YEARS = {"6M": 0.5, "1Y": 1, "3Y": 3, "5Y": 5, "10Y": 10, "30Y": 30}
GAPS = {"1M": "The Bank of England publishes no spot point below 6 months with regular data.",
        "3M": "The Bank of England publishes no spot point below 6 months with regular data."}


def parse_xlsx(blob: bytes) -> dict[str, list[tuple[date, float]]]:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(blob), read_only=True, data_only=True)
    ws = wb["4. spot curve"]
    cols: dict[str, int] = {}
    out = {t: [] for t in YEARS}
    for row in ws.iter_rows(values_only=True):
        if row and row[0] == "years:":
            for t, y in YEARS.items():
                for i, v in enumerate(row):
                    if isinstance(v, (int, float)) and abs(v - y) < 1e-9:
                        cols[t] = i
            continue
        if row and isinstance(row[0], datetime) and cols:
            d = row[0].date()
            for t, i in cols.items():
                v = row[i] if i < len(row) else None
                if isinstance(v, (int, float)):
                    out[t].append((d, float(v)))
    if not cols:
        raise ValueError("BoE spot curve sheet: no 'years:' header row found")
    return out


def _member(z: zipfile.ZipFile, suffix: str) -> bytes:
    """The nominal file only: the current-month zip also holds the Inflation, Real and OIS files with the same layout."""
    names = [n for n in z.namelist() if n.lower().endswith(suffix.lower()) and "nominal" in n.lower()]
    if not names:
        raise ValueError(f"no nominal member ending '{suffix}' in {z.namelist()[:5]}")
    return z.read(names[0])


def fetch(g, today: date, env=None, prev=None) -> Raw:
    latest = parse_xlsx(_member(zipfile.ZipFile(io.BytesIO(g.get(LATEST))), "current month.xlsx"))
    hist = parse_xlsx(_member(zipfile.ZipFile(io.BytesIO(g.get(HISTORY))), "to present.xlsx"))
    raw = Raw(gaps=dict(GAPS))
    start = window_start(today)
    for t in YEARS:
        merged = {d: v for d, v in hist[t] if d >= start}
        merged.update({d: v for d, v in latest[t]})      # the current-month file is newer than the history file
        raw.series[t] = [Series("D", list(merged.items()), max_lag=5)]
    return raw
