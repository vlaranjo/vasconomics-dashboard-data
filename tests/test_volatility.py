"""Volatility page (13 Nov 2026): Cboe VX curve and slope, level changes, the US-index completed-bar rule, chart thinning, the job.
No network: Cboe answers come from FakeGetter, Yahoo from a function."""
import json
import math
from datetime import date, datetime, timedelta, timezone

import pytest
import yaml

from conftest import ROOT, seed_markets
from dashjobs import cboe, history, lookback, validate, volatility
from dashjobs.yields.http import FakeGetter

E = date.fromisoformat


# ---- the curve: roll date, missing contract, weeklies ------------------------------------------------------------------------
EXP = [E("2026-10-21"), E("2026-11-18"), E("2026-12-16"), E("2027-01-20"), E("2027-02-17"), E("2027-03-17"), E("2027-04-21"),
       E("2027-05-18"), E("2027-06-16"), E("2027-07-21")]


def flat_settles(days, base=16.0):
    """Every contract settles at base + its expiry index on every given day."""
    return {e: {d: base + i for d in days} for i, e in enumerate(EXP)}


def test_roll_on_the_expiry_day():
    day_before, expiry_day = E("2026-11-17"), E("2026-11-18")
    s = flat_settles([day_before, expiry_day])
    before = cboe.curve_on(day_before, EXP, s)
    on = cboe.curve_on(expiry_day, EXP, s)
    assert before[0]["expiry"] == E("2026-11-18") and before[0]["days"] == 1        # the November contract is still the 1st month
    assert on[0]["expiry"] == E("2026-12-16") and on[0]["days"] == 28                 # on its expiry day it is gone: December is 1st
    assert [p["pos"] for p in on] == list(range(1, 9))
    assert on[0]["settle"] == 18.0 and on[7]["settle"] == 25.0
    # the old 2nd month became the 1st: same contract, same price, one position lower
    assert before[1]["expiry"] == on[0]["expiry"] and before[1]["settle"] == on[0]["settle"]


def test_missing_contract_leaves_its_position_empty():
    d = E("2026-11-12")
    s = flat_settles([d])
    del s[E("2027-01-20")][d]                                                          # the 3rd month has no settlement that day
    c = cboe.curve_on(d, EXP, s)
    assert c[2]["expiry"] == E("2027-01-20") and c[2]["settle"] is None              # position 3 stays empty
    assert c[3]["expiry"] == E("2027-02-17") and c[3]["settle"] == 20.0              # the 4th is NOT moved into its place
    assert len(c) == 8


def test_settle_zero_rows_count_as_missing_and_weeklies_are_excluded():
    csv_text = (b"Trade Date,Futures,Open,High,Low,Close,Settle,Change,Total Volume,EFP,Open Interest\n"
                b"2013-01-02,F (Jan 2013),16.8,16.8,15.5,15.6,0,0,97535,3632,120663\n"
                b"2026-11-12,X (Nov 2026),18.5,19.13,17.85,18.6,18.7337,0.68,87284,0,71854\n")
    assert cboe.parse_contract_csv(csv_text) == {E("2026-11-12"): 18.7337}
    listing = {"2026": [
        {"product_display": "VX+VXT/X6", "expire_date": "2026-11-18", "futures_root": "VX", "duration_type": "M", "path": "p/VX_2026-11-18.csv"},
        {"product_display": "VX+VXT47/X6", "expire_date": "2026-11-24", "futures_root": "VX", "duration_type": "W", "path": "p/VX_2026-11-24.csv"},
        {"product_display": "VX+VXT/Z6", "expire_date": "2026-12-16", "futures_root": "VX", "duration_type": "M", "path": "p/VX_2026-12-16.csv"}]}
    cs = cboe.monthly_contracts(listing)
    assert [c["expiry"] for c in cs] == [E("2026-11-18"), E("2026-12-16")]
    assert cs[0]["code"] == "X6" and cs[0]["month"] == "Nov 2026"
    daily = (b"Product,Symbol,Expiration Date,Price\nVX,VX/X6,2026-11-18,18.7337\nVX,VX47/X6,2026-11-24,18.7337\n"
             b"VX,VX/Z6,2026-12-16,18.9627\nVXM,VXM/X6,2026-11-18,18.7337\n")
    assert cboe.parse_daily_settlement(daily) == {E("2026-11-18"): 18.7337, E("2026-12-16"): 18.9627}
    assert cboe.parse_daily_settlement(b"Product,Symbol,Expiration Date,Price\n") == {}


