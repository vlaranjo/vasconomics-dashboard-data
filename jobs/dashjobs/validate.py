"""Schema + sanity checks (m1-plan section 4 step 8). Any failure raises ValidationError -> nothing is published."""
from __future__ import annotations

import math
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
        "generated_at": _TS, "as_of": _DATE,
        "lookbacks": {"type": "array", "items": {"type": "string"}},
        "rows": {"type": "array", "items": {
            "type": "object",
            "required": ["id", "label", "ticker", "isin", "provider", "currency", "acc", "hedged", "first_close",
                         "last_close", "stale", "stale_reason", "last_success", "returns"],
            "properties": {
                "id": {"type": "string"}, "label": {"type": "string"}, "ticker": {"type": "string"},
                "isin": {"type": "string"}, "provider": {"type": "string"}, "currency": {"type": "string"},
                "acc": {"type": "boolean"}, "hedged": {"type": "boolean"},
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
    },
}

_POINT = {
    "type": "object", "required": ["value", "date", "kind"],
    "properties": {"value": {"type": "number"}, "date": _DATE, "kind": {"enum": ["D", "W", "B", "A"]},
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
        "curves": {"type": "array", "minItems": 4, "maxItems": 4, "items": {
            "type": "object", "required": ["id", "label", "date", "points"],
            "properties": {"id": {"enum": ["latest", "1m", "3m", "1y"]}, "label": {"type": "string"}, "date": _DATE,
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
    ids = [r["id"] for r in section["rows"]]
    if len(ids) != len(set(ids)):
        raise ValidationError("row ids are not unique")
    if n_total and n_fresh / n_total < min_fresh_fraction:
        raise ValidationError(f"coverage {n_fresh}/{n_total} is below the threshold {min_fresh_fraction}")
    if prev_as_of and section["as_of"] < prev_as_of:
        raise ValidationError(f"as_of {section['as_of']} is earlier than the published {prev_as_of}")
    for r in section["rows"]:
        if r["id"] in fresh_ids:
            age = (run_date - date.fromisoformat(r["last_close"])).days
            if age > max_close_age_days:
                raise ValidationError(f"{r['ticker']}: last close {r['last_close']} is {age} days before the run date")
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


def validate_manifest(manifest: dict) -> None:
    _check(MANIFEST_SCHEMA, manifest, "manifest")


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
            if not -3.0 <= p["value"] <= 40.0:
                raise ValidationError(f"{doc['country']} {t}: {p['value']} is outside -3..40 percent")
            if date.fromisoformat(p["date"]) > date.fromisoformat(c["date"]):
                raise ValidationError(f"{doc['country']} {t}: point dated after its curve")
    if prev and not prev.get("stale") and prev.get("as_of"):
        pl = prev["curves"][0]["points"]
        for t, p in latest["points"].items():
            q = pl.get(t)
            if q and p["kind"] != "A" and abs(p["value"] - q["value"]) > max_weekly_move_pp                     and (as_of - date.fromisoformat(prev["as_of"])).days <= 31:
                raise ValidationError(f"{doc['country']} {t}: moved {p['value'] - q['value']:+.2f} pp since the last file")
