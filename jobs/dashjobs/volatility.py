"""Volatility job (13 Nov 2026): ^VIX, ^SKEW, ^MOVE from Yahoo Finance and the VIX futures curve from Cboe -> validate -> atomic swap.

Published files (manifest block `volatility`), all under data/volatility/:
  summary.json     the page's table: latest level and the change over each look-back, for VIX, the VIX futures slope, SKEW, MOVE
  vix.json, skew.json, move.json
                   chart series: daily closes for the last five years, the last close of each week before that; the 10-year and
                   full-history averages computed on the FULL daily history
  vx-term.json     the four term-structure curves (latest, 1 month, 6 months and 1 year earlier). Source by config
                   (`vx_term_source`, 13 Nov 2026): "cboe" (default) = VIX futures settlement prices by contract position;
                   "yahoo" = the Cboe VIX indices on Yahoo (^VIX9D, ^VIX, ^VIX3M, ^VIX6M, ^VIX1Y) by horizon. The table's slope row
                   follows the same source. A ticker Yahoo has no history for (^VIX1Y, 13 Nov 2026) is left out and named.
  vx-history.json  the daily slope since the CSV archive starts (January 2013) and the daily curves of the last 400 days. The page
                   does not read it; the job does: each run fetches only the contracts still trading (about ten small CSVs) and
                   rebuilds the last ten days, and takes everything older from here. Without it (first run) every monthly contract's
                   CSV is read once (175 files on 13 Nov 2026, 1.5 s apart).
Keep-last-good: a series that cannot be fetched, or fails validation, keeps its published file, marked stale. A series whose new
data ends before the published file's is left exactly as published. Nothing is ever written into data/ while working.
"""
from __future__ import annotations

import time
from bisect import bisect_right
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import cboe, history, lookback, publish, status, validate

SOURCE_KEY = "volatility"
DIR = "volatility"
CURVES = [("latest", "Latest", None), ("1m", "1 month earlier", "1M"), ("6m", "6 months earlier", "6M"), ("1y", "1 year earlier", "1Y")]
CURVE_ANCHOR_MAX_GAP_DAYS = 7    # an earlier curve more than a week before its anchor is not shown (history too short)
SLOPE_ROW = {"id": "vx_slope", "name": "VIX futures slope", "long": "Least-squares slope of the first seven monthly VIX futures (points per month)"}
YAHOO_SLOPE_ROW = {"id": "vx_slope", "name": "VIX term-structure slope"}      # "long" names the indices used (yahoo_slope_row)
TERM_SOURCES = ("cboe", "yahoo")


class NothingFetched(Exception):
    """No series could be fetched and nothing is published to keep: the run fails."""


class OlderData(ValueError):
    pass


def _day(i: int) -> date:
    return date.fromordinal(i + history.EPOCH_ORDINAL)


# ---- Yahoo indices -----------------------------------------------------------------------------------------------------------
def check_index(meta: dict, bars, *, today: date, prev_doc: dict | None, max_age: int) -> None:
    lo, hi = meta["range"]
    if len(bars) < 250:
        raise validate.ValidationError(f"{meta['ticker']}: only {len(bars)} daily values")
    for d, v in bars:
        if not lo <= v <= hi:
            raise validate.ValidationError(f"{meta['ticker']}: {v} on {d.isoformat()} is outside {lo}..{hi}")
    age = (today - bars[-1][0]).days
    if age > max_age:
        raise validate.ValidationError(f"{meta['ticker']}: last value {bars[-1][0].isoformat()} is {age} days old")
    if prev_doc and bars[-1][0].isoformat() < prev_doc["as_of"]:
        raise OlderData(f"{meta['ticker']}: newest usable bar {bars[-1][0].isoformat()} is older than the published {prev_doc['as_of']}")


