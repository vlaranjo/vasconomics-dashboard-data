"""Schema + sanity checks (m1-plan section 4 step 8). Any failure raises ValidationError -> nothing is published."""
from __future__ import annotations

import math
import re
from datetime import date

from jsonschema import Draft202012Validator


class ValidationError(Exception):
    pass


_DATE = {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"}
_TS = {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"}
_NUM_OR_NULL = {"type": ["number", "null"]}

_CELL = {
    "type": "object",
    "required": ["value", "start", "status"],
    "properties": {
        "value": _NUM_OR_NULL,
        "start": {"type": ["string", "null"]},
        "status": {"enum": ["ok", "na_young", "na_missing"]},
        "since_launch": {"type": "object", "required": ["value", "start"],
                         "properties": {"value": {"type": "number"}, "start": _DATE}},
    },
    "additionalProperties": False,
}

SECTION_SCHEMA = {
    "type": "object",
    "required": ["schema_version", "section", "title", "generated_at", "as_of", "lookbacks", "rows"],
    "properties": {
        "schema_version": {"const": 1},
        "section": {"type": "string"}, "title": {"type": "string"},
        "page": {"type": "string"}, "kind": {"enum": ["funds", "fx"]},
        "default_visible": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
        "generated_at": _TS, "as_of": _DATE,
        "lookbacks": {"type": "array", "items": {"type": "string"}},
        "rows": {"type": "array", "items": {
            "type": "object",
            "required": ["id", "label", "ticker", "currency", "first_close",
                         "last_close", "stale", "stale_reason", "last_success", "returns"],
            "properties": {
                "id": {"type": "string"}, "label": {"type": "string"}, "ticker": {"type": "string"},
                "isin": {"type": "string"}, "provider": {"type": "string"}, "currency": {"type": "string"},
                "acc": {"type": "boolean"}, "hedged": {"type": "boolean"}, "fund_name": {"type": "string"}, "etc": {"type": "boolean"},
                "first_close": _DATE, "last_close": _DATE, "stale": {"type": "boolean"},
                "stale_reason": {"type": ["string", "null"]}, "last_success": _TS,
                "suspect": {"type": "boolean"},
                "returns": {"type": "object", "additionalProperties": _CELL},
            },
        }},
    },
}

PE_SCHEMA = {
    "type": "object",
    "required": ["schema_version", "slug", "name", "source", "source_url", "fetched_at", "last_success", "stale",
                 "stale_reason", "frequency", "last_point", "n_points", "avg_10y", "avg_full", "series"],
    "properties": {
        "schema_version": {"const": 1}, "slug": {"type": "string"}, "name": {"type": "string"},
        "source": {"const": "worldperatio.com"}, "source_url": {"type": "string"},
        "fetched_at": _TS, "last_success": _TS, "stale": {"type": "boolean"},
        "stale_reason": {"type": ["string", "null"]}, "frequency": {"const": "monthly"},
        "last_point": {"type": "string", "pattern": r"^\d{4}-\d{2}$"}, "n_points": {"type": "integer"},
        "avg_10y": {"type": "number"}, "avg_full": {"type": "number"},
        "series": {"type": "array", "items": {"type": "array", "minItems": 2, "maxItems": 2}},
    },
}

STATUS_SCHEMA = {
    "type": "object",
    "required": ["schema_version", "generated_at", "run", "sources", "heartbeat"],
    "properties": {
        "schema_version": {"const": 1}, "generated_at": _TS, "heartbeat": _TS,
        "run": {"type": "object"},
        "sources": {"type": "object", "additionalProperties": {
            "type": "object",
            "required": ["last_attempt", "last_success", "ok", "expected_cadence_hours", "stale", "items_ok",
                         "items_total", "failed"],
        }},
    },
}

MANIFEST_SCHEMA = {
    "type": "object",
    "required": ["schema_version", "generated_at", "status", "sections", "pe"],
    "properties": {
        "schema_version": {"const": 1}, "generated_at": _TS, "status": {"type": "string"},
        "sections": {"type": "object", "additionalProperties": {
            "type": "object", "required": ["path", "as_of"]}},
        "pe": {"type": "object", "additionalProperties": {
            "type": "object", "required": ["path", "last_point"]}},
        "yields": {"type": "object", "additionalProperties": {
            "type": "object", "required": ["path", "as_of"]}},
        "history": {"type": "object", "additionalProperties": {
            "type": "object", "required": ["path", "as_of"]}},
        "indicators": {"type": "object", "additionalProperties": {
            "type": "object", "required": ["path", "as_of"]}},
        "volatility": {"type": "object", "additionalProperties": {
            "type": "object", "required": ["path", "as_of"]}},
    },
}

_INTS = {"type": "array", "items": {"type": "integer"}}
_NUMS = {"type": "array", "items": {"type": "number"}}
_NUMS_NULL = {"type": "array", "items": {"type": ["number", "null"]}}
_HEAD = {"schema_version": {"const": 1}, "section": {"type": "string"}, "generated_at": _TS, "as_of": _DATE}
HISTORY_SCHEMA = {
    "type": "object", "required": ["schema_version", "section", "generated_at", "as_of", "series"],
    "properties": {**_HEAD, "series": {"type": "array", "items": {
        "type": "object", "required": ["id", "d", "v"], "additionalProperties": False,
        "properties": {"id": {"type": "string"}, "d": _INTS, "v": _NUMS}}}},
}
INDICATORS_SCHEMA = {
    "type": "object", "required": ["schema_version", "section", "generated_at", "as_of", "series"],
    "properties": {**_HEAD, "series": {"type": "array", "items": {
        "type": "object", "required": ["id", "d", "p", "ma50", "ma200", "rsi"], "additionalProperties": False,
        "properties": {"id": {"type": "string"}, "d": _INTS, "p": _NUMS, "ma50": _NUMS_NULL, "ma200": _NUMS_NULL, "rsi": _NUMS_NULL}}}},
}

_POINT = {
    "type": "object", "required": ["value", "date", "kind"],
    "properties": {"value": {"type": "number"}, "date": _DATE, "kind": {"enum": ["D", "W", "B", "M", "A", "C"]},
                   "label": {"type": "string"}, "days": {"type": "integer"}},
    "additionalProperties": False,
}
YIELD_SCHEMA = {
    "type": "object",
    "required": ["schema_version", "country", "name", "source", "source_url", "terms", "status", "fetched_at",
                 "last_success", "stale", "stale_reason", "as_of", "tenors", "tenor_labels", "gaps", "curves"],
    "properties": {
        "schema_version": {"const": 1}, "country": {"type": "string"}, "name": {"type": "string"},
        "source": {"type": "string"}, "source_url": {"type": "string"}, "terms": {"type": "string"},
        "status": {"enum": ["ok", "untested"]}, "fetched_at": _TS, "last_success": _TS,
        "stale": {"type": "boolean"}, "stale_reason": {"type": ["string", "null"]}, "as_of": _DATE,
        "tenors": {"type": "array", "items": {"type": "string"}},
        "tenor_labels": {"type": "object", "additionalProperties": {"type": "string"}},
        "gaps": {"type": "object", "additionalProperties": {"type": "string"}},
        # Curve ids: latest, 1m, 6m, 1y since round 17 (11 Nov 2026); a file published before then has 3m in place of 6m and
        # may still be carried forward as stale, so 3m stays valid. The front end styles curves by position, not by id.
        "curves": {"type": "array", "minItems": 4, "maxItems": 4, "items": {
            "type": "object", "required": ["id", "label", "date", "points"],
            "properties": {"id": {"enum": ["latest", "1m", "3m", "6m", "1y"]}, "label": {"type": "string"}, "date": _DATE,
                           "points": {"type": "object", "additionalProperties": _POINT}}}},
        "state": {"type": "object"},
    },
}


def _check(schema, obj, what):
    errs = sorted(Draft202012Validator(schema).iter_errors(obj), key=lambda e: list(e.path))
    if errs:
        e = errs[0]
        raise ValidationError(f"{what}: {e.message} at {'/'.join(map(str, e.path))}")


def _walk_numbers(obj, what, path=""):
    if isinstance(obj, bool):
        return
    if isinstance(obj, float) and not math.isfinite(obj):
        raise ValidationError(f"{what}: non-finite number at {path}")
    if isinstance(obj, dict):
        for k, v in obj.items():
            _walk_numbers(v, what, f"{path}/{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _walk_numbers(v, what, f"{path}/{i}")


def validate_section(section: dict, *, run_date: date, prev_as_of: str | None, n_fresh: int, n_total: int,
                     min_fresh_fraction: float, max_close_age_days: int, max_abs_1d_pct: float,
                     fresh_ids: set[str]) -> None:
    _check(SECTION_SCHEMA, section, "section")
    _walk_numbers(section, "section")
    if section.get("kind", "funds") == "funds":                          # fund rows must carry the reference-table fields
        for r in section["rows"]:
            for k in ("isin", "provider", "acc", "hedged", "fund_name"):
                if k not in r:
                    raise ValidationError(f"{r['ticker']}: fund row without '{k}'")
    ids = [r["id"] for r in section["rows"]]
    if len(ids) != len(set(ids)):
        raise ValidationError("row ids are not unique")
    if any(i not in ids for i in section.get("default_visible", [])):
        raise ValidationError("default_visible names a row that is not in the section")
    if n_total and n_fresh / n_total < min_fresh_fraction:
        raise ValidationError(f"coverage {n_fresh}/{n_total} is below the threshold {min_fresh_fraction}")
    if prev_as_of and section["as_of"] < prev_as_of:
        raise ValidationError(f"as_of {section['as_of']} is earlier than the published {prev_as_of}")
    for r in section["rows"]:
        if r["id"] in fresh_ids:
            age = (run_date - date.fromisoformat(r["last_close"])).days
            if age > max_close_age_days:
                raise ValidationError(f"{r['ticker']}: last close {r['last_close']} is {age} days before the run date")
        for k, cell in r["returns"].items():
            for what, v in (("return", cell.get("value")), ("since-launch return", (cell.get("since_launch") or {}).get("value"))):
                if isinstance(v, (int, float)) and v < -100:
                    raise ValidationError(f"{r['ticker']} {k}: {what} {v}% is below -100% (a fund cannot lose more than everything)")
        c1 = r["returns"].get("1D", {}).get("value")
        if c1 is not None and abs(c1) > max_abs_1d_pct and not r.get("suspect"):
            raise ValidationError(f"{r['ticker']}: |1D| {c1}% above {max_abs_1d_pct}% without a suspect flag")


def check_price_jumps(ticker: str, bars, max_pct: float, exceptions=()) -> None:
    """No close-to-close move above `max_pct` percent anywhere in the series (decision rule of 6 Nov 2026), except on the
    dates listed for this ticker in `validation.jump_exceptions` (config/universe.yaml). An exception names the ticker and the
    exact dates of a real market event plus the reason; it never widens the limit for other days or other tickers."""
    allowed = set()
    for ex in exceptions or ():
        if ex["ticker"] == ticker:
            allowed |= {str(d) for d in ex["dates"]}
    prev = None
    for d, c in bars:
        if prev and prev > 0 and abs(c / prev - 1) * 100 > max_pct and d.isoformat() not in allowed:
            raise ValidationError(f"{ticker}: {(c / prev - 1) * 100:+.1f}% on {d.isoformat()} is above {max_pct}% "
                                  f"and the date is not in validation.jump_exceptions")
        prev = c


def validate_pe(pe: dict) -> None:
    _check(PE_SCHEMA, pe, f"pe/{pe.get('slug')}")
    _walk_numbers(pe, "pe")


def validate_status(status: dict) -> None:
    _check(STATUS_SCHEMA, status, "status")


def validate_manifest(manifest: dict, universe: dict) -> None:
    """Schema and completeness. The universe config is MANDATORY (no default, no None): a job that cannot load it cannot publish. every section of the config must have its returns entry
    and its history entry, and every section with indicators its indicators entry. A job that would publish a manifest
    without them fails here and publishes nothing (the "no data yet" bug of 9 Nov 2026)."""
    _check(MANIFEST_SCHEMA, manifest, "manifest")
    if not isinstance(universe, dict) or not universe.get("sections"):
        raise ValidationError("the universe config (config/universe.yaml) is required to validate the manifest and has no sections")
    missing = []
    for sec in universe["sections"]:
        sid = sec["id"]
        need = ["sections", "history"] + (["indicators"] if sec.get("indicators") else [])
        missing += [f"{b}/{sid}" for b in need if sid not in (manifest.get(b) or {})]
    if missing:
        raise ValidationError("manifest is missing entries: " + ", ".join(missing))


def validate_manifest_files(root, manifest: dict) -> None:
    """Every path the manifest names exists under `root` (the staged folder) and parses as JSON."""
    import json
    from pathlib import Path
    root = Path(root)
    paths = [manifest["status"]] + [v["path"] for b in ("sections", "history", "indicators", "pe", "yields", "volatility")
                                    for v in (manifest.get(b) or {}).values()]
    for rel in paths:
        p = root / rel
        if not p.is_file():
            raise ValidationError(f"manifest names {rel}, which does not exist")
        json.loads(p.read_text(encoding="utf-8"))


def same_source(prev: dict, doc: dict) -> bool:
    """Same source for the like-with-like checks: the same `source` text, or both from worldgovernmentbonds.com (round 18 shortened
    its source line, which is not a switch of source)."""
    wgb = lambda d: re.match(r"https://(www\.)?worldgovernmentbonds\.com/", d.get("source_url") or "") is not None   # noqa: E731
    return prev.get("source") == doc.get("source") or (wgb(prev) and wgb(doc))


def validate_yield(doc: dict, *, today: date, prev: dict | None, max_age_days: int = 21,
                   max_weekly_move_pp: float = 2.0) -> None:
    """Schema + sanity for one country. Any failure keeps the last good file (the job marks it stale)."""
    _check(YIELD_SCHEMA, doc, f"yields/{doc.get('country')}")
    _walk_numbers(doc, "yield")
    latest = doc["curves"][0]
    if latest["id"] != "latest" or latest["date"] != doc["as_of"]:
        raise ValidationError(f"{doc['country']}: first curve must be 'latest' dated as_of")
    as_of = date.fromisoformat(doc["as_of"])
    if as_of > today:
        raise ValidationError(f"{doc['country']}: as_of {as_of} is in the future")
    if (today - as_of).days > max_age_days:
        raise ValidationError(f"{doc['country']}: latest observation {as_of} is {(today - as_of).days} days old")
    if len(latest["points"]) < 3:
        raise ValidationError(f"{doc['country']}: only {len(latest['points'])} tenors on the latest curve")
    for c in doc["curves"]:
        for t, p in c["points"].items():
            if t not in doc["tenors"]:
                raise ValidationError(f"{doc['country']}: unknown tenor {t}")
            if not -3.0 <= p["value"] <= 60.0:     # 60 since round 18: Turkey 3Y was 35.99% on 12 Nov 2026, 40.15% six months earlier
                raise ValidationError(f"{doc['country']} {t}: {p['value']} is outside -3..60 percent")
            if date.fromisoformat(p["date"]) > date.fromisoformat(c["date"]):
                raise ValidationError(f"{doc['country']} {t}: point dated after its curve")
    # No going backwards (round 17): from the same source, a new file may not be older than the published one. A switch of
    # source in config (wgb <-> official) is a deliberate change and may move the date either way.
    if prev and prev.get("as_of") and same_source(prev, doc) and doc["as_of"] < prev["as_of"]:
        raise ValidationError(f"{doc['country']}: as_of {doc['as_of']} is earlier than the published {prev['as_of']}")
    # The weekly move check compares like with like: after a switch of source (official <-> wgb) the two definitions may differ.
    if prev and not prev.get("stale") and prev.get("as_of") and same_source(prev, doc):
        pl = prev["curves"][0]["points"]
        for t, p in latest["points"].items():
            q = pl.get(t)
            if q and p["kind"] != "A" and abs(p["value"] - q["value"]) > max_weekly_move_pp                     and (as_of - date.fromisoformat(prev["as_of"])).days <= 31:
                raise ValidationError(f"{doc['country']} {t}: moved {p['value'] - q['value']:+.2f} pp since the last file")


def _check_series(doc: dict, what: str, value_keys: tuple[str, ...], section_ids: set[str] | None) -> None:
    seen = set()
    for s in doc["series"]:
        sid = s["id"]
        if sid in seen:
            raise ValidationError(f"{what}: duplicate series {sid}")
        seen.add(sid)
        if section_ids is not None and sid not in section_ids:
            raise ValidationError(f"{what}: series {sid} is not a row of the section")
        n = len(s["d"])
        if n < 2:
            raise ValidationError(f"{what} {sid}: fewer than two points")
        if any(b <= a for a, b in zip(s["d"], s["d"][1:])):
            raise ValidationError(f"{what} {sid}: dates are not strictly increasing")
        for k in value_keys:
            if len(s[k]) != n:
                raise ValidationError(f"{what} {sid}: '{k}' has {len(s[k])} values for {n} dates")


def validate_history(doc: dict, section_ids: set[str] | None = None) -> None:
    _check(HISTORY_SCHEMA, doc, f"history/{doc.get('section')}")
    _check_series(doc, f"history/{doc['section']}", ("v",), section_ids)
    for s in doc["series"]:
        if s["v"][0] != 100 or any(v <= 0 for v in s["v"]):
            raise ValidationError(f"history/{doc['section']} {s['id']}: must start at 100 and stay positive")


def validate_indicators(doc: dict, section_ids: set[str] | None = None) -> None:
    _check(INDICATORS_SCHEMA, doc, f"indicators/{doc.get('section')}")
    _check_series(doc, f"indicators/{doc['section']}", ("p", "ma50", "ma200", "rsi"), section_ids)
    for s in doc["series"]:
        if s["p"][0] != 100 or any(v <= 0 for v in s["p"]):
            raise ValidationError(f"indicators/{doc['section']} {s['id']}: level must start at 100 and stay positive")
        if any(v is not None and not 0 <= v <= 100 for v in s["rsi"]):
            raise ValidationError(f"indicators/{doc['section']} {s['id']}: RSI outside 0..100")


# ---- Volatility page (13 Nov 2026) -------------------------------------------------------------------------------------------
_STAMPS = {"fetched_at": _TS, "last_success": _TS, "stale": {"type": "boolean"}, "stale_reason": {"type": ["string", "null"]}}
VOL_INDEX_SCHEMA = {
    "type": "object",
    "required": ["schema_version", "id", "name", "long", "ticker", "source", *_STAMPS, "first_date", "as_of", "last_value", "n_daily",
                 "daily_from", "avg_10y", "avg_full", "averages", "d", "v"],
    "properties": {"schema_version": {"const": 1}, "id": {"type": "string"}, "name": {"type": "string"}, "long": {"type": "string"},
                   "ticker": {"type": "string"}, "source": {"const": "Yahoo Finance"}, **_STAMPS, "first_date": _DATE, "as_of": _DATE,
                   "daily_from": _DATE, "last_value": {"type": "number"}, "n_daily": {"type": "integer"}, "avg_10y": _NUM_OR_NULL,
                   "avg_full": {"type": "number"}, "d": _INTS, "v": _NUMS,
                   "averages": {"type": "object", "required": ["1Y", "5Y", "10Y"], "additionalProperties": False,
                                "properties": {"1Y": _NUM_OR_NULL, "5Y": _NUM_OR_NULL, "10Y": _NUM_OR_NULL}}},
    "additionalProperties": False,
}
_CHANGE = {"type": "object", "required": ["value", "start", "start_value", "status"], "additionalProperties": False,
           "properties": {"value": _NUM_OR_NULL, "start": {"type": ["string", "null"]}, "start_value": _NUM_OR_NULL,
                          "status": {"enum": ["ok", "na_young", "na_missing"]}}}
VOL_SUMMARY_SCHEMA = {
    "type": "object", "required": ["schema_version", "generated_at", "as_of", "lookbacks", "rows"],
    "properties": {"schema_version": {"const": 1}, "generated_at": _TS, "as_of": _DATE, "lookbacks": {"type": "array", "items": {"type": "string"}},
                   "slope_source": {"enum": ["cboe", "yahoo"]},
                   "rows": {"type": "array", "items": {
                       "type": "object", "required": ["id", "name", "long", "direction", "latest", "date", "first_date", "stale", "stale_reason", "changes"],
                       "properties": {"id": {"enum": ["vix", "vx_slope", "skew", "move"]}, "name": {"type": "string"}, "long": {"type": "string"},
                                      "direction": {"enum": ["up_bad", "up_good"]}, "latest": {"type": "number"}, "date": _DATE, "first_date": _DATE,
                                      "stale": {"type": "boolean"}, "stale_reason": {"type": ["string", "null"]},
                                      "changes": {"type": "object", "additionalProperties": _CHANGE}}}}},
}
VX_HISTORY_SCHEMA = {
    "type": "object", "required": ["schema_version", "source", "source_url", *_STAMPS, "as_of", "first_date", "archive_last", "slope", "curves"],
    "properties": {"schema_version": {"const": 1}, "source": {"const": "Cboe"}, "source_url": {"type": "string"}, **_STAMPS, "as_of": _DATE,
                   "first_date": {"type": ["string", "null"]}, "archive_last": _DATE,
                   "slope": {"type": "object", "required": ["d", "v"], "properties": {"d": _INTS, "v": _NUMS}},
                   "curves": {"type": "object", "required": ["d", "s"], "properties": {"d": _INTS, "s": {"type": "array", "items": _NUMS_NULL}}}},
}
_VX_POINT = {"type": "object", "required": ["pos", "code", "month", "expiry", "days", "settle"], "additionalProperties": False,
             "properties": {"pos": {"type": "integer", "minimum": 1}, "code": {"type": "string"}, "month": {"type": "string"},
                            "expiry": _DATE, "days": {"type": "integer", "minimum": 1}, "settle": _NUM_OR_NULL}}
_YT_POINT = {"type": "object", "required": ["pos", "ticker", "label", "short", "months", "value"], "additionalProperties": False,
             "properties": {"pos": {"type": "integer", "minimum": 1}, "ticker": {"type": "string"}, "label": {"type": "string"},
                            "short": {"type": "string"}, "months": {"type": "number", "exclusiveMinimum": 0}, "value": _NUM_OR_NULL}}
VX_TERM_SCHEMA = {
    "type": "object", "required": ["schema_version", "source", "source_url", *_STAMPS, "as_of", "positions", "slope_positions",
                                   "slope_latest", "curves"],
    "properties": {"schema_version": {"const": 1}, "source": {"enum": ["Cboe", "Yahoo Finance"]}, "kind": {"enum": ["futures", "indices"]},
                   "source_url": {"type": "string"}, "terms_url": {"type": "string"},
                   "tenors": {"type": "array"}, "left_out": {"type": "array"},
                   **_STAMPS, "as_of": _DATE, "positions": {"type": "integer"}, "slope_positions": {"type": "integer"}, "slope_latest": _NUM_OR_NULL,
                   "curves": {"type": "array", "minItems": 4, "maxItems": 4, "items": {
                       "type": "object", "required": ["id", "label", "date", "points"],
                       "properties": {"id": {"enum": ["latest", "1m", "6m", "1y"]}, "label": {"type": "string"},
                                      "date": {"type": ["string", "null"]}, "anchor": _DATE, "points": {"type": "array", "items": _VX_POINT}}}}},
}


def _increasing(d: list[int], what: str) -> None:
    if any(b <= a for a, b in zip(d, d[1:])):
        raise ValidationError(f"{what}: dates are not strictly increasing")


def validate_vol_index(doc: dict) -> None:
    _check(VOL_INDEX_SCHEMA, doc, f"volatility/{doc.get('id')}")
    _walk_numbers(doc, "volatility index")
    if len(doc["d"]) != len(doc["v"]) or len(doc["d"]) < 2:
        raise ValidationError(f"volatility/{doc['id']}: {len(doc['d'])} dates for {len(doc['v'])} values")
    _increasing(doc["d"], f"volatility/{doc['id']}")


def validate_vol_summary(doc: dict) -> None:
    _check(VOL_SUMMARY_SCHEMA, doc, "volatility/summary")
    _walk_numbers(doc, "volatility summary")
    ids = [r["id"] for r in doc["rows"]]
    if len(ids) != len(set(ids)):
        raise ValidationError("volatility/summary: row ids are not unique")


def validate_vx_history(doc: dict) -> None:
    _check(VX_HISTORY_SCHEMA, doc, "volatility/vx-history")
    _walk_numbers(doc, "vx history")
    for k, vals in (("slope", doc["slope"]["v"]), ("curves", doc["curves"]["s"])):
        if len(doc[k]["d"]) != len(vals):
            raise ValidationError(f"volatility/vx-history {k}: {len(doc[k]['d'])} dates for {len(vals)} values")
        _increasing(doc[k]["d"], f"volatility/vx-history {k}")


def validate_vx_term(doc: dict) -> None:
    """Cboe futures (kind "futures", the default) or Yahoo's VIX indices (kind "indices"): each kind has its own point shape."""
    kind = doc.get("kind", "futures")
    schema = VX_TERM_SCHEMA
    if kind == "indices":
        import copy
        schema = copy.deepcopy(VX_TERM_SCHEMA)
        schema["properties"]["curves"]["items"]["properties"]["points"] = {"type": "array", "items": _YT_POINT}
        schema["required"] = schema["required"] + ["tenors", "left_out"]
        schema["properties"]["tenors"] = {"type": "array", "items": {"type": "object", "required": ["ticker", "label", "short", "months"]}}
        schema["properties"]["left_out"] = {"type": "array", "items": {"type": "object", "required": ["ticker", "label", "reason"]}}
    else:
        import copy
        schema = copy.deepcopy(VX_TERM_SCHEMA)
        schema["required"] = schema["required"] + ["terms_url"]
    _check(schema, doc, "volatility/vx-term")
    if kind == "indices" and doc["positions"] != len(doc["tenors"]):
        raise ValidationError(f"volatility/vx-term: {doc['positions']} positions for {len(doc['tenors'])} horizons")
    if (doc["source"] == "Cboe") != (kind == "futures"):
        raise ValidationError(f"volatility/vx-term: source {doc['source']} does not match kind {kind}")
    _walk_numbers(doc, "vx term")
    latest = doc["curves"][0]
    if latest["id"] != "latest" or latest["date"] != doc["as_of"]:
        raise ValidationError("volatility/vx-term: the first curve must be 'latest', dated as_of")
    for c in doc["curves"]:
        if [p["pos"] for p in c["points"]] != list(range(1, len(c["points"]) + 1)):
            raise ValidationError(f"volatility/vx-term {c['id']}: positions are not 1, 2, 3, ...")
        order = [p["months"] for p in c["points"]] if kind == "indices" else [p["expiry"] for p in c["points"]]
        if order != sorted(order) or len(set(order)) != len(order):
            raise ValidationError(f"volatility/vx-term {c['id']}: points are not in {'horizon' if kind == 'indices' else 'expiry'} order")