def test_listing_gap_is_found():
    cs = [{"expiry": e} for e in EXP if e != E("2027-02-17")]
    assert "2027-01-20" in cboe.listing_gap(cs, E("2026-11-01"))
    assert cboe.listing_gap([{"expiry": e} for e in EXP], E("2026-11-01")) is None


# ---- the slope, by hand -----------------------------------------------------------------------------------------------------
def curve(values):
    return [{"pos": i + 1, "settle": v} for i, v in enumerate(values)]


def test_slope_matches_the_hand_calculation():
    # positions 1..7, settlements 15, 16, 17, 17.5, 18, 18.2, 18.5. Mean position 4; sum of (x - 4) * y =
    # -45 - 32 - 17 + 0 + 18 + 36.4 + 55.5 = 15.9; sum of (x - 4)^2 = 28; slope = 15.9 / 28 = 0.567857...
    c = curve([15, 16, 17, 17.5, 18, 18.2, 18.5, 30.0])                    # the 8th position is not in the slope
    assert cboe.slope_of(c) == 0.5679
    # position 3 missing: x = 1,2,4,5,6,7 (mean 25/6), y = 15,16,17.5,18,18.2,18.5. Sxy = 445.7 - 6 * (25/6) * 17.2 = 15.7;
    # Sxx = 131 - 6 * (25/6)^2 = 26.8333; slope = 0.585093...
    c[2]["settle"] = None
    assert cboe.slope_of(c) == 0.5851
    # backwardation: 30, 28, 26.5, 25.5, 25 -> negative. Sxy = -3*0 ... computed: x 1..5, mean 3, y mean 27; Sxy = (-2)(3) + (-1)(1) + 0
    # + (1)(-1.5) + (2)(-2) = -12.5; Sxx = 10; slope -1.25
    assert cboe.slope_of(curve([30, 28, 26.5, 25.5, 25])) == -1.25


def test_slope_needs_four_contracts():
    assert cboe.slope_of(curve([15, 16, 17])) is None
    assert cboe.slope_of(curve([15, None, 17, None, None, 18, None, 30])) is None   # 3 of positions 1..7
    assert cboe.slope_of(curve([15, None, 17, None, None, 18, 19])) is not None


def test_bot_check_or_web_page_is_a_challenge():
    with pytest.raises(cboe.Challenge):
        cboe.check_body(b"<!DOCTYPE html><html><title>Just a moment...</title>", "x", "csv")
    with pytest.raises(cboe.Challenge):
        cboe.check_body(b'<?xml version="1.0"?><Error><Code>AccessDenied</Code></Error>', "x", "csv")
    cboe.check_body(b"Trade Date,Futures\n", "x", "csv")


# ---- level changes and the completed-bar rule ---------------------------------------------------------------------------------
def test_changes_are_in_points_with_the_calendar_anchor_rule():
    s = [(E("2025-11-12"), 20.0), (E("2026-10-12"), 15.5), (E("2026-10-13"), 16.0), (E("2026-11-12"), 18.25), (E("2026-11-13"), 17.0)]
    ch = lookback.compute_changes(s)
    assert ch["1D"] == {"value": -1.25, "start": "2026-11-12", "start_value": 18.25, "status": "ok"}
    assert ch["1M"]["start"] == "2026-10-13" and ch["1M"]["value"] == 1.0          # last value on or before 13 Oct 2026
    assert ch["1Y"]["start"] == "2025-11-12" and ch["1Y"]["value"] == -3.0         # 13 Nov 2025 has no value: 12 Nov is used
    assert ch["2Y"]["status"] == "na_young" and ch["2Y"]["value"] is None
    assert "YTD" not in ch
    neg = lookback.compute_changes([(E("2026-11-12"), -0.42), (E("2026-11-13"), 0.31)])
    assert neg["1D"]["value"] == 0.73                                              # a slope can change sign


def test_us_index_bar_is_complete_from_2215_utc():
    t = E("2026-11-13")
    assert lookback.last_completed_date("us_index", t, datetime(2026, 11, 13, 22, 10, tzinfo=timezone.utc)) == E("2026-11-12")
    assert lookback.last_completed_date("us_index", t, datetime(2026, 11, 13, 22, 20, tzinfo=timezone.utc)) == t
    assert lookback.last_completed_date("us_index", t, datetime(2026, 11, 13, 14, 0, tzinfo=timezone.utc)) == E("2026-11-12")
    assert lookback.last_completed_date("us_index", t) == t                          # no clock: the 22:37 evening run


