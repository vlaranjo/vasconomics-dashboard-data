"""Daily markets job: fetch -> returns -> carry-forward -> stage -> validate -> atomic swap."""
from __future__ import annotations

import time
from datetime import date, datetime, timezone
from pathlib import Path

from . import lookback, publish, status, validate


def _row_record(meta: dict, bars, now_iso: str) -> dict:
    return {
        "id": meta["id"], "label": meta["label"], "ticker": meta["ticker"], "isin": meta["isin"],
        "provider": meta["provider"], "currency": meta["currency"], "acc": meta["acc"], "hedged": meta["hedged"],
        "first_close": bars[0][0].isoformat(), "last_close": bars[-1][0].isoformat(),
        "stale": False, "stale_reason": None, "last_success": now_iso,
        "returns": lookback.compute_returns(bars),
    }


def run(cfg: dict, fetch, *, today: date, now: datetime | None = None, data_dir, work_dir,
        env=None, sleep=time.sleep, delay: float = 3.0, workflow: str = "markets") -> dict:
    now = now or datetime.now(timezone.utc)
    started = now
    data_dir, work_dir = Path(data_dir), Path(work_dir)
    out_dir = work_dir / "out"
    vcfg = cfg["validation"]
    now_iso = status.iso(now)

    prev_manifest = publish.read_json(data_dir / "manifest.json") or {}
    prev_status = publish.read_json(data_dir / "status.json")
    files: dict[str, object] = {}
    sections_meta: dict[str, dict] = {}
    n_fresh = n_total = 0
    failed: list[str] = []
    missing: list[str] = []
    all_fresh_ids: set[str] = set()
    last_success = (prev_status or {}).get("sources", {}).get("yahoo_markets", {}).get("last_success")
    section_for_validation = None

    for sec in cfg["sections"]:
        rel = f"sections/{sec['id']}.json"
        prev_section = publish.read_json(data_dir / rel)
        prev_rows = {r["id"]: r for r in (prev_section or {}).get("rows", [])}
        rows, fresh_ids = [], set()
        for i, meta in enumerate(sec["rows"]):
            n_total += 1
            if i:
                sleep(delay)
            try:
                bars = lookback.clean_bars(fetch(meta["ticker"]), today)
                if not bars:
                    raise ValueError("no usable bars")
                rows.append(_row_record(meta, bars, now_iso))
                fresh_ids.add(meta["id"])
                n_fresh += 1
            except Exception as e:  # noqa: BLE001 - any fetch/parse failure carries the row forward
                failed.append(f"{meta['ticker']}: {str(e)[:120]}")
                old = prev_rows.get(meta["id"])
                if old:
                    old = dict(old)
                    old["stale"], old["stale_reason"] = True, "fetch_failed"
                    rows.append(old)
                else:
                    missing.append(meta["ticker"])
        if not rows:
            raise validate.ValidationError(f"section {sec['id']}: no rows at all")
        latest = max(date.fromisoformat(r["last_close"]) for r in rows)
        for r in rows:
            if not r["stale"] and lookback.is_stale_close(date.fromisoformat(r["last_close"]), latest):
                r["stale"], r["stale_reason"] = True, "old_close"
        section = {
            "schema_version": 1, "section": sec["id"], "title": sec["title"], "generated_at": now_iso,
            "as_of": latest.isoformat(), "lookbacks": cfg["lookbacks"], "rows": rows,
        }
        files[rel] = section
        sections_meta[sec["id"]] = {"path": rel, "as_of": section["as_of"]}
        all_fresh_ids |= fresh_ids
        validate.validate_section(
            section, run_date=today, prev_as_of=(prev_section or {}).get("as_of"), n_fresh=len(fresh_ids),
            n_total=len(sec["rows"]), min_fresh_fraction=vcfg["min_fresh_fraction"],
            max_close_age_days=vcfg["max_close_age_days"], max_abs_1d_pct=vcfg["max_abs_1d_pct"], fresh_ids=fresh_ids)
        section_for_validation = section

    any_stale = any(r["stale"] for s in files.values() for r in s["rows"])
    if n_fresh:
        last_success = now_iso
    finished = datetime.now(timezone.utc) if now is None else now
    st = status.merge_status(
        prev_status, "yahoo_markets",
        status.source_block(now=now, last_success=last_success, items_ok=n_fresh, items_total=n_total,
                            failed=failed + [f"{t}: missing" for t in missing], cadence_hours=24, stale=any_stale),
        status.run_info(workflow, started, finished, env), now)
    manifest = {
        "schema_version": 1, "generated_at": now_iso, "status": "status.json",
        "sections": {**prev_manifest.get("sections", {}), **sections_meta},
        "pe": prev_manifest.get("pe", {}),
    }
    files["status.json"] = st
    validate.validate_status(st)
    validate.validate_manifest(manifest)

    publish.stage(data_dir, out_dir)
    order = publish.write_outputs(out_dir, files, manifest)
    publish.atomic_swap(data_dir, out_dir)
    return {"n_fresh": n_fresh, "n_total": n_total, "failed": failed, "missing": missing, "order": order,
            "as_of": section_for_validation["as_of"] if section_for_validation else None}