def index_doc(meta: dict, bars, now_iso: str, daily_key: str) -> dict:
    a10, afull = history.averages(bars)
    pts = history.level_points(bars, daily_key)
    dates = [d for d, _ in bars]
    return {
        "schema_version": 1, "id": meta["id"], "name": meta["name"], "long": meta["long"], "ticker": meta["ticker"],
        "source": "Yahoo Finance", "fetched_at": now_iso, "last_success": now_iso, "stale": False, "stale_reason": None,
        "first_date": dates[0].isoformat(), "as_of": dates[-1].isoformat(), "last_value": round(bars[-1][1], 2),
        "n_daily": len(bars), "daily_from": dates[history._start_index(dates, dates[-1], daily_key)].isoformat(),
        "avg_10y": a10, "avg_full": afull, "d": pts["d"], "v": pts["v"],
    }


def summary_row(meta: dict, series, *, stale: bool, stale_reason: str | None, keys, ndigits: int = 2, direction: str = "up_bad") -> dict:
    return {"id": meta["id"], "name": meta["name"], "long": meta["long"], "direction": direction,
            "latest": round(series[-1][1], ndigits), "date": series[-1][0].isoformat(), "first_date": series[0][0].isoformat(),
            "stale": stale, "stale_reason": stale_reason, "changes": lookback.compute_changes(series, keys, ndigits)}


# ---- Cboe VX ----------------------------------------------------------------------------------------------------------------
def _cached_get(getter, url: str, cache_file: Path | None, immutable: bool) -> bytes:
    if cache_file is not None and immutable and cache_file.exists():
        return cache_file.read_bytes()
    body = getter.get(url)
    if cache_file is not None and immutable:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(body)
    return body


def _get(getter, url: str, what: str, cache_file=None, immutable=False) -> bytes:
    """A refusal (401/403/429) or a web page where data was expected is a Challenge: no further request to Cboe this run."""
    try:
        return _cached_get(getter, url, cache_file, immutable)
    except Exception as e:  # noqa: BLE001
        if any(f"HTTP {c}" in str(e) for c in (401, 403, 429)):
            raise cboe.Challenge(f"{what}: {e}") from e
        raise


