"""Relative Momentum charts (21 Nov 2026): each fund's relative strength and relative momentum against a benchmark fund, from weekly closes.

The maths is a port of the owner's reference implementation (_reference/local/rrg/rrg_calculations.py, normalised mode,
config.NORMALIZE_AXES = True), kept line for line so tests/test_momentum.py can compare the two to 1e-9:

    RawRS = price / benchmark                                   (weekly closes, aligned on the dates both have)
    MACD  = SMA10(RawRS) - SMA30(RawRS)
    x     = 100 + 100 * MACD / SMA30(RawRS)                     relative strength; > 100 <=> the 10-week average leads the 30-week
    y     = 100 + 5 * rolling_scale(SMA5(diff(x)), 16)          relative momentum; rolling_scale = x / rolling std (ddof 0), NO mean
                                                                subtraction, so y > 100 <=> x is rising
    quadrant: inclusive rule with epsilon 1e-6 (a point on an axis belongs to the upper/right quadrant)

Weekly bars are the last adjusted close of each COMPLETED week (Monday to Friday), labelled with that week's Friday. A week is
completed when the run's completed-bar cutoff (lookback.last_completed_date) is on or after its Friday. The frequency assertion of the
reference (median bar spacing 5-10 days) is kept: daily data can never reach the formula.

Each chart file carries the last `weeks` (40) points per fund; the warm-up (49 weeks before the first valid point) is computed
here from the full history and never published. Everything is rolling over fixed windows, so the history before the warm-up does not
change a single published number."""
from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd

# ---- constants, as in the reference config.py ------------------------------------------------------------------------------
SHORT_MA = 10            # short moving average of the relative line (reference config: the "short MA")
LONG_MA = 30             # long moving average (the "long MA")
MOMENTUM_MA = 5          # smoothing of the momentum leg
NORMALIZE_WINDOW = 16    # rolling std window of the momentum leg
NORMALIZE_SCALE = 5.0    # y = 100 + 5 * ...
STRENGTH_SCALE = 100.0   # x = 100 + 100 * ...
CENTER = 100.0
EPSILON = 1e-6
BAR_SPACING_DAYS = {"1wk": (5.0, 10.0), "1d": (0.5, 2.0)}
WARMUP_WEEKS = LONG_MA + MOMENTUM_MA + NORMALIZE_WINDOW - 2   # = 49: x from bar 29, diff from 30, SMA5 from 34, std16 from 49

LEADING, WEAKENING, LAGGING, IMPROVING = "Leading", "Weakening", "Lagging", "Improving"
QUADRANTS = (LEADING, WEAKENING, LAGGING, IMPROVING)


class FrequencyError(ValueError):
    """A price panel reached the momentum maths at the wrong bar frequency."""


def assert_frequency(index, *, expected: str = "1wk", context: str = "") -> None:
    """Fail unless `index` has weekly bar spacing (median 5-10 days), measured from the data. Ported from the reference."""
    lo, hi = BAR_SPACING_DAYS[expected]
    if len(index) < 3:
        return
    idx = pd.DatetimeIndex(index)
    spacing = float(idx.to_series().diff().dt.total_seconds().median() / 86_400.0)
    if not (lo <= spacing <= hi):
        raise FrequencyError(f"{context or 'momentum input'}: median bar spacing is {spacing:.2f} days, outside the {lo}-{hi} day "
                             f"range for weekly bars; the 10/30/5/16 windows are tuned for weekly bars only")


def _rolling_scale(x: pd.DataFrame, window: int) -> pd.DataFrame:
    std = x.rolling(window).std(ddof=0)
    return x / std.where(std > 0)


def _align(price_df: pd.DataFrame, benchmark: pd.Series):
    idx = price_df.index.intersection(benchmark.index).sort_values()
    return price_df.reindex(idx), benchmark.reindex(idx)


