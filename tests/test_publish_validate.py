"""V1-V6 (validation and publishing) and S1 (status.json merge)."""
import hashlib
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from conftest import FIX, fixture_fetch
from dashjobs import lookback, markets, pe, publish, validate

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


# V3 (an earlier as_of fails the whole run) was replaced on 10 Nov 2026 by tests/test_regression.py R2-R9: the section is kept, the run succeeds.


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
           data_dir=tmp_path / "data", work_dir=tmp_path / "work", sleep=lambda s: None, universe=cfg)
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


# --- manifest: merge, never rebuild (the "no data yet" bug of 9 Nov 2026) -------------------------------------------

import copy  # noqa: E402
import yaml  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _prod():
    return yaml.safe_load((ROOT / "config" / "universe.yaml").read_text(encoding="utf-8"))


def _full_manifest(prod):
    return {"schema_version": 1, "generated_at": "2026-11-05T00:00:00Z", "status": "status.json",
            "sections": {s["id"]: {"path": f"sections/{s['id']}.json", "as_of": "2026-11-04"} for s in prod["sections"]},
            "history": {s["id"]: {"path": f"history/{s['id']}.json", "as_of": "2026-11-04"} for s in prod["sections"]},
            "indicators": {s["id"]: {"path": f"indicators/{s['id']}.json", "as_of": "2026-11-04"} for s in prod["sections"] if s.get("indicators")},
            "pe": {"sp-500": {"path": "pe/sp-500.json", "last_point": "2026-11"}}, "yields": {"us": {"path": "yields/us.json", "as_of": "2026-11-02"}}}


def test_M1_merge_keeps_every_block_the_job_does_not_own():
    prod = _prod()
    prev = _full_manifest(prod)
    prev["something_new"] = {"x": 1}
    m = publish.merge_manifest(prev, generated_at="2026-11-09T00:00:00Z", updates={"pe": {"nasdaq-100": {"path": "pe/nasdaq-100.json", "last_point": "2026-11"}}})
    for b in ("sections", "history", "indicators", "yields"):
        assert m[b] == prev[b], b
    assert set(m["pe"]) == {"sp-500", "nasdaq-100"} and m["something_new"] == {"x": 1} and m["generated_at"] == "2026-11-09T00:00:00Z"
    assert prev["pe"].keys() == {"sp-500"}                       # the input is not modified


def test_M2_merge_prunes_only_what_the_jobs_own_config_dropped():
    m = publish.merge_manifest(_full_manifest(_prod()), generated_at="2026-11-09T00:00:00Z", updates={},
                               keep={"pe": set()})
    assert m["pe"] == {} and m["sections"] and m["yields"]


def test_M3_validation_fails_when_a_section_lacks_its_history_or_indicators_entry():
    prod = _prod()
    good = _full_manifest(prod)
    validate.validate_manifest(good, universe=prod)
    for block, sid in (("history", "fx"), ("indicators", "us-sectors"), ("sections", "asset-classes")):
        bad = copy.deepcopy(good)
        del bad[block][sid]
        with pytest.raises(validate.ValidationError, match=f"{block}/{sid}"):
            validate.validate_manifest(bad, universe=prod)
    bad = copy.deepcopy(good)
    bad["history"] = {}
    bad["indicators"] = {}                                       # what a rebuild-from-scratch job used to publish
    with pytest.raises(validate.ValidationError, match="missing entries"):
        validate.validate_manifest(bad, universe=prod)
    assert "fixed-income" not in good["indicators"]
    validate.validate_manifest(good, universe=prod)              # a section without indicators needs no indicators entry


def test_M4_every_job_publishes_a_complete_manifest_and_a_pe_or_yield_run_cannot_drop_chart_entries(tmp_path, pe_cfg):
    prod = _prod()
    today = date(2026, 11, 6)
    markets.run(prod, lambda t: __import__("test_universe")._bars(t, today), today=today, now=datetime(2026, 11, 6, 22, 40, tzinfo=timezone.utc),
                data_dir=tmp_path / "data", work_dir=tmp_path / "work", sleep=lambda s: None)
    full = json.loads((tmp_path / "data/manifest.json").read_text())
    validate.validate_manifest(full, universe=prod)
    pages = {i["url"]: (FIX / "pe" / f"{i['slug']}.html").read_text(encoding="utf-8") for i in pe_cfg["indices"]}
    pe.run(pe_cfg, lambda u: pages[u], today=date(2026, 11, 7), now=datetime(2026, 11, 8, 3, 7, tzinfo=timezone.utc),
           data_dir=tmp_path / "data", work_dir=tmp_path / "work", sleep=lambda s: None, universe=prod)
    after = json.loads((tmp_path / "data/manifest.json").read_text())
    assert after["history"] == full["history"] and after["indicators"] == full["indicators"] and after["sections"] == full["sections"]
    # a manifest that already lost its chart entries (a broken earlier run) is refused instead of being republished
    (tmp_path / "data/manifest.json").write_text(json.dumps({**after, "history": {}, "indicators": {}}))
    with pytest.raises(validate.ValidationError, match="missing entries"):
        pe.run(pe_cfg, lambda u: pages[u], today=date(2026, 11, 7), now=datetime(2026, 11, 8, 3, 7, tzinfo=timezone.utc),
               data_dir=tmp_path / "data", work_dir=tmp_path / "work", sleep=lambda s: None, universe=prod)


