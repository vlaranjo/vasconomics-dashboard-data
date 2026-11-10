"""R1-R9: a run whose data is OLDER than what is published (the failed markets run of 10 Nov 2026, 04:17 UTC:
"as_of 2026-11-06 is earlier than the published 2026-11-09"). The run must keep what is published, publish the rest and succeed;
only genuine problems (coverage, schema, numbers) fail it."""
import json
from datetime import date, datetime, timedelta, timezone

import pytest

from conftest import ROOT
from dashjobs import lookback, markets, validate
from test_history import _mini_cfg, _walk, utc


def _run(cfg, tmp_path, fetch, now, retry_wait=0, **kw):
    return markets.run(cfg, fetch, today=now.date(), now=now, data_dir=tmp_path / "data", work_dir=tmp_path / "work",
                       sleep=lambda s: None, retry_wait=retry_wait, delay=0, **kw)


def _tree(tmp_path):
    return {p.relative_to(tmp_path / "data").as_posix(): p.read_bytes() for p in sorted((tmp_path / "data").rglob("*")) if p.is_file()}


def _bars_ending(last, n=500):
    return _walk(last, n=n)


def _two_section_cfg():
    c = _mini_cfg()                                                    # section f (fund, Xetra-style) and x (FX)
    c["sections"][0]["rows"].append({"id": "b", "label": "B", "ticker": "B.DE", "isin": "Y", "provider": "P", "currency": "EUR", "acc": True, "hedged": False})
    return c


def test_R1_the_completed_bar_and_london_day_rules_are_not_the_cause_at_04_17_utc():
    """At 04:17 UTC on Tue 10 Nov the usable fund bar is Mon 9 Nov (yesterday) and the usable FX bar is Mon 9 Nov too, exactly as in the
    runs at 13:47 and 20:25 UTC that published 9 Nov. So a 6 Nov as_of can only come from the data Yahoo returned."""
    now = utc(2026, 11, 10, 4, 17)
    assert lookback.last_completed_date("funds", now.date(), now) == date(2026, 11, 9)
    assert lookback.last_completed_date("fx", now.date(), now) == date(2026, 11, 9)
    now2 = utc(2026, 11, 10, 13, 47)
    assert lookback.last_completed_date("funds", now2.date(), now2) == date(2026, 11, 9)
    now3 = utc(2026, 11, 9, 20, 25)
    assert lookback.last_completed_date("funds", now3.date(), now3) == date(2026, 11, 9)
    assert lookback.last_completed_date("fx", now3.date(), now3) == date(2026, 11, 8)        # a Sunday: the last FX bar on or before it is Friday 6 Nov, the as_of published that evening


def test_R2_a_section_whose_new_data_is_older_is_kept_and_the_run_succeeds(tmp_path):
    cfg = _two_section_cfg()
    _run(cfg, tmp_path, lambda t: _bars_ending(date(2026, 11, 9)), utc(2026, 11, 9, 20, 25))
    before = _tree(tmp_path)
    assert json.loads(before["sections/f.json"])["as_of"] == "2026-11-09"
    stale_yahoo = {"A.DE": _bars_ending(date(2026, 11, 6)), "B.DE": _bars_ending(date(2026, 11, 6)), "EURJPY=X": _bars_ending(date(2026, 11, 9))}
    res = _run(cfg, tmp_path, lambda t: stale_yahoo[t], utc(2026, 11, 10, 4, 17))             # the failed run's situation: no exception
    after = _tree(tmp_path)
    for k in ("sections/f.json", "history/f.json", "indicators/f.json"):
        assert after[k] == before[k], k                                                       # the published section is untouched
    assert json.loads(after["manifest.json"])["sections"]["f"]["as_of"] == "2026-11-09"
    assert json.loads(after["sections/x.json"])["as_of"] == "2026-11-09"                      # everything else published (FX moved on)
    assert after["status.json"] != before["status.json"] and json.loads(after["status.json"])["heartbeat"] == "2026-11-10T04:17:00Z"
    k = res["kept_sections"]["f"]
    assert k["published_as_of"] == "2026-11-09" and k["cutoff"] == "2026-11-09"
    assert any("A.DE" in t and "2026-11-06" in t for t in k["tickers"]) and any("B.DE" in t for t in k["tickers"])