def test_level_points_daily_for_five_years_weekly_before_and_averages_on_the_full_history():
    bars, d = [], E("2006-01-02")
    while d <= E("2026-11-13"):
        if d.weekday() < 5:
            bars.append((d, 10 + (d.toordinal() % 7)))
        d += timedelta(days=1)
    pts = history.level_points(bars, "5Y")
    days = [history.EPOCH_ORDINAL + x for x in pts["d"]]
    i5 = next(i for i, x in enumerate(days) if date.fromordinal(x) >= E("2021-11-12"))
    assert all(b - a <= 3 for a, b in zip(days[i5:], days[i5 + 1:]))                 # daily inside five years
    assert sum(1 for a, b in zip(days[:i5], days[1:i5]) if b - a < 5) <= 6           # weekly before (a few look-back start bars)
    assert len(pts["d"]) < len(bars) / 2
    a10, full = history.averages(bars)
    assert full == round(sum(v for _, v in bars) / len(bars), 2)
    ten = [v for x, v in bars if x >= E("2016-11-11")]
    assert a10 == round(sum(ten) / len(ten), 2)


# ---- the job ----------------------------------------------------------------------------------------------------------------
TODAY = E("2026-11-13")


def synthetic_cboe(today=TODAY, first=E("2024-01-17"), last=E("2027-07-21"), with_daily=True, break_listing=False):
    """A contract list with monthly (third-Wednesday-like) and weekly contracts, a CSV per monthly contract up to the day before
    `today` (the CSVs are rewritten overnight), and the day's settlement file for `today`."""
    exps, y, m = [], first.year, first.month
    while (y, m) <= (last.year, last.month):
        d = date(y, m, 15)
        while d.weekday() != 2:
            d += timedelta(days=1)
        exps.append(d)
        m += 1
        if m == 13:
            y, m = y + 1, 1
    if break_listing:
        exps = [e for e in exps if not (e.year == 2026 and e.month == 12)]
    listing = {}
    for e in exps:
        listing.setdefault(str(e.year), []).append({"product_display": "VX", "expire_date": e.isoformat(), "contract_dt": e.isoformat(),
                                                    "futures_root": "VX", "duration_type": "M", "path": f"data/VX/VX_{e.isoformat()}.csv"})
        w = e + timedelta(days=7)
        listing[str(e.year)].append({"product_display": "VXw", "expire_date": w.isoformat(), "contract_dt": w.isoformat(),
                                     "futures_root": "VX", "duration_type": "W", "path": f"data/VX/VX_{w.isoformat()}.csv"})

    def price(e, d):
        months = (e - d).days / 30.4
        return round(16 + 0.6 * months + 2 * math.sin(d.toordinal() / 40.0), 4)

    def csv_for(e):
        rows = ["Trade Date,Futures,Open,High,Low,Close,Settle,Change,Total Volume,EFP,Open Interest"]
        d = e - timedelta(days=270)
        while d <= min(e, today - timedelta(days=1)):
            if d.weekday() < 5:
                rows.append(f"{d.isoformat()},X ({e:%b %Y}),0,0,0,0,{price(e, d)},0,0,0,0")
            d += timedelta(days=1)
        return ("\n".join(rows) + "\n").encode()

    routes = {"product/list/VX": json.dumps(listing).encode()}
    for e in exps:
        routes[f"VX_{e.isoformat()}.csv"] = csv_for(e)
    daily = ["Product,Symbol,Expiration Date,Price"]
    if with_daily:
        for e in exps:
            if e > today:
                daily.append(f"VX,VX/{cboe.MONTH_CODES[e.month - 1]}{e.year % 10},{e.isoformat()},{price(e, today)}")
                daily.append(f"VX,VX47/{cboe.MONTH_CODES[e.month - 1]}{e.year % 10},{(e + timedelta(days=7)).isoformat()},99.0")
    routes[f"dt={today.isoformat()}"] = ("\n".join(daily) + "\n").encode()
    routes["settlement/csv?dt="] = b"Product,Symbol,Expiration Date,Price\n"           # every other day: header only
    return FakeGetter(routes), exps, price


def fake_yahoo(today=TODAY, fail=()):
    def fetch(symbol):
        if symbol in fail:
            raise RuntimeError("simulated failure")
        start = {"^VIX": E("1990-01-02"), "^SKEW": E("1990-01-02"), "^MOVE": E("2002-11-12")}[symbol]
        base = {"^VIX": 20.0, "^SKEW": 135.0, "^MOVE": 100.0}[symbol]
        out, d = [], start
        while d <= today:
            if d.weekday() < 5:
                out.append((d, round(base + 5 * math.sin(d.toordinal() / 50.0), 2)))
            d += timedelta(days=1)
        return out
    return fetch


