"""Weekly P/E job: fetch each index once, parse, validate, average, stage, atomic swap."""
from __future__ import annotations

import time
from datetime import date, datetime, timezone
from pathlib import Path

from . import publish, status, validate, worldperatio


class NothingFetched(Exception):
    """Every index failed: the source is unreachable or changed. The run fails; nothing is published."""


def run(cfg: dict, fetch_text, *, today: date, now: datetime | None = None, data_dir, work_dir, env=None,
        sleep=time.sleep, workflow: str = "pe", universe: dict | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    started = now
    data_dir, work_dir = Path(data_dir), Path(work_dir)
    out_dir = work_dir / "out"
    now_iso = status.iso(now)
    prev_manifest = publish.read_json(data_dir / "manifest.json") or {}
    prev_status = publish.read_json(data_dir / "status.json")
    files: dict[str, object] = {}
    pe_meta: dict[str, dict] = {}
    ok, failed = 0, []
    last_success = (prev_status or {}).get("sources", {}).get("worldperatio", {}).get("last_success")
    for i, idx in enumerate(cfg["indices"]):
        if i:
            sleep(cfg.get("delay_seconds", 4))
        rel = f"pe/{idx['slug']}.json"
        prev = publish.read_json(data_dir / rel)
        try:
            html = fetch_text(idx["url"])
            series = worldperatio.parse_series(html)
            worldperatio.validate_series(series, today, idx.get("first_point"))
            a10, afull = worldperatio.averages(series)
            doc = {
                "schema_version": 1, "slug": idx["slug"], "name": idx["name"], "source": "worldperatio.com",
                "source_url": idx["url"], "fetched_at": now_iso, "last_success": now_iso, "stale": False,
                "stale_reason": None, "frequency": "monthly", "last_point": series[-1][0], "n_points": len(series),
                "avg_10y": a10, "avg_full": afull, "series": [[ym, v] for ym, v in series],
            }
            ok += 1
        except Exception as e:  # noqa: BLE001
            failed.append(f"{idx['slug']}: {str(e)[:120]}")
            if prev:
                doc = dict(prev)
                doc["stale"], doc["stale_reason"] = True, "fetch_or_parse_failed"
            else:
                continue  # no previous file: the page shows "no data yet"
        validate.validate_pe(doc)
        files[rel] = doc
        pe_meta[idx["slug"]] = {"path": rel, "last_point": doc["last_point"], "name": idx["name"],
                                "group": idx.get("group", ""), "pages": list(idx.get("pages", []))}
    if ok == 0:
        raise NothingFetched("; ".join(failed) or "no index fetched")
    last_success = now_iso
    st = status.merge_status(
        prev_status, "worldperatio",
        status.source_block(now=now, last_success=last_success, items_ok=ok, items_total=len(cfg["indices"]),
                            failed=failed, cadence_hours=168, stale=bool(failed)),
        status.run_info(workflow, started, now, env), now)
    manifest = publish.merge_manifest(prev_manifest, generated_at=now_iso, updates={"pe": pe_meta},
                                      keep={"pe": {i["slug"] for i in cfg["indices"]}})
    files["status.json"] = st
    validate.validate_status(st)
    validate.validate_manifest(manifest, universe=universe)
    publish.stage(data_dir, out_dir)
    order = publish.write_outputs(out_dir, files, manifest)
    validate.validate_manifest_files(out_dir, manifest)
    publish.atomic_swap(data_dir, out_dir)
    return {"ok": ok, "failed": failed, "order": order}
