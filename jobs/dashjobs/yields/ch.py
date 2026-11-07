"""Switzerland: SNB spot yields on Confederation bonds (1Y, 3Y, 5Y, 10Y, 30Y; the cube is published Mondays with data to the
previous Friday) plus money-market debt register claim auctions (3M, 6M) from the Federal Finance Administration workbook.
The workbook link carries a hash, so it is re-read from the SNB page each run."""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime

from .core import Auction, Raw, Series, window_start

META = {
    "code": "ch", "name": "Switzerland", "source": "Swiss National Bank (bond yields); Federal Finance Administration (bill auctions)",
    "source_url": "https://data.snb.ch/en/topics/ziredev/cube/rendeiduebd",
    "terms": "SNB: data may be used for non-commercial purposes with reference to the source; commercial use needs SNB consent.",
}
CUBE = "https://data.snb.ch/api/cube/rendeiduebd/data/csv/en"
PAGE = "https://marketoperations.snb.ch/en/mmdrc"
LINK = re.compile(r"https://www\.efv\.admin\.ch/dam/en/sd-web/[A-Za-z0-9_-]+/resultate-gmbf\.xlsx")
TEN = {"1J": "1Y", "3J": "3Y", "5J": "5Y", "10J": "10Y", "30J": "30Y"}
GAPS = {"1M": "Switzerland auctions no bill of about one month."}


def parse_cube(blob: bytes) -> dict[str, list[tuple[date, float]]]:
    out = {t: [] for t in TEN.values()}
    for r in csv.reader(io.StringIO(blob.decode("utf-8-sig")), delimiter=";"):
        if len(r) == 4 and r[2] in TEN and r[3].strip() not in ("", "Value"):
            try:
                out[TEN[r[2]]].append((date.fromisoformat(r[0]), float(r[3])))
            except ValueError:
                pass
    return out


def parse_auctions(blob: bytes, first_year: int) -> list[Auction]:
    """Columns are found by their English header on each sheet: sheets before 2026 carry an extra 'Series' column."""
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(blob), read_only=True, data_only=True)
    out = []
    for name in wb.sheetnames:
        if not name.isdigit() or int(name) < first_year:
            continue
        i_days = i_yield = None
        for r in wb[name].iter_rows(values_only=True):
            if r and r[0] == "Auction":
                heads = [str(c).strip() if c else "" for c in r]
                i_days, i_yield = heads.index("Maturity period (days)"), heads.index("Yield p.a.")
                continue
            if i_yield is None or len(r) <= i_yield:
                continue
            if isinstance(r[0], datetime) and isinstance(r[1], datetime) and isinstance(r[i_days], (int, float))                     and isinstance(r[i_yield], (int, float)):
                out.append(Auction(r[0].date(), int(r[i_days]), float(r[i_yield]) * 100.0, r[1].date()))   # yield is a fraction
    return out


def fetch(g, today: date, env=None, prev=None) -> Raw:
    start = window_start(today)
    cube = parse_cube(g.get(CUBE, params={"fromDate": start.isoformat(), "dimSel": "D0(CHF)"}))
    page = g.get(PAGE).decode("utf-8", errors="replace")
    m = LINK.search(page)
    if not m:
        raise ValueError("SNB page no longer links the auction workbook (resultate-gmbf.xlsx)")
    aus = parse_auctions(g.get(m.group(0)), start.year - 1)
    raw = Raw(gaps=dict(GAPS))
    for t, pts in cube.items():
        raw.series[t] = [Series("D", pts, max_lag=5)]
    raw.auctions = {"1M": aus, "3M": aus, "6M": aus}
    return raw