def vx_update(vcfg: dict, getter, *, today: date, prev_hist: dict | None, cache_dir: Path | None = None) -> dict:
    """Fetch what is needed and rebuild the recent days. Returns {"hist": new vx-history document body (without stamps),
    "contracts": monthly contracts, "requests": n, "daily_dates": [dates read from the day's settlement file]}.
    Raises cboe.Challenge, cboe.ParseError, FetchError or validate.ValidationError; the caller keeps the last good files."""
    log0 = len(getattr(getter, "log", []))
    listing = cboe.parse_listing(_get(getter, cboe.LIST_URL, "contract list"))
    contracts = cboe.monthly_contracts(listing)
    expiries = [c["expiry"] for c in contracts]
    first_ok = cboe.first_valid_day(contracts)
    if prev_hist and prev_hist.get("slope", {}).get("d"):
        last = date.fromisoformat(prev_hist["as_of"])
        start = last - timedelta(days=vcfg["recompute_days"])           # days after `start` are rebuilt
    else:
        start = first_ok - timedelta(days=1)
    gap = cboe.listing_gap(contracts, start)
    if gap:
        raise validate.ValidationError(f"VX contract list: {gap}")
    need = [c for c in contracts if c["expiry"] > start and c["expiry"] > first_ok]
    settles: dict[date, dict[date, float]] = {}
    for c in need:
        if c["expiry"] - timedelta(days=300) > today:
            continue                                                     # listed but not trading yet
        name = Path(c["path"]).name
        body = _get(getter, cboe.CDN + c["path"], name, cache_dir / name if cache_dir else None,
                    immutable=c["expiry"] < today - timedelta(days=7))
        settles[c["expiry"]] = {d: v for d, v in cboe.parse_contract_csv(body).items() if d <= today}
    archive_last = max((d for s in settles.values() for d in s), default=start)
    # The CSVs are rewritten once a day around 01:06 New York time, so the evening run reads the day itself from the day's settlement file.
    daily_dates = []
    d = archive_last
    tried = 0
    while tried < vcfg["daily_settlement_lookback"]:
        d += timedelta(days=1)
        if d > today:
            break
        if d.weekday() >= 5:
            continue
        tried += 1
        day = cboe.parse_daily_settlement(_get(getter, cboe.SETTLE_URL.format(d=d.isoformat()), f"daily settlement {d.isoformat()}"))
        if day:
            daily_dates.append(d.isoformat())
            for exp, v in day.items():
                if exp in settles or exp > d:
                    settles.setdefault(exp, {})[d] = v
    new_days = [x for x in cboe.trade_dates(settles) if x > start and x >= first_ok]
    lo_s, hi_s = vcfg["settle_range"]
    new_slope, new_curves = {}, {}
    for x in new_days:
        cv = cboe.curve_on(x, expiries, settles, vcfg["positions"])
        vals = [p["settle"] for p in cv]
        if all(v is None for v in vals):
            continue
        for p in cv:
            if p["settle"] is not None and not lo_s <= p["settle"] <= hi_s:
                raise validate.ValidationError(f"VX {p['expiry'].isoformat()} on {x.isoformat()}: settlement {p['settle']} outside {lo_s}..{hi_s}")
        new_curves[x] = vals + [None] * (vcfg["positions"] - len(vals))
        s = cboe.slope_of(cv, vcfg["slope_positions"], vcfg["slope_min_points"])
        if s is not None:
            if abs(s) > vcfg["max_abs_slope"]:
                raise validate.ValidationError(f"VX slope {s} on {x.isoformat()} is outside +-{vcfg['max_abs_slope']}")
            new_slope[x] = s
    # merge with the published history: everything up to `start` is kept as published
    old_s = {}
    old_c = {}
    if prev_hist:
        old_s = {_day(i): v for i, v in zip(prev_hist["slope"]["d"], prev_hist["slope"]["v"]) if _day(i) <= start}
        old_c = {_day(i): v for i, v in zip(prev_hist["curves"]["d"], prev_hist["curves"]["s"]) if _day(i) <= start}
    slope = {**old_s, **new_slope}
    curves = {**old_c, **new_curves}
    if not curves:
        raise validate.ValidationError("VX: no settlement at all")
    as_of = max(curves)
    keep_from = as_of - timedelta(days=vcfg["keep_curve_days"])
    curves = {k: v for k, v in curves.items() if k >= keep_from}
    sd = sorted(slope)
    cd = sorted(curves)
    return {
        "hist": {"as_of": as_of.isoformat(), "first_date": sd[0].isoformat() if sd else None, "archive_last": archive_last.isoformat(),
                 "slope": {"d": [history.epoch_day(x) for x in sd], "v": [slope[x] for x in sd]},
                 "curves": {"d": [history.epoch_day(x) for x in cd], "s": [curves[x] for x in cd]}},
        "contracts": contracts, "requests": len(getattr(getter, "log", [])) - log0, "daily_dates": daily_dates, "rebuilt_from": (start + timedelta(days=1)).isoformat(),
    }


def term_curves(hist: dict, contracts: list[dict]) -> list[dict]:
    """The four curves by contract position, each on its own date: the last stored day on or before each anchor."""
    cd = [_day(i) for i in hist["curves"]["d"]]
    expiries = [c["expiry"] for c in contracts]
    by_exp = {c["expiry"]: c for c in contracts}
    latest = cd[-1]
    out = []
    for cid, label, key in CURVES:
        if key is None:
            i = len(cd) - 1
        else:
            anchor = lookback.anchor_for(latest, key)
            i = bisect_right(cd, anchor) - 1
            if i < 0 or (anchor - cd[i]).days > CURVE_ANCHOR_MAX_GAP_DAYS:
                out.append({"id": cid, "label": label, "date": None, "anchor": anchor.isoformat(), "points": []})
                continue
        day = cd[i]
        vals = hist["curves"]["s"][i]
        after = [e for e in expiries if e > day][: len(vals)]
        pts = []
        for pos, (e, v) in enumerate(zip(after, vals), start=1):
            c = by_exp[e]
            pts.append({"pos": pos, "code": c["code"], "month": c["month"], "expiry": e.isoformat(), "days": (e - day).days, "settle": v})
        out.append({"id": cid, "label": label, "date": day.isoformat(), **({"anchor": lookback.anchor_for(latest, key).isoformat()} if key else {}),
                    "points": pts})
    return out