@pytest.fixture
def vcfg():
    return yaml.safe_load((ROOT / "config" / "volatility.yaml").read_text(encoding="utf-8"))


def run_job(tmp_path, cfg, vcfg, getter, yahoo=None, today=TODAY, now=None):
    return volatility.run(vcfg, yahoo or fake_yahoo(today), getter, today=today, now=now or datetime(2026, 11, 13, 22, 40, tzinfo=timezone.utc),
                          data_dir=tmp_path / "data", work_dir=tmp_path / "work", universe=cfg, sleep=lambda s: None)


def read(tmp_path, rel):
    return json.loads((tmp_path / "data" / rel).read_text(encoding="utf-8"))


def test_job_publishes_table_curves_and_charts(tmp_path, cfg, vcfg):
    seed_markets(tmp_path, cfg)
    g, exps, price = synthetic_cboe()
    res = run_job(tmp_path, cfg, vcfg, g)
    assert res["ok"] == 4 and not res["failed"]
    man = read(tmp_path, "manifest.json")
    assert set(man["volatility"]) == {"summary", "vix", "skew", "move", "vx-term", "vx-history"}
    assert set(man["sections"]) == {"m1-demo"}                                         # the markets entries are kept
    s = read(tmp_path, "volatility/summary.json")
    assert [r["id"] for r in s["rows"]] == ["vix", "vx_slope", "skew", "move"]
    assert {r["id"]: r["direction"] for r in s["rows"]} == {"vix": "up_bad", "vx_slope": "up_good", "skew": "up_bad", "move": "up_bad"}
    assert s["lookbacks"] == ["1D", "1W", "1M", "3M", "6M", "1Y", "2Y", "5Y", "10Y"]
    t = read(tmp_path, "volatility/vx-term.json")
    assert t["as_of"] == "2026-11-13"                                                  # the day itself, from the day's settlement file
    assert res["vx"]["daily_dates"] == ["2026-11-13"]
    latest = t["curves"][0]
    assert [p["pos"] for p in latest["points"]] == list(range(1, 9))
    assert latest["points"][0]["expiry"] == "2026-11-18" and latest["points"][0]["days"] == 5
    assert latest["points"][0]["settle"] == price(E("2026-11-18"), TODAY)
    assert [c["id"] for c in t["curves"]] == ["latest", "1m", "6m", "1y"]
    one_y = t["curves"][3]
    assert one_y["date"] == "2025-11-13" and one_y["points"][0]["expiry"] == "2025-11-19"    # each curve by position on its own date
    six = t["curves"][2]
    assert six["date"] == "2026-05-13"
    slope_row = s["rows"][1]
    hand = cboe.slope_of([{"pos": p["pos"], "settle": p["settle"]} for p in latest["points"]])
    assert slope_row["latest"] == round(hand, 2) and t["slope_latest"] == hand
    h = read(tmp_path, "volatility/vx-history.json")
    assert h["first_date"] <= "2024-01-02"
    vix = read(tmp_path, "volatility/vix.json")
    assert vix["first_date"] == "1990-01-02" and vix["avg_10y"] is not None and vix["daily_from"] == "2021-11-12"
    assert vix["as_of"] == "2026-11-13"                                                # 22:40 UTC: the day's bar counts
    # weeklies never requested
    assert not any("VX_" in u and E(u.rsplit("VX_", 1)[1][:10]) not in exps for u in g.log if "VX_" in u)


def test_second_run_reads_only_the_live_contracts(tmp_path, cfg, vcfg):
    seed_markets(tmp_path, cfg)
    g, exps, _ = synthetic_cboe(today=E("2026-11-12"))
    run_job(tmp_path, cfg, vcfg, g, today=E("2026-11-12"), now=datetime(2026, 11, 12, 22, 40, tzinfo=timezone.utc))
    first_csvs = sum(".csv" in u and "VX_" in u for u in g.log)
    g2, _, _ = synthetic_cboe(today=TODAY)
    res = run_job(tmp_path, cfg, vcfg, g2)
    csvs = [u for u in g2.log if "VX_" in u]
    assert first_csvs >= 30 and len(csvs) <= 11                                        # ten days back: the live contracts only
    assert all(E(u.rsplit("VX_", 1)[1][:10]) > E("2026-11-02") for u in csvs)
    h = read(tmp_path, "volatility/vx-history.json")
    assert h["as_of"] == "2026-11-13" and res["vx"]["rebuilt_from"] == "2026-11-03"
    assert h["first_date"] <= "2024-01-02"                                             # the older slope history is kept


