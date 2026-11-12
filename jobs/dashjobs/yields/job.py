"""Weekly yield-curve job: per country fetch -> build four curves -> validate -> stage -> atomic swap.
One country failing keeps its last good file and marks it stale; a missing optional secret skips that country quietly.

Source per country (config `source:`, round 17): `wgb` reads worldgovernmentbonds.com in a browser (wgb.py), `official` runs the
country's own adapter (us.py, uk.py, ...). China has no official adapter (its sources' terms forbid reuse), so only `wgb`;
nor do Poland, Portugal, Russia, Turkey and South Africa (round 18, site only).
A challenge page on worldgovernmentbonds.com stops every further load of that site in the run: the remaining `wgb` countries
keep their last good files and go stale; `official` countries still run."""
from __future__ import annotations

import importlib
from datetime import date, datetime, timezone
from pathlib import Path

from .. import publish, status, validate
from . import core, wgb
from .core import Skipped

COUNTRIES = ["us", "uk", "ca", "jp", "de", "es", "ch", "br", "fr", "it", "au", "in", "cn", "pl", "pt", "ru", "tr", "za"]
MODULES = {"in": "india"}          # `in` is a Python keyword
NO_OFFICIAL = {"cn": "China has no official adapter (ChinaBond and CFETS terms forbid reuse); set its source to wgb."} | {
    c: f"{n} has no official adapter (added from worldgovernmentbonds.com only, round 18); set its source to wgb."
    for c, n in (("pl", "Poland"), ("pt", "Portugal"), ("ru", "Russia"), ("tr", "Turkey"), ("za", "South Africa"))}
SOURCES = ("wgb", "official")


class NothingFetched(Exception):
    """Every attempted country failed: the run fails and nothing is published."""


def adapter(code: str):
    return importlib.import_module(f"{__package__}.{MODULES.get(code, code)}")


def build_doc(code: str, raw: core.Raw, *, today: date, now_iso: str, meta: dict) -> dict:
    as_of = core.curve_date(raw)
    if as_of is None:
        raise ValueError("no observation at all")
    doc = {
        "schema_version": 1, "country": code, "name": meta["name"], "source": meta["source"],
        "source_url": meta["source_url"], "terms": meta["terms"], "status": meta.get("status", "ok"),
        "fetched_at": now_iso, "last_success": now_iso, "stale": False, "stale_reason": None,
        "as_of": as_of.isoformat(), "tenors": core.TENORS, "tenor_labels": core.tenor_labels(raw),
        "gaps": raw.gaps, "curves": core.build_curves(raw, as_of), "state": raw.extra,
    }
    return doc


def max_move(cfg: dict, code: str) -> float:
    """The weekly move limit in percentage points: `max_move_pp`, or the country's own in `max_move_pp_country` (round 18:
    Turkey and Russia, whose yields are in the teens and thirties and move by several points in a month)."""
    return float((cfg.get("max_move_pp_country") or {}).get(code, cfg.get("max_move_pp", 2.0)))


def source_of(cfg: dict, code: str) -> str:
    src = (cfg.get("source") or {}).get(code, "official")
    if src not in SOURCES:
        raise ValueError(f"unknown source {src!r} for {code} in config (use wgb or official)")
    return src


def run(cfg: dict, getter, *, today: date, now: datetime | None = None, data_dir, work_dir, env=None,
        workflow: str = "yields", only: list[str] | None = None, universe: dict, pager=None, pager_factory=None) -> dict:
    """`pager` (tests) or `pager_factory` (run_yields.py) gives the browser for `wgb` countries; it is opened only if one runs."""
    pager_factory = pager_factory or wgb.BrowserPager
    now = now or datetime.now(timezone.utc)
    env = {} if env is None else env
    data_dir, work_dir = Path(data_dir), Path(work_dir)
    out_dir = work_dir / "out"
    now_iso = status.iso(now)
    prev_manifest = publish.read_json(data_dir / "manifest.json") or {}
    prev_status = publish.read_json(data_dir / "status.json")
    codes = [c for c in cfg.get("countries", COUNTRIES) if not only or c in only]
    files: dict[str, object] = {}
    meta_out: dict[str, dict] = {}
    ok, failed, skipped, warnings = [], [], [], []
    opened = None
    try:
        for code in codes:
            rel = f"yields/{code}.json"
            prev = publish.read_json(data_dir / rel)
            try:
                src = source_of(cfg, code)
                if src == "wgb":
                    if pager is None:
                        pager = opened = pager_factory()
                    raw, meta = wgb.fetch(code, pager, today, (prev or {}).get("state")), wgb.meta(code)
                else:
                    if code in NO_OFFICIAL:
                        raise ValueError(NO_OFFICIAL[code])
                    mod = adapter(code)
                    raw, meta = mod.fetch(getter, today, env, (prev or {}).get("state")), mod.META
                warnings += [f"{code}: {w}" for w in raw.warnings]
                doc = build_doc(code, raw, today=today, now_iso=now_iso, meta=meta)
                validate.validate_yield(doc, today=today, prev=prev, max_age_days=cfg.get("max_age_days", 21),
                                        max_weekly_move_pp=max_move(cfg, code))
                ok.append(code)
            except Skipped as e:
                skipped.append(f"{code}: {e}")
                continue
            except Exception as e:  # noqa: BLE001 - any failure (a challenge page included) keeps the last good file
                failed.append(f"{code}: {type(e).__name__ + ': ' if isinstance(e, (wgb.Challenge, wgb.LayoutChanged)) else ''}{str(e)[:160]}")
                if not prev:
                    continue
                doc = dict(prev)
                doc["stale"], doc["stale_reason"], doc["fetched_at"] = True, "fetch_or_parse_failed", now_iso
                if code in wgb.COUNTRIES and validate.same_source(prev, {"source_url": wgb.meta(code)["source_url"]}):
                    doc |= {k: wgb.meta(code)[k] for k in ("source", "terms")}   # round 18 wording, even while stale
            files[rel] = doc
            meta_out[code] = {"path": rel, "as_of": doc["as_of"], "stale": doc["stale"], "status": doc["status"], "name": doc["name"]}
    finally:
        if opened is not None:
            try:
                opened.close()
            except Exception:  # noqa: BLE001 - closing the browser must never cost the run its results
                pass
    attempted = len(ok) + len(failed)
    if attempted and not ok:
        raise NothingFetched("; ".join(failed))
    last_success = now_iso if ok else (prev_status or {}).get("sources", {}).get("yield_curves", {}).get("last_success")
    st = status.merge_status(
        prev_status, "yield_curves",
        status.source_block(now=now, last_success=last_success, items_ok=len(ok), items_total=attempted, failed=failed,
                            cadence_hours=168, stale=bool(failed)) | {"skipped": skipped, "warnings": warnings},
        status.run_info(workflow, now, now, env), now)
    manifest = publish.merge_manifest(prev_manifest, generated_at=now_iso, updates={"yields": meta_out})
    files["status.json"] = st
    validate.validate_status(st)
    validate.validate_manifest(manifest, universe=universe)
    publish.stage(data_dir, out_dir)
    order = publish.write_outputs(out_dir, files, manifest)
    validate.validate_manifest_files(out_dir, manifest)
    publish.atomic_swap(data_dir, out_dir)
    return {"ok": ok, "failed": failed, "skipped": skipped, "order": order}