# ---- the Yahoo term structure (fallback source, 13 Nov 2026) ---------------------------------------------------------------
def yahoo_term_update(tcfg: dict, fetch, *, cutoff: date) -> dict:
    """The VIX indices by horizon from Yahoo. A ticker with fewer than `min_history` completed daily values is left out (Yahoo gives
    only today's live quote for ^VIX1Y), and so is an `optional` ticker that cannot be fetched; a fetch error on any other ticker
    fails the source (the last good file is kept). A day counts only when EVERY ticker kept has a value, so the slope is one
    measure over its whole history (review of 13 Nov 2026): the curve and the least-squares slope of level on horizon in months.
    Raises ValidationError when a value or a slope is out of range, or fewer than `min_points` tickers are kept."""
    lo, hi = tcfg["range"]
    tenors, left_out, series = [], [], {}
    for t in tcfg["tickers"]:
        try:
            raw = fetch(t["ticker"])
        except Exception as e:  # noqa: BLE001
            if not t.get("optional"):
                raise
            left_out.append({"ticker": t["ticker"], "label": t["label"], "reason": f"it could not be fetched from Yahoo Finance in this run ({str(e)[:80]})"})
            continue
        bars = lookback.clean_bars(raw, cutoff)
        if len(bars) < tcfg["min_history"]:
            left_out.append({"ticker": t["ticker"], "label": t["label"],
                             "reason": f"Yahoo Finance has {len(bars)} completed daily value{'' if len(bars) == 1 else 's'} for it, not a history"})
            continue
        for d, v in bars:
            if not lo <= v <= hi:
                raise validate.ValidationError(f"{t['ticker']}: {v} on {d.isoformat()} is outside {lo}..{hi}")
        tenors.append(t)
        series[t["ticker"]] = dict(bars)
    if len(tenors) < tcfg["min_points"]:
        raise validate.ValidationError(f"Yahoo term structure: only {len(tenors)} tickers with a history (need {tcfg['min_points']})")
    slope, curves = {}, {}
    for d in sorted(set().union(*(s.keys() for s in series.values()))):
        vals = [series[t["ticker"]].get(d) for t in tenors]
        if any(v is None for v in vals):
            continue
        curves[d] = [round(v, 2) for v in vals]
        slope[d] = round(cboe.ols_slope([(t["months"], v) for t, v in zip(tenors, vals)]), 4)
        if abs(slope[d]) > tcfg.get("max_abs_slope", 15):
            raise validate.ValidationError(f"Yahoo term-structure slope {slope[d]} on {d.isoformat()} is outside +-{tcfg.get('max_abs_slope', 15)}")
    if not curves:
        raise validate.ValidationError("Yahoo term structure: no day with enough values")
    return {"tenors": tenors, "left_out": left_out, "slope": slope, "curves": curves}


def yahoo_term_curves(res: dict) -> list[dict]:
    days = sorted(res["curves"])
    latest = days[-1]
    out = []
    for cid, label, key in CURVES:
        i = len(days) - 1
        if key is not None:
            anchor = lookback.anchor_for(latest, key)
            i = bisect_right(days, anchor) - 1
            if i < 0 or (anchor - days[i]).days > CURVE_ANCHOR_MAX_GAP_DAYS:
                out.append({"id": cid, "label": label, "date": None, "anchor": anchor.isoformat(), "points": []})
                continue
        day = days[i]
        pts = [{"pos": n, "ticker": t["ticker"], "label": t["label"], "short": t["short"], "months": t["months"], "value": v}
               for n, (t, v) in enumerate(zip(res["tenors"], res["curves"][day]), start=1)]
        out.append({"id": cid, "label": label, "date": day.isoformat(),
                    **({"anchor": lookback.anchor_for(latest, key).isoformat()} if key else {}), "points": pts})
    return out


