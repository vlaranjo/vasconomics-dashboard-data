"""Round 17 (11 Nov 2026): worldgovernmentbonds.com read in a browser. No network: the pages are saved, rendered HTML from
the Part 1 run (headless Chromium, 11 Nov 2026), trimmed to the parts the parser reads (tests/fixtures/yields/wgb/)."""
import json
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from conftest import FIX, seed_markets
from dashjobs import validate
from dashjobs.yields import core, job, wgb
from dashjobs.yields.core import Raw, Series
from dashjobs.yields.wgb import Challenge, FakePager, LayoutChanged

W = FIX / "yields" / "wgb"
TODAY = date(2026, 11, 11)
NOW = datetime(2026, 11, 11, 21, 30, tzinfo=timezone.utc)
US, DE, CN = ((W / f"{c}.html").read_text(encoding="utf-8") for c in ("united-states", "germany", "china"))
URL = {c: wgb.meta(c)["source_url"] for c in wgb.COUNTRIES}
CHALLENGE = """<!DOCTYPE html><html><head><title>Just a moment...</title></head><body><div id="challenge-stage">
<h1>www.worldgovernmentbonds.com</h1><p>Verify you are human by completing the action below.</p></div></body></html>"""


def doc_for(code, html, prev=None):
    raw = wgb.fetch(code, FakePager({URL[code]: html}), TODAY, prev)
    return job.build_doc(code, raw, today=TODAY, now_iso="2026-11-11T21:30:00Z", meta=wgb.meta(code))


# ---- the calculation ---------------------------------------------------------------------------------------------------

def test_W1_earlier_is_last_minus_change_in_basis_points():
    assert wgb.earlier(4.998, -26.4) == 5.262            # yields fell over the month: the earlier value is higher
    assert wgb.earlier(3.024, 21.4) == 2.81               # yields rose: the earlier value is lower
    assert wgb.earlier(-0.11, 1.0) == -0.12               # negative yields (Switzerland 1M)
    assert wgb.earlier(4.0, 0.0) == 4.0
    assert wgb.earlier(4.0, None) is None and wgb.earlier(None, 5.0) is None      # missing: never guessed


def test_W2_missing_change_leaves_that_tenor_empty_on_that_earlier_curve_only():
    html = US.replace("+29.0 bp", "-", 1)                 # 1 month row: Chg 6M missing
    doc = doc_for("us", html)
    cur = {c["id"]: c for c in doc["curves"]}
    assert "1M" not in cur["6m"]["points"]
    assert cur["1m"]["points"]["1M"]["value"] == 4.022 and cur["1y"]["points"]["1M"]["value"] == 3.956
    assert cur["latest"]["points"]["1M"]["value"] == 3.95


def test_W3_two_real_values_verified_in_part_1_against_official_data():
    """Part 1(b): Last - Chg matched the official value of the earlier date (Last + Chg did not)."""
    us = {c["id"]: c for c in doc_for("us", US)["curves"]}
    de = {c["id"]: c for c in doc_for("de", DE)["curves"]}
    # US 10Y: Last 4.998, Chg 1M -26.4 bp -> 5.262; US Treasury par yield 9 Oct 2026: 5.24.
    assert us["1m"]["points"]["10Y"]["value"] == 5.262 and abs(5.262 - 5.24) < 0.05
    # US 10Y: Chg 12M +92.9 bp -> 4.069; US Treasury 10 Nov 2025: 4.13 (Last + Chg would be 5.927).
    assert us["1y"]["points"]["10Y"]["value"] == 4.069 and abs(4.069 - 4.13) < 0.1
    # Germany 3Y: Last 3.099, Chg 1M -2.7 bp -> 3.126; Bundesbank 3Y 9 Oct 2026: 3.12.
    assert de["1m"]["points"]["3Y"]["value"] == 3.126 and abs(3.126 - 3.12) < 0.05
    # Germany 5Y: Last 3.144, Chg 12M +88.6 bp -> 2.258; Bundesbank 5Y 11 Nov 2025: 2.25.
    assert de["1y"]["points"]["5Y"]["value"] == 2.258 and abs(2.258 - 2.25) < 0.05


# ---- the page -----------------------------------------------------------------------------------------------------------

