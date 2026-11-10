"""Daily markets job: fetch -> returns -> carry-forward -> stage -> validate -> atomic swap."""
from __future__ import annotations

import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import history, lookback, publish, status, validate


class OlderData(ValueError):
    """Yahoo's answer ends before the row's published last close (a lagging or cached response). Never published over newer data."""

    def __init__(self, new: str, published: str, cutoff: str, raw_last: str):
        super().__init__(f"newest usable bar {new} is older than the published {published}")
        self.new, self.published, self.cutoff, self.raw_last = new, published, cutoff, raw_last


# A legal-entity prefix Yahoo puts in front of the fund's own name: "iShares VII PLC - iShares Core ...", "Xtrackers (IE) Plc - Xtrackers ...",
# "Amundi Index Solutions - Amundi ...". The prefix is the text before the FIRST " - " when it ends in one of these entity words.
# "WisdomTree Industrial Metals - EUR Daily Hedged" is a share-class suffix, not an entity, and is left alone.
_ENTITY_END = re.compile(r"(?:\bplc|\bicav|\bsicav|\bindex solutions|\bfunds?|\btrust|\bumbrella)$", re.I)


def clean_name(name: str) -> str:
    name = " ".join((name or "").split())
    head, sep, rest = name.partition(" - ")
    brand = head.split()[0].lower() if head.split() else ""
    if sep and rest and _ENTITY_END.search(head.strip()) and re.match(r"[A-Za-z0-9$\u20ac]", rest) and brand in rest.lower():
        return rest.strip()
    return name


def pick_name(meta: dict, fetched: dict | None, last_good: str | None) -> str:
    """The fund name shown: the config's name_override if there is one (with a reason in the config), else Yahoo's longName,
    else its shortName, else the last good name already published. Never blank it when an earlier name exists."""
    if meta.get("name_override"):
        if not meta.get("name_reason"):
            raise validate.ValidationError(f"{meta['ticker']}: name_override needs a one-line name_reason in config/universe.yaml")
        return meta["name_override"]
    f = fetched or {}
    for k in ("longName", "shortName"):
        n = clean_name(f.get(k) or "")
        if n:
            return n
    return clean_name(last_good or "")


def _row_record(meta: dict, bars, now_iso: str) -> dict:
    extra = {k: meta[k] for k in ("isin", "provider", "acc", "hedged", "fund_name", "etc") if k in meta}
    return {
        "id": meta["id"], "label": meta["label"], "ticker": meta["ticker"], "currency": meta["currency"], **extra,
        "first_close": bars[0][0].isoformat(), "last_close": bars[-1][0].isoformat(),
        "stale": False, "stale_reason": None, "last_success": now_iso,
        "returns": lookback.compute_returns(bars),
    }