def yahoo_slope_row(tenors: list[dict]) -> dict:
    names = [t["ticker"].lstrip("^") for t in tenors]
    return {**YAHOO_SLOPE_ROW, "long": f"Least-squares slope of {', '.join(names[:-1])} and {names[-1]} against horizon in months (points per month)"}


# ---- the run ----------------------------------------------------------------------------------------------------------------
def run(cfg: dict, fetch_yahoo, getter, *, today: date, now: datetime | None = None, data_dir, work_dir, universe: dict,
        env=None, sleep=time.sleep, cache_dir: Path | None = None, workflow: str = "volatility") -> dict:
    clock = now is None
    now = now or datetime.now(timezone.utc)
    started = now
    data_dir, work_dir = Path(data_dir), Path(work_dir)
    out_dir = work_dir / "out"
    now_iso = status.iso(now)
    keys = cfg["lookbacks"]
    vcfg = cfg["vx"]
    max_age = cfg["validation"]["max_close_age_days"]
    daily_key = f"{cfg['validation']['daily_years']}Y"
    prev_manifest = publish.read_json(data_dir / "manifest.json") or {}
    prev_status = publish.read_json(data_dir / "status.json")
    prev_summary = publish.read_json(data_dir / DIR / "summary.json") or {}
    prev_rows = {r["id"]: r for r in prev_summary.get("rows", [])}
    last_success = (prev_status or {}).get("sources", {}).get(SOURCE_KEY, {}).get("last_success")
    files: dict[str, object] = {}
    rows: dict[str, dict] = {}
    failed: list[str] = []
    notes: list[str] = []
    ok = 0
    source = cfg.get("vx_term_source", "cboe")
    if source not in TERM_SOURCES:
        raise validate.ValidationError(f"config vx_term_source is {source!r}; it must be one of {', '.join(TERM_SOURCES)}")
    raw_cache: dict[str, object] = {}

    def yfetch(ticker):
        """One Yahoo request per symbol per run, 3 s apart (^VIX serves both its chart and the Yahoo term structure)."""
        if ticker not in raw_cache:
            if raw_cache:
                sleep(3.0)
            raw_cache[ticker] = None                      # counts as asked, even if it fails
            raw_cache[ticker] = fetch_yahoo(ticker)
        if raw_cache[ticker] is None:
            raise RuntimeError(f"{ticker}: the earlier request this run failed")
        return raw_cache[ticker]

    def keep(rel: str, row_id: str, reason: str, mark_stale: bool = True) -> bool:
        """Carry the published file and table row forward. Returns False when there is nothing published to keep."""
        prev = publish.read_json(data_dir / rel)
        if not prev:
            return False
        if mark_stale:
            prev = {**prev, "stale": True, "stale_reason": reason}
        files[rel] = prev
        if row_id in prev_rows:
            rows[row_id] = {**prev_rows[row_id], **({"stale": True, "stale_reason": reason} if mark_stale else {})}
        return True

    # Yahoo: one symbol at a time, 3 s apart
    cutoff = lookback.last_completed_date("us_index", today, now)
    for i, meta in enumerate(cfg["indices"]):
        rel = f"{DIR}/{meta['id']}.json"
        prev_doc = publish.read_json(data_dir / rel)
        try:
            bars = lookback.clean_bars(yfetch(meta["ticker"]), cutoff)
            check_index(meta, bars, today=today, prev_doc=prev_doc, max_age=max_age)
            doc = index_doc(meta, bars, now_iso, daily_key)
            validate.validate_vol_index(doc)
            files[rel] = doc
            rows[meta["id"]] = summary_row(meta, bars, stale=False, stale_reason=None, keys=keys)
            ok += 1
        except OlderData as e:
            notes.append(f"{e} (kept as published)")
            keep(rel, meta["id"], "", mark_stale=False)
        except Exception as e:  # noqa: BLE001 - any fetch or validation failure keeps the last good file
            failed.append(f"{meta['ticker']}: {str(e)[:160]}")
            keep(rel, meta["id"], "fetch_or_validation_failed")

    # Cboe: the contract list, the CSVs still needed, the day's settlement file
    hist_rel, term_rel = f"{DIR}/vx-history.json", f"{DIR}/vx-term.json"
    prev_hist = publish.read_json(data_dir / hist_rel)
    prev_term = publish.read_json(data_dir / term_rel)
    vx_info = None
    if source == "yahoo":
        keep(hist_rel, "", "", mark_stale=False)          # the Cboe history waits, unchanged, for a switch back
        try:
            res = yahoo_term_update(cfg["yahoo_term"], yfetch, cutoff=cutoff)
            as_of = max(res["curves"])
            if prev_term and prev_term.get("source") == "Yahoo Finance" and as_of.isoformat() < prev_term["as_of"]:
                raise OlderData(f"Yahoo term structure: newest day {as_of.isoformat()} is older than the published {prev_term['as_of']}")
            age = (today - as_of).days
            if age > max_age:
                raise validate.ValidationError(f"Yahoo term structure: last complete day {as_of.isoformat()} is {age} days old")
            n = len(res["tenors"])
            term_doc = {"schema_version": 1, "source": "Yahoo Finance", "kind": "indices", "source_url": "https://finance.yahoo.com/",
                        "fetched_at": now_iso, "last_success": now_iso, "stale": False, "stale_reason": None, "as_of": as_of.isoformat(),
                        "positions": n, "slope_positions": n, "slope_latest": res["slope"].get(as_of),
                        "tenors": [{k: t[k] for k in ("ticker", "label", "short", "months")} for t in res["tenors"]],
                        "left_out": res["left_out"], "curves": yahoo_term_curves(res)}
            validate.validate_vx_term(term_doc)
            files[term_rel] = term_doc
            slope_series = sorted(res["slope"].items())
            rows[SLOPE_ROW["id"]] = summary_row(yahoo_slope_row(res["tenors"]), slope_series, stale=False, stale_reason=None, keys=keys, direction="up_good")
            ok += 1
            vx_info = {"requests": 0, "daily_dates": [], "rebuilt_from": "", "left_out": [x["ticker"] for x in res["left_out"]]}
        except OlderData as e:
            notes.append(f"{e} (kept as published)")
            keep(term_rel, SLOPE_ROW["id"], "", mark_stale=False)
        except Exception as e:  # noqa: BLE001
            failed.append(f"Yahoo VIX term structure: {type(e).__name__}: {str(e)[:160]}")
            keep(term_rel, SLOPE_ROW["id"], "fetch_or_validation_failed")
    else:
        try:
            res = vx_update(vcfg, getter, today=today, prev_hist=prev_hist, cache_dir=cache_dir)
            h = res["hist"]
            if prev_hist and h["as_of"] < prev_hist["as_of"]:
                raise OlderData(f"VX: newest settlement {h['as_of']} is older than the published {prev_hist['as_of']}")
            age = (today - date.fromisoformat(h["as_of"])).days
            if age > max_age:
                raise validate.ValidationError(f"VX: last settlement {h['as_of']} is {age} days old")
            curves = term_curves(h, res["contracts"])
            n_latest = sum(p["settle"] is not None for p in curves[0]["points"])
            if n_latest < vcfg["slope_min_points"]:
                raise validate.ValidationError(f"VX: only {n_latest} settlements on the latest curve ({h['as_of']})")
            hist_doc = {"schema_version": 1, "source": "Cboe", "source_url": cboe.PAGE_URL, "fetched_at": now_iso, "last_success": now_iso,
                        "stale": False, "stale_reason": None, **h}
            sd = h["slope"]
            slope_series = [(_day(i), v) for i, v in zip(sd["d"], sd["v"])]
            last_slope = slope_series[-1] if slope_series else None
            term_doc = {"schema_version": 1, "source": "Cboe", "kind": "futures", "source_url": cboe.PAGE_URL, "terms_url": "https://www.cboe.com/terms/",
                        "fetched_at": now_iso, "last_success": now_iso, "stale": False, "stale_reason": None, "as_of": h["as_of"],
                        "positions": vcfg["positions"], "slope_positions": vcfg["slope_positions"],
                        "slope_latest": last_slope[1] if last_slope and last_slope[0].isoformat() == h["as_of"] else None,
                        "curves": curves}
            validate.validate_vx_history(hist_doc)
            validate.validate_vx_term(term_doc)
            files[hist_rel], files[term_rel] = hist_doc, term_doc
            if slope_series:
                rows[SLOPE_ROW["id"]] = summary_row(SLOPE_ROW, slope_series, stale=False, stale_reason=None, keys=keys, direction="up_good")
            ok += 1
            vx_info = {k: res[k] for k in ("requests", "daily_dates", "rebuilt_from")}
        except OlderData as e:
            notes.append(f"{e} (kept as published)")
            keep(hist_rel, "", "", mark_stale=False)
            keep(term_rel, SLOPE_ROW["id"], "", mark_stale=False)       # the slope row travels with the term file it belongs to
        except Exception as e:  # noqa: BLE001 - Challenge, fetch, parse or validation: keep the last good files, marked stale
            failed.append(f"Cboe VX: {type(e).__name__}: {str(e)[:160]}")
            reason = "challenge" if isinstance(e, cboe.Challenge) else "fetch_or_validation_failed"
            keep(hist_rel, "", reason)
            keep(term_rel, SLOPE_ROW["id"], reason)                     # with the term file, whichever source it came from

    if not ok and not files:
        raise NothingFetched("; ".join(failed) or "nothing fetched")
    # The table's source line names the source of the term-structure file actually published, not the config: after a failed first
    # run on the other source, the kept file (and its slope row, carried with it) is still the old source's (review of 13 Nov 2026).
    published_term = files.get(term_rel)
    published_source = source if not published_term else ("yahoo" if published_term.get("kind") == "indices" else "cboe")
    order = [m["id"] for m in cfg["indices"]]
    order = order[:1] + [SLOPE_ROW["id"]] + order[1:]                       # VIX, the slope, SKEW, MOVE
    srows = [rows[i] for i in order if i in rows]
    # Review of 13 Nov 2026: a series that fetches but stops advancing (^MOVE on Yahoo can lag) is flagged like a lagging fund row:
    # its last value 2 or more business days behind the table's latest date.
    latest = max((date.fromisoformat(r["date"]) for r in srows), default=None)
    for r in srows:
        if not r["stale"] and latest and lookback.is_stale_close(date.fromisoformat(r["date"]), latest):
            r["stale"], r["stale_reason"] = True, "old_close"
    summary = {"schema_version": 1, "generated_at": now_iso, "as_of": max(r["date"] for r in srows) if srows else today.isoformat(),
               "lookbacks": keys, "slope_source": published_source, "rows": srows}
    validate.validate_vol_summary(summary)
    files[f"{DIR}/summary.json"] = summary
    if ok:
        last_success = now_iso
    finished = datetime.now(timezone.utc) if clock else now
    n_items = len(cfg["indices"]) + 1
    st = status.merge_status(
        prev_status, SOURCE_KEY,
        status.source_block(now=now, last_success=last_success, items_ok=ok, items_total=n_items, failed=failed + notes,
                            cadence_hours=24, stale=bool(failed)),
        status.run_info(workflow, started, finished, env), now)
    entries = {}
    for rel, doc in files.items():
        key = Path(rel).stem
        entries[key] = {"path": rel, "as_of": doc["as_of"]}
    manifest = publish.merge_manifest(prev_manifest, generated_at=now_iso, updates={"volatility": entries},
                                      keep={"volatility": set(entries)})
    files["status.json"] = st
    validate.validate_status(st)
    validate.validate_manifest(manifest, universe=universe)
    publish.stage(data_dir, out_dir)
    written = publish.write_outputs(out_dir, files, manifest)
    validate.validate_manifest_files(out_dir, manifest)
    publish.atomic_swap(data_dir, out_dir)
    return {"ok": ok, "total": n_items, "failed": failed, "notes": notes, "order": written, "vx": vx_info,
            "rows": {r["id"]: r for r in srows}, "sizes": {}}
