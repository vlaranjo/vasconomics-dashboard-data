"""Relative Momentum charts (21 Nov 2026).

R1-R4 compare the port with the owner's reference implementation (_reference/local/rrg/rrg_calculations.py, normalised mode) to 1e-9.
The expected values in tests/fixtures/momentum/reference.json were produced by running the reference itself on the same weekly inputs
(_scratch/rm_reference.py); R5 re-runs the reference live when the _reference folder is present next to the repo."""
import copy
import json
import math
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from conftest import FIX, ROOT, fixture_fetch, load_csv

from dashjobs import markets, momentum, validate

REF = json.loads((FIX / "momentum" / "reference.json").read_text())
REF_DIR = ROOT.parent / "_reference" / "local" / "rrg"
TOL = 1e-9


def _frame(entities):
    return pd.DataFrame({k: pd.Series({pd.Timestamp(d): c for d, c in v}) for k, v in entities.items()}).sort_index()


def _series(pairs):
    return pd.Series({pd.Timestamp(d): c for d, c in pairs}).sort_index()


@pytest.mark.parametrize("case", REF["cases"], ids=[c["name"] for c in REF["cases"]])
def test_R1_port_matches_the_reference_to_1e9(case):
    x, y = momentum.compute(_frame(case["entities"]), _series(case["benchmark"]))
    assert [t.date().isoformat() for t in x.index] == case["dates"]
    n_valid = 0
    for k in case["entities"]:
        for got_x, got_y, ex, ey in zip(x[k], y[k], case["x"][k], case["y"][k]):
            for got, exp in ((got_x, ex), (got_y, ey)):
                if exp is None:
                    assert math.isnan(got)
                else:
                    assert abs(got - exp) <= TOL, (k, got, exp)
            n_valid += ex is not None and ey is not None
    assert n_valid > 100                                     # the comparison covers real points, not only the warm-up


@pytest.mark.parametrize("case", REF["cases"], ids=[c["name"] for c in REF["cases"]])
def test_R2_quadrants_match_the_reference_including_the_epsilon_rule(case):
    x, y = momentum.compute(_frame(case["entities"]), _series(case["benchmark"]))
    for k in case["entities"]:
        got = [momentum.classify(a, b) if not (math.isnan(a) or math.isnan(b)) else None for a, b in zip(x[k], y[k])]
        assert got == case["quadrant"][k], k
    if case["name"] == "synthetic_walks":                    # a fund equal to the benchmark: x = 100 within float noise, right side
        xs = [v for v in x["same_as_benchmark"] if not math.isnan(v)]
        assert max(abs(v - 100) for v in xs) < 1e-9
        assert {q for q in case["quadrant"]["same_as_benchmark"] if q} <= {"Leading", "Weakening"}


def test_R3_warmup_is_49_weeks_as_measured_by_the_reference():
    assert momentum.WARMUP_WEEKS == REF["reference_warmup_bars"] == 49
    case = REF["cases"][1]
    x, y = momentum.compute(_frame(case["entities"]), _series(case["benchmark"]))
    first = int((x["w0"].notna() & y["w0"].notna()).to_numpy().argmax())
    assert first == 49


def test_R4_daily_bars_are_refused_like_the_reference():
    assert REF["reference_refuses_daily"] is True
    idx = pd.date_range("2024-01-01", periods=300, freq="B")
    with pytest.raises(momentum.FrequencyError):
        momentum.compute(pd.DataFrame({"a": np.linspace(1, 2, 300)}, index=idx), pd.Series(np.linspace(1, 3, 300), index=idx))


