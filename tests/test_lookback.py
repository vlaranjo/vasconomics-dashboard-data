"""L1-L13: the D7 lookback rule and the stale rule (2 or more business days)."""
import math
from datetime import date, timedelta

from conftest import load_csv
from dashjobs import lookback as lb


def returns_at(symbol, end, run_date=None):
    bars = lb.clean_bars(load_csv(symbol, end), run_date)
    return lb.compute_returns(bars)


def test_L1_holiday_anchor_1w():
    r = returns_at("SXR8.DE", date(2026, 5, 8))
    assert lb.anchor_for(date(2026, 5, 8), "1W") == date(2026, 5, 1)  # Xetra closed on 1 May
    assert r["1W"]["start"] == "2026-04-30" and r["1W"]["value"] == 2.77


def test_L2_weekend_run_uses_friday():
    sat = date(2026, 10, 31)
    bars = lb.clean_bars(load_csv("SXR8.DE"), run_date=sat)
    assert bars[-1][0] == date(2026, 10, 30)
    r = lb.compute_returns(bars)
    assert r["1D"]["start"] == "2026-10-29" and r["1D"]["value"] == -1.53  # the old app gives -1.97


def test_L3_month_end_clamp():
    r = returns_at("SXR8.DE", date(2026, 3, 31))
    assert lb.anchor_for(date(2026, 3, 31), "1M") == date(2026, 2, 28)
    assert r["1M"]["start"] == "2026-02-27" and r["1M"]["value"] == -3.83


def test_L4_leap_handling():
    assert lb.anchor_for(date(2028, 3, 31), "1M") == date(2028, 2, 29)
    assert lb.anchor_for(date(2028, 2, 29), "1Y") == date(2027, 2, 28)
    assert lb.anchor_for(date(2026, 8, 31), "6M") == date(2026, 2, 28)


def test_L5_young_fund_10y_na_with_since_launch():
    r = returns_at("MVEA.DE", date(2026, 11, 4))
    assert r["10Y"]["status"] == "na_young" and r["10Y"]["value"] is None
    bars = load_csv("MVEA.DE", date(2026, 11, 4))
    # independent check of the since-launch figure on the saved pull (the 85.93% quoted in the plan was taken from a
    # live intraday 4 Nov bar; the saved pull holds the final 4 Nov close, which is one of the E5 differences)
    assert r["10Y"]["since_launch"] == {"value": round((bars[-1][1] / bars[0][1] - 1) * 100, 2), "start": "2020-04-24"}
    assert 84 < r["10Y"]["since_launch"]["value"] < 90
    start5 = dict(bars)[date(2021, 11, 4)]
    assert r["5Y"]["status"] == "ok" and r["5Y"]["start"] == "2021-11-04" and r["5Y"]["value"] == round((bars[-1][1] / start5 - 1) * 100, 2)


def _series(start, n, step=1, c0=100.0, g=0.001):
    return [(start + timedelta(days=i * step), c0 * (1 + g) ** i) for i in range(n)]


def test_L6_first_close_exactly_on_anchor_is_ok():
    bars = _series(date(2025, 1, 1), 400)
    end = bars[-1][0]
    anchor = lb.anchor_for(end, "1Y")
    bars = [b for b in bars if b[0] >= anchor]  # first close lands exactly on the anchor
    r = lb.compute_returns(bars)
    assert r["1Y"]["status"] == "ok" and r["1Y"]["start"] == anchor.isoformat()


def test_L7_anchor_on_trading_day_uses_that_day():
    # weekday-only series; end chosen so the 1M anchor is itself a weekday close
    days = [date(2026, 1, 5) + timedelta(days=i) for i in range(200)]
    days = [d for d in days if d.weekday() < 5]
    end = date(2026, 5, 20)  # Wednesday; anchor Monday 20 Apr: a trading day
    bars = [(d, 100.0 + i) for i, d in enumerate(days) if d <= end]
    assert bars[-1][0] == end and lb.anchor_for(end, "1M") == date(2026, 4, 20)
    assert lb.compute_returns(bars)["1M"]["start"] == "2026-04-20"


def test_L8_gap_spanning_anchor_uses_last_close_before_gap():
    bars = _series(date(2025, 1, 1), 100) + _series(date(2025, 6, 1), 60)  # gap 11 Apr - 31 May
    end = bars[-1][0]
    anchor = lb.anchor_for(end, "3M")  # falls inside the gap
    assert date(2025, 4, 11) < anchor < date(2025, 6, 1)
    assert lb.compute_returns(bars)["3M"]["start"] == "2025-04-10"


def test_L9_single_row_series():
    r = lb.compute_returns([(date(2026, 11, 4), 10.0)])
    assert r["1D"]["status"] == "na_missing"
    assert all(r[k]["status"] == "na_young" for k in lb.LOOKBACKS if k != "1D")


def test_L10_nan_zero_negative_and_future_bars_dropped():
    raw = [(date(2026, 1, 1), 10.0), (date(2026, 1, 2), float("nan")), (date(2026, 1, 3), 0.0),
           (date(2026, 1, 4), -5.0), (date(2026, 1, 5), 11.0), (date(2026, 1, 9), 99.0)]
    bars = lb.clean_bars(raw, run_date=date(2026, 1, 6))
    assert bars == [(date(2026, 1, 1), 10.0), (date(2026, 1, 5), 11.0)]
    assert lb.compute_returns(bars)["1D"]["start"] == "2026-01-01"


def test_L11_stale_rule_two_or_more():
    latest = date(2026, 11, 4)
    assert lb.is_stale_close(date(2026, 10, 29), latest)               # 4 business days
    assert lb.is_stale_close(date(2026, 10, 30), date(2026, 11, 3))    # Fri -> Tue: Mon, Tue = 2
    assert lb.is_stale_close(date(2026, 10, 29), date(2026, 11, 2))    # exactly 2: stale under "2 or more"
    assert not lb.is_stale_close(date(2026, 10, 30), date(2026, 11, 2))  # 1 business day
    assert not lb.is_stale_close(latest, latest)


def test_L12_ibc4_f_fixture_is_stale():
    assert lb.business_days_behind(date(2026, 10, 29), date(2026, 11, 2)) == 2
    assert lb.is_stale_close(date(2026, 10, 29), date(2026, 11, 2))


def test_L13_closed_form_all_ten_lookbacks():
    g = 0.0005
    bars = _series(date(2013, 1, 1), 365 * 13 + 4, g=g)  # one close per calendar day for 13 years
    end = bars[-1][0]
    r = lb.compute_returns(bars)
    for k in lb.LOOKBACKS:
        if k == "1D":
            expect = ((1 + g) - 1) * 100
        else:
            days = (end - lb.anchor_for(end, k)).days
            expect = ((1 + g) ** days - 1) * 100
        assert r[k]["status"] == "ok"
        assert math.isclose(r[k]["value"], round(expect, 2), abs_tol=0.011), (k, r[k]["value"], expect)
