"""Fixed-income characteristics (21 Nov 2026). Fixtures: the issuers' real pages as saved on 21 Nov 2026 (gzip), never fetched by tests."""
import copy
import gzip
import json
from datetime import date, datetime, timezone

import pytest
import yaml

from conftest import FIX, ROOT

from dashjobs import characteristics as ch
from dashjobs import validate
from dashjobs.yields.http import FakeGetter

PAGES = {k: gzip.decompress((FIX / "characteristics" / f"{k}.html.gz").read_bytes())
         for k in ("ssga_sybt", "ssga_spfa", "vanguard_vgea", "vanguard_veca")}
TODAY = date(2026, 11, 21)
NOW = datetime(2026, 11, 21, 7, 20, tzinfo=timezone.utc)


@pytest.fixture
def cfgs(tmp_path):
    """The real configs; the universe reduced to the Fixed Income section, whose published entries are seeded (every job validates the
    complete manifest it merges into)."""
    c = yaml.safe_load((ROOT / "config" / "characteristics.yaml").read_text(encoding="utf-8"))
    u = yaml.safe_load((ROOT / "config" / "universe.yaml").read_text(encoding="utf-8"))
    u = {**u, "sections": [s for s in u["sections"] if s["id"] == "fixed-income"]}
    data = tmp_path / "data"
    for rel in ("sections/fixed-income.json", "history/fixed-income.json"):
        (data / rel).parent.mkdir(parents=True, exist_ok=True)
        (data / rel).write_text('{"schema_version": 1}')
    (data / "manifest.json").write_text(json.dumps({
        "schema_version": 1, "generated_at": "2026-11-20T22:40:00Z", "status": "status.json", "pe": {},
        "sections": {"fixed-income": {"path": "sections/fixed-income.json", "as_of": "2026-11-20"}},
        "history": {"fixed-income": {"path": "history/fixed-income.json", "as_of": "2026-11-20"}}}))
    return c, u


def routes(**over):
    r = {"-sybt-gy": PAGES["ssga_sybt"], "-spfa-gy": PAGES["ssga_spfa"], "/9591/": PAGES["vanguard_vgea"], "/9695/": PAGES["vanguard_veca"]}
    r.update(over)
    return r


def run(cfgs, tmp_path, getter, today=TODAY, now=NOW):
    c, u = cfgs
    return ch.run(c, u, getter, today=today, now=now, data_dir=tmp_path / "data", work_dir=tmp_path / "w")


def doc(tmp_path):
    return json.loads((tmp_path / "data" / "characteristics" / "fixed-income.json").read_text(encoding="utf-8"))


# ---- adapters on the real pages ----------------------------------------------------------------------------------------------
def test_C1_state_street_pages():
    s = ch.parse_ssga(PAGES["ssga_sybt"], "IE00B44CND37")
    assert s == {"ytm": {"value": 4.95, "as_of": "2026-11-19", "name": "Yield to Maturity"},
                 "duration": {"value": 5.55, "as_of": "2026-11-19", "name": "Effective Duration"}}
    s = ch.parse_ssga(PAGES["ssga_spfa"], "IE00BFWFPY67")
    assert (s["ytm"]["value"], s["duration"]["value"], s["ytm"]["as_of"]) == (6.55, 6.15, "2026-11-19")


def test_C2_vanguard_pages_take_the_fund_not_the_benchmark():
    v = ch.parse_vanguard(PAGES["vanguard_vgea"], "IE00BH04GL39")
    assert v["ytm"]["as_of"] == v["duration"]["as_of"] == v["rating"]["as_of"] == "2026-10-31"
    assert round(v["ytm"]["value"], 4) == 3.8623 and round(v["duration"]["value"], 4) == 6.7934 and v["rating"]["value"] == "A+"
    v = ch.parse_vanguard(PAGES["vanguard_veca"], "IE00BGYWT403")
    assert round(v["ytm"]["value"], 4) == 4.2712 and round(v["duration"]["value"], 4) == 4.3783 and v["rating"]["value"] == "A-"
    assert "oas" not in v


def test_C3_layout_changes_and_a_wrong_fund_are_detected():
    with pytest.raises(ch.LayoutError, match="Fund Characteristics"):
        ch.parse_ssga(PAGES["ssga_sybt"].replace(b"Fund Characteristics", b"Key Figures"), "IE00B44CND37")
    with pytest.raises(ch.LayoutError, match="Yield to Maturity"):
        ch.parse_ssga(PAGES["ssga_sybt"].replace(b"Yield to Maturity", b"Yield to Worst"), "IE00B44CND37")
    with pytest.raises(ch.LayoutError, match="not a number"):
        ch.parse_ssga(PAGES["ssga_sybt"].replace(b"<td class=\"data\">5.55</td>", b"<td class=\"data\">-</td>"), "IE00B44CND37")
    with pytest.raises(ch.LayoutError, match="ISIN"):
        ch.parse_ssga(PAGES["ssga_sybt"], "IE00BFWFPY67")                   # the SPFA ISIN on the SYBT page
    with pytest.raises(ch.LayoutError, match="YLDMAT"):
        ch.parse_vanguard(PAGES["vanguard_vgea"].replace(b'"YLDMAT"', b'"YLDMAT2"'), "IE00BH04GL39")
    with pytest.raises(ch.LayoutError, match="serverApp-state"):
        ch.parse_vanguard(PAGES["vanguard_vgea"].replace(b'id="serverApp-state"', b'id="state"'), "IE00BH04GL39")
    with pytest.raises(ch.LayoutError, match="ISIN"):
        ch.parse_vanguard(PAGES["vanguard_vgea"], "IE00BGYWT403")