def test_R3_a_row_is_never_replaced_by_one_with_an_older_last_close(tmp_path):
    cfg = _two_section_cfg()
    _run(cfg, tmp_path, lambda t: _bars_ending(date(2026, 11, 9)), utc(2026, 11, 9, 20, 25))
    old = {r["id"]: r for r in json.loads((tmp_path / "data/sections/f.json").read_text())["rows"]}
    new_yahoo = {"A.DE": _bars_ending(date(2026, 11, 10), 501), "B.DE": _bars_ending(date(2026, 11, 6)), "EURJPY=X": _bars_ending(date(2026, 11, 9))}
    res = _run(cfg, tmp_path, lambda t: new_yahoo[t], utc(2026, 11, 10, 18, 0))                 # A moves on, B is lagging
    rows = {r["id"]: r for r in json.loads((tmp_path / "data/sections/f.json").read_text())["rows"]}
    assert rows["a"]["last_close"] == "2026-11-10" and rows["b"] == old["b"]
    assert "f" not in res["kept_sections"] and any("f/B.DE" in o for o in res["older_rows"])
    hist = {s["id"] for s in json.loads((tmp_path / "data/history/f.json").read_text())["series"]}
    assert hist == {"a", "b"}                                                                   # B's chart series is carried with its row
    assert res["n_fresh"] == 2 and res["n_total"] == 3                                          # A and the FX row; B was not refreshed


def test_R4_a_lagging_answer_that_recovers_on_the_retry_is_published(tmp_path):
    cfg = _two_section_cfg()
    _run(cfg, tmp_path, lambda t: _bars_ending(date(2026, 11, 9)), utc(2026, 11, 9, 20, 25))
    calls = {}

    def fetch(t):
        calls[t] = calls.get(t, 0) + 1
        return _bars_ending(date(2026, 11, 6) if calls[t] == 1 and t != "EURJPY=X" else date(2026, 11, 10), 501)
    res = _run(cfg, tmp_path, fetch, utc(2026, 11, 10, 18, 0), retry_wait=20)
    assert not res["kept_sections"] and not res["older_rows"] and calls["A.DE"] == 2             # asked again, not served from the run's cache
    assert json.loads((tmp_path / "data/sections/f.json").read_text())["as_of"] == "2026-11-10"


def test_R5_a_kept_section_that_stays_old_is_marked_stale_by_the_normal_rule_only(tmp_path):
    cfg = _two_section_cfg()
    _run(cfg, tmp_path, lambda t: _bars_ending(date(2026, 11, 9)), utc(2026, 11, 9, 20, 25))
    lag = {"A.DE": _bars_ending(date(2026, 11, 6)), "B.DE": _bars_ending(date(2026, 11, 6)), "EURJPY=X": _bars_ending(date(2026, 11, 12))}
    res = _run(cfg, tmp_path, lambda t: lag[t], utc(2026, 11, 13, 4, 17))
    assert "f" in res["kept_sections"]
    rows = json.loads((tmp_path / "data/sections/f.json").read_text())["rows"]
    assert all(r["last_close"] == "2026-11-09" and r["stale"] is False for r in rows)           # a published section is never re-stamped stale here
    # inside a refreshed section the ordinary rule (2+ business days behind the section's latest) still applies
    mix = {"A.DE": _bars_ending(date(2026, 11, 12), 503), "B.DE": _bars_ending(date(2026, 11, 9), 500), "EURJPY=X": _bars_ending(date(2026, 11, 12))}
    _run(cfg, tmp_path, lambda t: mix[t], utc(2026, 11, 13, 18, 0))
    rows = {r["id"]: r for r in json.loads((tmp_path / "data/sections/f.json").read_text())["rows"]}
    assert rows["b"]["stale"] is True and rows["b"]["stale_reason"] == "old_close" and rows["a"]["stale"] is False


def test_R6_genuine_problems_still_fail_the_run(tmp_path):
    cfg = _two_section_cfg()
    _run(cfg, tmp_path, lambda t: _bars_ending(date(2026, 11, 9)), utc(2026, 11, 9, 20, 25))
    before = _tree(tmp_path)
    def boom(t):
        raise RuntimeError("down")
    with pytest.raises(validate.ValidationError, match="coverage"):                             # fetch failures below the threshold
        _run(cfg, tmp_path, boom, utc(2026, 11, 10, 18, 0))
    bad = _bars_ending(date(2026, 11, 9))
    bad[-1] = (bad[-1][0], bad[-1][1] * 1.6)                                                    # +60% in a day: invalid numbers
    with pytest.raises(validate.ValidationError):
        _run(cfg, tmp_path, lambda t: bad, utc(2026, 11, 10, 18, 0))
    assert _tree(tmp_path) == before                                                            # nothing was published by either


def test_R7_a_first_run_has_nothing_to_keep_and_publishes_what_it_got(tmp_path):
    res = _run(_two_section_cfg(), tmp_path, lambda t: _bars_ending(date(2026, 11, 6)), utc(2026, 11, 10, 4, 17))
    assert not res["kept_sections"] and json.loads((tmp_path / "data/sections/f.json").read_text())["as_of"] == "2026-11-06"