@pytest.mark.skipif(not REF_DIR.exists(), reason="the owner's reference code is not next to the repo")
def test_R5_live_against_the_reference_on_fresh_random_input():
    sys.path.insert(0, str(REF_DIR))
    try:
        import rrg_calculations as ref
        rng = np.random.default_rng(2026)
        idx = pd.date_range("2015-01-02", periods=300, freq="W-FRI")
        df = pd.DataFrame({f"e{i}": 50 * np.exp(np.cumsum(rng.normal(0, 0.025, 300))) for i in range(6)}, index=idx)
        b = pd.Series(80 * np.exp(np.cumsum(rng.normal(0, 0.02, 300))), index=idx)
        rx, ry = ref.compute_rrg_metrics(df, b, normalize=True)
        mx, my = momentum.compute(df, b)
        assert np.allclose(rx.to_numpy(), mx.to_numpy(), atol=TOL, rtol=0, equal_nan=True)
        assert np.allclose(ry.to_numpy(), my.to_numpy(), atol=TOL, rtol=0, equal_nan=True)
        assert ref.warmup_bars(normalize=True) == momentum.WARMUP_WEEKS
    finally:
        sys.path.remove(str(REF_DIR))


# ---- weekly bars ---------------------------------------------------------------------------------------------------------------
def test_R6_weekly_closes_are_completed_weeks_labelled_by_friday():
    bars = [(date(2026, 11, 2) + timedelta(days=i), 100.0 + i) for i in range(12) if (date(2026, 11, 2) + timedelta(days=i)).weekday() < 5]
    # Mon 2 Nov .. Fri 13 Nov 2026; cutoff Thursday 12 Nov: the week of 13 Nov is not complete
    assert momentum.weekly_closes(bars, date(2026, 11, 12)) == [(date(2026, 11, 6), 104.0)]
    assert momentum.weekly_closes(bars, date(2026, 11, 13)) == [(date(2026, 11, 6), 104.0), (date(2026, 11, 13), 111.0)]
    # a Friday holiday: the week's last close is Thursday's, still labelled with the Friday
    no_fri = [b for b in bars if b[0] != date(2026, 11, 13)]
    assert momentum.weekly_closes(no_fri, date(2026, 11, 14))[-1] == (date(2026, 11, 13), 110.0)
    assert momentum.latest_complete_friday(date(2026, 11, 12)) == date(2026, 11, 6)
    assert momentum.latest_complete_friday(date(2026, 11, 14)) == date(2026, 11, 13)


def test_R7_weekly_closes_of_the_fixture_feed_the_reference_case():
    cut = date(2026, 11, 5)
    got = [p for p in momentum.weekly_closes(load_csv("EUNK.DE", cut), cut) if p[0] >= date(2022, 11, 1)]
    assert [[d.isoformat(), c] for d, c in got] == REF["cases"][0]["benchmark"]
    assert got[-1][0] == date(2026, 10, 30)                   # Thu 5 Nov is the last bar: the week of 6 Nov is incomplete


# ---- config: never mix hedged and unhedged ---------------------------------------------------------------------------------------
@pytest.fixture
def universe():
    return yaml.safe_load((ROOT / "config" / "universe.yaml").read_text(encoding="utf-8"))


def test_R8_the_real_config_passes_and_covers_every_hedged_row(universe):
    sections = {s["id"]: s for s in universe["sections"]}
    momentum.check_config(universe["momentum"], sections)
    for ch in universe["momentum"]["charts"]:
        members, left = momentum.chart_members(ch, sections[ch["section"]])
        assert all(not ch.get("substitutes", {}).get(m["id"], {}).get("hedged") for m in members)
        by_id = {r["id"]: r for r in sections[ch["section"]]["rows"]}
        for m in members:
            assert not by_id[m["id"]].get("hedged") or "substitute" in m, m
    regions = next(c for c in universe["momentum"]["charts"] if c["id"] == "equity-regions")
    assert set(regions["substitutes"]) == {"ubuj", "ibcg"} and set(regions["leave_out"]) == {"acwie"}
    assert {c["id"]: c["benchmark"]["ticker"] for c in universe["momentum"]["charts"]} == {
        "equity-regions": "IUSQ.DE", "equity-countries": "IUSQ.DE", "us-sectors": "SXR8.DE", "eu-sectors": "EUNK.DE"}


