"""Daily markets job: fetch -> returns -> carry-forward -> stage -> validate -> atomic swap."""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import history, lookback, publish, status, validate


def _row_record(meta: dict, bars, now_iso: str) -> dict:
    extra = {k: meta[k] for k in ("isin", "provider", "acc", "hedged", "holds") if k in meta}
    return {
        "id": meta["id"], "label": meta["label"], "ticker": meta["ticker"], "currency": meta["currency"], **extra,
        "first_close": bars[0][0].isoformat(), "last_close": bars[-1][0].isoformat(),
        "stale": False, "stale_reason": None, "last_success": now_iso,
        "returns": lookback.compute_returns(bars),
    }


def run(cfg: dict, fetch, *, today: date, now: datetime | None = None, data_dir, work_dir,
        env=None, sleep=time.sleep, delay: float = 3.0, retry_wait: float = 20.0, workflow: str = "markets") -> dict:
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
    history_meta: dict[str, dict] = {}
    indicators_meta: dict[str, dict] = {}
    n_fresh = n_total = 0
    failed: list[str] = []
    missing: list[str] = []
    all_fresh_ids: set[str] = set()
    last_success = (prev_status or {}).get("sources", {}).get("yahoo_markets", {}).get("last_success")
    section_for_validation = None
    cache: dict[str, object] = {}                       # a ticker used on several pages is fetched once per run

    def fetch_once(ticker):
        if ticker in cache:
            return cache[ticker], False
        bars_raw = fetch(ticker)
        cache[ticker] = bars_raw
        return bars_raw, True

    waited_once = False
    for sec in cfg["sections"]:
        rel = f"sections/{sec['id']}.json"
        prev_section = publish.read_json(data_dir / rel)
        prev_rows = {r["id"]: r for r in (prev_section or {}).get("rows", [])}
        by_id: dict[str, dict] = {}
        hist_by_id: dict[str, dict] = {}
        ind_by_id: dict[str, dict] = {}
        want_ind = bool(sec.get("indicators"))
        kind = sec.get("kind", "funds")
        cutoff = lookback.last_completed_date(kind, today, now)      # only COMPLETED daily bars are used (never a live quote)
        prev_hist = {s["id"]: s for s in (publish.read_json(data_dir / f"history/{sec['id']}.json") or {}).get("series", [])}
        prev_ind = {s["id"]: s for s in (publish.read_json(data_dir / f"indicators/{sec['id']}.json") or {}).get("series", [])}
        fresh_ids = set()
        sec_failed_from = len(failed)

        def attempt(meta):
            raw, _net = fetch_once(meta["ticker"])
            bars = lookback.clean_bars(raw, cutoff)
            if not bars:
                raise ValueError("no usable bars")
            # Only the window the figures use is checked: a bar older than the 10Y anchor (plus a month of margin) never enters a number.
            window_start = date(today.year - 10, today.month, 1) - timedelta(days=31)
            validate.check_price_jumps(meta["ticker"], [b for b in bars if b[0] >= window_start], vcfg["max_abs_1d_pct"], vcfg.get("jump_exceptions"))
            rec = _row_record(meta, bars, now_iso)
            hist_by_id[meta["id"]] = {"id": meta["id"], **history.history_points(bars)}
            if want_ind:
                ind_by_id[meta["id"]] = {"id": meta["id"], **history.indicator_points(bars)}
            return rec

        errors: dict[str, str] = {}
        for meta in sec["rows"]:
            n_total += 1
            if meta["ticker"] not in cache and waited_once:
                sleep(delay)                              # one request at a time, with a pause between network calls
            waited_once = waited_once or meta["ticker"] not in cache
            try:
                by_id[meta["id"]] = attempt(meta)
                fresh_ids.add(meta["id"])
            except Exception as e:  # noqa: BLE001 - any fetch/parse failure is retried once below, then carried forward
                errors[meta["id"]] = str(e)[:120]
        if errors and retry_wait:                         # one cool-down, then one more try for what failed (Yahoo throttles bursts)
            sleep(retry_wait)
            for meta in sec["rows"]:
                if meta["id"] in errors:
                    sleep(delay)
                    try:
                        by_id[meta["id"]] = attempt(meta)
                        fresh_ids.add(meta["id"])
                        del errors[meta["id"]]
                    except Exception as e:  # noqa: BLE001
                        errors[meta["id"]] = str(e)[:120]
        n_fresh += len(fresh_ids)
        for meta in sec["rows"]:
            if meta["id"] in errors:
                failed.append(f"{meta['ticker']}: {errors[meta['id']]}")
                old = prev_rows.get(meta["id"])
                if old:
                    old = dict(old)
                    old["stale"], old["stale_reason"] = True, "fetch_failed"
                    by_id[meta["id"]] = old
                    if meta["id"] in prev_hist:                    # chart series are carried forward with the row
                        hist_by_id[meta["id"]] = prev_hist[meta["id"]]
                    if want_ind and meta["id"] in prev_ind:
                        ind_by_id[meta["id"]] = prev_ind[meta["id"]]
                else:
                    missing.append(meta["ticker"])
        rows = [by_id[m["id"]] for m in sec["rows"] if m["id"] in by_id]
        if not rows:
            raise validate.ValidationError(f"section {sec['id']}: no rows at all")
        latest = max(date.fromisoformat(r["last_close"]) for r in rows)
        for r in rows:
            if not r["stale"] and lookback.is_stale_close(date.fromisoformat(r["last_close"]), latest):
                r["stale"], r["stale_reason"] = True, "old_close"
        section = {
            "schema_version": 1, "section": sec["id"], "title": sec["title"], "page": sec.get("page", sec["id"]),
            "kind": sec.get("kind", "funds"), "generated_at": now_iso,
            "as_of": latest.isoformat(), "lookbacks": cfg["lookbacks"], "rows": rows,
            **({"default_visible": [i for i in sec["default_visible"] if i in by_id]} if sec.get("default_visible") else {}),
        }
        files[rel] = section
        sections_meta[sec["id"]] = {"path": rel, "as_of": section["as_of"]}
        ids = {m["id"] for m in sec["rows"]}
        base = {"schema_version": 1, "section": sec["id"], "generated_at": now_iso, "as_of": latest.isoformat()}
        hdoc = {**base, "series": [hist_by_id[m["id"]] for m in sec["rows"] if m["id"] in hist_by_id]}
        validate.validate_history(hdoc, ids)
        files[f"history/{sec['id']}.json"] = hdoc
        history_meta[sec["id"]] = {"path": f"history/{sec['id']}.json", "as_of": hdoc["as_of"]}
        if want_ind:
            idoc = {**base, "series": [ind_by_id[m["id"]] for m in sec["rows"] if m["id"] in ind_by_id]}
            validate.validate_indicators(idoc, ids)
            files[f"indicators/{sec['id']}.json"] = idoc
            indicators_meta[sec["id"]] = {"path": f"indicators/{sec['id']}.json", "as_of": idoc["as_of"]}
        all_fresh_ids |= fresh_ids
        try:
            validate.validate_section(
                section, run_date=today, prev_as_of=(prev_section or {}).get("as_of"), n_fresh=len(fresh_ids),
                n_total=len(sec["rows"]), min_fresh_fraction=vcfg["min_fresh_fraction"],
                max_close_age_days=vcfg["max_close_age_days"], max_abs_1d_pct=vcfg["max_abs_1d_pct"], fresh_ids=fresh_ids)
        except validate.ValidationError as e:
            if failed[sec_failed_from:]:                    # say which tickers failed, so a coverage failure can be diagnosed from the log
                raise validate.ValidationError(f"{e} (section {sec['id']}; failed: {'; '.join(failed[sec_failed_from:])})") from e
            raise
        section_for_validation = section

    any_stale = any(r["stale"] for k, s in files.items() if k.startswith("sections/") for r in s["rows"])
    if n_fresh:
        last_success = now_iso
    finished = datetime.now(timezone.utc) if now is None else now
    st = status.merge_status(
        prev_status, "yahoo_markets",
        # a lagging row (old close) is shown on its own row; only fetch failures mark the run stale
        status.source_block(now=now, last_success=last_success, items_ok=n_fresh, items_total=n_total,
                            failed=failed + [f"{t}: missing" for t in missing], cadence_hours=24, stale=bool(failed or missing)),
        status.run_info(workflow, started, finished, env), now)
    manifest = {
        "schema_version": 1, "generated_at": now_iso, "status": "status.json",
        "sections": {**{k: v for k, v in prev_manifest.get("sections", {}).items() if k in {x["id"] for x in cfg["sections"]}},
                     **sections_meta},
        "history": history_meta, "indicators": indicators_meta,
        "pe": prev_manifest.get("pe", {}),
        **({"yields": prev_manifest["yields"]} if "yields" in prev_manifest else {}),
    }
    files["status.json"] = st
    validate.validate_status(st)
    validate.validate_manifest(manifest)

    publish.stage(data_dir, out_dir)
    order = publish.write_outputs(out_dir, files, manifest)
    publish.atomic_swap(data_dir, out_dir)
    return {"n_fresh": n_fresh, "n_total": n_total, "failed": failed, "missing": missing, "order": order,
            "as_of": section_for_validation["as_of"] if section_for_validation else None}