def test_W4_us_page_parses_to_four_curves_with_dates_kinds_and_labels():
    doc = doc_for("us", US)
    assert doc["as_of"] == "2026-11-11" and doc["source"] == wgb.SOURCE
    assert doc["source"] == "World Government Bonds (worldgovernmentbonds.com), data from Investing.com and TradingEconomics"
    assert doc["source_url"] == "https://www.worldgovernmentbonds.com/country/united-states/"
    cur = {c["id"]: c for c in doc["curves"]}
    assert [c["id"] for c in doc["curves"]] == ["latest", "1m", "6m", "1y"]
    assert [cur[k]["date"] for k in ("latest", "1m", "6m", "1y")] == ["2026-11-11", "2026-10-11", "2026-05-11", "2025-11-11"]
    lat = cur["latest"]["points"]
    assert list(lat) == core.TENORS and lat["10Y"] == {"value": 4.998, "date": "2026-11-11", "kind": "D"}
    assert lat["30Y"] == {"value": 5.358, "date": "2026-11-10", "kind": "D"}        # each row keeps its own date
    p = cur["6m"]["points"]["10Y"]
    assert p == {"value": 4.411, "date": "2026-05-11", "kind": "C",
                 "label": "derived from the site's 6-month change column (latest minus Chg 6M)"}
    assert cur["1m"]["points"]["30Y"]["date"] == "2026-10-10"                        # 10 Nov row: 1 month before its own date
    assert doc["gaps"] == {} and doc["state"]["wgb_page_updated"] == "2026-11-11T00:15Z"
    assert "2 months" in doc["state"]["wgb_other_rows"] and "20 years" in doc["state"]["wgb_other_rows"]
    validate.validate_yield(doc, today=TODAY, prev=None)


def test_W5_germany_and_china_missing_rows_are_gaps():
    de = doc_for("de", DE)
    assert set(de["curves"][0]["points"]) == {"3M", "6M", "1Y", "3Y", "5Y", "10Y", "30Y"}
    assert de["gaps"] == {"1M": "World Government Bonds lists no 1M row for Germany."}
    cn = doc_for("cn", CN)
    assert cn["name"] == "China" and set(cn["curves"][0]["points"]) == {"1Y", "3Y", "5Y", "10Y", "30Y"}
    assert set(cn["gaps"]) == {"1M", "3M", "6M"}
    for d in (de, cn):
        validate.validate_yield(d, today=TODAY, prev=None)


def test_W6_row_date_without_year_is_read_against_the_page_update_date():
    assert wgb._row_date("10 Nov", date(2026, 11, 11)) == date(2026, 11, 10)
    assert wgb._row_date("30 Dec", date(2027, 1, 2)) == date(2026, 12, 30)


@pytest.mark.parametrize("change,match", [
    (lambda h: h.replace('id="table-curve"', 'id="table-curve-v2"'), "no yield-curve table"),
    (lambda h: h.replace(">Chg 1M<", ">1M Chg<", 1), "header changed"),
    (lambda h: h.replace(">Annualized Yield<", ">Yield to Maturity<", 1), "header changed"),
    (lambda h: h.replace("-26.4 bp", "-0.264 %", 1), "not a number in 'bp'"),
    (lambda h: h.replace("4.998%", "4.998", 1), "not a number in '%'"),
    (lambda h: h.replace("GMT+0", "CET"), "Last Update"),
])
def test_W7_a_layout_change_is_a_clear_error(change, match):
    with pytest.raises(LayoutChanged, match=match):
        wgb.parse_page(change(US))


def test_W8_challenge_pages_and_refusals_are_recognised_and_normal_pages_are_not():
    assert wgb.challenge_reason(CHALLENGE) == "challenge text on the page ('just a moment')"
    assert "verify you are human" in wgb.challenge_reason(CHALLENGE.replace("Just a moment...", "Security check"))
    assert wgb.challenge_reason("<html><body>ok</body></html>", status=403) == "HTTP 403 on the page"
    assert wgb.challenge_reason("<html><body>ok</body></html>", status=200, api_statuses=[403]) == \
        "HTTP 403 on the page's own data request (/wp-json/country/v1/main)"
    assert wgb.challenge_reason(US, 200, [200]) is None and wgb.challenge_reason(DE) is None