def test_R9_a_hedged_row_without_substitute_or_a_hedged_substitute_is_refused(universe):
    sections = {s["id"]: s for s in universe["sections"]}
    bad = copy.deepcopy(universe["momentum"])
    del bad["charts"][1]["substitutes"]["ibcf"]
    with pytest.raises(ValueError, match="IBCF.DE is EUR-hedged"):
        momentum.check_config(bad, sections)
    bad = copy.deepcopy(universe["momentum"])
    bad["charts"][0]["substitutes"]["ubuj"]["hedged"] = True
    with pytest.raises(ValueError, match="must be unhedged"):
        momentum.check_config(bad, sections)
    bad = copy.deepcopy(universe["momentum"])
    bad["charts"][2]["benchmark"]["hedged"] = True
    with pytest.raises(ValueError, match="benchmark must be an unhedged"):
        momentum.check_config(bad, sections)


# ---- the job --------------------------------------------------------------------------------------------------------------------
MCFG = {"weeks": 40, "charts": [{
    "id": "m1-demo", "section": "m1-demo",
    "benchmark": {"label": "MSCI Europe", "ticker": "EUNK.DE", "isin": "IE00B4K48X80", "provider": "iShares", "fund": "Test", "hedged": False}}]}
NOW = datetime(2026, 11, 4, 22, 41, tzinfo=timezone.utc)


def _cfg(cfg):
    c = copy.deepcopy(cfg)
    c["momentum"] = copy.deepcopy(MCFG)
    return c


def test_R10_markets_job_publishes_the_chart_with_40_weeks_and_a_manifest_entry(tmp_path, cfg):
    c = _cfg(cfg)
    markets.run(c, fixture_fetch(date(2026, 11, 4)), today=date(2026, 11, 4), now=NOW, data_dir=tmp_path / "data",
                work_dir=tmp_path / "w", sleep=lambda s: None, retry_wait=0)
    man = json.loads((tmp_path / "data" / "manifest.json").read_text())
    assert man["momentum"]["m1-demo"] == {"path": "momentum/m1-demo.json", "as_of": "2026-10-30"}
    doc = json.loads((tmp_path / "data" / "momentum" / "m1-demo.json").read_text())
    validate.validate_momentum(doc, section_ids={"sxr8", "eunk", "mvea"}, today=date(2026, 11, 4))
    ids = [s["id"] for s in doc["series"]]
    assert ids == ["sxr8", "mvea"]
    # EUNK against itself: x = 100 but the momentum leg divides 0 by a rolling spread of 0, so (as in the reference) it has no point
    assert doc["left_out"] == [{"id": "eunk", "label": "MSCI Europe", "reason": "its relative momentum is undefined: it moves exactly with the benchmark"}]
    for s in doc["series"]:
        assert len(s["d"]) == 40 and s["d"][-1] == (date(2026, 10, 30) - date(1970, 1, 1)).days
    # the published (rounded) values are the reference maths on the job's own weekly closes
    cut = date(2026, 11, 4)
    p, b = momentum.weekly_closes(load_csv("SXR8.DE", cut), cut), momentum.weekly_closes(load_csv("EUNK.DE", cut), cut)
    x, y = momentum.compute(_frame({"f": p}), _series(b))
    sx = doc["series"][0]
    assert sx["x"][-1] == round(float(x["f"].iloc[-1]), 4) and sx["y"][-1] == round(float(y["f"].iloc[-1]), 4)
    assert sx["quadrant"] == momentum.classify(float(x["f"].iloc[-1]), float(y["f"].iloc[-1]))
    raw = (tmp_path / "data" / "momentum" / "m1-demo.json").read_text()
    assert "\n" not in raw.strip()                            # compact


