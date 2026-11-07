"""Completed-bar rule, chart series (rebased history, indicators) and their published files."""
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from dashjobs import history, lookback, markets, validate, yahoo

FIX = Path(__file__).resolve().parent / "fixtures"
ROOT = Path(__file__).resolve().parent.parent


def utc(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


# ---- completed bars -----------------------------------------------------------------------------------------------
def test_H1_london_date_follows_summer_time():
    assert lookback.london_date(utc(2026, 7, 1, 23, 30)) == date(2026, 7, 2)      # BST: 00:30 next day
    assert lookback.london_date(utc(2026, 11, 6, 23, 30)) == date(2026, 11, 6)    # GMT
    assert lookback.london_date(utc(2026, 3, 29, 0, 30)) == date(2026, 3, 29)     # before the changeover (29 Mar 2026, 01:00 UTC)
    assert lookback.london_date(utc(2026, 3, 29, 23, 30)) == date(2026, 3, 30)    # after it
    assert lookback.london_date(utc(2026, 10, 25, 0, 30)) == date(2026, 10, 25)   # BST until 01:00 UTC on 25 Oct 2026
    assert lookback.london_date(utc(2026, 10, 24, 23, 30)) == date(2026, 10, 25)
    assert lookback.london_date(utc(2026, 10, 25, 23, 30)) == date(2026, 10, 25)  # GMT again


@pytest.mark.parametrize("kind,now,expected", [
    ("fx", utc(2026, 11, 5, 22, 37), date(2026, 11, 4)),      # Thursday evening run: today's FX bar is still being traded
    ("funds", utc(2026, 11, 5, 22, 37), date(2026, 11, 5)),   # funds: every exchange has closed
    ("funds", utc(2026, 11, 5, 5, 47), date(2026, 11, 4)),    # morning repair run: today's bar does not exist yet
    ("fx", utc(2026, 11, 7, 5, 47), date(2026, 11, 6)),       # Saturday repair run: Friday's FX bar is complete
    ("funds", utc(2026, 11, 7, 5, 47), date(2026, 11, 6)),
    ("fx", utc(2026, 11, 6, 22, 37), date(2026, 11, 5)),      # Friday evening: Friday's FX bar waits for Saturday
    ("fx", utc(2026, 7, 2, 23, 30), date(2026, 7, 2)),        # summer: already 00:30 on 3 Jul in London, so 2 Jul is complete
    ("funds", utc(2026, 7, 2, 16, 59), date(2026, 7, 1)),
    ("funds", utc(2026, 7, 2, 17, 0), date(2026, 7, 2)),
])
def test_H2_last_completed_date(kind, now, expected):
    assert lookback.last_completed_date(kind, now.date(), now) == expected


def test_H3_a_run_described_only_by_its_date_is_the_evening_run():
    assert lookback.last_completed_date("fx", date(2026, 11, 5), None) == date(2026, 11, 4)
    assert lookback.last_completed_date("funds", date(2026, 11, 5), None) == date(2026, 11, 5)
    # `now` on another day than `today` (a backfill) is ignored
    assert lookback.last_completed_date("fx", date(2026, 11, 5), utc(2026, 12, 1, 3)) == date(2026, 11, 4)


def test_H4_the_live_quote_row_with_a_time_of_day_is_dropped_but_plain_dates_are_kept():
    import pandas as pd
    idx = pd.MultiIndex.from_tuples([("E", date(2026, 11, 5)), ("E", date(2026, 11, 6)),
                                     ("E", pd.Timestamp("2026-11-07 05:21:16+00:00"))], names=["symbol", "date"])
    df = pd.DataFrame({"adjclose": [1.0, 2.0, 3.0]}, index=idx)
    assert yahoo._normalise(df) == [(date(2026, 11, 5), 1.0), (date(2026, 11, 6), 2.0)]
    # a series whose every row has a time stamp is not a daily series with a live row: nothing is dropped
    idx2 = pd.MultiIndex.from_tuples([("E", pd.Timestamp("2026-11-05 09:00:00+01:00")), ("E", pd.Timestamp("2026-11-06 09:00:00+01:00"))],
                                     names=["symbol", "date"])
    assert len(yahoo._normalise(pd.DataFrame({"adjclose": [1.0, 2.0]}, index=idx2))) == 2


def _walk(end, n=800, start=100.0, step=0.001):
    d, out, c = end, [], start * (1 + step) ** n
    while len(out) < n:
        if d.weekday() < 5:
            out.append((d, c))
            c /= (1 + step)
        d -= timedelta(days=1)
    return sorted(out)


def _mini_cfg():
    return {"schema_version": 1, "lookbacks": lookback.LOOKBACKS,
            "validation": {"min_fresh_fraction": 0.5, "max_close_age_days": 5, "max_abs_1d_pct": 25.0},
            "sections": [
                {"id": "f", "page": "p", "title": "F", "indicators": True,
                 "rows": [{"id": "a", "label": "A", "ticker": "A.DE", "isin": "X", "provider": "P", "currency": "EUR", "acc": True, "hedged": False}]},
                {"id": "x", "page": "q", "kind": "fx", "title": "X", "indicators": True,
                 "rows": [{"id": "eurjpy", "label": "EURJPY", "ticker": "EURJPY=X", "currency": "JPY"}]}]}


def test_H5_job_uses_only_completed_bars_for_fx_and_for_funds(tmp_path):
    today = date(2026, 11, 5)                                      # Thursday
    bars = _walk(today)

    def run(now, d):
        markets.run(_mini_cfg(), lambda t: bars, today=today, now=now, data_dir=tmp_path / d, work_dir=tmp_path / ("w" + d),
                    sleep=lambda s: None, retry_wait=0)
    run(utc(2026, 11, 5, 22, 37), "evening")
    fx = json.loads((tmp_path / "evening/sections/x.json").read_text())["rows"][0]
    fund = json.loads((tmp_path / "evening/sections/f.json").read_text())["rows"][0]
    assert fx["last_close"] == "2026-11-04" and fund["last_close"] == "2026-11-05"
    run(utc(2026, 11, 5, 12, 0), "noon")                           # a midday run: today's fund bar is not complete either
    assert json.loads((tmp_path / "noon/sections/f.json").read_text())["rows"][0]["last_close"] == "2026-11-04"


# ---- indicators against reference values ----------------------------------------------------------------------------
REF = json.loads((FIX / "indicators" / "reference.json").read_text())


@pytest.mark.parametrize("name", ["walk", "real", "textbook"])
def test_H6_sma_and_rsi_match_talib_reference_values(name):
    r = REF[name]
    for ours, theirs in ((history.sma(r["close"], 50), r["sma50"]), (history.sma(r["close"], 200), r["sma200"]),
                         (history.rsi_wilder(r["close"], 14), r["rsi14"])):
        assert len(ours) == len(theirs)
        for a, b in zip(ours, theirs):
            assert (a is None) == (b is None)
            if a is not None:
                assert a == pytest.approx(b, abs=1e-9)


def test_H7_rsi_hand_calculation_and_flat_series():
    out = history.rsi_wilder([10, 11, 10, 12], 2)
    assert out[:2] == [None, None] and out[2] == pytest.approx(50.0) and out[3] == pytest.approx(100 * 1.25 / 1.5)
    assert history.rsi_wilder([5.0] * 20, 14)[14:] == [None] * 6           # undefined, not 0 (the one deliberate difference from TA-Lib)
    assert history.rsi_wilder([1, 2, 3, 4, 5, 6], 3)[3:] == [100.0, 100.0, 100.0]
    assert history.sma([1, 2, 3, 4], 2) == [None, 1.5, 2.5, 3.5]


def test_H8_published_indicator_series_matches_the_reference_after_rounding():
    closes = REF["walk"]["close"]
    d, bars = date(2024, 1, 1), []
    for c in closes:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        bars.append((d, c))
        d += timedelta(days=1)
    ind = history.indicator_points(bars)
    n = len(ind["d"])
    assert 480 < n < 540 and ind["p"][0] == 100.0                   # about two years of trading days
    off = len(bars) - n
    k = 100.0 / bars[off][1]
    for j in (0, n // 2, n - 1):
        i = off + j
        assert ind["p"][j] == pytest.approx(bars[i][1] * k, abs=0.006)
        assert ind["ma50"][j] == pytest.approx(REF["walk"]["sma50"][i] * k, abs=0.006)
        assert ind["rsi"][j] == pytest.approx(REF["walk"]["rsi14"][i], abs=0.05)
    assert ind["ma200"][-1] == pytest.approx(REF["walk"]["sma200"][-1] * k, abs=0.006)


# ---- rebased history -----------------------------------------------------------------------------------------------
def test_H9_history_points_daily_for_one_year_weekly_before_and_anchor_bars_kept():
    bars = _walk(date(2026, 11, 6), n=3200)                         # about 12.5 years
    h = history.history_points(bars)
    dates = [date.fromordinal(x + history.EPOCH_ORDINAL) for x in h["d"]]
    end = bars[-1][0]
    a1 = lookback.anchor_for(end, "1Y")
    in_year = [d for d in dates if d >= a1]
    assert len(in_year) >= 250 and len(dates) < 262 + 10 * 53 + 5      # daily for a year, then roughly one point a week
    assert h["v"][0] == 100 and h["d"] == sorted(set(h["d"]))
    allset = {d for d, _ in bars}
    for key in ("3Y", "5Y", "10Y"):
        start = max(d for d in allset if d <= lookback.anchor_for(end, key))
        assert start in dates                                       # the heatmap's start bar for this look-back is a published point
    assert dates[0] == max(d for d in allset if d <= lookback.anchor_for(end, "10Y"))


def test_H10_history_end_point_matches_the_heatmap_return_for_every_lookback():
    bars = _walk(date(2026, 11, 6), n=3200, step=0.0007)
    ret = lookback.compute_returns(bars)
    h = history.history_points(bars)
    by_date = dict(zip((date.fromordinal(x + history.EPOCH_ORDINAL) for x in h["d"]), h["v"]))
    end_level = h["v"][-1]
    for key in ("1M", "3M", "6M", "1Y", "3Y", "5Y", "10Y"):
        start = date.fromisoformat(ret[key]["start"])
        assert (end_level / by_date[start] - 1) * 100 == pytest.approx(ret[key]["value"], abs=0.05), key


def test_H11_young_fund_starts_at_its_first_close_and_publishes_no_prices():
    bars = _walk(date(2026, 11, 6), n=300)
    h = history.history_points(bars)
    assert date.fromordinal(h["d"][0] + history.EPOCH_ORDINAL) == bars[0][0] and 250 < len(h["d"]) < 300
    assert max(h["v"]) < 1000 and h["v"][0] == 100                   # an index, whatever the price level was


def test_H12_validators_reject_bad_series():
    ok = {"schema_version": 1, "section": "s", "generated_at": "2026-11-06T00:00:00Z", "as_of": "2026-11-06",
          "series": [{"id": "a", "d": [1, 2], "v": [100, 101.5]}]}
    validate.validate_history(ok, {"a"})
    for bad in ({"id": "a", "d": [2, 1], "v": [100, 101]}, {"id": "a", "d": [1, 2], "v": [99, 101]}, {"id": "a", "d": [1, 2], "v": [100]},
                {"id": "zz", "d": [1, 2], "v": [100, 101]}):
        with pytest.raises(validate.ValidationError):
            validate.validate_history({**ok, "series": [bad]}, {"a"})
    with pytest.raises(validate.ValidationError):
        validate.validate_indicators({**ok, "series": [{"id": "a", "d": [1, 2], "p": [100, 101], "ma50": [None, None], "ma200": [None, None], "rsi": [None, 120]}]})


def test_H13_production_job_publishes_history_for_all_sections_and_indicators_where_the_old_app_had_them(tmp_path):
    prod = yaml.safe_load((ROOT / "config" / "universe.yaml").read_text(encoding="utf-8"))
    today = date(2026, 11, 6)
    markets.run(prod, lambda t: _walk(today, n=3000), today=today, now=utc(2026, 11, 6, 22, 40), data_dir=tmp_path / "data",
                work_dir=tmp_path / "w", sleep=lambda s: None, retry_wait=0)
    man = json.loads((tmp_path / "data/manifest.json").read_text())
    assert set(man["history"]) == {s["id"] for s in prod["sections"]}
    assert set(man["indicators"]) == {"equity-regions", "equity-countries", "us-majors", "us-factors", "us-sectors", "eu-sectors",
                                      "commodity-sectors", "commodity-components", "fx"}
    for sec in man["history"]:
        assert (tmp_path / "data" / man["history"][sec]["path"]).exists()