def test_M5_the_committed_data_folder_is_complete():
    """Checks data/ itself (skipped on a fresh clone with no data): complete manifest, every named file present and valid."""
    d = ROOT / "data"
    if not (d / "manifest.json").exists():
        pytest.skip("no data folder")
    m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    validate.validate_manifest(m, universe=_prod())
    validate.validate_manifest_files(d, m)


# ---- fund names from Yahoo (9 Nov 2026) and the mandatory config ------------------------------------------------------------------
def _names_cfg(override=None, reason="Yahoo has the old brand"):
    c = {"schema_version": 1, "lookbacks": lookback.LOOKBACKS,
         "validation": {"min_fresh_fraction": 0.5, "max_close_age_days": 5, "max_abs_1d_pct": 25.0},
         "sections": [{"id": "f", "page": "p", "title": "F", "rows": [
             {"id": "a", "label": "A", "ticker": "A.DE", "isin": "X", "provider": "P", "currency": "EUR", "acc": True, "hedged": False, **({"name_override": override, "name_reason": reason} if override else {})},
             {"id": "b", "label": "B", "ticker": "B.DE", "isin": "Y", "provider": "P", "currency": "EUR", "acc": True, "hedged": False}]}]}
    return c


def _run_names(tmp_path, cfg, fetch_names):
    today = date(2026, 11, 5)
    bars = [(date(2026, 11, 5) - timedelta(days=i), 100 + i) for i in range(400, -1, -1) if (date(2026, 11, 5) - timedelta(days=i)).weekday() < 5]
    markets.run(cfg, lambda t: bars, today=today, now=datetime(2026, 11, 5, 22, 40, tzinfo=timezone.utc), data_dir=tmp_path / "data",
                work_dir=tmp_path / "work", sleep=lambda s: None, retry_wait=0, fetch_names=fetch_names)
    return {r["id"]: r["fund_name"] for r in json.loads((tmp_path / "data/sections/f.json").read_text())["rows"]}


def test_N1_name_is_yahoos_longname_then_shortname_and_an_override_wins(tmp_path):
    got = _run_names(tmp_path, _names_cfg(), lambda ts: {"A.DE": {"longName": "A Long", "shortName": "A Short"}, "B.DE": {"longName": None, "shortName": "B Short"}})
    assert got == {"a": "A Long", "b": "B Short"}
    got = _run_names(tmp_path / "o", _names_cfg(override="Amundi A"), lambda ts: {"A.DE": {"longName": "Lyxor A", "shortName": "x"}})
    assert got["a"] == "Amundi A"


def test_N2_a_failed_or_partial_name_call_keeps_the_last_good_name_never_blank(tmp_path):
    first = _run_names(tmp_path, _names_cfg(), lambda ts: {"A.DE": {"longName": "A Long", "shortName": None}, "B.DE": {"longName": "B Long", "shortName": None}})
    assert first == {"a": "A Long", "b": "B Long"}

    def boom(ts):
        raise RuntimeError("yahoo down")
    assert _run_names(tmp_path, _names_cfg(), boom) == first                              # whole call fails
    assert _run_names(tmp_path, _names_cfg(), lambda ts: {"A.DE": {"longName": "A New", "shortName": None}}) == {"a": "A New", "b": "B Long"}
    assert _run_names(tmp_path, _names_cfg(), lambda ts: {"A.DE": {"longName": "  ", "shortName": ""}}) == {"a": "A New", "b": "B Long"}


def test_N3_the_universe_config_is_mandatory_for_every_job(tmp_path, cfg, pe_cfg):
    import inspect
    from dashjobs.yields import job as yjob
    for fn in (pe.run, yjob.run):
        p = inspect.signature(fn).parameters["universe"]
        assert p.default is inspect.Parameter.empty and p.kind is inspect.Parameter.KEYWORD_ONLY, fn.__module__
    pages = {i["url"]: (FIX / "pe" / f"{i['slug']}.html").read_text(encoding="utf-8") for i in pe_cfg["indices"]}
    kw = dict(today=date(2026, 11, 5), data_dir=tmp_path / "data", work_dir=tmp_path / "work", sleep=lambda s: None)
    with pytest.raises(TypeError):
        pe.run(pe_cfg, lambda u: pages[u], **kw)
    for bad in (None, {}, {"sections": []}):                                  # present but useless: refused, nothing published
        with pytest.raises(validate.ValidationError, match="universe config"):
            pe.run(pe_cfg, lambda u: pages[u], universe=bad, **kw)
    assert not (tmp_path / "data").exists()
    with pytest.raises(validate.ValidationError, match="universe config"):
        validate.validate_manifest(_full_manifest(_prod()), None)


