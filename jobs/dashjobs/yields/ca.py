"""Canada: Bank of Canada Valet. Bonds daily (3Y, 5Y, 10Y), bills weekly (1M, 3M, 6M, 1Y). The 30Y point is the
'long-term benchmark' series: the Bank's page names 2-, 5-, 10- and 30-year selected issues but its series description
says only "long-term benchmark bond", so it is labelled as such, not as 30Y (decisions 6 Nov, item d)."""
from __future__ import annotations

import json
from datetime import date

from .core import Raw, Series, window_start

META = {
    "code": "ca", "name": "Canada", "source": "Bank of Canada, Valet API",
    "source_url": "https://www.bankofcanada.ca/rates/interest-rates/canadian-bonds/",
    "terms": "Bank of Canada terms: free use with attribution 'Bank of Canada'; request limits apply.",
}
BASE = "https://www.bankofcanada.ca/valet/observations"
BONDS = {"3Y": "BD.CDN.3YR.DQ.YLD", "5Y": "BD.CDN.5YR.DQ.YLD", "10Y": "BD.CDN.10YR.DQ.YLD"}
LONG = ("30Y", "BD.CDN.LONG.DQ.YLD")
BILLS = {"1M": "V80691342", "3M": "V80691344", "6M": "V80691345", "1Y": "V80691346"}


def parse(blob: bytes) -> dict[str, list[tuple[date, float]]]:
    out: dict[str, list[tuple[date, float]]] = {}
    for o in json.loads(blob).get("observations", []):
        d = date.fromisoformat(o["d"])
        for k, v in o.items():
            if k != "d" and isinstance(v, dict) and v.get("v") not in (None, ""):
                out.setdefault(k, []).append((d, float(v["v"])))
    return out


def fetch(g, today: date, env=None, prev=None) -> Raw:
    start = window_start(today).isoformat()
    codes = list(BONDS.values()) + [LONG[1]]
    bonds = parse(g.get(f"{BASE}/{','.join(codes)}/json", params={"start_date": start}))
    bills = parse(g.get(f"{BASE}/{','.join(BILLS.values())}/json", params={"start_date": start}))
    raw = Raw()
    for t, c in BONDS.items():
        raw.series[t] = [Series("D", bonds.get(c, []), max_lag=5)]
    for t, c in BILLS.items():
        raw.series[t] = [Series("W", bills.get(c, []), max_lag=10, label="weekly observation")]
    raw.series[LONG[0]] = [Series("B", bonds.get(LONG[1], []), max_lag=5, label="long-term benchmark bond (the Bank does not state its maturity)",
                                  tenor_label="long-term benchmark")]
    return raw