def test_R11_a_failed_fund_keeps_its_last_series_stale_and_a_failed_benchmark_keeps_the_file(tmp_path, cfg):
    c = _cfg(cfg)
    kw = dict(data_dir=tmp_path / "data", work_dir=tmp_path / "w", sleep=lambda s: None, retry_wait=0)
    markets.run(c, fixture_fetch(date(2026, 11, 4)), today=date(2026, 11, 4), now=NOW, **kw)
    first = json.loads((tmp_path / "data" / "momentum" / "m1-demo.json").read_text())
    nxt = datetime(2026, 11, 5, 22, 41, tzinfo=timezone.utc)
    markets.run(c, fixture_fetch(date(2026, 11, 5), fail={"MVEA.DE"}), today=date(2026, 11, 5), now=nxt, **kw)
    doc = json.loads((tmp_path / "data" / "momentum" / "m1-demo.json").read_text())
    mv = next(s for s in doc["series"] if s["id"] == "mvea")
    assert mv["stale"] and mv["stale_reason"] == "fetch_failed" and mv["d"] == first["series"][1]["d"]
    res = markets.run(c, fixture_fetch(date(2026, 11, 5), fail={"EUNK.DE"}), today=date(2026, 11, 5), now=nxt, **kw)
    doc = json.loads((tmp_path / "data" / "momentum" / "m1-demo.json").read_text())
    assert doc["stale"] and doc["stale_reason"] == "benchmark_failed"
    assert any("momentum/m1-demo: benchmark_failed" in n for n in res["momentum"])
    st = json.loads((tmp_path / "data" / "status.json").read_text())
    assert any("benchmark_failed" in f for f in st["sources"]["yahoo_markets"]["failed"])


def test_R12_a_chart_that_fails_validation_keeps_the_last_good_file(tmp_path, cfg, monkeypatch):
    c = _cfg(cfg)
    kw = dict(data_dir=tmp_path / "data", work_dir=tmp_path / "w", sleep=lambda s: None, retry_wait=0)
    markets.run(c, fixture_fetch(date(2026, 11, 4)), today=date(2026, 11, 4), now=NOW, **kw)
    good = json.loads((tmp_path / "data" / "momentum" / "m1-demo.json").read_text())

    def broken(*a, **k):
        raise validate.ValidationError("simulated")
    monkeypatch.setattr(validate, "validate_momentum", broken)
    markets.run(c, fixture_fetch(date(2026, 11, 4)), today=date(2026, 11, 4), now=NOW, **kw)
    doc = json.loads((tmp_path / "data" / "momentum" / "m1-demo.json").read_text())
    assert doc["stale"] and doc["stale_reason"] == "validation_failed"
    assert doc["series"] == good["series"]


def test_R13_validation_rejects_bad_files(tmp_path, cfg):
    c = _cfg(cfg)
    markets.run(c, fixture_fetch(date(2026, 11, 4)), today=date(2026, 11, 4), now=NOW, data_dir=tmp_path / "data",
                work_dir=tmp_path / "w", sleep=lambda s: None, retry_wait=0)
    good = json.loads((tmp_path / "data" / "momentum" / "m1-demo.json").read_text())
    ids, today = {"sxr8", "eunk", "mvea"}, date(2026, 11, 4)

    def bad(mut, msg):
        d = copy.deepcopy(good)
        mut(d)
        with pytest.raises(validate.ValidationError, match=msg):
            validate.validate_momentum(d, section_ids=ids, today=today)

    bad(lambda d: d["series"][0]["d"].__setitem__(-1, d["series"][0]["d"][-1] + 1), "Friday|increasing")
    bad(lambda d: d["series"][0].__setitem__("quadrant", "Lagging" if d["series"][0]["quadrant"] != "Lagging" else "Leading"), "quadrant")
    bad(lambda d: d["series"][0]["x"].__setitem__(-1, 350.0), "outside 0-300")
    ok = copy.deepcopy(good)                                   # y has no fixed range (no mean subtraction: far from 100 can be real)
    ok["series"][0]["y"][-1], ok["series"][0]["x"][-1], ok["series"][0]["quadrant"] = 258.0, 101.0, "Leading"
    validate.validate_momentum(ok, section_ids=ids, today=today)
    bad(lambda d: d["series"][0]["x"].pop(), "dates")
    bad(lambda d: d.__setitem__("as_of", "2026-10-29"), "not a Friday")
    bad(lambda d: d["series"].append(copy.deepcopy(d["series"][0])), "duplicated")
    with pytest.raises(validate.ValidationError, match="days old"):
        validate.validate_momentum(good, section_ids=ids, today=date(2026, 12, 1))
    with pytest.raises(validate.ValidationError, match="earlier than the published"):
        validate.validate_momentum(good, section_ids=ids, today=today, prev={"as_of": "2026-11-06"})


