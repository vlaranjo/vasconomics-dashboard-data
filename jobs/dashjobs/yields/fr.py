"""France: Banque de France Webstat API (v1), UNTESTED until a client id exists.

Reads FR_WEBSTAT_CLIENT_ID (and, only if the API turns out to need one, FR_WEBSTAT_CLIENT_SECRET) from the environment, which
the workflow fills from GitHub secrets. With no client id the adapter raises Skipped and the job moves on quietly.
Nothing secret is stored in any file.

Documented request: GET https://api.webstat.banque-france.fr/webstat-en/v1/data/{dataset}/{series key}
  ?format=json&detail=dataonly&startPeriod=YYYY-MM-DD with header X-IBM-Client-Id (developer.webstat.banque-france.fr).
Series: TEC (constant maturity Treasury yields) in dataset FM: FM.D.FR.EUR.FR2.BB.FRMOYTEC{n}.HSTA for n = 1, 5, 10, 30
(the key pattern is listed in the public Webstat catalogue; 1Y, 5Y, 10Y, 30Y). No 3Y by decision. The bill series for 1M, 3M and
6M ("taux indicatifs") are NOT confirmed: fill BILL_KEYS from the catalogue once a key exists. Until then those tenors are gaps.
"""
from __future__ import annotations

import json
from datetime import date

from .core import Raw, Series, Skipped, window_start

META = {
    "code": "fr", "name": "France", "source": "Banque de France, Webstat (TEC constant-maturity yields)",
    "source_url": "https://webstat.banque-france.fr/",
    "terms": "Not read; the developer portal lists the API as open with an account (10,000 calls a day).",
    "status": "untested",
}
BASE = "https://api.webstat.banque-france.fr/webstat-en/v1/data"
TEC = {"1Y": 1, "5Y": 5, "10Y": 10, "30Y": 30}
BILL_KEYS: dict[str, str] = {}      # {"1M": "FM....", "3M": "FM....", "6M": "FM...."}  unconfirmed, see the docstring
GAPS = {"3Y": "No official French 3-year constant-maturity yield is used.",
        "1M": "Series key for the 1-month 'taux indicatif' not confirmed yet.",
        "3M": "Series key for the 3-month 'taux indicatif' not confirmed yet.",
        "6M": "Series key for the 6-month 'taux indicatif' not confirmed yet."}


def tec_key(n: int) -> str:
    return f"FM.D.FR.EUR.FR2.BB.FRMOYTEC{n}.HSTA"


def parse_sdmx_json(blob: bytes) -> list[tuple[date, float]]:
    """One series from SDMX-JSON (detail=dataonly)."""
    j = json.loads(blob)
    j = j.get("data", j)
    ds = j["dataSets"][0]["series"]
    times = j["structure"]["dimensions"]["observation"][0]["values"]
    out = []
    for s in ds.values():
        for i, obs in s["observations"].items():
            v = obs[0]
            if v is not None:
                out.append((date.fromisoformat(times[int(i)]["id"][:10]), float(v)))
    return sorted(out)


def fetch(g, today: date, env=None, prev=None) -> Raw:
    env = env or {}
    cid = env.get("FR_WEBSTAT_CLIENT_ID")
    if not cid:
        raise Skipped("FR_WEBSTAT_CLIENT_ID is not set")
    headers = {"X-IBM-Client-Id": cid, "Accept": "application/json"}
    if env.get("FR_WEBSTAT_CLIENT_SECRET"):
        headers["X-IBM-Client-Secret"] = env["FR_WEBSTAT_CLIENT_SECRET"]
    start = window_start(today).isoformat()
    raw = Raw(gaps=dict(GAPS))
    keys = {t: tec_key(n) for t, n in TEC.items()}
    keys.update(BILL_KEYS)
    for t, key in keys.items():
        ds = key.split(".")[0]
        pts = parse_sdmx_json(g.get(f"{BASE}/{ds}/{key}", params={"format": "json", "detail": "dataonly", "startPeriod": start},
                                    headers=headers))
        raw.series[t] = [Series("D", pts, max_lag=5)]
        raw.gaps.pop(t, None)
    return raw
