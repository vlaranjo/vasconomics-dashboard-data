"""Italy: Ministry of Economy and Finance, Department of the Treasury, auction results (checked 11 Nov 2026, plain requests).

Italy has no daily official yield source that answers plain requests: the Bank of Italy's Infostat API answers with its
"Risorsa Protetta" page (404 on 11 Nov 2026), and the Treasury's "Yields at Issue" CSV is monthly, has no auction dates and lags.
So every tenor comes from auctions (decisions of 11 Nov 2026: the auction rule, extended to long tenors by remaining maturity).

Each instrument has a results page, one per year (`?selezione-anno=YYYY`), listing one small PDF per auction:
    https://www.dt.mef.gov.it/en/debito_pubblico/emissioni_titoli_di_stato_interni/risultati_aste/<category>/index.html
The PDF is text (pypdf reads it): "Auction Date", "Settlement Date", "Maturity Date" and the yield, which for BOTs is the
"Weighted Average Yield" (simple, 360-day basis; the figure the Treasury's own "Yields at Issue" table shows) and for BTPs the
"Gross Yield" (365-day basis). Remaining maturity = maturity - settlement, so a re-opening counts at what is left (a 7-year BTP
re-opened with 5.5 years left is a 5Y auction). Only files named "...Auction Results..." are read: syndicated placements and
press releases are not auctions. Only conventional fixed-rate bonds: BTP Italia, BTP Valore, BTP-i (real), CCTeu (floating)
and BTP Green are never used. 1M comes only from the occasional re-opening of a 12-month BOT with about one month left (28 Oct
2026: 45 days; 29 Oct 2025: 42 days; flexible BOTs were last auctioned in July 2020), so it is usually empty; 30Y is usually
empty too, because 30-year BTPs are mostly placed by syndicate (not an auction). Both get a gap note when nothing is in window.

The log of parsed auctions is kept in the document's `state` (like Japan), so a weekly run reads one page per category for the
current year plus only the PDFs it has not seen; the first run also reads the previous year to reach the 1-year-earlier curve.
"""
from __future__ import annotations

import io
import re
from datetime import date, datetime, timedelta

from .core import Auction, Raw, curve_date, pick_auction, window_start

META = {
    "code": "it", "name": "Italy", "source": "Ministry of Economy and Finance, Department of the Treasury (BOT and BTP auction results)",
    "source_url": "https://www.dt.mef.gov.it/en/debito_pubblico/emissioni_titoli_di_stato_interni/risultati_aste/",
    "terms": "Treasury Department legal notes: the source must be cited; use, copying and distribution for purposes of profit "
             "need prior written permission.",
    "status": "ok",
}
BASE = "https://www.dt.mef.gov.it"
PAGE = BASE + "/en/debito_pubblico/emissioni_titoli_di_stato_interni/risultati_aste/{cat}/index.html"
CATEGORIES = ["risultati_aste_bot_3_mesi", "risultati_aste_bot_6_mesi", "risultati_aste_bot_12_mesi", "risultati_aste_btp_short_term",
              "risultati_aste_btp_3_anni", "risultati_aste_btp_5_anni", "risultati_aste_btp_7_anni", "risultati_aste_btp_10_anni",
              "risultati_aste_btp_15_anni", "risultati_aste_btp_20_anni", "risultati_aste_btp_30_anni", "risultati_aste_btp_50_anni"]
TENORS = ["1M", "3M", "6M", "1Y", "3Y", "5Y", "10Y", "30Y"]
GAPS = {"1M": "Italy auctions a bill with about one month left only occasionally (a re-opened 12-month BOT); none in the last 90 days.",
        "30Y": "30-year BTPs are mostly placed by syndicate, not auctioned; no auction with 25-35 years left in the last 90 days."}
KEEP_DAYS = 480
SEEN_KEEP = 600
_DATE = r"([A-Z][a-z]+ \d{1,2}, \d{4})"


