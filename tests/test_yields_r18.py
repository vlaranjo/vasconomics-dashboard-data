"""Round 18 (12 Nov 2026): Poland, Portugal, Russia, Turkey and South Africa from worldgovernmentbonds.com, same adapter.
No network: the pages are rendered HTML from the 12 Nov 2026 run (headless Chromium, browser defaults, 5 s apart), trimmed to
the parts the parser reads (tests/fixtures/yields/wgb/)."""
import json
from datetime import date, datetime, timezone

import pytest

from conftest import FIX
from dashjobs import validate
from dashjobs.yields import job, wgb
from dashjobs.yields.wgb import FakePager

W = FIX / "yields" / "wgb"
TODAY = date(2026, 11, 12)
NOW = datetime(2026, 11, 12, 21, 0, tzinfo=timezone.utc)
SLUG = {"pl": "poland", "pt": "portugal", "ru": "russia", "tr": "turkey", "za": "south-africa"}
HTML = {c: (W / f"{s}.html").read_text(encoding="utf-8") for c, s in SLUG.items()}
URL = {c: wgb.meta(c)["source_url"] for c in wgb.COUNTRIES}

# Which of our 8 tenors the site lists on 12 Nov 2026 (the rest are gaps).
COVERAGE = {
    "pl": ["1M", "1Y", "3Y", "5Y", "10Y"],
    "pt": ["3M", "6M", "1Y", "3Y", "5Y", "10Y", "30Y"],
    "ru": ["1M", "3M", "6M", "1Y", "3Y", "5Y", "10Y"],
    "tr": ["3M", "6M", "3Y", "5Y", "10Y"],
    "za": ["3M", "5Y", "10Y", "30Y"],
}


def doc_for(code, prev=None):
    raw = wgb.fetch(code, FakePager({URL[code]: HTML[code]}), TODAY)
    doc = job.build_doc(code, raw, today=TODAY, now_iso="2026-11-12T21:00:00Z", meta=wgb.meta(code))
    validate.validate_yield(doc, today=TODAY, prev=prev, max_weekly_move_pp=job.max_move({"max_move_pp_country": {"tr": 5.0, "ru": 5.0}}, code))
    return doc


def curves(doc):
    return {c["id"]: c for c in doc["curves"]}


def test_R18_1_the_five_countries_are_site_only_with_their_pages_and_names():
    assert {c: wgb.COUNTRIES[c] for c in SLUG} == {
        "pl": ("poland", "Poland"), "pt": ("portugal", "Portugal"), "ru": ("russia", "Russia"), "tr": ("turkey", "Turkey"),
        "za": ("south-africa", "South Africa")}
    assert URL["za"] == "https://www.worldgovernmentbonds.com/country/south-africa/"
    for c in SLUG:
        assert c in job.NO_OFFICIAL and c in job.COUNTRIES


@pytest.mark.parametrize("code", list(SLUG))
def test_R18_2_coverage_per_country_and_the_rest_are_labelled_gaps(code):
    doc = doc_for(code)
    lat = curves(doc)["latest"]
    assert [t for t in doc["tenors"] if t in lat["points"]] == COVERAGE[code]
    assert set(doc["gaps"]) == set(doc["tenors"]) - set(COVERAGE[code])
    assert doc["gaps"][next(iter(doc["gaps"]))].startswith("World Government Bonds lists no ")
    assert doc["source"] == "World Government Bonds (worldgovernmentbonds.com)" and doc["name"] == wgb.COUNTRIES[code][1]
    assert all(p["kind"] == "D" for p in lat["points"].values())


def test_R18_3_russia_n_a_change_cells_leave_the_one_year_curve_empty_not_guessed():
    page = wgb.parse_page(HTML["ru"])
    assert all(r["Chg 12M"] is None for r in page["rows"])           # the site prints "n.a." in the whole 12M column
    assert wgb._num("n.a.", "bp", "x") is None and wgb._num("N.A.", "bp", "x") is None
    cur = curves(doc_for("ru"))
    assert cur["1y"]["points"] == {}
    assert set(cur["1m"]["points"]) == set(COVERAGE["ru"]) and set(cur["6m"]["points"]) == set(COVERAGE["ru"])
    assert cur["latest"]["date"] == "2026-11-11"                        # Russia's rows are dated 11 Nov on a 12 Nov page
    # Still a layout error for anything else that is not a number
    with pytest.raises(wgb.LayoutChanged):
        wgb._num("n.b.", "bp", "x")


