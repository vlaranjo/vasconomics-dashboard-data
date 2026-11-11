"""Australia: Reserve Bank of Australia statistical tables (checked 11 Nov 2026, plain requests, CSV).

F2  "Capital Market Yields - Government Bonds - Daily" (f2-data.csv): the RBA's interpolated 3, 5 and 10-year Australian Government
    bond yields (series FCMYGBAG3D, FCMYGBAG5D, FCMYGBAG10D), daily, published weekly (06-Nov-2026 file runs to 04-Nov-2026). D.
F16 "Indicative Mid Rates of Australian Government Securities" (f16-data.csv): one daily column per Treasury Bond, its coupon and
    maturity in the Description row. 1Y and 30Y have no F2 series, so each date takes the Treasury Bond whose remaining maturity
    is inside the tenor's window (1Y: 0.8-1.2 years, 30Y: 25-35 years), the one closest to the tenor if several are. A labelled
    bucket (B): the label names the bond and its remaining years, and changes with the date. Treasury Indexed Bonds are never used.
1M, 3M, 6M are GAPS: F1's Treasury Note columns stopped (3M and 6M in May 2013, 1M in Dec 2022) and the AOFM's Treasury Note tender
results could not be read (www.aofm.gov.au gave no answer at all to plain requests on 11 Nov 2026, two 60-second timeouts; not
pursued). Bank bills (BABs/NCDs) and OIS are not government yields and are never used.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date

from .core import YEAR_DAYS, Raw, Series, window_start

META = {
    "code": "au", "name": "Australia",
    "source": "Reserve Bank of Australia, statistical tables F2 (government bond yields) and F16 (indicative mid rates of Treasury Bonds)",
    "source_url": "https://www.rba.gov.au/statistics/tables/",
    "terms": "RBA material is under CC BY 4.0 unless noted; Financial Data may be used for personal or commercial use if no RBA "
             "endorsement is implied; attribution 'Source: Reserve Bank of Australia [year]' or 'Source: RBA [year]'.",
    "status": "ok",
}
F2 = "https://www.rba.gov.au/statistics/tables/csv/f2-data.csv"
F16 = "https://www.rba.gov.au/statistics/tables/csv/f16-data.csv"
F2_IDS = {"3Y": "FCMYGBAG3D", "5Y": "FCMYGBAG5D", "10Y": "FCMYGBAG10D"}
BUCKETS = {"1Y": (1.0, 0.8, 1.2), "30Y": (30.0, 25.0, 35.0)}          # tenor -> (target, low, high) in years left
SHORT_GAP = ("The RBA's Treasury Note yields (table F1) stopped in 2013 (3M, 6M) and 2022 (1M), and the AOFM's Treasury Note "
             "tender results could not be read without a browser (its site did not answer plain requests); left empty.")
GAPS = {"1M": SHORT_GAP, "3M": SHORT_GAP, "6M": SHORT_GAP}
MON = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def _d(s: str) -> date | None:
    m = re.fullmatch(r"(\d{2})-([A-Z][a-z]{2})-(\d{4})", s.strip())
    return date(int(m.group(3)), MON[m.group(2)], int(m.group(1))) if m and m.group(2) in MON else None


def _table(blob: bytes) -> tuple[dict[str, list[str]], list[list[str]]]:
    """(header rows by their first cell, data rows) of an RBA statistical table CSV."""
    rows = list(csv.reader(io.StringIO(blob.decode("utf-8-sig", errors="replace"))))
    head = {r[0].strip(): r for r in rows if r and r[0].strip() and not _d(r[0])}
    if "Series ID" not in head:
        raise ValueError("RBA table: no 'Series ID' row (layout changed)")
    return head, [r for r in rows if r and _d(r[0])]


def parse_f2(blob: bytes) -> dict[str, list[tuple[date, float]]]:
    head, data = _table(blob)
    ids = [c.strip() for c in head["Series ID"]]
    col = {t: ids.index(s) for t, s in F2_IDS.items() if s in ids}
    if len(col) != len(F2_IDS):
        raise ValueError(f"F2: series missing ({sorted(set(F2_IDS.values()) - set(ids))})")
    out = {t: [] for t in col}
    for r in data:
        d = _d(r[0])
        for t, i in col.items():
            if i < len(r) and r[i].strip():
                out[t].append((d, float(r[i])))
    return out


def parse_f16(blob: bytes) -> tuple[list[dict], list[list[str]]]:
    """Treasury Bond columns ({col, name, coupon, maturity}) and the data rows."""
    head, data = _table(blob)
    bonds = []
    for i, (title, desc) in enumerate(zip(head["Title"], head["Description"])):
        if i == 0 or title.strip() != "Treasury Bond":
            continue
        m = re.fullmatch(r"(Treasury Bond \d+) ([\d.]+%) (\d{2}-[A-Z][a-z]{2}-\d{4})", desc.strip())
        if not m:
            raise ValueError(f"F16: Description not recognised: {desc[:60]!r}")
        bonds.append({"col": i, "name": m.group(1), "coupon": m.group(2), "maturity": _d(m.group(3))})
    if not bonds:
        raise ValueError("F16: no Treasury Bond columns")
    return bonds, data


def bucket_series(bonds: list[dict], data: list[list[str]], tenor: str, since: date) -> Series:
    target, lo, hi = BUCKETS[tenor]
    pts, labels = [], {}
    for r in data:
        d = _d(r[0])
        if d < since:
            continue
        best = None
        for b in bonds:
            i = b["col"]
            if i >= len(r) or not r[i].strip():
                continue
            left = (b["maturity"] - d).days / YEAR_DAYS
            if lo <= left <= hi and (best is None or abs(left - target) < abs(best[1] - target)):
                best = (b, left, float(r[i]))
        if best:
            b, left, v = best
            pts.append((d, v))
            labels[d] = f"{b['name']} ({b['coupon']}, {b['maturity'].day} {b['maturity'].strftime('%b %Y')}), {left:.1f} years left"
    return Series("B", pts, max_lag=5, labels=labels)


def fetch(g, today: date, env=None, prev=None) -> Raw:
    since = window_start(today)
    raw = Raw(gaps=dict(GAPS))
    for t, pts in parse_f2(g.get(F2)).items():
        raw.series[t] = [Series("D", [p for p in pts if p[0] >= since], max_lag=5)]
    bonds, data = parse_f16(g.get(F16))
    for t in BUCKETS:
        s = bucket_series(bonds, data, t, since)
        if s.points:
            raw.series[t] = [s]
        else:
            raw.gaps[t] = f"No Treasury Bond in F16 has {BUCKETS[t][1]:g}-{BUCKETS[t][2]:g} years left; left empty."
    return raw
