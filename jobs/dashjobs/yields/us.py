"""United States: Treasury daily par yield curve (XML, one request per month). All eight tenors daily."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from .core import CURVE_DEFS, Raw, Series, curve_date

META = {
    "code": "us", "name": "United States", "source": "US Department of the Treasury, daily par yield curve",
    "source_url": "https://home.treasury.gov/resource-center/data-chart-center/interest-rates",
    "terms": "Page states no reuse terms; US federal-government work (not confirmed from the page).",
}
URL = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
       "?data=daily_treasury_yield_curve&field_tdr_date_value_month={ym}")
FIELDS = {"1M": "BC_1MONTH", "3M": "BC_3MONTH", "6M": "BC_6MONTH", "1Y": "BC_1YEAR", "3Y": "BC_3YEAR",
          "5Y": "BC_5YEAR", "10Y": "BC_10YEAR", "30Y": "BC_30YEAR"}


def parse_month(xml: bytes) -> dict[date, dict[str, float]]:
    """{date: {tenor: yield}} from one month of Atom/XML."""
    root = ET.fromstring(xml)
    out: dict[date, dict[str, float]] = {}
    for el in root.iter():
        if not el.tag.endswith("}properties"):
            continue
        vals = {c.tag.split("}")[-1]: (c.text or "").strip() for c in el}
        if "NEW_DATE" not in vals:
            continue
        d = date.fromisoformat(vals["NEW_DATE"][:10])
        row = {}
        for t, f in FIELDS.items():
            if vals.get(f):
                row[t] = float(vals[f])
        out[d] = row
    return out


def fetch(g, today: date, env=None, prev=None) -> Raw:
    have: dict[date, dict[str, float]] = {}
    fetched: set[str] = set()

    def month(d: date):
        ym = f"{d.year}{d.month:02d}"
        if ym not in fetched:
            fetched.add(ym)
            have.update(parse_month(g.get(URL.format(ym=ym))))

    month(today)
    if today.day < 10 or not have:
        month(today - relativedelta(months=1))
    as_of = max(have)
    for _, _, delta in CURVE_DEFS[1:]:
        t = as_of - delta
        month(t)
        if t.day < 8:
            month(t - timedelta(days=8))
    raw = Raw()
    for t, f in FIELDS.items():
        pts = [(d, row[t]) for d, row in have.items() if t in row]
        raw.series[t] = [Series("D", pts, max_lag=5)]
    assert curve_date(raw) == as_of
    return raw