def test_R18_4_turkey_fits_the_wider_range_and_the_wider_weekly_limit():
    cur = curves(doc_for("tr"))
    assert cur["latest"]["points"]["3Y"]["value"] == 35.99
    assert cur["6m"]["points"]["3Y"]["value"] == 40.15                  # 35.99 + 416 bp: above the old 40% cap, below 60
    assert job.max_move({"max_move_pp": 2.0, "max_move_pp_country": {"tr": 5.0}}, "tr") == 5.0
    assert job.max_move({"max_move_pp": 2.0, "max_move_pp_country": {"tr": 5.0}}, "pl") == 2.0
    assert job.max_move({}, "tr") == 2.0
    doc = doc_for("tr")
    prev = json.loads(json.dumps(doc))
    prev["as_of"] = "2026-11-06"
    for p in prev["curves"][0]["points"].values():
        p["value"] = round(p["value"] - 3.0, 3)                        # three points lower a week ago
    validate.validate_yield(doc, today=TODAY, prev=prev, max_weekly_move_pp=5.0)
    with pytest.raises(validate.ValidationError, match="moved"):
        validate.validate_yield(doc, today=TODAY, prev=prev, max_weekly_move_pp=2.0)


def test_R18_5_ten_year_sanity_checks_against_independent_figures():
    """12 Nov 2026 checks (docs/yield-sources.md, round 18). Monthly averages are compared with the site's level a month
    earlier (Last - Chg 1M, dated 12 Oct) and today; daily figures with the same day."""
    pl, pt, ru, za = (curves(doc_for(c)) for c in ("pl", "pt", "ru", "za"))
    # Poland: ECB long-term (convergence) rate, October 2026 average 6.32; the site: 6.382 on 12 Oct, 6.268 on 12 Nov.
    assert pl["1m"]["points"]["10Y"]["value"] == 6.382 and pl["latest"]["points"]["10Y"]["value"] == 6.268
    assert abs(6.32 - (6.382 + 6.268) / 2) < 0.1
    # Portugal: ECB October 2026 average 3.917; the site: 4.014 on 12 Oct, 3.796 on 12 Nov.
    assert pt["1m"]["points"]["10Y"]["value"] == 4.014 and abs(3.917 - (4.014 + 3.796) / 2) < 0.1
    # Russia: Bank of Russia zero-coupon curve, 10 years, 11 Nov 2026: 16.66; the site, same day: 16.755.
    assert ru["latest"]["points"]["10Y"]["value"] == 16.755 and abs(16.755 - 16.66) < 0.15
    # South Africa: OECD long-term rate, October 2026 average 8.94; the site: 8.965 on 12 Oct.
    assert za["1m"]["points"]["10Y"]["value"] == 8.965 and abs(8.965 - 8.94) < 0.1


def test_R18_6_the_job_runs_the_five_one_page_each_and_names_them_in_the_manifest(tmp_path, monkeypatch):
    from test_yields_wgb import run

    cfg = {"countries": list(SLUG), "source": {c: "wgb" for c in SLUG}, "max_move_pp_country": {"ru": 5.0, "tr": 5.0}}
    pager = FakePager({URL[c]: HTML[c] for c in SLUG})
    res = run(tmp_path, monkeypatch, cfg, pager, today=TODAY, now=NOW)
    assert res["ok"] == list(SLUG) and pager.calls == [URL[c] for c in SLUG]
    man = json.loads((tmp_path / "data" / "manifest.json").read_text())
    assert {c: man["yields"][c]["name"] for c in SLUG} == {"pl": "Poland", "pt": "Portugal", "ru": "Russia", "tr": "Turkey",
                                                          "za": "South Africa"}
    # A site-only country cannot be switched to official
    res = run(tmp_path, monkeypatch, {"countries": ["pl", "za"], "source": {"pl": "wgb", "za": "official"}},
              FakePager({URL["pl"]: HTML["pl"]}), today=TODAY, now=NOW)
    assert res["ok"] == ["pl"]
    assert res["failed"] == ["za: South Africa has no official adapter (added from worldgovernmentbonds.com only, round 18); "
                             "set its source to wgb."]
    assert json.loads((tmp_path / "data" / "yields" / "za.json").read_text())["stale"] is True


def test_R18_7_probe_sources_loads_the_five_new_pages_in_the_shared_browser(monkeypatch):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "jobs"))
    import probe_sources as ps

    names = [n for g, n, fn in ps.PROBES if "worldgovernmentbonds.com" in n]
    for country in ("US", "Poland", "Portugal", "Russia", "Turkey", "South Africa"):
        assert any(f" {country} page" in n for n in names), country
    pages = {URL[c]: HTML[c] for c in SLUG} | {URL["tr"]: "<html><head><title>Just a moment...</title></head><body></body></html>"}
    fake = FakePager(pages)
    monkeypatch.setattr(ps, "_WGB", {"pager": fake})
    probes = {n.split(" page")[0].split(".com ")[1]: fn for g, n, fn in ps.PROBES if "worldgovernmentbonds.com" in n}
    st, detail, ok = probes["Portugal"]()
    assert st == 200 and ok and "'3M', '6M', '1Y', '3Y', '5Y', '10Y', '30Y'" in detail
    assert probes["Turkey"]()[0] == 403                                                  # the challenge itself
    st, detail, ok = probes["South Africa"]()                                            # a challenge stops the rest
    assert (st, ok) == ("-", False) and detail.startswith("not requested: ")
    assert ps.WGB_MIN_TENORS == {"us": 6}                                               # the US page must keep 6 of our tenors
    ps.close_wgb()
    assert ps._WGB == {}


