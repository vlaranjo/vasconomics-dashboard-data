"""Yield-curve core: series types, the auction rule, the earlier-curve anchors, and the per-country document.

Cell kinds: D daily official observation, W weekly official observation, B bucket (the bucket is named in `label`),
A auction yield (own date, residual days). A tenor with no usable point is simply absent from `points`.
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
AUCTION_MAX_AGE_DAYS = 90

CURVE_DEFS = [("latest", "Latest", None), ("1m", "1 month earlier", relativedelta(months=1)),
              ("3m", "3 months earlier", relativedelta(months=3)), ("1y", "1 year earlier", relativedelta(years=1))]


class Skipped(Exception):
    """The adapter cannot run on purpose (for example a missing optional secret). Not a failure."""


@dataclass
class Series:
    kind: str                                   # D, W or B
    points: list[tuple[date, float]]            # ascending by date
    max_lag: int = 4                            # a value may be this many days older than the date asked for
    label: str | None = None                    # tooltip text for buckets ("1-3 month bucket")
    tenor_label: str | None = None              # axis/legend label override (Canada: "long-term benchmark")

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
            if s.label:
                p["label"] = s.label
            return p
    if tenor in AUCTION_WINDOWS and raw.auctions.get(tenor) is not None:
        a = pick_auction(raw.auctions[tenor], tenor, target)
        if a:
            return {"value": round(float(a.value), 4), "date": a.date.isoformat(), "kind": "A", "days": a.days}
    return None


def curve_date(raw: Raw) -> date | None:
    """The country's own latest observation among its daily/weekly/bucket series (auctions never set it)."""
    last = [s.last_date for cands in raw.series.values() for s in cands if s.kind in ("D", "W", "B") and s.last_date]
    return max(last) if last else None


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