def compute(price_df: pd.DataFrame, benchmark: pd.Series) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(x, y) frames: relative strength and relative momentum for every column of `price_df` (weekly closes) against `benchmark`."""
    if price_df.empty:
        return price_df.copy(), price_df.copy()
    price_df, benchmark = _align(price_df, benchmark)
    assert_frequency(price_df.index, context="momentum.compute")
    raw_rs = price_df.div(benchmark, axis=0)
    macd = raw_rs.rolling(SHORT_MA).mean() - raw_rs.rolling(LONG_MA).mean()
    x = 100.0 + STRENGTH_SCALE * macd.div(raw_rs.rolling(LONG_MA).mean())
    roc = x.diff(1).rolling(MOMENTUM_MA).mean()
    y = 100.0 + NORMALIZE_SCALE * _rolling_scale(roc, NORMALIZE_WINDOW)
    return x, y


def classify(x: float, y: float) -> str:
    """Inclusive quadrant rule: within EPSILON of 100 counts as the upper / right side."""
    strong_x = x >= CENTER - EPSILON
    strong_y = y >= CENTER - EPSILON
    if strong_x and strong_y:
        return LEADING
    if strong_x:
        return WEAKENING
    if not strong_y:
        return LAGGING
    return IMPROVING


# ---- weekly bars -----------------------------------------------------------------------------------------------------------
def week_friday(d: date) -> date:
    return d + timedelta(days=4 - d.weekday()) if d.weekday() <= 4 else d - timedelta(days=d.weekday() - 4)


def weekly_closes(bars, cutoff: date) -> list[tuple[date, float]]:
    """Last close of each completed Monday-Friday week, labelled with the week's Friday. `bars` = sorted [(date, close)] of completed
    daily bars. A week counts only when `cutoff` (the last completed daily bar date allowed) is on or after its Friday; weekend bars
    (none on the exchanges we use) belong to the week before."""
    out: dict[date, float] = {}
    for d, c in bars:
        if d > cutoff:
            continue
        f = week_friday(d)
        if f > cutoff:
            continue
        out[f] = c                       # bars are in date order: the last one of the week wins
    return sorted(out.items())


def latest_complete_friday(cutoff: date) -> date:
    f = week_friday(cutoff)
    return f if f <= cutoff else f - timedelta(days=7)


# ---- one chart -------------------------------------------------------------------------------------------------------------
def _epoch(d: date) -> int:
    return (d - date(1970, 1, 1)).days


def series_points(weekly: list[tuple[date, float]], bench_weekly: list[tuple[date, float]], weeks: int):
    """The last `weeks` valid points [(friday, x, y)] of one fund (exact floats), or [] if it has none yet."""
    if not weekly or not bench_weekly:
        return []
    p = pd.Series({pd.Timestamp(d): c for d, c in weekly}, dtype=float).sort_index()
    b = pd.Series({pd.Timestamp(d): c for d, c in bench_weekly}, dtype=float).sort_index()
    x, y = compute(p.to_frame("f"), b)
    ok = x["f"].notna() & y["f"].notna() & np.isfinite(x["f"]) & np.isfinite(y["f"])
    rows = [(ts.date(), float(xv), float(yv)) for ts, xv, yv, k in zip(x.index, x["f"], y["f"], ok) if k]
    return rows[-weeks:]


def build_series(meta: dict, pts, *, decimals: int = 4) -> dict:
    last = pts[-1]
    return {"id": meta["id"], "label": meta["label"], "ticker": meta["ticker"],
            **({"substitute": meta["substitute"]} if meta.get("substitute") else {}),
            "stale": False, "stale_reason": None,
            "quadrant": classify(last[1], last[2]),
            "d": [_epoch(d) for d, _, _ in pts],
            "x": [round(v, decimals) for _, v, _ in pts],
            "y": [round(v, decimals) for _, _, v in pts]}


def chart_members(chart: dict, section: dict) -> tuple[list[dict], list[dict]]:
    """The funds of one chart, in the section's order: [{id, label, ticker, substitute?}], and the rows left out [{id, label, reason}].
    A hedged row is never charted as it is: it has a substitute (an unhedged fund on the same index) or is left out with a reason."""
    subs, outs = chart.get("substitutes") or {}, chart.get("leave_out") or {}
    members, left = [], []
    for r in section["rows"]:
        if r["id"] in outs:
            left.append({"id": r["id"], "label": r["label"], "reason": outs[r["id"]]})
        elif r["id"] in subs:
            s = subs[r["id"]]
            members.append({"id": r["id"], "label": s["label"], "ticker": s["ticker"],
                            "substitute": {"ticker": s["ticker"], "isin": s["isin"], "provider": s["provider"], "fund": s["fund"],
                                           "replaces": r["ticker"], "replaces_label": r["label"]}})
        else:
            members.append({"id": r["id"], "label": r["label"], "ticker": r["ticker"]})
    return members, left


def check_config(mcfg: dict, sections: dict) -> None:
    """Never mix EUR-hedged and unhedged funds in one chart: the benchmark and every substitute are unhedged, and every hedged row of
    the section is substituted or left out. Raises ValueError (the job then fails before any request)."""
    for ch in mcfg.get("charts", []):
        sec = sections.get(ch["section"])
        if sec is None:
            raise ValueError(f"momentum chart {ch['id']}: unknown section {ch['section']}")
        if ch["benchmark"].get("hedged") is not False:
            raise ValueError(f"momentum chart {ch['id']}: the benchmark must be an unhedged fund (hedged: false)")
        ids = {r["id"] for r in sec["rows"]}
        for k in list((ch.get("substitutes") or {})) + list((ch.get("leave_out") or {})):
            if k not in ids:
                raise ValueError(f"momentum chart {ch['id']}: {k} is not a row of {ch['section']}")
        for k, s in (ch.get("substitutes") or {}).items():
            if s.get("hedged") is not False:
                raise ValueError(f"momentum chart {ch['id']}: substitute for {k} must be unhedged (hedged: false)")
            for f in ("ticker", "isin", "provider", "fund", "label"):
                if not s.get(f):
                    raise ValueError(f"momentum chart {ch['id']}: substitute for {k} needs '{f}'")
        for r in sec["rows"]:
            if not isinstance(r.get("hedged"), bool):          # an unstated flag is never taken as "unhedged"
                raise ValueError(f"momentum chart {ch['id']}: {r['ticker']} has no explicit hedged: true/false in the section")
            if r["hedged"] and r["id"] not in (ch.get("substitutes") or {}) and r["id"] not in (ch.get("leave_out") or {}):
                raise ValueError(f"momentum chart {ch['id']}: {r['ticker']} is EUR-hedged; give it an unhedged substitute or leave it out")


def build_chart(chart: dict, section: dict, *, weeks: int, cutoff: date, bars_for, prev: dict | None, now_iso: str,
                max_jump_pct: float, jump_exceptions=()) -> tuple[dict, list[str]]:
    """One chart document and the problems met. `bars_for(ticker)` returns sorted completed daily bars or raises.
    A fund that cannot be read keeps its previously published series, marked stale ("fetch_failed"); if the BENCHMARK cannot be read
    the caller keeps the whole previous file (raises BenchmarkError)."""
    from . import validate
    problems: list[str] = []
    bench = chart["benchmark"]
    window_start = cutoff - timedelta(weeks=weeks + WARMUP_WEEKS + 8)     # the bars that enter a published number, plus margin

    def weekly_for(ticker):
        bars = bars_for(ticker)
        validate.check_price_jumps(ticker, [b for b in bars if b[0] >= window_start], max_jump_pct, jump_exceptions)
        return weekly_closes(bars, cutoff)

    try:
        bw = weekly_for(bench["ticker"])
    except Exception as e:  # noqa: BLE001
        raise BenchmarkError(f"benchmark {bench['ticker']}: {str(e)[:120]}") from e
    if not bw:
        raise BenchmarkError(f"benchmark {bench['ticker']}: no completed weeks")
    members, left = chart_members(chart, section)
    prev_series = {s["id"]: s for s in (prev or {}).get("series", [])}
    series = []
    for m in members:
        try:
            fw = weekly_for(m["ticker"])
            pts = series_points(fw, bw, weeks)
        except Exception as e:  # noqa: BLE001
            problems.append(f"{m['ticker']}: {str(e)[:120]}")
            # carried forward only if it was computed from the SAME fund: after a config change (e.g. a new unhedged substitute) the old
            # series is another fund's, and republishing it could mix a hedged fund into the chart
            if m["id"] in prev_series and prev_series[m["id"]].get("ticker") == m["ticker"]:
                old = dict(prev_series[m["id"]])
                old["stale"], old["stale_reason"] = True, "fetch_failed"
                series.append(old)
            continue
        if not pts:
            common = len({d for d, _ in fw} & {d for d, _ in bw})
            reason = (f"less than {WARMUP_WEEKS + 1} weeks of history in common with the benchmark" if common <= WARMUP_WEEKS
                      else "its relative momentum is undefined: it moves exactly with the benchmark")
            left.append({"id": m["id"], "label": m["label"], "reason": reason})
            continue
        series.append(build_series(m, pts))
    as_of = max((s["d"][-1] for s in series), default=None)
    for s in series:
        if not s["stale"] and as_of is not None and s["d"][-1] < as_of:
            s["stale"], s["stale_reason"] = True, "old_close"
    doc = {
        "schema_version": 1, "chart": chart["id"], "section": chart["section"], "generated_at": now_iso, "last_success": now_iso,
        "stale": False, "stale_reason": None,
        "as_of": (date(1970, 1, 1) + timedelta(days=as_of)).isoformat() if as_of is not None else None,
        "weeks": weeks, "frequency": "weekly", "week_ends": "Friday",
        "benchmark": {k: bench[k] for k in ("label", "ticker", "isin", "provider", "fund")},
        "method": {"short_ma": SHORT_MA, "long_ma": LONG_MA, "momentum_ma": MOMENTUM_MA, "normalize_window": NORMALIZE_WINDOW,
                   "momentum_scale": NORMALIZE_SCALE, "strength_scale": STRENGTH_SCALE, "center": CENTER, "epsilon": EPSILON,
                   "warmup_weeks": WARMUP_WEEKS},
        "series": series, "left_out": left,
    }
    return doc, problems


class BenchmarkError(Exception):
    pass


def quadrant_ok(q: str, x: float, y: float, tol: float = 1e-4) -> bool:
    """A published (rounded) point agrees with its quadrant, unless it sits within `tol` of an axis (rounding may cross it)."""
    if abs(x - CENTER) <= tol or abs(y - CENTER) <= tol:
        return True
    return classify(x, y) == q


def finite(v) -> bool:
    return isinstance(v, (int, float)) and math.isfinite(v)
