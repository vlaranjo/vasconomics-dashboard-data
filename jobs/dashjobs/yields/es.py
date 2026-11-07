"""Spain: Banco de Espana secondary-market yields (table TI 1.3, whole market, simple spot trades).
3M = the Letras 1-3 month bucket (labelled). 1Y = the exact 1-year Letras series on the day, falling back to the
6-12 month bucket when the exact series is blank (labelled). 1M and 30Y: not published (the longest bond is 15Y)."""
from __future__ import annotations

import csv
import io
import re
from datetime import date

from .core import Raw, Series, window_start

META = {
    "code": "es", "name": "Spain", "source": "Banco de España, secondary market yields (TI 1.3)",
    "source_url": "https://www.bde.es/webbe/en/estadisticas/temas/tipos-interes.html",
    "terms": "Terms not confirmed (legal-notice pages not reachable); credit 'Source: Banco de España'.",
}
URL = "https://www.bde.es/webbe/es/estadisticas/compartido/datos/csv/ti_1_3.csv"
MONTHS = {m: i + 1 for i, m in enumerate("ENE FEB MAR ABR MAY JUN JUL AGO SEP OCT NOV DIC".split())}
MONTHS.update({"JAN": 1, "APR": 4, "AUG": 8, "DEC": 12})
GAPS = {"1M": "Spain publishes no 1-month bill yield; the 1-3 month bucket is used for 3M.",
        "30Y": "The longest Spanish bond series is 15 years."}
CODES = {"3M": "D_DTES00B7", "6M": "D_DTES00S7", "1Y_exact": "D_DTES00U7", "1Y_bucket": "D_DTES00T7",
         "3Y": "D_G0B1F0ZN", "5Y": "D_G0B1F0ZO", "10Y": "D_G0B1F0ZP"}


def _d(s: str):
    m = re.match(r"^(\d{1,2}) ([A-Z]{3}) (\d{4})$", s.strip().upper())
    if not m or m.group(2) not in MONTHS:
        return None
    return date(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)))


def parse(blob: bytes, since: date) -> dict[str, list[tuple[date, float]]]:
    rows = list(csv.reader(io.StringIO(blob.decode("latin-1"))))
    head = rows[0]
    col = {k: head.index(c) for k, c in CODES.items() if c in head}
    missing = set(CODES) - set(col)
    if missing:
        raise ValueError(f"Banco de España CSV: series not found: {sorted(missing)}")
    out = {k: [] for k in CODES}
    for r in rows[1:]:
        d = _d(r[0]) if r else None
        if not d or d < since:
            continue
        for k, i in col.items():
            if i < len(r):
                try:
                    out[k].append((d, float(r[i])))
                except ValueError:
                    pass                      # "_" means blank
    return out


def fetch(g, today: date, env=None, prev=None) -> Raw:
    p = parse(g.get(URL), window_start(today))
    raw = Raw(gaps=dict(GAPS))
    raw.series["3M"] = [Series("B", p["3M"], max_lag=4, label="Letras 1-3 month bucket")]
    raw.series["6M"] = [Series("D", p["6M"], max_lag=4)]
    raw.series["1Y"] = [Series("D", p["1Y_exact"], max_lag=0),
                        Series("B", p["1Y_bucket"], max_lag=4, label="Letras 6-12 month bucket (the exact 1-year series was blank)")]
    for t in ("3Y", "5Y", "10Y"):
        raw.series[t] = [Series("D", p[t], max_lag=4)]
    return raw
