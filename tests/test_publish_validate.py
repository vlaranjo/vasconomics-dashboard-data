"""V1-V6 (validation and publishing) and S1 (status.json merge)."""
import hashlib
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from conftest import FIX, fixture_fetch
from dashjobs import markets, pe, publish, validate

NOW = datetime(2026, 11, 4, 22, 41, 7, tzinfo=timezone.utc)
TODAY = date(2026, 11, 4)


def tree_hash(p: Path):
    h = hashlib.sha256()
    for f in sorted(p.rglob("*")):
        if f.is_file():
            h.update(f.relative_to(p).as_posix().encode())
            h.update(f.read_bytes())
    return h.hexdigest()


def run(cfg, tmp_path, fetch=None, today=TODAY, now=NOW):
    return markets.run(cfg, fetch or fixture_fetch(today), today=today, now=now, data_dir=tmp_path / "data",
                       work_dir=tmp_path / "work", delay=0, sleep=lambda s: None)


def test_V1_coverage_below_threshold_publishes_nothing(cfg, tmp_path):
    run(cfg, tmp_path)
    before = tree_hash(tmp_path / "data")
    with pytest.raises(validate.ValidationError, match="coverage"):
        run(cfg, tmp_path, fetch=fixture_fetch(TODAY, fail={"SXR8.DE", "EUNK.DE"}))
    assert tree_hash(tmp_path / "data") == before


def test_V2_one_ticker_fails_is_carried_forward_stale(cfg, tmp_path):
    run(cfg, tmp_path)
    old = json.loads((tmp_path / "data/sections/m1-demo.json").read_text())
    later = datetime(2026, 11, 5, 22, 41, 7, tzinfo=timezone.utc)
    res = run(cfg, tmp_path, fetch=fixture_fetch(TODAY, fail={"EUNK.DE"}), now=later)
    new = json.loads((tmp_path / "data/sections/m1-demo.json").read_text())
    rows = {r["id"]: r for r in new["rows"]}
    old_rows = {r["id"]: r for r in old["rows"]}
    assert res["n_fresh"] == 2 and rows["eunk"]["stale"] is True and rows["eunk"]["stale_reason"] == "fetch_failed"
    assert rows["eunk"]["last_success"] == old_rows["eunk"]["last_success"]
    assert rows["eunk"]["returns"] == old_rows["eunk"]["returns"]
    assert rows["sxr8"]["stale"] is False and rows["sxr8"]["last_success"] == "2026-11-05T22:41:07Z"
    st = json.loads((tmp_path / "data/status.json").read_text())
    assert st["sources"]["yahoo_markets"]["items_ok"] == 2 and st["sources"]["yahoo_markets"]["stale"] is True


def test_V3_output_earlier_than_published_is_rejected(cfg, tmp_path):
    run(cfg, tmp_path)
    before = tree_hash(tmp_path / "data")
    with pytest.raises(validate.ValidationError, match="earlier than the published"):
        run(cfg, tmp_path, fetch=fixture_fetch(date(2026, 10, 30)), today=date(2026, 11, 1))
    assert tree_hash(tmp_path / "data") == before


def _section(cfg, tmp_path):
    run(cfg, tmp_path)
    return json.loads((tmp_path / "data/sections/m1-demo.json").read_text())


def _kw(**over):
    d = dict(run_date=TODAY, prev_as_of=None, n_fresh=3, n_total=3, min_fresh_fraction=0.66, max_close_age_days=5,
             max_abs_1d_pct=25.0, fresh_ids={"sxr8", "eunk", "mvea"})
    d.update(over)
    return d


def test_V4_bad_schema_and_nan_rejected(cfg, tmp_path):
    s = _section(cfg, tmp_path)
    bad = json.loads(json.dumps(s)); del bad["rows"][0]["isin"]
    with pytest.raises(validate.ValidationError):
        validate.validate_section(bad, **_kw())
    nan = json.loads(json.dumps(s)); nan["rows"][0]["returns"]["1W"]["value"] = float("nan")
    with pytest.raises(validate.ValidationError):
        validate.validate_section(nan, **_kw())
    big = json.loads(json.dumps(s)); big["rows"][0]["returns"]["1D"]["value"] = 40.0
    with pytest.raises(validate.ValidationError, match="suspect"):
        validate.validate_section(big, **_kw())
    dup = json.loads(json.dumps(s)); dup["rows"][1]["id"] = dup["rows"][0]["id"]
    with pytest.raises(validate.ValidationError, match="unique"):
        validate.validate_section(dup, **_kw())
    old = json.loads(json.dumps(s))
    with pytest.raises(validate.ValidationError, match="days before the run date"):
        validate.validate_section(old, **_kw(run_date=date(2026, 12, 1)))


def test_V5_killed_between_staging_and_swap_leaves_data_unchanged(cfg, tmp_path, monkeypatch):
    run(cfg, tmp_path)
    before = tree_hash(tmp_path / "data")

    def killed(*a, **k):
        raise KeyboardInterrupt("job killed")

    monkeypatch.setattr(publish, "atomic_swap", killed)
    with pytest.raises(KeyboardInterrupt):
        run(cfg, tmp_path, now=datetime(2026, 11, 5, 22, 0, 0, tzinfo=timezone.utc))
    assert tree_hash(tmp_path / "data") == before
    assert (tmp_path / "work/out/manifest.json").exists()  # staged, never swapped


def test_V5b_failed_rename_restores_old_data(tmp_path, monkeypatch):
    data, out = tmp_path / "data", tmp_path / "out"
    data.mkdir(); (data / "a.json").write_text("{}")
    out.mkdir(); (out / "b.json").write_text("{}")
    real = os.rename
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk error")
        return real(src, dst)

    monkeypatch.setattr(os, "rename", flaky)
    with pytest.raises(OSError):
        publish.atomic_swap(data, out)
    assert (data / "a.json").exists() and not (data / "b.json").exists()


def test_V6_manifest_is_written_last(cfg, tmp_path):
    res = run(cfg, tmp_path)
    assert res["order"][-1] == "manifest.json" and "sections/m1-demo.json" in res["order"][:-1]


def test_S1_weekly_job_leaves_daily_status_block_intact(cfg, pe_cfg, tmp_path):
    run(cfg, tmp_path)
    daily = json.loads((tmp_path / "data/status.json").read_text())["sources"]["yahoo_markets"]
    pages = {i["url"]: (FIX / "pe" / f"{i['slug']}.html").read_text(encoding="utf-8") for i in pe_cfg["indices"]}
    pe.run(pe_cfg, lambda u: pages[u], today=date(2026, 11, 5), now=datetime(2026, 11, 8, 3, 7, 0, tzinfo=timezone.utc),
           data_dir=tmp_path / "data", work_dir=tmp_path / "work", sleep=lambda s: None)
    st = json.loads((tmp_path / "data/status.json").read_text())
    assert st["sources"]["yahoo_markets"] == daily
    assert st["sources"]["worldperatio"]["items_ok"] == 2
    assert st["heartbeat"] == "2026-11-08T03:07:00Z"
    man = json.loads((tmp_path / "data/manifest.json").read_text())
    assert "m1-demo" in man["sections"] and set(man["pe"]) == {"sp-500", "sp-500-energy"}
