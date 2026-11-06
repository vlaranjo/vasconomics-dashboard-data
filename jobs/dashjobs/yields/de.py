"""Germany: Bundesbank term structure of listed federal securities (Svensson), 6M (0.5Y), 1Y, 3Y, 5Y, 10Y, 30Y daily, and
Bubill auction yields for 3M from the Finanzagentur results workbook. A Bubill is issued with 12 months and re-opened
at 11, 9, 6, 5 and 3 months, so a re-opening with about 3 months left is a 3M auction. Settlement is auction day
plus two business days (a 13-week re-opening then shows 91 days, as expected). 6M keeps the daily curve point
(decisions 6 Nov, item a); 1M has no Bubill."""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta

from .core import Auction, Raw, Series, window_start

META = {
    "code": "de", "name": "Germany", "source": "Deutsche Bundesbank (term structure); Deutsche Finanzagentur (Bubill auctions)",
    "source_url": "https://www.bundesbank.de/en/statistics/money-and-capital-markets/interest-rates-and-yields",
    "terms": "Bundesbank: source must be quoted ('Source: Deutsche Bundesbank'); exact reuse terms for this series not confirmed.",
}
BBK = ("https://api.statistiken.bundesbank.de/rest/data/BBSIS/D.I.ZST.ZI.EUR.S1311.B.A604..R.A.A._Z._Z.A")
AUC = "https://www.deutsche-finanzagentur.de/fileadmin/user_upload/Institutionelle-investoren/auktionen/emissionsergebnisse_aktuell_en.xlsx"
# Same layout, all auctions since 1999 (linked from the issuance-results page). The current-year file starts in January, so the
# history file is what gives the 1-year-earlier curve its 3M point. Optional: if it cannot be fetched or read, Germany still runs.
AUC_HISTORY = "https://www.deutsche-finanzagentur.de/fileadmin/user_upload/Institutionelle-investoren/auktionen/emissionshistorie_en.xlsx"
MAT = {"6M": "R005X", "1Y": "R01XX", "3Y": "R03XX", "5Y": "R05XX", "10Y": "R10XX", "30Y": "R30XX"}
GAPS = {"1M": "No Bubill with about one month left is auctioned."}


def parse_bbk(blob: bytes) -> dict[str, list[tuple[date, float]]]:
    text = blob.decode("utf-8-sig", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))
    head = rows[0]
    col = {}
    for t, m in MAT.items():
        for i, h in enumerate(head):
            if f".{m}." in h and not h.endswith("_FLAGS"):
                col[t] = i
    out = {t: [] for t in MAT}
    for r in rows[1:]:
        if r and len(r[0]) == 10 and r[0][4] == "-":
            d = date.fromisoformat(r[0])
            for t, i in col.items():
                if i < len(r) and r[i] not in ("", ".", "-"):
                    out[t].append((d, float(r[i])))
    if not col:
        raise ValueError("Bundesbank CSV: expected maturity columns not found")
    return out


def _settle(d: date, n: int = 2) -> date:
    while n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def parse_bubills(blob: bytes) -> list[Auction]:
    import openpyxl

    ws = openpyxl.load_workbook(io.BytesIO(blob), read_only=True, data_only=True).worksheets[0]
    out = []
    for r in ws.iter_rows(values_only=True):
        if len(r) > 16 and r[3] == "Bubill" and isinstance(r[1], datetime) and isinstance(r[5], datetime) \
                and isinstance(r[16], (int, float)):
            a = r[1].date()
            s = _settle(a)
            out.append(Auction(a, (r[5].date() - s).days, float(r[16]), s))
    return out


def fetch(g, today: date, env=None, prev=None) -> Raw:
    start = window_start(today).isoformat()
    bbk = parse_bbk(g.get(BBK, params={"startPeriod": start, "format": "csv", "lang": "en"}))
    raw = Raw(gaps=dict(GAPS))
    for t, pts in bbk.items():
        raw.series[t] = [Series("D", pts, max_lag=5)]
    aus = parse_bubills(g.get(AUC))
    try:
        seen = {(a.date, a.days) for a in aus}
        floor = window_start(today) - timedelta(days=100)       # a year back plus the 90-day auction rule
        aus += [a for a in parse_bubills(g.get(AUC_HISTORY)) if a.date >= floor and (a.date, a.days) not in seen]
    except Exception as e:  # noqa: BLE001 - optional source: the current-year workbook alone still gives the latest 3M
        raw.extra["history_workbook"] = f"not used: {str(e)[:80]}"
    raw.auctions = {"1M": aus, "3M": aus}
    return raw
