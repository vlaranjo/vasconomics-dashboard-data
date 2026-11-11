"""Yield-curve core: series types, the auction rule, the earlier-curve anchors, and the per-country document.

Cell kinds: D daily official observation, W weekly official observation, B bucket (the bucket is named in `label`),
M monthly average (named in `label`, e.g. France's 13-week BTF auctions), A auction yield (own date, residual days),
C calculated: an earlier value derived from a source's change column (worldgovernmentbonds.com: Last minus Chg 1M/6M/12M; the
column is named in `label`). D is also used for the latest worldgovernmentbonds.com quote (the source line names the site).
A tenor with no usable point is simply absent from `points`.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

TENORS = ["1M", "3M", "6M", "1Y", "3Y", "5Y", "10Y", "30Y"]

# Auction rule (decided 6 Nov 2026): the most recent auction whose residual maturity at settlement falls inside the
# window, not older than AUCTION_MAX_AGE_DAYS before the reference date.
AUCTION_WINDOWS = {"1M": (20, 45), "3M": (70, 110), "6M": (160, 200)}
# Long tenors (decided 11 Nov 2026), ONLY for a country with no daily official source for that tenor (Italy, India): the same
# rule, with the window in years of remaining maturity at settlement. An adapter opts in by giving auctions for the tenor.
YEAR_DAYS = 365.25
LONG_AUCTION_YEARS = {"1Y": (0.8, 1.2), "3Y": (2.5, 3.5), "5Y": (4.0, 6.0), "10Y": (8.5, 11.5), "30Y": (25.0, 35.0)}
AUCTION_WINDOWS.update({t: (lo * YEAR_DAYS, hi * YEAR_DAYS) for t, (lo, hi) in LONG_AUCTION_YEARS.items()})
AUCTION_MAX_AGE_DAYS = 90

CURVE_DEFS = [("latest", "Latest", None), ("1m", "1 month earlier", relativedelta(months=1)),
              ("6m", "6 months earlier", relativedelta(months=6)), ("1y", "1 year earlier", relativedelta(years=1))]
# Round 17 (11 Nov 2026): the comparison curves are 1 month, 6 months and 1 year earlier (was 3 months), for every source.


class Skipped(Exception):
    """The adapter cannot run on purpose (for example a missing optional secret). Not a failure."""


@dataclass
class Series:
    kind: str                                   # D, W, B, M or C
    points: list[tuple[date, float]]            # ascending by date
    max_lag: int = 4                            # a value may be this many days older than the date asked for
    label: str | None = None                    # tooltip text for buckets ("1-3 month bucket")
    tenor_label: str | None = None              # axis/legend label override (Canada: "long-term benchmark")
    labels: dict | None = None                  # per-date label, when the bucket changes with the date (Australia's bond buckets)

    def __post_init__(self):
        self.points = sorted(self.points)
        self._dates = [d for d, _ in self.points]

    def on_or_before(self, target: date):
        i = bisect_right(self._dates, target)
        if i == 0:
            return None
        d, v = self.points[i - 1]
        if (target - d).days > self.max_lag:
            return None
        return d, v

    @property
    def last_date(self):
        return self._dates[-1] if self._dates else None


@dataclass
class Auction:
    date: date                                  # auction date
    days: int                                   # residual days at settlement
    value: float                                # average yield, percent
    settle: date | None = None


@dataclass
class Raw:
    """What an adapter returns."""
    series: dict[str, list[Series]] = field(default_factory=dict)      # tenor -> candidates, best first
    auctions: dict[str, list[Auction]] = field(default_factory=dict)   # tenor -> all known auctions (any residual days)
    gaps: dict[str, str] = field(default_factory=dict)                 # tenor -> why it is empty
    extra: dict = field(default_factory=dict)                          # adapter state to keep in the document
    warnings: list[str] = field(default_factory=list)                  # shown in status.json (e.g. files that could not be read)
    auction_dated: bool = False        # Italy, India: no series at all, so the latest in-window auction dates the curve


def pick_auction(auctions: list[Auction], tenor: str, ref: date) -> Auction | None:
    """Most recent auction on or before `ref` whose residual days fall in the tenor's window and which is at most
    AUCTION_MAX_AGE_DAYS old. Ties on the date resolve to the residual days closest to the window's middle."""
    lo, hi = AUCTION_WINDOWS[tenor]
    mid = (lo + hi) / 2
    best = None
    for a in auctions:
        if a.date > ref or (ref - a.date).days > AUCTION_MAX_AGE_DAYS or not (lo <= a.days <= hi):
            continue
        if best is None or (a.date, -abs(a.days - mid)) > (best.date, -abs(best.days - mid)):
            best = a
    return best


def point_at(raw: Raw, tenor: str, target: date) -> dict | None:
    """The value for one tenor on one curve date, or None."""
    for s in raw.series.get(tenor, []):
        hit = s.on_or_before(target)
        if hit:
            d, v = hit
            p = {"value": round(float(v), 4), "date": d.isoformat(), "kind": s.kind}
            label = (s.labels or {}).get(d) or s.label
            if label:
                p["label"] = label
            return p
    if tenor in AUCTION_WINDOWS and raw.auctions.get(tenor) is not None:
        a = pick_auction(raw.auctions[tenor], tenor, target)
        if a:
            return {"value": round(float(a.value), 4), "date": a.date.isoformat(), "kind": "A", "days": int(a.days)}
    return None


def curve_date(raw: Raw) -> date | None:
    """The country's own latest observation among its daily/weekly/bucket series (auctions and monthly averages never set it).
    Only an adapter that says so (`auction_dated`: Italy, India, auctions only) is dated by its latest in-window auction; any
    other country with no series fails as before (Japan with an empty curve file must not publish its bills alone)."""
    last = [s.last_date for cands in raw.series.values() for s in cands if s.kind in ("D", "W", "B") and s.last_date]
    if last:
        return max(last)
    if not raw.auction_dated:
        return None
    aus = [a.date for t, lst in raw.auctions.items() if t in AUCTION_WINDOWS for a in lst
           if AUCTION_WINDOWS[t][0] <= a.days <= AUCTION_WINDOWS[t][1]]
    return max(aus) if aus else None


def build_curves(raw: Raw, as_of: date) -> list[dict]:
    curves = []
    for cid, label, delta in CURVE_DEFS:
        target = as_of if delta is None else as_of - delta
        pts = {}
        for t in TENORS:
            p = point_at(raw, t, target)
            if p:
                pts[t] = p
        curves.append({"id": cid, "label": label, "date": target.isoformat(), "points": pts})
    return curves


def tenor_labels(raw: Raw) -> dict[str, str]:
    out = {}
    for t, cands in raw.series.items():
        for s in cands:
            if s.tenor_label:
                out[t] = s.tenor_label
    return out


def window_start(today: date) -> date:
    """Earliest date a bulk source must cover: the 1-year-earlier curve plus slack for look-back."""
    return today - relativedelta(years=1) - timedelta(days=20)