def test_W9_browser_pager_waits_five_seconds_between_pages_and_stops_at_the_first_challenge(monkeypatch):
    slept, t = [], [100.0]
    pg = wgb.BrowserPager(sleep=lambda s: (slept.append(round(s, 1)), t.__setitem__(0, t[0] + s)), clock=lambda: t[0])
    pages = iter([US, CHALLENGE])

    class P:
        def goto(self, url, **kw):
            t[0] += 1.0
            return SimpleNamespace(status=200)

        def wait_for_function(self, *a, **kw):
            pass

        def content(self):
            return next(pages)
    pg._page = P()
    assert pg.load("u1") == US
    with pytest.raises(Challenge):
        pg.load("u2")
    assert slept == [5.0] and pg.loads == 2                    # 5 s from the end of one load to the start of the next
    with pytest.raises(Challenge, match="run stopped at a challenge page"):
        pg.load("u3")
    assert pg.loads == 2                                       # nothing more was loaded


# ---- the job -------------------------------------------------------------------------------------------------------------

def stub(code, value=3.0):
    def fetch(g, today, env=None, prev=None):
        raw = Raw()
        for t in core.TENORS:
            raw.series[t] = [Series("D", [(date(2026, 11, 10), value), (date(2025, 11, 10), value - 1)], max_lag=5)]
        return raw
    return SimpleNamespace(fetch=fetch, META={"name": code.upper(), "source": "stub official", "source_url": "https://x", "terms": "t"})


def run(tmp_path, monkeypatch, cfg, pager, today=TODAY, now=NOW, stubs=None):
    stubs = stubs or {}
    monkeypatch.setattr(job, "adapter", lambda code: stubs[code])
    uni = yaml.safe_load((FIX / "config" / "universe_m1.yaml").read_text(encoding="utf-8"))
    if not (tmp_path / "data" / "manifest.json").exists():
        seed_markets(tmp_path, uni)
    return job.run(cfg, None, today=today, now=now, data_dir=tmp_path / "data", work_dir=tmp_path / "work", env={},
                   universe=uni, pager=pager)


CFG = {"countries": ["us", "de", "cn"], "source": {"us": "wgb", "de": "wgb", "cn": "wgb"}}


def test_W10_job_publishes_wgb_countries_china_included(tmp_path, monkeypatch):
    pager = FakePager({URL["us"]: US, URL["de"]: DE, URL["cn"]: CN})
    res = run(tmp_path, monkeypatch, CFG, pager)
    assert res["ok"] == ["us", "de", "cn"] and pager.calls == [URL["us"], URL["de"], URL["cn"]]
    man = json.loads((tmp_path / "data" / "manifest.json").read_text())
    assert man["yields"]["cn"] == {"path": "yields/cn.json", "as_of": "2026-11-11", "stale": False, "status": "ok", "name": "China"}


def test_W11_a_challenge_stops_every_later_page_load_and_those_countries_keep_their_last_good_file(tmp_path, monkeypatch):
    run(tmp_path, monkeypatch, CFG, FakePager({URL["us"]: US, URL["de"]: DE, URL["cn"]: CN}))
    good = json.loads((tmp_path / "data" / "yields" / "cn.json").read_text())
    cfg = {"countries": ["us", "de", "jp", "cn"], "source": {"us": "wgb", "de": "wgb", "jp": "official", "cn": "wgb"}}
    pager = FakePager({URL["us"]: US, URL["de"]: CHALLENGE, URL["cn"]: CN})
    res = run(tmp_path, monkeypatch, cfg, pager, stubs={"jp": stub("jp")})
    assert pager.calls == [URL["us"], URL["de"]]                       # China's page was never requested
    assert res["ok"] == ["us", "jp"]                                    # official sources still run
    assert res["failed"][0].startswith("de: Challenge: challenge text on the page")
    assert res["failed"][1].startswith("cn: Challenge: not loaded: the run stopped at a challenge page")
    cn = json.loads((tmp_path / "data" / "yields" / "cn.json").read_text())
    assert cn["stale"] is True and cn["curves"] == good["curves"]
    st = json.loads((tmp_path / "data" / "status.json").read_text())["sources"]["yield_curves"]
    assert st["stale"] is True and len(st["failed"]) == 2