# ---- the job -----------------------------------------------------------------------------------------------------------------
def test_C4_job_publishes_every_fund_with_values_or_reasons_and_asks_only_enabled_issuers(cfgs, tmp_path):
    g = FakeGetter(routes())
    res = run(cfgs, tmp_path, g)
    assert res["ok"] == res["tried"] == 4 and not res["problems"]
    assert len(g.log) == 4 and not any("ishares" in u or "invesco" in u for u in g.log)
    d = doc(tmp_path)
    by = {f["id"]: f for f in d["funds"]}
    assert [f["id"] for f in d["funds"]] == ["sybt", "vgea", "iust", "ibci", "iglt", "spfa", "ibcd", "ihyu", "veca", "ihyg", "qdvp", "muni"]
    assert by["sybt"]["measures"]["ytm"] == {"value": 4.95, "as_of": "2026-11-19", "name": "Yield to Maturity"}
    assert by["sybt"]["measures"]["oas"]["value"] is None and "does not publish an option-adjusted spread" in by["sybt"]["measures"]["oas"]["reason"]
    assert "breakdown of this fund by rating" in by["spfa"]["measures"]["rating"]["reason"]
    assert by["vgea"]["measures"]["rating"]["value"] == "A+" and by["vgea"]["measures"]["duration"]["value"] == 6.79
    assert by["vgea"]["as_of"] == "2026-10-31" and by["sybt"]["as_of"] == "2026-11-19" and d["as_of"] == "2026-11-19"
    for fid in ("iust", "ibci", "iglt", "ibcd", "ihyu", "ihyg", "qdvp"):
        assert by[fid]["status"] == "unavailable" and all("HTTP 403" in m["reason"] for m in by[fid]["measures"].values())
    assert "HTTP 406" in by["muni"]["measures"]["ytm"]["reason"]
    man = json.loads((tmp_path / "data" / "manifest.json").read_text())
    assert man["characteristics"] == {"fixed-income": {"path": "characteristics/fixed-income.json", "as_of": "2026-11-19"}}
    st = json.loads((tmp_path / "data" / "status.json").read_text())["sources"]["fund_issuers"]
    assert st["items_ok"] == 4 and st["stale"] is False and st["expected_cadence_hours"] == 168


def _refuse(url, _p):
    raise ch.Refused(f"HTTP 403 for {url}")


def test_C5_a_refusal_stops_that_issuer_for_the_run_and_keeps_the_last_figures(cfgs, tmp_path):
    run(cfgs, tmp_path, FakeGetter(routes()))
    g = FakeGetter(routes(**{"-sybt-gy": _refuse}))
    res = run(cfgs, tmp_path, g, now=datetime(2026, 11, 28, 7, 20, tzinfo=timezone.utc), today=date(2026, 11, 28))
    assert not any("-spfa-gy" in u for u in g.log), "after a refusal the issuer is not asked again"
    assert "ssga" in res["refused"]
    by = {f["id"]: f for f in doc(tmp_path)["funds"]}
    for fid in ("sybt", "spfa"):
        assert by[fid]["stale"] and by[fid]["stale_reason"] == "refused" and by[fid]["measures"]["ytm"]["value"] in (4.95, 6.55)
    assert not by["vgea"]["stale"]


def test_C6_a_layout_change_keeps_the_last_good_figures_marked_stale(cfgs, tmp_path):
    run(cfgs, tmp_path, FakeGetter(routes()))
    changed = PAGES["vanguard_veca"].replace(b'"AVGDURADJ"', b'"DURATION"')
    run(cfgs, tmp_path, FakeGetter(routes(**{"/9695/": changed})))
    veca = next(f for f in doc(tmp_path)["funds"] if f["id"] == "veca")
    assert veca["stale"] and veca["stale_reason"] == "layout_changed" and veca["measures"]["duration"]["value"] == 4.38


def test_C7_a_first_run_failure_shows_n_a_with_the_reason(cfgs, tmp_path):
    run(cfgs, tmp_path, FakeGetter(routes(**{"/9591/": PAGES["vanguard_vgea"].replace(b"serverApp-state", b"x")})))
    vgea = next(f for f in doc(tmp_path)["funds"] if f["id"] == "vgea")
    assert vgea["status"] == "unavailable" and "could not be read on 2026-11-21 (layout changed)" in vgea["measures"]["ytm"]["reason"]