def run(cfg: dict, fetch, *, today: date, now: datetime | None = None, data_dir, work_dir,
        env=None, sleep=time.sleep, delay: float = 3.0, retry_wait: float = 20.0, workflow: str = "markets", fetch_names=None) -> dict:
    now = now or datetime.now(timezone.utc)
    started = now
    data_dir, work_dir = Path(data_dir), Path(work_dir)
    out_dir = work_dir / "out"
    vcfg = cfg["validation"]
    for sec0 in cfg["sections"]:                          # checked up front: a failure inside the per-fund fetch would be mistaken for a fetch error
        for m0 in sec0["rows"]:
            if m0.get("name_override") and not m0.get("name_reason"):
                raise validate.ValidationError(f"{m0['ticker']}: name_override needs a one-line name_reason in config/universe.yaml")
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
    kept_sections: dict[str, dict] = {}                 # sections left as published because the new data was older
    older_rows: list[str] = []                          # rows left as published, inside sections that were refreshed
    cache: dict[str, object] = {}                       # a ticker used on several pages is fetched once per run

    def fetch_once(ticker):
        if ticker in cache:
            return cache[ticker], False
        bars_raw = fetch(ticker)
        cache[ticker] = bars_raw
        return bars_raw, True

    # Fund names come from Yahoo too (longName, then shortName). One batch for the whole run; if the call fails or skips a ticker,
    # the last published name for that ticker is kept.
    last_names: dict[str, str] = {}
    for rel0 in (prev_manifest.get("sections") or {}).values():
        for r in (publish.read_json(data_dir / rel0["path"]) or {}).get("rows", []):
            if r.get("fund_name"):
                last_names[r["ticker"]] = r["fund_name"]
    fund_tickers = sorted({m["ticker"] for s in cfg["sections"] if s.get("kind", "funds") == "funds" for m in s["rows"]})
    fetched_names: dict = {}
    if fetch_names is not None:
        try:
            fetched_names = fetch_names(fund_tickers) or {}
        except Exception:  # noqa: BLE001
            fetched_names = {}

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
            pub = prev_rows.get(meta["id"])
            if pub and bars[-1][0].isoformat() < pub["last_close"]:          # never replace a row with one whose last close is older
                cache.pop(meta["ticker"], None)                               # so that the retry asks Yahoo again
                raw_last = max((d for d, _ in raw), default=None)
                raise OlderData(bars[-1][0].isoformat(), pub["last_close"], cutoff.isoformat(), raw_last.isoformat() if raw_last else "none")
            # Only the window the figures use is checked: a bar older than the 10Y anchor (plus a month of margin) never enters a number.
            window_start = date(today.year - 10, today.month, 1) - timedelta(days=31)
            validate.check_price_jumps(meta["ticker"], [b for b in bars if b[0] >= window_start], vcfg["max_abs_1d_pct"], vcfg.get("jump_exceptions"))
            if kind == "funds":
                meta = {**meta, "fund_name": pick_name(meta, fetched_names.get(meta["ticker"]), last_names.get(meta["ticker"]))}
            rec = _row_record(meta, bars, now_iso)
            hist_by_id[meta["id"]] = {"id": meta["id"], **history.history_points(bars)}
            if want_ind:
                ind_by_id[meta["id"]] = {"id": meta["id"], **history.indicator_points(bars)}
            return rec

        errors: dict[str, str] = {}
        older: dict[str, OlderData] = {}
        for meta in sec["rows"]:
            n_total += 1
            if meta["ticker"] not in cache and waited_once:
                sleep(delay)                              # one request at a time, with a pause between network calls
            waited_once = waited_once or meta["ticker"] not in cache
            try:
                by_id[meta["id"]] = attempt(meta)
                fresh_ids.add(meta["id"])
            except OlderData as e:
                older[meta["id"]] = e
            except Exception as e:  # noqa: BLE001 - any fetch/parse failure is retried once below, then carried forward
                errors[meta["id"]] = str(e)[:120]
        if (errors or older) and retry_wait:              # one cool-down, then one more try for what failed (Yahoo throttles bursts, lags)
            sleep(retry_wait)
            for meta in sec["rows"]:
                if meta["id"] in errors or meta["id"] in older:
                    sleep(delay)
                    try:
                        by_id[meta["id"]] = attempt(meta)
                        fresh_ids.add(meta["id"])
                        errors.pop(meta["id"], None)
                        older.pop(meta["id"], None)
                    except OlderData as e:
                        errors.pop(meta["id"], None)
                        older[meta["id"]] = e
                    except Exception as e:  # noqa: BLE001
                        older.pop(meta["id"], None)
                        errors[meta["id"]] = str(e)[:120]
        tick_of = {m["id"]: m["ticker"] for m in sec["rows"]}
        if older:
            new_asof = max((by_id[i]["last_close"] for i in fresh_ids), default=None)
            if prev_section and not fresh_ids:
                # The section's new as_of would be earlier than the published one: keep the published section (rows, charts,
                # manifest entry) untouched and carry on with the others. The row-level stale rule shows it if it stays old.
                failed.extend(f"{tick_of[i]}: {errors[i]}" for i in errors)
                missing.extend(m["ticker"] for m in sec["rows"] if m["id"] not in prev_rows)       # new in the config, nothing published to keep
                kept_sections[sec["id"]] = {
                    "published_as_of": prev_section["as_of"], "new_as_of": new_asof, "cutoff": cutoff.isoformat(),
                    "tickers": [f"{tick_of[i]} (newest bar {e.new}, published {e.published}, Yahoo's last raw bar {e.raw_last})" for i, e in older.items()]}
                continue
            for i, e in older.items():                    # partly older: those rows stay as published, the rest is refreshed
                older_rows.append(f"{sec['id']}/{tick_of[i]}: newest bar {e.new} is older than the published {e.published}")
                by_id[i] = dict(prev_rows[i])
                if kind == "funds":
                    mi = next(m for m in sec["rows"] if m["id"] == i)
                    by_id[i]["fund_name"] = pick_name(mi, fetched_names.get(mi["ticker"]), by_id[i].get("fund_name") or last_names.get(mi["ticker"]))
                if i in prev_hist:
                    hist_by_id[i] = prev_hist[i]
                if want_ind and i in prev_ind:
                    ind_by_id[i] = prev_ind[i]
        n_fresh += len(fresh_ids)
        for meta in sec["rows"]:
            if meta["id"] in errors:
                failed.append(f"{meta['ticker']}: {errors[meta['id']]}")
                old = prev_rows.get(meta["id"])
                if old:
                    old = dict(old)
                    old["stale"], old["stale_reason"] = True, "fetch_failed"
                    if kind == "funds":                            # rows published before names existed get one now; an existing name is never blanked
                        old["fund_name"] = pick_name(meta, fetched_names.get(meta["ticker"]), old.get("fund_name") or last_names.get(meta["ticker"]))
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
                section, run_date=today, prev_as_of=(prev_section or {}).get("as_of"), n_fresh=len(fresh_ids) + len(older),
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
                            failed=failed + [f"{t}: missing" for t in missing]
                            + [f"{sid}: kept as published, newer data not available ({'; '.join(k['tickers'])})" for sid, k in kept_sections.items()]
                            + older_rows,
                            cadence_hours=24, stale=bool(failed or missing)),
        status.run_info(workflow, started, finished, env), now)
    manifest = publish.merge_manifest(
        prev_manifest, generated_at=now_iso,
        updates={"sections": sections_meta, "history": history_meta, "indicators": indicators_meta},
        keep={"sections": {x["id"] for x in cfg["sections"]}, "history": {x["id"] for x in cfg["sections"]},
              "indicators": {x["id"] for x in cfg["sections"] if x.get("indicators")}})
    files["status.json"] = st
    validate.validate_status(st)
    validate.validate_manifest(manifest, universe=cfg)

    publish.stage(data_dir, out_dir)
    order = publish.write_outputs(out_dir, files, manifest)
    validate.validate_manifest_files(out_dir, manifest)
    publish.atomic_swap(data_dir, out_dir)
    return {"n_fresh": n_fresh, "n_total": n_total, "failed": failed, "missing": missing, "order": order,
            "kept_sections": kept_sections, "older_rows": older_rows,
            "as_of": section_for_validation["as_of"] if section_for_validation else None}
