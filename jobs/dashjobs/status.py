"""status.json: per-source last success and stale flags, plus the keep-alive heartbeat (decisions D3)."""
from __future__ import annotations

import os
from datetime import datetime, timezone


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_info(workflow: str, started: datetime, finished: datetime, env=None) -> dict:
    env = os.environ if env is None else env
    run_id = env.get("GITHUB_RUN_ID")
    repo = env.get("GITHUB_REPOSITORY")
    server = env.get("GITHUB_SERVER_URL", "https://github.com")
    return {
        "workflow": workflow,
        "run_id": int(run_id) if run_id and run_id.isdigit() else None,
        "run_url": f"{server}/{repo}/actions/runs/{run_id}" if run_id and repo else None,
        "started_at": iso(started),
        "finished_at": iso(finished),
    }


def merge_status(existing: dict | None, source_key: str, block: dict, run: dict, now: datetime) -> dict:
    """Update only this job's source block and the heartbeat; the other job's block stays intact (test S1)."""
    sources = dict((existing or {}).get("sources", {}))
    sources[source_key] = block
    return {
        "schema_version": 1,
        "generated_at": iso(now),
        "run": run,
        "sources": sources,
        "heartbeat": iso(now),
    }


def source_block(*, now: datetime, last_success: str | None, items_ok: int, items_total: int, failed: list[str],
                 cadence_hours: int, stale: bool) -> dict:
    return {
        "last_attempt": iso(now),
        "last_success": last_success,
        "ok": items_ok == items_total,
        "expected_cadence_hours": cadence_hours,
        "stale": stale,
        "items_ok": items_ok,
        "items_total": items_total,
        "failed": failed,
    }