def test_R14_a_bad_config_stops_the_run_before_any_request(tmp_path, cfg):
    c = _cfg(cfg)
    c["sections"][0]["rows"][0]["hedged"] = True
    calls = []
    with pytest.raises(validate.ValidationError, match="EUR-hedged"):
        markets.run(c, lambda t: calls.append(t), today=date(2026, 11, 4), now=NOW, data_dir=tmp_path / "data",
                    work_dir=tmp_path / "w", sleep=lambda s: None, retry_wait=0)
    assert calls == []


def test_R16_a_carried_forward_series_must_be_the_same_fund(tmp_path, cfg):
    """Review of 21 Nov 2026: after a config change (a new unhedged substitute) the old series is another fund's; if the new fund
    cannot be read, it is NOT republished in its place."""
    c = _cfg(cfg)
    kw = dict(data_dir=tmp_path / "data", work_dir=tmp_path / "w", sleep=lambda s: None, retry_wait=0)
    markets.run(c, fixture_fetch(date(2026, 11, 4)), today=date(2026, 11, 4), now=NOW, **kw)
    c["momentum"]["charts"][0]["substitutes"] = {"mvea": {"label": "Sub", "ticker": "SUBX.DE", "isin": "IE0000000009", "provider": "p",
                                                          "fund": "f", "hedged": False}}
    res = markets.run(c, fixture_fetch(date(2026, 11, 5)), today=date(2026, 11, 5), now=datetime(2026, 11, 5, 22, 41, tzinfo=timezone.utc), **kw)
    doc = json.loads((tmp_path / "data" / "momentum" / "m1-demo.json").read_text())
    assert "mvea" not in [s["id"] for s in doc["series"]] and any("SUBX.DE" in n for n in res["momentum"])


def test_R17_a_row_without_an_explicit_hedged_flag_is_refused(universe):
    sections = copy.deepcopy({s["id"]: s for s in universe["sections"]})
    del sections["us-sectors"]["rows"][0]["hedged"]
    with pytest.raises(ValueError, match="no explicit hedged"):
        momentum.check_config(universe["momentum"], sections)


def test_R15_a_young_fund_is_left_out_with_a_reason():
    weekly = [(date(2026, 1, 2) + timedelta(weeks=i), 100.0 + i) for i in range(30)]
    bench = [(date(2024, 1, 5) + timedelta(weeks=i), 100.0) for i in range(150)]
    assert momentum.series_points(weekly, bench, 40) == []
    sec = {"rows": [{"id": "a", "label": "A", "ticker": "A"}]}
    ch = {"id": "t", "section": "s", "benchmark": {"label": "B", "ticker": "B", "isin": "x", "provider": "p", "fund": "f", "hedged": False}}
    daily = lambda first, n: [(first + timedelta(days=i), 100.0 + (i % 7)) for i in range(n) if (first + timedelta(days=i)).weekday() < 5]  # noqa: E731
    bars = {"A": daily(date(2026, 6, 1), 120), "B": daily(date(2023, 1, 2), 1400)}
    doc, problems = momentum.build_chart(ch, sec, weeks=40, cutoff=date(2026, 9, 25), bars_for=bars.__getitem__, prev=None,
                                         now_iso="2026-09-25T22:00:00Z", max_jump_pct=25.0)
    assert doc["series"] == [] and doc["left_out"][0]["id"] == "a" and "50 weeks" in doc["left_out"][0]["reason"]