def test_challenge_keeps_the_last_good_files_marked_stale(tmp_path, cfg, vcfg):
    seed_markets(tmp_path, cfg)
    g, _, _ = synthetic_cboe()
    run_job(tmp_path, cfg, vcfg, g)
    before = read(tmp_path, "volatility/vx-term.json")
    blocked = FakeGetter({"product/list/VX": b"<!DOCTYPE html><title>Just a moment...</title>"})
    res = run_job(tmp_path, cfg, vcfg, blocked, now=datetime(2026, 11, 13, 23, 30, tzinfo=timezone.utc))
    assert len(blocked.log) == 1                                                       # nothing else asked of Cboe after the challenge
    assert any("Challenge" in f for f in res["failed"])
    t = read(tmp_path, "volatility/vx-term.json")
    assert t["stale"] is True and t["stale_reason"] == "challenge" and t["curves"] == before["curves"]
    s = read(tmp_path, "volatility/summary.json")
    assert next(r for r in s["rows"] if r["id"] == "vx_slope")["stale"] is True
    assert next(r for r in s["rows"] if r["id"] == "vix")["stale"] is False
    st = read(tmp_path, "status.json")["sources"]["volatility"]
    assert st["stale"] is True and st["items_ok"] == 3


def test_a_gap_in_the_contract_list_fails_validation_and_keeps_the_last_good(tmp_path, cfg, vcfg):
    seed_markets(tmp_path, cfg)
    run_job(tmp_path, cfg, vcfg, synthetic_cboe()[0])
    res = run_job(tmp_path, cfg, vcfg, synthetic_cboe(break_listing=True)[0])
    assert any("no monthly contract between" in f for f in res["failed"])
    assert read(tmp_path, "volatility/vx-term.json")["stale"] is True


def test_yahoo_failure_and_older_data(tmp_path, cfg, vcfg):
    seed_markets(tmp_path, cfg)
    run_job(tmp_path, cfg, vcfg, synthetic_cboe()[0])
    res = run_job(tmp_path, cfg, vcfg, synthetic_cboe()[0], yahoo=fake_yahoo(fail={"^SKEW"}))
    assert read(tmp_path, "volatility/skew.json")["stale"] is True and res["ok"] == 3
    # Yahoo lags: the newest usable bar is older than the published one -> left exactly as published, not stale
    res = run_job(tmp_path, cfg, vcfg, synthetic_cboe()[0], yahoo=fake_yahoo(today=E("2026-11-12")))
    vix = read(tmp_path, "volatility/vix.json")
    assert vix["as_of"] == "2026-11-13" and vix["stale"] is False
    assert any("older than the published" in n for n in res["notes"])


def test_a_bar_dated_today_is_not_used_before_2215_utc(tmp_path, cfg, vcfg):
    seed_markets(tmp_path, cfg)
    run_job(tmp_path, cfg, vcfg, synthetic_cboe()[0], now=datetime(2026, 11, 13, 17, 50, tzinfo=timezone.utc))
    assert read(tmp_path, "volatility/vix.json")["as_of"] == "2026-11-12"


def test_out_of_range_value_fails_that_series_only(tmp_path, cfg, vcfg):
    seed_markets(tmp_path, cfg)
    base = fake_yahoo()

    def bad(symbol):
        out = base(symbol)
        return out[:-1] + [(out[-1][0], 500.0)] if symbol == "^VIX" else out
    res = run_job(tmp_path, cfg, vcfg, synthetic_cboe()[0], yahoo=bad)
    assert any("^VIX" in f and "outside" in f for f in res["failed"])
    assert not (tmp_path / "data" / "volatility" / "vix.json").exists()              # nothing published before: no file, no row
    assert [r["id"] for r in read(tmp_path, "volatility/summary.json")["rows"]] == ["vx_slope", "skew", "move"]


def test_volatility_is_an_owned_manifest_block_for_commits():
    from commit_data import OWN, merge_shared
    blocks, source, volatile = OWN["volatility"]
    assert blocks == {"volatility"} and source == "volatility" and "last_success" in volatile
    theirs = json.dumps({"schema_version": 1, "sections": {"a": 1}, "volatility": {"old": 1}, "generated_at": "2026-11-13T22:00:00Z"}).encode()
    mine = json.dumps({"schema_version": 1, "sections": {"b": 2}, "volatility": {"summary": 1}, "generated_at": "2026-11-13T22:40:00Z"}).encode()
    out = json.loads(merge_shared("data/manifest.json", "volatility", theirs, mine))
    assert out["sections"] == {"a": 1} and out["volatility"] == {"summary": 1}


