"""France: Banque de France Webstat (Opendatasoft "Explore" API v2.1), live-tested on 11 Nov 2026.

Reads FR_WEBSTAT_CLIENT_ID from the environment (the workflow fills it from a GitHub secret, for the yields step only).
It is an API key: it is sent ONLY in the request header `Authorization: Apikey <key>`; it is never put in a URL, logged,
stored in the document or written to any file. With no key the adapter raises Skipped and the job moves on quietly.

The old IBM endpoint (api.webstat.banque-france.fr/webstat-en/v1, header X-IBM-Client-Id) answers 401 "Invalid client id
or secret" for the current key: Webstat moved to the Explore API, and no secret exists.

One request for all series (the bulk export, JSON array):
  GET https://webstat.banque-france.fr/api/explore/v2.1/catalog/datasets/observations/exports/json
      ?select=series_key,time_period_end,obs_value&where=series_key IN (...) AND time_period_end >= date'YYYY-MM-DD'
Series: TEC (taux de l'echeance constante, daily, dataset FM) FM.D.FR.EUR.FR2.BB.FRMOYTEC{n}.HSTA for n = 1, 3, 5, 10, 30
(1Y, 3Y, 5Y, 10Y, 30Y). TEC 3 exists and is current, so 3Y is filled from it. Weekends and holidays come back as rows
with obs_value null (status M): they are skipped.
3M (decided 11 Nov 2026): the Banque de France's MONTHLY average of the 13-week BTF auction rates, FM.M.FR.EUR.FR2.MM.TMB.HSTA
("Taux d'adjudication des Bons du tresor a 13 semaines (TMB)", the only TMB series in Webstat), fetched in the same request.
It is a monthly average, not a daily observation: kind "M", labelled "monthly average of 13-week BTF auctions, <month>", dated
the last day of its month, and used only while that date is within 90 days of the curve date (never stretched further).
The daily "taux indicatifs des bons du Tresor" stopped on 10 July 2024. The Agence France Tresor's own BTF results could not be
read: aft.gouv.fr answers non-browser requests with HTTP 403 (bot protection, not circumvented), and the Ministry's mirror
applis.finances.gouv.fr serves the certificate of its "unavailable" page (indispo.finances.gouv.fr), so no page is readable
(both checked 11 Nov 2026). So 6M stays a gap, and so does 1M: the AFT's auction notices of 2025-26 (seen through a web search, not fetched) list BTFs of
about 11 to 52 weeks (e.g. 11, 13, 26 and 52 weeks on 13 July 2026), none of about one month.
"""
from __future__ import annotations

import json
from datetime import date

from .core import Raw, Series, Skipped, curve_date, point_at, window_start

META = {
    "code": "fr", "name": "France", "source": "Banque de France, Webstat (TEC constant-maturity yields)",
    "source_url": "https://webstat.banque-france.fr/",
    "terms": "Source must be credited ('Source: Banque de France'); data stays the Banque de France's property, no distortion; "
             "licence is per dataset (none stated in the API metadata).",
    "status": "ok",
}
URL = "https://webstat.banque-france.fr/api/explore/v2.1/catalog/datasets/observations/exports/json"
TEC = {"1Y": 1, "3Y": 3, "5Y": 5, "10Y": 10, "30Y": 30}
TMB_KEY = "FM.M.FR.EUR.FR2.MM.TMB.HSTA"     # monthly average of the 13-week BTF auction rates
TMB_MAX_DAYS = 90
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
BILL_GAP = ("The Banque de France stopped publishing the 'taux indicatifs' of Treasury bills on 10 July 2024 and Webstat has no "
            "daily bill series; the Agence France Tresor's auction results are not readable without a browser (its site refuses "
            "non-browser requests, HTTP 403), so no auction yield is used; left empty.")
GAPS = {"1M": "France's BTFs are auctioned with about 11 to 52 weeks to maturity, none of about one month, and Webstat has no such "
              "series; left empty.",
        "6M": BILL_GAP}
TMB_GAP = "The Banque de France's monthly 13-week BTF auction rate is more than 90 days old or missing; left empty."


def tmb_label(d: date) -> str:
    return f"monthly average of 13-week BTF auctions, {MONTHS[d.month - 1]} {d.year}"


def tec_key(n: int) -> str:
    return f"FM.D.FR.EUR.FR2.BB.FRMOYTEC{n}.HSTA"


def parse_export(blob: bytes) -> dict[str, list[tuple[date, float]]]:
    """Rows of the JSON export -> {series_key: [(date, value)]}. Null values (non-business days) are dropped."""
    out: dict[str, list[tuple[date, float]]] = {}
    for r in json.loads(blob):
        v = r.get("obs_value")
        if v is not None:
            out.setdefault(r["series_key"], []).append((date.fromisoformat(str(r["time_period_end"])[:10]), float(v)))
    return {k: sorted(v) for k, v in out.items()}


def fetch(g, today: date, env=None, prev=None) -> Raw:
    env = env or {}
    cid = env.get("FR_WEBSTAT_CLIENT_ID")
    if not cid:
        raise Skipped("FR_WEBSTAT_CLIENT_ID is not set")
    keys = {t: tec_key(n) for t, n in TEC.items()}
    keys["3M"] = TMB_KEY
    where = ("series_key IN (" + ",".join(f'"{k}"' for k in keys.values()) + ") AND time_period_end >= date'"
             + window_start(today).isoformat() + "'")
    blob = g.get(URL, params={"select": "series_key,time_period_end,obs_value", "where": where,
                              "order_by": "series_key,time_period_end", "limit": -1},
                 headers={"Authorization": f"Apikey {cid}", "Accept": "application/json"})
    data = parse_export(blob)
    raw = Raw(gaps=dict(GAPS))
    for t, key in keys.items():
        if key == TMB_KEY:
            pts = data.get(key, [])
            if pts:
                raw.series[t] = [Series("M", pts, max_lag=TMB_MAX_DAYS, labels={d: tmb_label(d) for d, _ in pts})]
        elif data.get(key):
            raw.series[t] = [Series("D", data[key], max_lag=5)]
        else:
            raw.gaps[t] = f"Webstat returned no observations for {key}."
    as_of = curve_date(raw)
    if as_of is None or point_at(raw, "3M", as_of) is None:
        raw.gaps["3M"] = TMB_GAP          # judged on the latest curve's date; earlier curves may still have a 3M
    return raw