def test_C8_figures_never_go_backwards_and_old_figures_fail_validation(cfgs, tmp_path):
    run(cfgs, tmp_path, FakeGetter(routes()))
    older = PAGES["ssga_sybt"].replace(b"as of 19 Nov 2026", b"as of 18 Nov 2026")
    res = run(cfgs, tmp_path, FakeGetter(routes(**{"-sybt-gy": older})))
    sybt = next(f for f in doc(tmp_path)["funds"] if f["id"] == "sybt")
    assert sybt["measures"]["ytm"]["as_of"] == "2026-11-19" and any("kept as published" in p for p in res["problems"])
    # 31 Oct is 75 days old on 14 Jan: Vanguard's limit is 75, so on 15 Jan the figures fail and the last good ones stay (stale)
    res = run(cfgs, tmp_path, FakeGetter(routes()), today=date(2027, 1, 15), now=datetime(2027, 1, 15, 7, 20, tzinfo=timezone.utc))
    vgea = next(f for f in doc(tmp_path)["funds"] if f["id"] == "vgea")
    assert vgea["stale"] and vgea["stale_reason"] == "validation_failed"


def test_C9_the_config_must_list_exactly_the_sections_funds(cfgs, tmp_path):
    c, u = copy.deepcopy(cfgs[0]), cfgs[1]
    del c["funds"]["muni"]
    with pytest.raises(validate.ValidationError, match="muni"):
        ch.run(c, u, FakeGetter(routes()), today=TODAY, now=NOW, data_dir=tmp_path / "d", work_dir=tmp_path / "w")


def test_C10_the_getter_never_retries_a_refusal_and_spots_challenge_pages():
    class R:
        def __init__(self, code, text=""):
            self.status_code, self.text, self.content = code, text, text.encode()

    class S:
        def __init__(self, answers):
            self.answers, self.calls, self.headers = list(answers), 0, {}

        def get(self, url, timeout):
            self.calls += 1
            return self.answers.pop(0)
    for code in (401, 403, 406, 429):
        g = ch.Getter(sleep=lambda s: None)
        g.s = S([R(code), R(200, "ok")])
        with pytest.raises(ch.Refused):
            g.get("https://example.org/x")
        assert g.s.calls == 1
    g = ch.Getter(sleep=lambda s: None)
    g.s = S([R(200, "<html><title>Access Denied</title></html>")])
    with pytest.raises(ch.Refused, match="challenge"):
        g.get("https://example.org/x")
    g = ch.Getter(sleep=lambda s: None)
    g.s = S([R(503), R(200, "<html>fine</html>")])
    assert g.get("https://example.org/x") == b"<html>fine</html>" and g.s.calls == 2


def test_C12_vanguard_refuses_ambiguous_or_undisplayed_figures():
    """Review of 21 Nov 2026: the embedded JSON must hold ONE set of fund figures, and they must be the ones the page displays."""
    page = PAGES["vanguard_vgea"]
    i = page.index(b'"AVGDURADJ":{')                          # duplicate the fund analytics entry under another key
    with pytest.raises(ch.LayoutError):
        ch.parse_vanguard(page.replace(b'<script id="serverApp-state" type="application/json">{',
                                       b'<script id="serverApp-state" type="application/json">{"999":' + _entry_with_analytics(page) + b",", 1), "IE00BH04GL39")
    assert i > 0
    with pytest.raises(ch.LayoutError, match="does not display"):
        ch.parse_vanguard(page.replace(b'"analyticValue":"6.7933690440"', b'"analyticValue":"5.1000000000"'), "IE00BH04GL39")


def _entry_with_analytics(page: bytes) -> bytes:
    import re
    state = json.loads(re.search(rb'<script id="serverApp-state" type="application/json">(.*?)</script>', page, re.S).group(1))
    e = next(v for v in state.values() if b"AVGDURADJ" in json.dumps(v).encode() and "6.7933690440" in json.dumps(v))
    return json.dumps(e).encode()


def test_C13_a_figure_missing_today_keeps_the_last_one_instead_of_not_published(cfgs, tmp_path):
    run(cfgs, tmp_path, FakeGetter(routes()))
    res = run(cfgs, tmp_path, FakeGetter(routes(**{"/9695/": PAGES["vanguard_veca"].replace(b'"AVGQLYTFTO"', b'"OTHER"')})))
    veca = next(f for f in doc(tmp_path)["funds"] if f["id"] == "veca")
    assert veca["measures"]["rating"]["value"] == "A-" and any("missing on the issuer's page today" in p for p in res["problems"])


def test_C11_validation_rejects_a_malformed_file(cfgs, tmp_path):
    run(cfgs, tmp_path, FakeGetter(routes()))
    good = doc(tmp_path)
    ids = {f["id"] for f in good["funds"]}
    bad = copy.deepcopy(good)
    bad["funds"][0]["measures"]["oas"] = {"value": None, "reason": ""}
    with pytest.raises(validate.ValidationError):
        validate.validate_characteristics(bad, section_ids=ids)
    bad = copy.deepcopy(good)
    bad["funds"][1]["measures"]["rating"]["value"] = 3.0
    with pytest.raises(validate.ValidationError, match="wrong value type"):
        validate.validate_characteristics(bad, section_ids=ids)
    with pytest.raises(validate.ValidationError):
        validate.validate_characteristics(good, section_ids=ids - {"muni"})