def test_validators_reject_bad_documents():
    with pytest.raises(validate.ValidationError):
        validate.validate_vx_term({"schema_version": 1})
    good = {"schema_version": 1, "source": "Cboe", "source_url": "u", "terms_url": "t", "fetched_at": "2026-11-13T22:40:00Z",
            "last_success": "2026-11-13T22:40:00Z", "stale": False, "stale_reason": None, "as_of": "2026-11-13", "positions": 8,
            "slope_positions": 7, "slope_latest": 0.5,
            "curves": [{"id": i, "label": i, "date": "2026-11-13" if i == "latest" else None, "points": []} for i in ("latest", "1m", "6m", "1y")]}
    validate.validate_vx_term(good)
    good["curves"][0]["points"] = [{"pos": 2, "code": "X6", "month": "Nov 2026", "expiry": "2026-11-18", "days": 5, "settle": 18.0}]
    with pytest.raises(validate.ValidationError):
        validate.validate_vx_term(good)


def test_a_lagging_series_is_flagged_like_a_lagging_fund_row(tmp_path, cfg, vcfg):
    seed_markets(tmp_path, cfg)
    base = fake_yahoo()

    def lag(symbol):                                                                   # MOVE stops on Mon 9 Nov: 4 business days behind
        return [b for b in base(symbol) if symbol != "^MOVE" or b[0] <= E("2026-11-09")]
    run_job(tmp_path, cfg, vcfg, synthetic_cboe()[0], yahoo=lag)
    rows = {r["id"]: r for r in read(tmp_path, "volatility/summary.json")["rows"]}
    assert rows["move"]["stale"] is True and rows["move"]["stale_reason"] == "old_close"
    assert rows["vix"]["stale"] is False and rows["skew"]["stale"] is False


def test_archive_last_alone_is_a_stamp_not_a_change():
    from commit_data import normalised
    a = json.dumps({"as_of": "2026-11-12", "archive_last": "2026-11-11", "slope": {"d": [1], "v": [0.4]}}).encode()
    b = json.dumps({"as_of": "2026-11-12", "archive_last": "2026-11-12", "slope": {"d": [1], "v": [0.4]}}).encode()
    p = "data/volatility/vx-history.json"
    assert normalised(p, a, "volatility") == normalised(p, b, "volatility")


# ---- the Yahoo term structure (fallback source, 13 Nov 2026 second request) ---------------------------------------------------
TERM_MONTHS = {"^VIX9D": 0.2957, "^VIX": 0.9856, "^VIX3M": 3, "^VIX6M": 6}
TERM_FIRST = {"^VIX9D": E("2011-01-03"), "^VIX": E("1990-01-02"), "^VIX3M": E("2006-07-17"), "^VIX6M": E("2008-01-02")}


def term_yahoo(today=TODAY):
    """Every horizon = the same wave + 0.5 x its horizon in months, so the slope is exactly 0.5 every day. ^VIX1Y: today's quote only."""
    base = fake_yahoo(today)

    def fetch(symbol):
        if symbol in ("^SKEW", "^MOVE"):
            return base(symbol)
        if symbol == "^VIX1Y":
            return [(today, 22.93)]
        out, d = [], TERM_FIRST[symbol]
        while d <= today:
            if d.weekday() < 5:
                out.append((d, round(15 + 3 * math.sin(d.toordinal() / 50.0) + 0.5 * TERM_MONTHS[symbol], 6)))
            d += timedelta(days=1)
        return out
    return fetch


def with_source(vcfg, source):
    return {**vcfg, "vx_term_source": source}


def test_yahoo_source_builds_the_curves_by_horizon_and_leaves_out_vix1y(tmp_path, cfg, vcfg):
    seed_markets(tmp_path, cfg)
    g = FakeGetter({})
    res = run_job(tmp_path, cfg, with_source(vcfg, "yahoo"), g, yahoo=term_yahoo())
    assert g.log == [], "no request to Cboe when the source is Yahoo"
    assert res["ok"] == 4 and not res["failed"]
    t = read(tmp_path, "volatility/vx-term.json")
    assert t["source"] == "Yahoo Finance" and t["kind"] == "indices" and t["as_of"] == "2026-11-13"
    assert [x["ticker"] for x in t["tenors"]] == ["^VIX9D", "^VIX", "^VIX3M", "^VIX6M"]
    assert t["left_out"][0]["ticker"] == "^VIX1Y" and "1 completed daily value" in t["left_out"][0]["reason"]
    assert [c["date"] for c in t["curves"]] == ["2026-11-13", "2026-10-13", "2026-05-13", "2025-11-13"]
    p = t["curves"][0]["points"]
    assert [x["short"] for x in p] == ["9D", "30D", "3M", "6M"] and [x["pos"] for x in p] == [1, 2, 3, 4]
    assert t["slope_latest"] == 0.5                                                  # least squares against horizon in months
    s = read(tmp_path, "volatility/summary.json")
    assert s["slope_source"] == "yahoo"
    row = next(r for r in s["rows"] if r["id"] == "vx_slope")
    assert row["name"] == "VIX term-structure slope" and "VIX9D, VIX, VIX3M and VIX6M" in row["long"]
    assert row["latest"] == 0.5 and row["changes"]["10Y"]["value"] == 0.0 and row["first_date"] == "2011-01-03"
    assert not (tmp_path / "data" / "volatility" / "vx-history.json").exists()        # nothing to carry: never published