def test_W12_a_layout_change_fails_that_country_only(tmp_path, monkeypatch):
    bad = DE.replace(">Chg 1M<", ">1M Chg<", 1)
    res = run(tmp_path, monkeypatch, CFG, FakePager({URL["us"]: US, URL["de"]: bad, URL["cn"]: CN}))
    assert res["ok"] == ["us", "cn"] and res["failed"][0].startswith("de: LayoutChanged: yield-curve table header changed")
    assert not (tmp_path / "data" / "yields" / "de.json").exists()      # no earlier file: nothing published for it


def test_W13_every_wgb_country_challenged_publishes_nothing(tmp_path, monkeypatch):
    with pytest.raises(job.NothingFetched, match="Challenge"):
        run(tmp_path, monkeypatch, CFG, FakePager({URL["us"]: CHALLENGE}))


def test_W14_source_switch_one_line_back_to_official_and_state_survives(tmp_path, monkeypatch):
    run(tmp_path, monkeypatch, {"countries": ["us"], "source": {"us": "official"}}, FakePager({}), stubs={"us": stub("us", 4.5)})
    off = json.loads((tmp_path / "data" / "yields" / "us.json").read_text())
    assert off["source"] == "stub official" and [c["id"] for c in off["curves"]] == ["latest", "1m", "6m", "1y"]
    run(tmp_path, monkeypatch, {"countries": ["us"], "source": {"us": "wgb"}}, FakePager({URL["us"]: US}))
    doc = json.loads((tmp_path / "data" / "yields" / "us.json").read_text())
    assert doc["source"] == wgb.SOURCE and doc["stale"] is False
    # China cannot be switched to official; an unknown source word is refused
    res = run(tmp_path, monkeypatch, {"countries": ["us", "cn"], "source": {"us": "wgb", "cn": "official"}},
              FakePager({URL["us"]: US}))
    assert res["failed"] == ["cn: China has no official adapter (ChinaBond and CFETS terms forbid reuse); set its source to wgb."]
    with pytest.raises(job.NothingFetched, match="unknown source 'wbg' for us"):
        run(tmp_path, monkeypatch, {"countries": ["us"], "source": {"us": "wbg"}}, FakePager({}), stubs={"us": stub("us")})


def test_W15_official_state_is_kept_through_wgb_runs():
    prev = {"auction_log": [{"date": "2026-10-29"}], "seen": ["x"], "wgb_page_updated": "old"}
    raw = wgb.raw_from_page("it", wgb.parse_page(US), prev)
    assert raw.extra["auction_log"] == [{"date": "2026-10-29"}] and raw.extra["seen"] == ["x"]
    assert raw.extra["wgb_page_updated"] == "2026-11-11T00:15Z"


def test_W16_no_going_backwards_from_the_same_source_but_a_switch_may():
    doc = doc_for("us", US)
    newer = dict(doc, as_of="2026-11-12")
    with pytest.raises(validate.ValidationError, match="earlier than the published"):
        validate.validate_yield(doc, today=TODAY, prev=newer)
    validate.validate_yield(doc, today=TODAY, prev=dict(newer, source="US Department of the Treasury"))


def test_W17_config_switches_every_country_to_wgb_and_lists_china():
    root = Path(__file__).resolve().parent.parent
    cfg = yaml.safe_load((root / "config" / "yields.yaml").read_text(encoding="utf-8"))
    assert cfg["countries"] == ["us", "uk", "ca", "jp", "de", "es", "ch", "br", "fr", "it", "au", "in", "cn"]
    assert cfg["source"] == {c: "wgb" for c in cfg["countries"]}
    assert set(cfg["countries"]) == set(wgb.COUNTRIES)


# ---- after the fresh-context review ----------------------------------------------------------------------------------------

