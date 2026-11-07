"""The production configs (config/universe.yaml, config/pe_index_map.yaml): decided fund changes applied, shape, and one
full offline run of the markets job over all sections with synthetic prices (no network)."""
import json
import random
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from dashjobs import markets, validate

ROOT = Path(__file__).resolve().parent.parent
PAGES = {"asset-classes", "countries-regions", "us-majors-factors", "us-sectors", "eu-sectors", "fixed-income", "commodities", "fx"}


@pytest.fixture(scope="module")
def prod():
    return yaml.safe_load((ROOT / "config" / "universe.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def pe_prod():
    return yaml.safe_load((ROOT / "config" / "pe_index_map.yaml").read_text(encoding="utf-8"))


def rows_of(prod, section):
    return {r["ticker"]: r for s in prod["sections"] if s["id"] == section for r in s["rows"]}


def test_U1_shape_every_page_has_sections_and_every_fund_row_is_complete(prod):
    assert {s["page"] for s in prod["sections"]} == PAGES
    assert [s["id"] for s in prod["sections"]] == [
        "asset-classes", "equity-regions", "equity-countries", "us-majors", "us-factors", "us-sectors", "eu-sectors",
        "fixed-income", "commodity-sectors", "commodity-components", "fx"]
    assert sum(len(s["rows"]) for s in prod["sections"]) == 112
    for s in prod["sections"]:
        ids = [r["id"] for r in s["rows"]]
        assert len(ids) == len(set(ids)), s["id"]
        if s.get("kind") == "fx":
            continue
        for r in s["rows"]:
            assert re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}\d", r["isin"]), (r["ticker"], r["isin"])
            assert r["provider"] and r["holds"] and isinstance(r["acc"], bool) and isinstance(r["hedged"], bool), r["ticker"]
            assert r["currency"] == "EUR"
            assert re.fullmatch(r"[A-Z0-9]+\.(DE|MI|PA|AS|F)", r["ticker"]), r["ticker"]


def test_U2_fx_section_has_the_18_pairs_of_the_old_app(prod):
    fx = next(s for s in prod["sections"] if s["id"] == "fx")
    assert fx["kind"] == "fx" and len(fx["rows"]) == 18
    assert [r["ticker"] for r in fx["rows"]] == [f"EUR{c}=X" for c in
        "USD GBP CHF HUF PLN NOK SEK JPY CNY AUD NZD INR CAD BRL MXN CLP COP ZAR".split()]


def test_U3_every_decided_fund_change_is_applied_where_it_was_decided_and_nowhere_else(prod):
    all_tickers = {r["ticker"] for s in prod["sections"] for r in s["rows"]}
    page_of = {r["ticker"]: set() for s in prod["sections"] for r in s["rows"]}
    for s in prod["sections"]:
        for r in s["rows"]:
            page_of[r["ticker"]].add(s["page"])
    for c in prod["m2_fund_changes"]:
        assert c["to"] in all_tickers, c
        assert page_of[c["to"]] & set(c["pages"]), c                  # the new fund appears on a page the change covers
        if c["from"] in page_of:                                    # the old ticker may survive only on a page the change does not cover
            assert not page_of[c["from"]] & set(c["pages"]), (c["from"], page_of[c["from"]])
    for old in ("36BZ.DE", "IBC4.F", "VECP.DE", "SPYJ.DE", "XAD5.MI", "NICK.MI", "PHAG.MI", "AIGI.MI", "BRNT.MI", "COTN.MI"):
        assert old not in all_tickers, old
    assert "SXR8.DE" in rows_of(prod, "us-majors") and "SXR8.DE" not in rows_of(prod, "equity-countries")
    assert "IBCF.DE" in rows_of(prod, "equity-countries")
    assert "XCS6.DE" in rows_of(prod, "equity-countries") and "IBC4.DE" in rows_of(prod, "equity-countries")
    assert rows_of(prod, "equity-countries")["LYP6.DE"]["label"] == "STOXX Europe 600"
    assert rows_of(prod, "commodity-components")["ESVR.MI"]["holds"] == "Silver (futures, EUR-hedged)"
    assert rows_of(prod, "commodity-components")["XAD1.DE"]["label"] == "Gold"
    assert rows_of(prod, "asset-classes")["XAD1.DE"]["hedged"] is True and "EPRA.PA" in rows_of(prod, "asset-classes")
    assert rows_of(prod, "us-factors")["SPYD.DE"]["acc"] is False                      # decided: stays Dist
    assert "VECA.DE" in rows_of(prod, "fixed-income")
    assert {e["ticker"] for e in prod["validation"]["jump_exceptions"]} == {"ENIK.MI"}


def test_U4_pe_map_has_all_34_indices_of_the_old_script_plus_nasdaq_and_dow(pe_prod):
    idx = pe_prod["indices"]
    slugs = [i["slug"] for i in idx]
    assert len(slugs) == len(set(slugs)) == 34 and len({i["url"] for i in idx}) == 34
    assert {"nasdaq-100", "dow-jones", "sp-500", "united-states"} <= set(slugs)
    assert sum(i["slug"].startswith("sp-500-") for i in idx) == 11                      # the 11 GICS sectors
    for i in idx:
        assert set(i["pages"]) <= PAGES and i["url"].startswith("https://worldperatio.com/"), i
    on = lambda p: {i["slug"] for i in idx if p in i["pages"]}                          # noqa: E731
    assert on("us-majors-factors") == {"sp-500", "united-states", "nasdaq-100", "dow-jones"}
    assert len(on("us-sectors")) == 12 and "sp-500" in on("us-sectors")
    assert on("eu-sectors") == set() and on("fixed-income") == set() and on("fx") == set()


def _bars(ticker, today, years=12):
    rnd = random.Random(sum(map(ord, ticker)))
    d, v, out = today - timedelta(days=int(365.25 * years)), 100.0, []
    while d < today:
        if d.weekday() < 5:
            v *= 1 + rnd.uniform(-0.01, 0.0105)
            out.append((d, round(v, 4)))
        d += timedelta(days=1)
    return out


def test_U5_full_offline_run_publishes_all_sections_and_fetches_each_ticker_once(prod, tmp_path):
    today = date(2026, 11, 6)
    calls = []

    def fetch(t):
        calls.append(t)
        return _bars(t, today)

    res = markets.run(prod, fetch, today=today, now=datetime(2026, 11, 6, 22, 40, tzinfo=timezone.utc), data_dir=tmp_path / "data",
                      work_dir=tmp_path / "work", sleep=lambda s: None)
    all_tickers = [r["ticker"] for s in prod["sections"] for r in s["rows"]]
    assert res["n_total"] == 112 and res["n_fresh"] == 112 and not res["failed"]
    assert len(calls) == len(set(all_tickers)) == 109 and sorted(calls) == sorted(set(all_tickers))   # shared tickers fetched once
    man = json.loads((tmp_path / "data" / "manifest.json").read_text())
    assert set(man["sections"]) == {s["id"] for s in prod["sections"]} and "m1-demo" not in man["sections"]
    fx = json.loads((tmp_path / "data" / "sections" / "fx.json").read_text())
    assert fx["kind"] == "fx" and fx["page"] == "fx" and "isin" not in fx["rows"][0] and len(fx["rows"]) == 18
    reg = json.loads((tmp_path / "data" / "sections" / "equity-regions.json").read_text())
    assert reg["rows"][0]["holds"] and reg["rows"][0]["isin"]


def test_U6_old_demo_section_is_dropped_from_the_manifest_but_other_runs_keep_carry_forward(prod, tmp_path):
    today = date(2026, 11, 6)
    data = tmp_path / "data"
    (data / "sections").mkdir(parents=True)
    (data / "manifest.json").write_text(json.dumps({"schema_version": 1, "generated_at": "2026-11-05T00:00:00Z", "status": "status.json",
        "sections": {"m1-demo": {"path": "sections/m1-demo.json", "as_of": "2026-11-04"}}, "pe": {}}))
    kw = dict(today=today, data_dir=data, work_dir=tmp_path / "work", sleep=lambda s: None)
    markets.run(prod, lambda t: _bars(t, today), now=datetime(2026, 11, 6, 22, 40, tzinfo=timezone.utc), **kw)
    bad = {"EWAT.MI"}

    def fetch(t):
        if t in bad:
            raise RuntimeError("down")
        return _bars(t, today)
    res = markets.run(prod, fetch, now=datetime(2026, 11, 7, 22, 40, tzinfo=timezone.utc), **kw)
    sec = json.loads((data / "sections" / "commodity-components.json").read_text())
    row = next(r for r in sec["rows"] if r["ticker"] == "EWAT.MI")
    assert row["stale"] is True and row["stale_reason"] == "fetch_failed" and res["failed"] and "m1-demo" not in json.loads((data / "manifest.json").read_text())["sections"]


def test_U7_a_fund_row_without_its_reference_fields_is_rejected_but_an_fx_row_is_fine():
    row = {"id": "a", "label": "A", "ticker": "A.DE", "currency": "EUR", "first_close": "2020-01-01", "last_close": "2026-11-05", "stale": False,
           "stale_reason": None, "last_success": "2026-11-06T00:00:00Z", "returns": {"1D": {"value": 1.0, "start": "2026-11-04", "status": "ok"}}}
    sec = {"schema_version": 1, "section": "s", "title": "S", "generated_at": "2026-11-06T00:00:00Z", "as_of": "2026-11-05",
           "lookbacks": ["1D"], "rows": [row]}
    kw = dict(run_date=date(2026, 11, 6), prev_as_of=None, n_fresh=1, n_total=1, min_fresh_fraction=0.5, max_close_age_days=5,
              max_abs_1d_pct=25, fresh_ids={"a"})
    with pytest.raises(validate.ValidationError, match="isin"):
        validate.validate_section(sec, **kw)
    validate.validate_section({**sec, "kind": "fx"}, **kw)


def test_U8_a_ticker_that_fails_once_is_retried_after_a_cool_down_and_published_fresh(prod, tmp_path):
    today = date(2026, 11, 6)
    seen, sleeps = {}, []

    def fetch(t):
        seen[t] = seen.get(t, 0) + 1
        if t in ("IBCG.DE", "LKOR.DE") and seen[t] == 1:
            raise RuntimeError("Too Many Requests")
        return _bars(t, today)

    res = markets.run(prod, fetch, today=today, now=datetime(2026, 11, 6, 22, 40, tzinfo=timezone.utc), data_dir=tmp_path / "data",
                      work_dir=tmp_path / "work", sleep=sleeps.append, delay=3, retry_wait=20)
    assert res["n_fresh"] == 112 and res["failed"] == [] and seen["IBCG.DE"] == 2 and seen["LKOR.DE"] == 2
    assert 20 in sleeps                                                   # the cool-down happened
    sec = json.loads((tmp_path / "data" / "sections" / "equity-countries.json").read_text())
    assert [r["ticker"] for r in sec["rows"]][:6] == ["IBCF.DE", "LYP6.DE", "SXRW.DE", "18MN.DE", "IBCG.DE", "SAUS.MI"]   # config order kept
    assert not any(r["stale"] for r in sec["rows"])


def test_U9_a_jump_older_than_the_ten_year_window_is_ignored_but_a_recent_one_is_not(prod, tmp_path):
    today = date(2026, 11, 6)

    def fetch(t):
        bars = _bars(t, today, years=17)
        if t in ("IBCJ.DE", "SXR1.DE"):
            i = 40 if t == "IBCJ.DE" else len(bars) - 60              # IBCJ: ~2009 (outside the window); SXR1: 2026 (inside)
            d, c = bars[i]
            bars[i:] = [(dd, cc * 0.7) for dd, cc in bars[i:]]
        return bars
    res = markets.run(prod, fetch, today=today, now=datetime(2026, 11, 6, 22, 40, tzinfo=timezone.utc), data_dir=tmp_path / "data",
                      work_dir=tmp_path / "work", sleep=lambda s: None, retry_wait=0)
    assert [f.split(":")[0] for f in res["failed"]] == ["SXR1.DE"] and "above 25.0%" in res["failed"][0]


def test_U10_a_row_with_an_old_close_does_not_mark_the_whole_run_stale(prod, tmp_path):
    today = date(2026, 11, 6)

    def fetch(t):
        bars = _bars(t, today)
        return bars[:-3] if t == "MUNI.MI" else bars                      # last close three sessions behind the rest
    markets.run(prod, fetch, today=today, now=datetime(2026, 11, 6, 22, 40, tzinfo=timezone.utc), data_dir=tmp_path / "data",
                work_dir=tmp_path / "work", sleep=lambda s: None)
    st = json.loads((tmp_path / "data" / "status.json").read_text())
    sec = json.loads((tmp_path / "data" / "sections" / "fixed-income.json").read_text())
    assert next(r for r in sec["rows"] if r["ticker"] == "MUNI.MI")["stale_reason"] == "old_close"
    assert st["sources"]["yahoo_markets"]["stale"] is False


def test_U_default_visible_rules(prod):
    """Sections with more than 8 funds name at most 8 series switched on by default, all among the first 10 positions
    (the 10 fixed hues, so the default lines never share a hue or need a dash)."""
    for s in prod["sections"]:
        ids = [r["id"] for r in s["rows"]]
        dv = s.get("default_visible")
        if len(ids) <= 8:
            assert dv is None or set(dv) <= set(ids)
            continue
        assert dv and len(dv) <= 8 and len(set(dv)) == len(dv), s["id"]
        assert all(i in ids[:10] for i in dv), s["id"]