def test_N4_entry_points_load_the_universe_config_themselves():
    import run_pe, run_yields
    for mod in (run_pe, run_yields):
        assert mod.load_universe(ROOT)["sections"]


def test_N5_every_name_override_has_a_one_line_reason_and_the_config_keeps_no_other_names():
    prod = _prod()
    rows = [r for s in prod["sections"] for r in s["rows"]]
    over = [r for r in rows if "name_override" in r]
    assert over and all(r.get("name_reason") and "\n" not in r["name_reason"] for r in over), over
    assert not [r for r in rows if "fund_name" in r]                                  # names come from Yahoo, not from the config
    assert "name_reason" not in [k for r in rows if "name_override" not in r for k in r]


def test_N6_published_rows_carry_the_name_but_never_the_override_bookkeeping(tmp_path):
    got = _run_names(tmp_path, _names_cfg(override="Amundi A"), lambda ts: {})
    row = json.loads((tmp_path / "data/sections/f.json").read_text())["rows"][0]
    assert got["a"] == "Amundi A" and "name_override" not in row and "name_reason" not in row


def test_N7_an_override_without_a_reason_is_refused_by_the_job(tmp_path):
    cfg = _names_cfg(override="X", reason=None)
    with pytest.raises(validate.ValidationError, match="name_reason"):
        _run_names(tmp_path, cfg, lambda ts: {})


def test_N8_legal_entity_prefixes_are_stripped_by_a_rule_and_nothing_else_is_touched():
    from dashjobs.markets import clean_name
    cases = {
        "iShares VII PLC - iShares Core MSCI Pac ex-Jpn ETF USD Acc": "iShares Core MSCI Pac ex-Jpn ETF USD Acc",          # abbreviation left as Yahoo has it
        "Xtrackers (IE) Plc - Xtrackers MSCI World UCITS ETF 1C": "Xtrackers MSCI World UCITS ETF 1C",
        "Amundi Index Solutions - Amundi MSCI Switzerland UCITS ETF-C CHF": "Amundi MSCI Switzerland UCITS ETF-C CHF",
        "Vanguard Funds plc - Vanguard FTSE All-World UCITS ETF": "Vanguard FTSE All-World UCITS ETF",
        "Invesco Markets III plc - Invesco Euro Cash 3 Months UCITS ETF": "Invesco Euro Cash 3 Months UCITS ETF",
        "WisdomTree Industrial Metals - EUR Daily Hedged": "WisdomTree Industrial Metals - EUR Daily Hedged",                    # a share-class suffix, not an entity
        "iShares S&P 500 EUR Hedged UCITS ETF (Acc)": "iShares S&P 500 EUR Hedged UCITS ETF (Acc)",
        "Amundi MSCI Brazil UCITS ETF Acc": "Amundi MSCI Brazil UCITS ETF Acc",
        "iShares VII PLC - ": "iShares VII PLC -",                                                                          # nothing after the prefix: never emptied
        "  iShares   VII PLC  -  iShares Core FTSE 100 ETF GBP Acc ": "iShares Core FTSE 100 ETF GBP Acc",                  # whitespace is normalised
        "": "",
    }
    for raw, want in cases.items():
        assert clean_name(raw) == want, raw


def test_N9_the_job_publishes_cleaned_names_and_cleans_a_previously_published_one(tmp_path):
    got = _run_names(tmp_path, _names_cfg(), lambda ts: {"A.DE": {"longName": "iShares VII PLC - iShares Core A ETF USD Acc", "shortName": None},
                                                       "B.DE": {"longName": None, "shortName": "Amundi Index Solutions - Amundi B"}})
    assert got == {"a": "iShares Core A ETF USD Acc", "b": "Amundi B"}
    assert _run_names(tmp_path, _names_cfg(), lambda ts: {}) == got                                       # failed call: the cleaned last good name stays


def test_N10_clean_name_never_reduces_a_name_to_a_bare_share_class():
    from dashjobs.markets import clean_name
    for keep in ("Some Index Fund - USD Acc", "Fund - Class A", "Global Trust - EUR Hedged", "Xtrackers II - Xtrackers EUR Overnight Rate Swap UCITS ETF 1D"):
        assert clean_name(keep) == keep, keep
    assert clean_name("Xtrackers II plc - Xtrackers EUR Overnight Rate Swap UCITS ETF 1D") == "Xtrackers EUR Overnight Rate Swap UCITS ETF 1D"
