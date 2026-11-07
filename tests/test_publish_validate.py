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


# --- price-jump rule and the documented ENIK.MI exception (decision of 6 Nov 2026) ---------------------------------

def _bars(*moves, start=date(2022, 3, 3), c0=100.0):
    """Closes on consecutive days; each move is a percent change from the previous close."""
    out, c, d = [(start, c0)], c0, start
    for m in moves:
        d = date.fromordinal(d.toordinal() + 1)
        c *= 1 + m / 100
        out.append((d, c))
    return out


NICKEL_EX = [{"ticker": "ENIK.MI", "dates": ["2022-03-07", "2022-03-09"], "reason": "LME nickel squeeze"}]


def test_V9_jump_above_limit_is_rejected_without_an_exception():
    bars = _bars(1, 1, 1, 1, 60.2)                       # 4 Mar..8 Mar; the +60.2% day is 2022-03-08 here
    with pytest.raises(validate.ValidationError, match="above 25.0%"):
        validate.check_price_jumps("ENIK.MI", bars, 25.0, [])
    validate.check_price_jumps("ENIK.MI", _bars(5, -5, 24.9), 25.0, [])      # inside the limit: fine


def test_V9b_exception_covers_only_the_named_ticker_and_dates():
    # +60.2% exactly on 2022-03-07 and -27.4% on 2022-03-09 (the two real ENIK.MI moves)
    real = [(date(2022, 3, 4), 100.0), (date(2022, 3, 7), 160.2), (date(2022, 3, 8), 160.2), (date(2022, 3, 9), 116.3)]
    validate.check_price_jumps("ENIK.MI", real, 25.0, NICKEL_EX)             # allowed: both dates are listed
    with pytest.raises(validate.ValidationError, match=r"NICK.MI: \+60.2%"):  # same moves, another ticker: not allowed
        validate.check_price_jumps("NICK.MI", real, 25.0, NICKEL_EX)
    shifted = [(date(2022, 3, 4), 100.0), (date(2022, 3, 8), 160.2)]         # the same jump on an unlisted date
    with pytest.raises(validate.ValidationError, match="2022-03-08"):
        validate.check_price_jumps("ENIK.MI", shifted, 25.0, NICKEL_EX)
    other_day = [(date(2024, 5, 2), 100.0), (date(2024, 5, 3), 130.0)]       # a new 30% day in another year
    with pytest.raises(validate.ValidationError):
        validate.check_price_jumps("ENIK.MI", other_day, 25.0, NICKEL_EX)


def test_V9c_config_carries_the_nickel_exception_with_a_reason():
    import yaml
    from pathlib import Path
    cfg = yaml.safe_load((Path(__file__).resolve().parents[1] / "config" / "universe.yaml").read_text(encoding="utf-8"))
    ex = {e["ticker"]: e for e in cfg["validation"]["jump_exceptions"]}
    assert ex["ENIK.MI"]["dates"] == ["2022-03-07", "2022-03-09"]
    assert "nickel" in ex["ENIK.MI"]["reason"].lower()
    assert any(c["to"] == "ENIK.MI" and c["from"] == "NICK.MI" for c in cfg["m2_fund_changes"])
    assert any(c["to"] == "ESVR.MI" and c["label"] == "Silver (futures, EUR-hedged)" for c in cfg["m2_fund_changes"])


def test_V9d_markets_job_carries_a_row_forward_when_its_history_has_an_unlisted_jump(cfg, tmp_path):
    run(cfg, tmp_path)                                                       # good first publish
    jumpy = fixture_fetch()

    def fetch(t):
        bars = list(jumpy(t))
        if t == "SXR8.DE":
            d, c = bars[-40]
            bars[-40] = (d, c * 1.5)                                         # a fake +50% day in the history
        return bars
    res = run(cfg, tmp_path, fetch=fetch)
    assert any("SXR8.DE" in f and "jump_exceptions" in f for f in res["failed"])


def test_V10_a_return_below_minus_100_percent_is_rejected(cfg, tmp_path):
    s = _section(cfg, tmp_path)
    validate.validate_section(s, **_kw())                                        # the real data passes
    edge = json.loads(json.dumps(s)); edge["rows"][0]["returns"]["1Y"]["value"] = -100.0
    validate.validate_section(edge, **_kw())                                     # exactly -100% (total loss) is possible
    for key, path in (("1Y", None), ("10Y", "since_launch")):
        bad = json.loads(json.dumps(s))
        cell = bad["rows"][0]["returns"][key]
        if path:
            cell["value"], cell["status"] = None, "na_young"
            cell["since_launch"] = {"value": -100.5, "start": "2020-04-24"}
        else:
            cell["value"] = -100.01
        with pytest.raises(validate.ValidationError, match="below -100%"):
            validate.validate_section(bad, **_kw())