def _d(s: str) -> date:
    return datetime.strptime(s, "%B %d, %Y").date()


def pdf_links(html: str) -> list[str]:
    """Auction-result PDFs on one category page (absolute URLs), newest first as listed."""
    out = []
    for href in re.findall(r'href="(/export/[^"]+\.pdf)"', html):
        name = href.rsplit("/", 1)[-1]
        if re.search(r"auction[-_ ]results", name, re.I) and not re.search(r"syndicat|placement|green", name, re.I):
            url = BASE + href
            if url not in out:
                out.append(url)
    return out


def name_date(url: str) -> date | None:
    """The last dd.mm.yyyy in the file name (the end of the auction period), or None."""
    m = re.findall(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", url.rsplit("/", 1)[-1])
    if not m:
        return None
    d, mo, y = (int(x) for x in m[-1])
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def pdf_text(blob: bytes) -> str:
    import pypdf

    return "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(blob)).pages)


# Only standard fixed-rate instruments count (decided 12 Nov 2026): BOT and CTZ (short end) and nominal BTP, including "BTP Short
# Term" and re-openings of any of them ("BTP 7 YEARS (5 YEAR RESIDUAL MATURITY)"). The heading of the result file must match
# STANDARD; the known non-standard families are named in EXCLUDED (and skipped quietly); any other heading is an unknown
# instrument and the file is reported as unreadable (status.json warnings), never used.
EXCLUDED = re.compile(r"BTP\s*(?:€|EUR|E)\s*I\b|BTPI\b|ITALIA|VALORE|PI[UÙ]\b|GREEN|CCT|FUTURA|INDEX|INFLAZ|INFLATION|RETAIL|FLOAT", re.I)
_RESIDUAL = r"(?:\s*\(\s*\d+\s+(?:MONTHS?|YEARS?)\s+RESIDUAL[\s_]+MATURIT(?:Y|IES)?\s*\)?)?"
STANDARD = re.compile(r"(?:\d+\s+MONTHS?\s+BOTS?|BOTS?(?:\s+\d+\s+MONTHS?)?|CTZ(?:\s+\d+\s+MONTHS?)?|BTP\s+SHORT\s+TERM|BTP\s+\d+\s+YEARS?)"
                      + _RESIDUAL, re.I)


def instrument(head: str) -> str:
    """'standard', 'excluded' (a known non-standard family) or 'unknown'."""
    h = re.sub(r"\s+", " ", head).strip()
    if EXCLUDED.search(h):
        return "excluded"
    return "standard" if STANDARD.fullmatch(h) else "unknown"


def parse_result(text: str) -> list[dict]:
    """One dict per security in an auction-result PDF. Raises ValueError if the layout or the instrument is not recognised."""
    if "Auction Results:" not in text:
        raise ValueError("not an auction-result file")
    head = re.search(r"Auction Results:\s*([^\n]+)", text).group(1).strip()
    kind = instrument(head)
    if kind == "excluded":
        return []                                       # inflation-linked, retail, green or floating: never used
    if kind == "unknown":
        raise ValueError(f"instrument not recognised as a standard BOT, CTZ or nominal BTP: {head[:60]!r}")
    auc = re.findall(r"Auction Date\s+" + _DATE, text)
    sett = re.findall(r"Settlement Date\s+" + _DATE, text)
    mat = re.findall(r"Maturity Date\s+" + _DATE, text)
    ys = re.findall(r"Weighted Average Yield\s+(-?[\d.]+)\s*%", text) or re.findall(r"Gross Yield\s+(-?[\d.]+)\s*%", text)
    isin = re.findall(r"ISIN Code\s+(\w{12})", text)
    coupon = re.findall(r"Coupon\s*(?:\(\s*\*+\s*\))?\s*(-?[\d.]+)\s*%", text)     # "Coupon 4.00%", "Coupon(*) 3.95%" (footnoted)
    n = len(auc)
    if not n or not (len(sett) == len(mat) == len(ys) == n):
        raise ValueError(f"auction-result layout not recognised ({head[:40]!r}: {n}/{len(sett)}/{len(mat)}/{len(ys)})")
    is_btp = head.upper().startswith("BTP")
    if is_btp and len(coupon) != n:
        raise ValueError(f"nominal BTP without a fixed coupon in the file ({head[:40]!r})")
    out = []
    for i in range(n):
        s, m = _d(sett[i]), _d(mat[i])
        out.append({"date": _d(auc[i]).isoformat(), "settle": s.isoformat(), "maturity": m.isoformat(), "days": (m - s).days,
                    "value": float(ys[i]), "isin": isin[i] if i < len(isin) else None, "what": re.sub(r"\s+", " ", head)[:60],
                    "coupon": float(coupon[i]) if is_btp else None})
    return out


def fetch(g, today: date, env=None, prev=None) -> Raw:
    prev = prev or {}
    log = list(prev.get("auction_log", []))
    seen = list(prev.get("seen", []))
    unreadable = dict(prev.get("unreadable", {}))          # url -> reason; retried every run until it parses
    floor = window_start(today) - timedelta(days=100)       # a year back plus the 90-day auction rule
    first = not log and not seen
    years = list(range(floor.year, today.year + 1)) if first else sorted({today.year, (today - timedelta(days=31)).year})
    tried = set()

    def read(url):
        tried.add(url)
        blob = g.get(url)                  # a fetch error fails the country (last good file kept, marked stale; retried next run)
        try:
            rows = parse_result(pdf_text(blob))
        except Exception as e:  # noqa: BLE001 - an unreadable PDF (layout change, damaged file) is retried next run
            unreadable[url] = f"{type(e).__name__}: {str(e)[:80]}"
            return []
        unreadable.pop(url, None)
        seen.append(url)
        return [r | {"url": url} for r in rows]

    for cat in CATEGORIES:
        for y in years:
            html = g.get(PAGE.format(cat=cat), params={"selezione-anno": str(y)}).decode("utf-8", errors="replace")
            for url in pdf_links(html):
                nd = name_date(url)
                if url in seen or (nd and nd < floor):
                    continue
                log += read(url)
    # A file that could not be read before is retried by its own address, also when it sits on an earlier year's page that
    # later runs no longer list (found 12 Nov 2026: eleven 2025 BTP files were never retried).
    for url in [u for u in list(unreadable) if u not in tried and (not name_date(u) or name_date(u) >= floor)]:
        log += read(url)
    cutoff = (today - timedelta(days=KEEP_DAYS)).isoformat()
    uniq = {(a["date"], a.get("isin"), a["maturity"]): a for a in log if a["date"] >= cutoff}
    log = sorted(uniq.values(), key=lambda a: (a["date"], a["days"]))
    unreadable = {u: why for u, why in unreadable.items() if not name_date(u) or name_date(u) >= floor}
    if not log:
        raise ValueError("no Italian auction result could be read" + (f" ({next(iter(unreadable.values()))})" if unreadable else ""))
    aus = [Auction(date.fromisoformat(a["date"]), a["days"], a["value"], date.fromisoformat(a["settle"])) for a in log]
    raw = Raw(auction_dated=True)
    raw.auctions = {t: aus for t in TENORS}
    as_of = curve_date(raw)
    raw.gaps = {t: why for t, why in GAPS.items() if pick_auction(aus, t, as_of) is None}
    raw.extra = {"auction_log": log, "seen": seen[-SEEN_KEEP:], "unreadable": unreadable}
    if unreadable:
        raw.warnings.append(f"{len(unreadable)} auction-result file(s) could not be read (retried each run): "
                            + "; ".join(u.rsplit("/", 1)[-1] for u in list(unreadable)[:3]))
    return raw