def test_yahoo_slope_matches_a_hand_calculation():
    # horizons 0.2957, 0.9856, 3, 6 months; values 14, 15, 16, 18. mean x = 10.2813/4 = 2.570325, mean y = 15.75.
    # Sxy = sum (x - mx) * y = 0.2957*14 + 0.9856*15 + 3*16 + 6*18 - 4 * 2.570325 * 15.75 = 174.9238 - 161.930475 = 12.993325
    # Sxx = sum x^2 - 4 * mx^2 = 0.08744 + 0.97141 + 9 + 36 - 26.42628 = 19.63257; slope = 12.993325 / 19.63257 = 0.66182
    cfg_t = {"tickers": [{"ticker": k, "label": k, "short": k, "months": m} for k, m in TERM_MONTHS.items()], "min_points": 4,
             "min_history": 1, "range": [5, 150]}
    vals = dict(zip(TERM_MONTHS, (14.0, 15.0, 16.0, 18.0)))
    res = volatility.yahoo_term_update(cfg_t, lambda s: [(TODAY, vals[s])], cutoff=TODAY)
    assert res["slope"][TODAY] == 0.6618


def test_switching_sources_keeps_the_cboe_history_and_back(tmp_path, cfg, vcfg):
    seed_markets(tmp_path, cfg)
    run_job(tmp_path, cfg, vcfg, synthetic_cboe(today=E("2026-11-12"))[0], today=E("2026-11-12"), now=datetime(2026, 11, 12, 22, 40, tzinfo=timezone.utc),
            yahoo=term_yahoo(E("2026-11-12")))
    hist = read(tmp_path, "volatility/vx-history.json")
    run_job(tmp_path, cfg, with_source(vcfg, "yahoo"), FakeGetter({}), yahoo=term_yahoo())
    assert read(tmp_path, "volatility/vx-history.json") == hist                      # waits, unchanged, for a switch back
    assert read(tmp_path, "volatility/vx-term.json")["source"] == "Yahoo Finance"
    g, _, _ = synthetic_cboe()
    run_job(tmp_path, cfg, vcfg, g, yahoo=term_yahoo(), now=datetime(2026, 11, 13, 23, 0, tzinfo=timezone.utc))
    t = read(tmp_path, "volatility/vx-term.json")
    assert t["source"] == "Cboe" and t["kind"] == "futures" and t["as_of"] == "2026-11-13"
    assert read(tmp_path, "volatility/summary.json")["slope_source"] == "cboe"
    assert next(r for r in read(tmp_path, "volatility/summary.json")["rows"] if r["id"] == "vx_slope")["name"] == "VIX futures slope"
    assert len([u for u in g.log if "VX_" in u]) <= 11                                # the incremental rebuild, not the whole archive


def test_an_unknown_source_is_refused(tmp_path, cfg, vcfg):
    seed_markets(tmp_path, cfg)
    with pytest.raises(validate.ValidationError):
        run_job(tmp_path, cfg, with_source(vcfg, "bloomberg"), FakeGetter({}))


def test_the_config_default_is_cboe(vcfg):
    assert vcfg["vx_term_source"] == "cboe"


# ---- after the second review (13 Nov 2026) ----------------------------------------------------------------------------------
def counting(fetch, fail=()):
    calls = []

    def f(symbol):
        calls.append(symbol)
        if symbol in fail:
            raise RuntimeError("simulated failure")
        return fetch(symbol)
    return f, calls


