"""Weekly yield-curve job: per country fetch -> build four curves -> validate -> stage -> atomic swap.
One country failing keeps its last good file and marks it stale; a missing optional secret skips that country quietly."""
from __future__ import annotations

import importlib
from datetime import date, datetime, timezone
from pathlib import Path

from .. import publish, status, validate
from . import core
from .core import Skipped

COUNTRIES = ["us", "uk", "ca", "jp", "de", "es", "ch", "br", "fr"]


class NothingFetched(Exception):
    """Every attempted country failed: the run fails and nothing is published."""


def adapter(code: str):
    return importlib.import_module(f"{__package__}.{code}")


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


def run(cfg: dict, getter, *, today: date, now: datetime | None = None, data_dir, work_dir, env=None,
        workflow: str = "yields", only: list[str] | None = None, universe: dict) -> dict:
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
    ok, failed, skipped = [], [], []
    for code in codes:
        mod = adapter(code)
        rel = f"yields/{code}.json"
        prev = publish.read_json(data_dir / rel)
        try:
            raw = mod.fetch(getter, today, env, (prev or {}).get("state"))
            doc = build_doc(code, raw, today=today, now_iso=now_iso, meta=mod.META)
            validate.validate_yield(doc, today=today, prev=prev, max_age_days=cfg.get("max_age_days", 21),
                                    max_weekly_move_pp=cfg.get("max_move_pp", 2.0))
            ok.append(code)
        except Skipped as e:
            skipped.append(f"{code}: {e}")
            continue
        except Exception as e:  # noqa: BLE001 - any failure keeps the last good file
            failed.append(f"{code}: {str(e)[:160]}")
            if not prev:
                continue
            doc = dict(prev)
            doc["stale"], doc["stale_reason"], doc["fetched_at"] = True, "fetch_or_parse_failed", now_iso
        files[rel] = doc
        meta_out[code] = {"path": rel, "as_of": doc["as_of"], "stale": doc["stale"], "status": doc["status"], "name": doc["name"]}
    attempted = len(ok) + len(failed)
    if attempted and not ok:
        raise NothingFetched("; ".join(failed))
    last_success = now_iso if ok else (prev_status or {}).get("sources", {}).get("yield_curves", {}).get("last_success")
    st = status.merge_status(
        prev_status, "yield_curves",
        status.source_block(now=now, last_success=last_success, items_ok=len(ok), items_total=attempted, failed=failed,
                            cadence_hours=168, stale=bool(failed)) | {"skipped": skipped},
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