def test_R18_8_the_shorter_source_line_is_not_a_switch_of_source_for_the_like_with_like_checks():
    doc = doc_for("pl")
    old = json.loads(json.dumps(doc))
    old["source"] = "World Government Bonds (worldgovernmentbonds.com), data from Investing.com and TradingEconomics"
    assert validate.same_source(old, doc)
    newer = dict(old, as_of="2026-11-13")
    with pytest.raises(validate.ValidationError, match="earlier than the published"):
        validate.validate_yield(doc, today=TODAY, prev=newer)                     # still no going backwards
    jump = json.loads(json.dumps(old))
    jump["as_of"] = "2026-11-06"
    jump["curves"][0]["points"]["10Y"]["value"] = 3.0
    with pytest.raises(validate.ValidationError, match="moved"):
        validate.validate_yield(doc, today=TODAY, prev=jump)                       # still the weekly move check
    official = dict(old, source="Narodowy Bank Polski", source_url="https://nbp.pl/x")
    assert not validate.same_source(official, doc)


def test_R18_9_weekly_run_is_saturday_06_47_utc_after_every_market_has_closed_for_the_week():
    from pathlib import Path

    import yaml

    wf = yaml.safe_load((Path(__file__).resolve().parent.parent / ".github" / "workflows" / "yields.yml").read_text(encoding="utf-8"))
    on = wf.get("on", wf.get(True))                                     # PyYAML reads the key `on` as True
    assert [s["cron"] for s in on["schedule"]] == ["47 6 * * 6"] and "workflow_dispatch" in on


def test_R18_10_the_job_applies_the_per_country_move_limit_from_config(tmp_path, monkeypatch):
    from pathlib import Path

    import yaml
    from test_yields_wgb import run

    cfg_file = yaml.safe_load((Path(__file__).resolve().parent.parent / "config" / "yields.yaml").read_text(encoding="utf-8"))
    assert cfg_file["max_move_pp_country"] == {"ru": 5.0, "tr": 5.0} and cfg_file["max_move_pp"] == 2.0
    base = {"countries": ["pl", "tr"], "source": {"pl": "wgb", "tr": "wgb"}}
    pages = lambda: FakePager({URL["pl"]: HTML["pl"], URL["tr"]: HTML["tr"]})       # noqa: E731
    run(tmp_path, monkeypatch, base, pages(), today=TODAY, now=NOW)
    f = tmp_path / "data" / "yields" / "tr.json"
    original = f.read_text()

    def week_earlier_three_points_lower():
        d = json.loads(original)
        d["as_of"], d["stale"] = "2026-11-06", False
        for p in d["curves"][0]["points"].values():
            p["value"] = round(p["value"] - 3.0, 3)
        f.write_text(json.dumps(d))
    week_earlier_three_points_lower()
    res = run(tmp_path, monkeypatch, base, pages(), today=TODAY, now=NOW)                 # default 2 pp: Turkey refused
    assert res["ok"] == ["pl"] and res["failed"][0].startswith("tr: ") and "moved" in res["failed"][0]
    week_earlier_three_points_lower()
    res = run(tmp_path, monkeypatch, base | {"max_move_pp_country": cfg_file["max_move_pp_country"]}, pages(), today=TODAY, now=NOW)
    assert res["ok"] == ["pl", "tr"]


def test_R18_11_a_stale_site_file_gets_the_new_source_wording_too(tmp_path, monkeypatch):
    from test_yields_wgb import CHALLENGE, run

    cfg = {"countries": ["pl", "pt"], "source": {"pl": "wgb", "pt": "wgb"}}
    run(tmp_path, monkeypatch, cfg, FakePager({URL["pl"]: HTML["pl"], URL["pt"]: HTML["pt"]}), today=TODAY, now=NOW)
    f = tmp_path / "data" / "yields" / "pt.json"
    d = json.loads(f.read_text())
    d["source"] = "World Government Bonds (worldgovernmentbonds.com), data from Investing.com and TradingEconomics"
    d["terms"] = "World Government Bonds: all rights reserved; the site credits Investing.com and TradingEconomics.com for its data."
    f.write_text(json.dumps(d))
    res = run(tmp_path, monkeypatch, cfg, FakePager({URL["pl"]: HTML["pl"], URL["pt"]: CHALLENGE}), today=TODAY, now=NOW)
    assert res["ok"] == ["pl"] and res["failed"][0].startswith("pt: Challenge")
    stale = json.loads(f.read_text())
    assert stale["stale"] is True and stale["source"] == "World Government Bonds (worldgovernmentbonds.com)"
    assert "Investing" not in json.dumps(stale) and stale["curves"] == d["curves"]
