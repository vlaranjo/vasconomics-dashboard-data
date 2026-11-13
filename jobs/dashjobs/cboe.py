"""Cboe VX futures: the contract list, the settlement CSVs, the term-structure curve and its slope (Volatility page, 13 Nov 2026).

Where the data comes from (all plain HTTP, no browser; checked 13 Nov 2026):
  - Contract list: Cboe's historical-data page (www.cboe.com/markets/us/futures/market-statistics/historical-data/futures) loads
    https://www-api.cboe.com/us/futures/market_statistics/historical_data/product/list/VX/ , a JSON object {year: [contract...]},
    each contract {product_display, expire_date, contract_dt, futures_root, duration_type ("M" monthly, "W" weekly), path}.
  - One CSV per contract at https://cdn.cboe.com/<path>: Trade Date, Futures, Open, High, Low, Close, Settle, Change, Total Volume,
    EFP, Open Interest. Cboe rewrites these files once a day at about 01:06 New York time (Last-Modified 06:06 UTC in November,
    05:06 UTC in October), so in the evening they end at the PREVIOUS trading day.
  - The day's settlements: https://www.cboe.com/us/futures/market_statistics/settlement/csv?dt=YYYY-MM-DD (Product, Symbol,
    Expiration Date, Price). Before settlement, and on a day without trading, it returns the header only. It is read only for trade
    dates after the last date in the CSVs, so the evening run has the day's curve.

Curve rules (pure functions below; tests in tests/test_volatility.py):
  - Monthly contracts only (duration_type "M"; the daily file's monthly symbols are "VX/<month code><year digit>").
  - On trade date T the contracts are the monthly ones that expire AFTER T, by expiry: position 1 is the first of them. On an
    expiry day the expiring contract is no longer counted (its last settlement is the final settlement value), so the curve rolls
    on the expiry date itself. Weekly expiries never enter.
  - A position whose contract has no settlement on T (missing row, or Settle 0, which the older files carry) is EMPTY: the next
    contract is never moved into its place.
  - Slope: least-squares slope of settlement on position over positions 1..7, using the positions that have a value; at least 4,
    otherwise no slope that day.
"""
from __future__ import annotations

import csv
import io
import json
import math
import re
from datetime import date, timedelta

LIST_URL = "https://www-api.cboe.com/us/futures/market_statistics/historical_data/product/list/VX/"
CDN = "https://cdn.cboe.com/"
SETTLE_URL = "https://www.cboe.com/us/futures/market_statistics/settlement/csv?dt={d}"
PAGE_URL = "https://www.cboe.com/markets/us/futures/market-statistics/historical-data/futures"

MONTH_CODES = "FGHJKMNQUVXZ"
_MONTHLY_SYMBOL = re.compile(r"^VX/([FGHJKMNQUVXZ])(\d{1,2})$")
_CHALLENGE = re.compile(rb"(?i)(captcha|just a moment|cf-chl|attention required|access denied|are you a robot)")


class Challenge(Exception):
    """A bot check, a refusal or an HTML page where data was expected. The job stops asking Cboe for the rest of the run."""


class ParseError(ValueError):
    pass


def check_body(body: bytes, what: str, expect: str) -> None:
    """expect: "json" or "csv". Anything that looks like a web page or a bot check is a Challenge."""
    head = body[:4096].lstrip()
    if head[:1] == b"<" or _CHALLENGE.search(head):
        raise Challenge(f"{what}: got a web page or a bot check instead of {expect}")


# ---- contract list ------------------------------------------------------------------------------------------------------------
def monthly_contracts(listing: dict) -> list[dict]:
    """[{expiry: date, path: str, code: "X6", month: "Nov 2026"}] for the monthly VX contracts, by expiry. Weeklies are left out."""
    out = {}
    for rows in (listing or {}).values():
        for r in rows or []:
            if r.get("duration_type") != "M" or r.get("futures_root") != "VX":
                continue
            exp = date.fromisoformat(r["expire_date"])
            out[exp] = {"expiry": exp, "path": r["path"], "code": f"{MONTH_CODES[exp.month - 1]}{exp.year % 10}",
                        "month": exp.strftime("%b %Y")}
    if not out:
        raise ParseError("the contract list has no monthly VX contract")
    return [out[k] for k in sorted(out)]