def test_R8_the_entry_point_exits_0_and_names_the_section_and_tickers(tmp_path, capsys):
    import run_markets
    cfg = ROOT / "tests" / "fixtures" / "config" / "universe_m1.yaml"
    args = ["--config", str(cfg), "--data-dir", str(tmp_path / "data"), "--work-dir", str(tmp_path / "work"), "--fixture-dir", str(ROOT / "tests" / "fixtures" / "yahoo")]
    assert run_markets.main(args + ["--today", "2026-11-05"]) == 0
    capsys.readouterr()
    assert run_markets.main(args + ["--today", "2026-10-30"]) == 0                              # data from 30 Oct against a published 4 Nov
    out = capsys.readouterr().out
    assert "SECTION KEPT AS PUBLISHED: m1-demo" in out and "SXR8.DE" in out and "EUNK.DE" in out and "MVEA.DE" in out
    assert json.loads((tmp_path / "data/sections/m1-demo.json").read_text())["as_of"] != "2026-10-30"


def test_R9_the_old_failure_is_reproduced_by_the_validator_alone(tmp_path):
    """The check itself stays as a safety net: handing a section with an earlier as_of to validate_section still raises."""
    cfg = _two_section_cfg()
    _run(cfg, tmp_path, lambda t: _bars_ending(date(2026, 11, 9)), utc(2026, 11, 9, 20, 25))
    sec = json.loads((tmp_path / "data/sections/f.json").read_text())
    sec["as_of"] = "2026-11-06"
    with pytest.raises(validate.ValidationError, match="earlier than the published 2026-11-09"):
        validate.validate_section(sec, run_date=date(2026, 11, 10), prev_as_of="2026-11-09", n_fresh=2, n_total=2, min_fresh_fraction=0.5,
                                  max_close_age_days=5, max_abs_1d_pct=25.0, fresh_ids={"a", "b"})


def _four_row_cfg():
    c = _mini_cfg()
    c["sections"][0]["rows"] = [{"id": i, "label": i.upper(), "ticker": f"{i.upper()}.DE", "isin": "X", "provider": "P", "currency": "EUR", "acc": True, "hedged": False}
                                for i in "abcd"]
    return c


def test_R10_rows_left_as_published_do_not_count_against_coverage(tmp_path):
    cfg = _four_row_cfg()
    _run(cfg, tmp_path, lambda t: _bars_ending(date(2026, 11, 9)), utc(2026, 11, 9, 20, 25))
    y = {f"{i.upper()}.DE": _bars_ending(date(2026, 11, 6)) for i in "bcd"}
    y["A.DE"] = _bars_ending(date(2026, 11, 10), 501)
    y["EURJPY=X"] = _bars_ending(date(2026, 11, 9))
    res = _run(cfg, tmp_path, lambda t: y[t], utc(2026, 11, 10, 18, 0))                          # 3 of 4 lag, 1 moved on: not a coverage failure
    rows = {r["id"]: r["last_close"] for r in json.loads((tmp_path / "data/sections/f.json").read_text())["rows"]}
    assert rows == {"a": "2026-11-10", "b": "2026-11-09", "c": "2026-11-09", "d": "2026-11-09"} and len(res["older_rows"]) == 3
    st = json.loads((tmp_path / "data/status.json").read_text())["sources"]["yahoo_markets"]
    assert any("f/B.DE" in f for f in st["failed"]) and st["stale"] is False                    # visible in the status, but only fetch failures make the run stale


def test_R11_a_kept_section_reports_a_ticker_that_is_new_in_the_config_and_says_so_in_the_status(tmp_path):
    cfg = _two_section_cfg()
    _run(cfg, tmp_path, lambda t: _bars_ending(date(2026, 11, 9)), utc(2026, 11, 9, 20, 25))
    cfg["sections"][0]["rows"].append({"id": "n", "label": "N", "ticker": "N.DE", "isin": "Z", "provider": "P", "currency": "EUR", "acc": True, "hedged": False})
    y = {"A.DE": _bars_ending(date(2026, 11, 6)), "B.DE": _bars_ending(date(2026, 11, 6)), "EURJPY=X": _bars_ending(date(2026, 11, 9))}      # the new ticker cannot be fetched

    def fetch(t):
        if t == "N.DE":
            raise RuntimeError("no data")
        return y[t]
    res = _run(cfg, tmp_path, fetch, utc(2026, 11, 10, 4, 17))
    assert "f" in res["kept_sections"] and "N.DE" in res["missing"]
    st = json.loads((tmp_path / "data/status.json").read_text())["sources"]["yahoo_markets"]
    assert any(f.startswith("f: kept as published") for f in st["failed"]) and any("N.DE" in f for f in st["failed"])


def test_R12_a_run_where_every_section_is_kept_still_succeeds_and_the_entry_point_says_so(tmp_path, capsys):
    import run_markets
    cfg = ROOT / "tests" / "fixtures" / "config" / "universe_m1.yaml"
    args = ["--config", str(cfg), "--data-dir", str(tmp_path / "data"), "--work-dir", str(tmp_path / "work"), "--fixture-dir", str(ROOT / "tests" / "fixtures" / "yahoo")]
    run_markets.main(args + ["--today", "2026-11-05"])
    capsys.readouterr()
    assert run_markets.main(args + ["--today", "2026-10-30"]) == 0
    assert "unchanged (no section had newer data)" in capsys.readouterr().out