def test_W18_a_normal_page_mentioning_recaptcha_or_access_denied_is_not_a_challenge():
    footer = '<footer><p>This site is protected by reCAPTCHA. Access denied pages are logged.</p></footer></body>'
    html = US.replace("</body>", footer)
    assert wgb.challenge_reason(html, 200, [200]) is None                 # the yield table is there: only the title counts
    assert wgb.challenge_reason(html.replace("<title>", "<title>Just a moment... ")) is not None
    no_table = html.replace('id="table-curve"', 'id="gone"')
    assert "captcha" in wgb.challenge_reason(no_table)                       # no table: the text counts


def test_W19_only_the_tables_own_data_request_is_watched():
    pg = wgb.BrowserPager()
    handlers = []
    pg._page = SimpleNamespace(on=lambda ev, fn: handlers.append(fn))
    pg._page.on("response", lambda r: pg._api.append(r.status) if wgb.DATA_ENDPOINT in r.url else None)
    for url, st in (("https://www.worldgovernmentbonds.com/wp-json/wp/v2/users/me", 401),
                    ("https://www.worldgovernmentbonds.com/wp-json/country/v1/main", 200)):
        handlers[0](SimpleNamespace(url=url, status=st))
    assert pg._api == [200]


def test_W20_row_dated_a_day_after_the_gmt_update_date_stays_this_year():
    assert wgb._row_date("11 Nov", date(2026, 11, 10)) == date(2026, 11, 11)
    assert wgb._row_date("13 Nov", date(2026, 11, 10)) == date(2025, 11, 13)


def test_W21_thousands_separator_in_a_change_cell():
    assert wgb._num("+1,050.0 bp", "bp", "x") == 1050.0 and wgb._num("-7.2 bp", "bp", "x") == -7.2
    with pytest.raises(LayoutChanged):
        wgb._num("1.050,0 bp", "bp", "x")


def test_W22_a_browser_that_cannot_start_fails_fast_and_is_cleaned_up(monkeypatch):
    import playwright.sync_api as sa
    started = []

    class PW:
        def start(self):
            started.append(1)
            return SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kw: (_ for _ in ()).throw(OSError("no chromium"))),
                                   stop=lambda: started.append("stopped"))
    monkeypatch.setattr(sa, "sync_playwright", lambda: PW())
    pg = wgb.BrowserPager()
    with pytest.raises(RuntimeError, match="could not start: OSError: no chromium"):
        pg.load("u1")
    with pytest.raises(RuntimeError, match="could not start"):
        pg.load("u2")
    assert started == [1, "stopped"] and pg.loads == 0                     # started once, stopped, never retried


def test_W23_the_job_opens_the_browser_only_for_wgb_countries_and_always_closes_it(tmp_path, monkeypatch):
    made = []

    class P(FakePager):
        def __init__(self):
            super().__init__({URL["us"]: US, URL["de"]: CHALLENGE})
            self.closed = 0
            made.append(self)

        def close(self):
            self.closed += 1
            raise RuntimeError("will not close")                          # must not cost the run its results
    uni = yaml.safe_load((FIX / "config" / "universe_m1.yaml").read_text(encoding="utf-8"))
    seed_markets(tmp_path, uni)
    monkeypatch.setattr(job, "adapter", lambda code: stub(code))
    res = job.run({"countries": ["jp"], "source": {"jp": "official"}}, None, today=TODAY, now=NOW, data_dir=tmp_path / "data",
                  work_dir=tmp_path / "work", env={}, universe=uni, pager_factory=P)
    assert res["ok"] == ["jp"] and made == []                              # no wgb country: no browser
    res = job.run({"countries": ["us", "de"], "source": {"us": "wgb", "de": "wgb"}}, None, today=TODAY, now=NOW,
                  data_dir=tmp_path / "data", work_dir=tmp_path / "work", env={}, universe=uni, pager_factory=P)
    assert res["ok"] == ["us"] and len(made) == 1 and made[0].closed == 1


def test_W24_the_weekly_move_check_compares_like_with_like():
    doc = doc_for("us", US)
    old = json.loads(json.dumps(doc))
    for p in old["curves"][0]["points"].values():
        p["value"] -= 2.5
    with pytest.raises(validate.ValidationError, match="moved"):
        validate.validate_yield(doc, today=TODAY, prev=old)
    validate.validate_yield(doc, today=TODAY, prev=dict(old, source="US Department of the Treasury"))