def parse_listing(body: bytes) -> dict:
    check_body(body, "contract list", "json")
    try:
        d = json.loads(body)
    except ValueError as e:
        raise ParseError(f"contract list is not JSON: {e}") from e
    if not isinstance(d, dict):
        raise ParseError("contract list is not a JSON object")
    return d


def listing_gap(contracts: list[dict], since: date) -> str | None:
    """A monthly contract missing from the list (two consecutive expiries more than 42 days apart) would shift every later
    position. Returns a description of the first gap among contracts expiring after `since`, or None."""
    exps = [c["expiry"] for c in contracts if c["expiry"] > since - timedelta(days=45)]
    for a, b in zip(exps, exps[1:]):
        if (b - a).days > 42:
            return f"no monthly contract between {a.isoformat()} and {b.isoformat()}"
    return None


# ---- settlement files ---------------------------------------------------------------------------------------------------------
def _num(s) -> float | None:
    try:
        v = float(str(s).strip())
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v > 0 else None


def parse_contract_csv(body: bytes) -> dict[date, float]:
    """{trade date: settlement} from one contract's CSV. Settle 0 or blank means no settlement that day (left out)."""
    check_body(body, "settlement CSV", "csv")
    text = body.decode("utf-8-sig", errors="replace")
    rd = csv.DictReader(io.StringIO(text))
    if not rd.fieldnames or "Trade Date" not in rd.fieldnames or "Settle" not in rd.fieldnames:
        raise ParseError(f"unexpected CSV header: {rd.fieldnames}")
    out: dict[date, float] = {}
    for row in rd:
        try:
            d = date.fromisoformat((row.get("Trade Date") or "").strip()[:10])
        except ValueError:
            continue
        v = _num(row.get("Settle"))
        if v is not None:
            out[d] = v
    return out


def parse_daily_settlement(body: bytes) -> dict[date, float]:
    """{expiry: price} for the MONTHLY VX contracts in the day's settlement file (empty before settlement or on a holiday)."""
    check_body(body, "daily settlement CSV", "csv")
    text = body.decode("utf-8-sig", errors="replace")
    rd = csv.DictReader(io.StringIO(text))
    if not rd.fieldnames or "Symbol" not in rd.fieldnames or "Price" not in rd.fieldnames:
        raise ParseError(f"unexpected daily settlement header: {rd.fieldnames}")
    out: dict[date, float] = {}
    for row in rd:
        if (row.get("Product") or "").strip() != "VX" or not _MONTHLY_SYMBOL.match((row.get("Symbol") or "").strip()):
            continue
        try:
            exp = date.fromisoformat((row.get("Expiration Date") or "").strip()[:10])
        except ValueError:
            continue
        v = _num(row.get("Price"))
        if v is not None:
            out[exp] = v
    return out


# ---- curve and slope ------------------------------------------------------------------------------------------------------------
def curve_on(day: date, expiries: list[date], settles: dict[date, dict[date, float]], n: int = 8) -> list[dict]:
    """The first n monthly contracts expiring after `day`, by expiry: [{pos, expiry, days, settle|None}]. Never shifts a contract
    into an empty position."""
    after = [e for e in expiries if e > day][:n]
    return [{"pos": i + 1, "expiry": e, "days": (e - day).days, "settle": settles.get(e, {}).get(day)} for i, e in enumerate(after)]


def ols_slope(points: list[tuple[float, float]]) -> float:
    n = len(points)
    mx = sum(x for x, _ in points) / n
    my = sum(y for _, y in points) / n
    sxx = sum((x - mx) ** 2 for x, _ in points)
    if sxx == 0:
        raise ValueError("all x equal")
    return sum((x - mx) * (y - my) for x, y in points) / sxx


def slope_of(curve: list[dict], upto: int = 7, min_points: int = 4) -> float | None:
    pts = [(c["pos"], c["settle"]) for c in curve if c["pos"] <= upto and c["settle"] is not None]
    if len(pts) < min_points:
        return None
    return round(ols_slope(pts), 4)


def trade_dates(settles: dict[date, dict[date, float]]) -> list[date]:
    return sorted({d for s in settles.values() for d in s})


def first_valid_day(contracts: list[dict]) -> date:
    """The list starts with the January 2013 contract. Before the previous expiry (about a month earlier) the true front
    contract is not in the list, so no curve is built for those days."""
    return contracts[0]["expiry"] - timedelta(days=28)