def test_each_yahoo_symbol_is_asked_once_and_3_s_apart(tmp_path, cfg, vcfg):
    seed_markets(tmp_path, cfg)
    f, calls = counting(term_yahoo())
    sleeps = []
    volatility.run(with_source(vcfg, "yahoo"), f, FakeGetter({}), today=TODAY, now=datetime(2026, 11, 13, 22, 40, tzinfo=timezone.utc),
                   data_dir=tmp_path / "data", work_dir=tmp_path / "work", universe=cfg, sleep=sleeps.append)
    assert sorted(calls) == sorted(["^VIX", "^SKEW", "^MOVE", "^VIX9D", "^VIX3M", "^VIX6M", "^VIX1Y"])       # ^VIX once
    assert sleeps == [3.0] * (len(calls) - 1)


def test_an_optional_ticker_that_fails_is_left_out_a_core_one_fails_the_source(tmp_path, cfg, vcfg):
    seed_markets(tmp_path, cfg)
    f, _ = counting(term_yahoo(), fail={"^VIX1Y"})
    res = run_job(tmp_path, cfg, with_source(vcfg, "yahoo"), FakeGetter({}), yahoo=f)
    t = read(tmp_path, "volatility/vx-term.json")
    assert not res["failed"] and "could not be fetched" in t["left_out"][0]["reason"]
    f, _ = counting(term_yahoo(), fail={"^VIX3M"})
    res = run_job(tmp_path, cfg, with_source(vcfg, "yahoo"), FakeGetter({}), yahoo=f)
    assert any("Yahoo VIX term structure" in x for x in res["failed"])
    assert read(tmp_path, "volatility/vx-term.json")["stale"] is True


def test_a_day_counts_only_with_every_horizon(tmp_path):
    cfg_t = {"tickers": [{"ticker": k, "label": k, "short": k, "months": m} for k, m in TERM_MONTHS.items()], "min_points": 4,
             "min_history": 1, "range": [5, 150]}
    d1, d2 = E("2026-11-12"), TODAY
    data = {k: [(d1, 15.0 + m), (d2, 16.0 + m)] for k, m in TERM_MONTHS.items()}
    data["^VIX3M"] = [(d2, 19.0)]                                                     # ^VIX3M missing on 12 Nov
    res = volatility.yahoo_term_update(cfg_t, lambda s: data[s], cutoff=TODAY)
    assert list(res["slope"]) == [d2] and list(res["curves"]) == [d2]


@pytest.mark.parametrize("first,then", [("cboe", "yahoo"), ("yahoo", "cboe")])
def test_after_a_failed_switch_the_source_line_follows_what_is_published(tmp_path, cfg, vcfg, first, then):
    seed_markets(tmp_path, cfg)
    run_job(tmp_path, cfg, with_source(vcfg, first), synthetic_cboe()[0], yahoo=term_yahoo())
    before = read(tmp_path, "volatility/vx-term.json")["source"]
    f, _ = counting(term_yahoo(), fail={"^VIX6M"})
    blocked = FakeGetter({"product/list/VX": b"<!DOCTYPE html><title>Just a moment...</title>"})
    res = run_job(tmp_path, cfg, with_source(vcfg, then), blocked, yahoo=f, now=datetime(2026, 11, 13, 23, 30, tzinfo=timezone.utc))
    assert res["failed"]
    t = read(tmp_path, "volatility/vx-term.json")
    s = read(tmp_path, "volatility/summary.json")
    assert t["source"] == before and t["stale"] is True
    assert s["slope_source"] == first                                                 # the table credits the source shown
    assert next(r for r in s["rows"] if r["id"] == "vx_slope")["stale"] is True


def test_yahoo_older_data_keeps_the_published_file(tmp_path, cfg, vcfg):
    seed_markets(tmp_path, cfg)
    run_job(tmp_path, cfg, with_source(vcfg, "yahoo"), FakeGetter({}), yahoo=term_yahoo())
    res = run_job(tmp_path, cfg, with_source(vcfg, "yahoo"), FakeGetter({}), yahoo=term_yahoo(E("2026-11-12")))
    t = read(tmp_path, "volatility/vx-term.json")
    assert t["as_of"] == "2026-11-13" and t["stale"] is False
    assert any("Yahoo term structure" in n and "older than the published" in n for n in res["notes"])


def test_yahoo_term_document_checks(tmp_path, cfg, vcfg):
    seed_markets(tmp_path, cfg)
    run_job(tmp_path, cfg, with_source(vcfg, "yahoo"), FakeGetter({}), yahoo=term_yahoo())
    t = read(tmp_path, "volatility/vx-term.json")
    validate.validate_vx_term(t)
    bad = {**t, "positions": 5}
    with pytest.raises(validate.ValidationError):
        validate.validate_vx_term(bad)
    with pytest.raises(validate.ValidationError):
        validate.validate_vx_term({**t, "source": "Cboe"})                            # source and kind must agree
