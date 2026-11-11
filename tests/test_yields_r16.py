"""Round 16 (11 Nov 2026): the long-tenor auction rule (Y20), France's monthly 3M (Y21), Australia (Y22), Italy (Y23), India (Y24),
and the new documents through validation (Y25). Fixtures are real files fetched on 11 Nov 2026 (trimmed)."""
import json
from datetime import date

import pytest

from conftest import FIX
from dashjobs import validate
from dashjobs.yields import au, core, fr, india, it, job
from dashjobs.yields.core import Auction, Raw, Series
from dashjobs.yields.http import FakeGetter

YF = FIX / "yields"
D = date.fromisoformat
TODAY = date(2026, 11, 11)


def text(name):
    return (YF / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------- Y20: auction rule for long tenors

@pytest.mark.parametrize("tenor,days,expect", [
    ("1Y", 292, False), ("1Y", 293, True), ("1Y", 364, True), ("1Y", 438, True), ("1Y", 439, False),
    ("3Y", 913, False), ("3Y", 914, True), ("3Y", 1278, True), ("3Y", 1279, False),
    ("5Y", 1460, False), ("5Y", 1461, True), ("5Y", 2191, True), ("5Y", 2192, False),
    ("10Y", 3104, False), ("10Y", 3105, True), ("10Y", 4200, True), ("10Y", 4201, False),
    ("30Y", 9131, False), ("30Y", 9132, True), ("30Y", 12783, True), ("30Y", 12784, False),
])
def test_Y20_long_tenor_windows_in_years_left(tenor, days, expect):
    """1Y 0.8-1.2, 3Y 2.5-3.5, 5Y 4-6, 10Y 8.5-11.5, 30Y 25-35 years left at settlement (365.25-day years)."""
    a = Auction(D("2026-10-29"), days, 4.0)
    assert (core.pick_auction([a], tenor, D("2026-10-30")) is a) is expect


def test_Y20_long_auction_point_age_limit_and_auction_only_curve_date():
    btp = Auction(D("2026-10-29"), 3621, 4.49, D("2026-11-02"))
    raw = Raw(auctions={"10Y": [btp], "3M": [Auction(D("2026-11-03"), 91, 2.6)]})
    assert core.point_at(raw, "10Y", D("2026-10-30")) == {"value": 4.49, "date": "2026-10-29", "kind": "A", "days": 3621}
    assert core.point_at(raw, "10Y", D("2027-01-28")) is None                       # 91 days old
    assert core.curve_date(raw) is None                       # not opted in (Japan with an empty curve file): fails as before
    raw.auction_dated = True
    assert core.curve_date(raw) == D("2026-11-03")                                   # Italy, India: the latest auction
    raw.auctions["10Y"].append(Auction(D("2026-11-20"), 20000, 5.0))                 # 55 years left: in no window
    assert core.curve_date(raw) == D("2026-11-03")
    raw.series["10Y"] = [Series("D", [(D("2026-10-30"), 4.6)])]                      # a daily series wins over any auction
    assert core.point_at(raw, "10Y", D("2026-10-30"))["kind"] == "D" and core.curve_date(raw) == D("2026-10-30")


def test_Y20_monthly_points_never_date_the_curve_and_labels_can_change_by_date():
    m = Series("M", [(D("2026-10-31"), 2.84)], max_lag=90, labels={D("2026-10-31"): "monthly average, October 2026"})
    raw = Raw(series={"3M": [m], "10Y": [Series("D", [(D("2026-10-30"), 4.9)])]})
    assert core.curve_date(raw) == D("2026-10-30")                                   # not the month end
    assert core.point_at(raw, "3M", D("2026-11-10"))["label"] == "monthly average, October 2026"
    assert core.curve_date(Raw(series={"3M": [m]})) is None


# ---------------------------------------------------------------- Y21: France 3M, the monthly 13-week BTF rate

def _fr(blob):
    class G(FakeGetter):
        def get(self, url, *, params=None, headers=None):
            return blob
    return G({})


def test_Y21_france_3m_is_the_monthly_13_week_btf_average_within_90_days():
    rows = json.loads((YF / "webstat_tec.json").read_bytes()) + json.loads((YF / "webstat_tmb.json").read_bytes())
    raw = fr.fetch(_fr(json.dumps(rows).encode()), D("2026-11-10"), env={"FR_WEBSTAT_CLIENT_ID": "k"})
    assert raw.series["3M"][0].kind == "M" and set(raw.gaps) == {"1M", "6M"}
    p = core.point_at(raw, "3M", D("2026-11-10"))
    assert p == {"value": 2.84, "date": "2026-10-31", "kind": "M", "label": "monthly average of 13-week BTF auctions, October 2026"}
    assert core.point_at(raw, "3M", D("2026-10-30"))["label"].endswith("September 2026")      # October's average is not known yet
    assert core.point_at(raw, "3M", D("2027-01-30")) is None                                  # 91 days after 31 Oct: never stretched
    assert core.curve_date(raw) == D("2026-11-10")
    doc = job.build_doc("fr", raw, today=D("2026-11-10"), now_iso="2026-11-10T15:47:00Z", meta=fr.META)
    validate.validate_yield(doc, today=D("2026-11-10"), prev=None)
    assert doc["curves"][3]["points"]["3M"]["value"] == 2.03 and doc["curves"][3]["points"]["3M"]["date"] == "2025-10-31"
    old = [r for r in rows if r["time_period_end"] <= "2026-07-31" or "TMB" not in r["series_key"]]
    raw2 = fr.fetch(_fr(json.dumps(old).encode()), D("2026-11-10"), env={"FR_WEBSTAT_CLIENT_ID": "k"})
    assert "3M" in raw2.gaps and core.point_at(raw2, "3M", D("2026-11-10")) is None          # latest month older than 90 days


# ---------------------------------------------------------------- Y22: Australia

def _au():
    return au.fetch(FakeGetter({"f2-data": (YF / "rba_f2.csv").read_bytes(), "f16-data": (YF / "rba_f16.csv").read_bytes()}), TODAY)


def test_Y22_australia_f2_daily_and_f16_bond_buckets():
    raw = _au()
    assert {t: raw.series[t][0].kind for t in raw.series} == {"3Y": "D", "5Y": "D", "10Y": "D", "1Y": "B", "30Y": "B"}
    assert set(raw.gaps) == {"1M", "3M", "6M"} and "AOFM" in raw.gaps["3M"]
    got = {t: core.point_at(raw, t, D("2026-10-30")) for t in raw.series}
    assert {t: p["value"] for t, p in got.items()} == {"1Y": 4.978, "3Y": 4.811, "5Y": 4.841, "10Y": 5.116, "30Y": 5.526}
    assert got["1Y"]["label"] == "Treasury Bond 148 (2.75%, 21 Nov 2027), 1.1 years left"
    assert got["30Y"]["label"] == "Treasury Bond 169 (4.75%, 21 Jun 2054), 27.6 years left"
    doc = job.build_doc("au", raw, today=TODAY, now_iso="2026-11-11T15:47:00Z", meta=au.META)
    validate.validate_yield(doc, today=TODAY, prev=None)
    cur = {c["id"]: c for c in doc["curves"]}
    assert doc["as_of"] == "2026-11-04" and "1Y" not in cur["3m"]["points"]          # 4 Aug: no bond had 0.8-1.2 years left
    assert cur["1y"]["points"]["1Y"]["label"].startswith("Treasury Bond 164")           # the bucket follows the date
    assert "Indexed" not in json.dumps(doc)


def test_Y22_australia_bucket_picks_the_bond_closest_to_the_tenor():
    bonds = [{"col": 1, "name": "TB A", "coupon": "1%", "maturity": D("2027-08-01")},     # 0.75 years: outside
             {"col": 2, "name": "TB B", "coupon": "2%", "maturity": D("2027-10-01")},     # 0.92 years
             {"col": 3, "name": "TB C", "coupon": "3%", "maturity": D("2027-11-15")}]     # 1.04 years: closer to 1
    s = au.bucket_series(bonds, [["30-Oct-2026", "4.1", "4.2", "4.3"], ["02-Nov-2026", "4.1", "4.2", ""]], "1Y", D("2026-01-01"))
    assert s.points == [(D("2026-10-30"), 4.3), (D("2026-11-02"), 4.2)] and s.labels[D("2026-11-02")].startswith("TB B")


# ---------------------------------------------------------------- Y23: Italy

def test_Y23_italy_result_files_and_layouts():
    links = it.pdf_links(text("mef_btp10_2026.html") + '<a href="/export/x/BTP-30-Years-Syndicate-placement-09.06.2026.pdf">s</a>'
                         '<a href="/export/x/Placement-details-of-the-tap-7-year-BTP-10.06.2026.pdf">p</a>')
    assert len(links) == 10 and all("Auction-Results" in u for u in links)
    assert it.name_date(links[0]) == D("2026-10-30") and it.name_date(links[5]) == D("2026-06-26")
    btp = it.parse_result(it.pdf_text((YF / "mef_btp10_20261030.pdf").read_bytes()))
    assert [(r["date"], r["settle"], r["maturity"], r["days"], r["value"]) for r in btp] == [("2026-10-29", "2026-11-02", "2036-10-01", 3621, 4.49)]
    bot = it.parse_result(text("mef_bot6m_20260928.txt"))
    assert [(r["date"], r["days"], r["value"]) for r in bot] == [("2026-09-25", 182, 2.873)]       # WAY, not the compound yield
    assert it.parse_result("Auction Results: BTP€i 10 YEARS\nAuction Date May 1, 2026") == []
    with pytest.raises(ValueError):
        it.parse_result("PRESS RELEASE Placement details of the syndicated issuance")
    with pytest.raises(ValueError):
        it.parse_result("Auction Results: BTP 5 YEARS\nAuction Date May 1, 2026\n")                  # fields missing


def test_Y23_italy_first_run_reads_two_years_later_runs_only_new_files():
    page, pdf = text("mef_btp10_2026.html").encode(), (YF / "mef_btp10_20261030.pdf").read_bytes()
    calls = []

    def route(url, params):
        calls.append((url.rsplit("/", 2)[-2] if url.endswith("index.html") else url.rsplit("/", 1)[-1], (params or {}).get("selezione-anno")))
        if url.endswith("index.html"):
            return page if "btp_10_anni" in url and params["selezione-anno"] == "2026" else b"<html></html>"
        return pdf if url.endswith("29-30.10.2026.pdf") else b"%PDF-1.4 damaged"
    raw = it.fetch(FakeGetter({"dt.mef.gov.it": route}), TODAY)
    pages = [c for c in calls if c[1]]
    assert len(pages) == 2 * len(it.CATEGORIES) and {c[1] for c in pages} == {"2025", "2026"}
    assert len([c for c in calls if c[0].endswith(".pdf")]) == 10 and len(raw.extra["unreadable"]) == 9
    assert raw.warnings and raw.warnings[0].startswith("9 auction-result file(s) could not be read")
    assert [a["value"] for a in raw.extra["auction_log"]] == [4.49] and set(raw.auctions) == set(it.TENORS)
    assert core.point_at(raw, "10Y", D("2026-10-30")) == {"value": 4.49, "date": "2026-10-29", "kind": "A", "days": 3621}
    assert core.curve_date(raw) == D("2026-10-29") and "1M" in raw.gaps
    calls.clear()
    raw2 = it.fetch(FakeGetter({"dt.mef.gov.it": route}), D("2026-11-16"), prev=raw.extra)
    pdfs = [c[0] for c in calls if c[0].endswith(".pdf")]
    assert len(calls) == len(it.CATEGORIES) + 9 and "BTP-10-Years-Auction-Results-29-30.10.2026.pdf" not in pdfs   # only the unreadable retried
    assert raw2.extra["auction_log"] == raw.extra["auction_log"]


def test_Y23_italy_a_fetch_error_fails_the_country_instead_of_losing_the_auction():
    page = text("mef_btp10_2026.html").encode()

    def route(url, params):
        if url.endswith("index.html"):
            return page if "btp_10_anni" in url else b"<html></html>"
        return None                                                                    # every PDF: HTTP 404
    from dashjobs.yields.http import FetchError
    with pytest.raises(FetchError):
        it.fetch(FakeGetter({"dt.mef.gov.it": route}), TODAY)


# ---------------------------------------------------------------- Y24: India

def test_Y24_india_list_results_and_announcements():
    items = india.parse_list(text("rbi_list.html"))
    kinds = [(d.isoformat(), p, india.kind_of(t)) for d, p, t in items if india.kind_of(t)]
    assert kinds[:5] == [("2026-11-11", 63956, "tb"), ("2026-11-09", 63952, "ann"), ("2026-11-06", 63937, "gs"),
                         ("2026-11-04", 63918, "tb"), ("2026-11-02", 63902, "ann")]
    assert {"__VIEWSTATE", "__EVENTVALIDATION", "UsrFontCntr$btn"} <= set(india.form_fields(text("rbi_list.html")))
    oct_ = india.parse_list(text("rbi_list_202610.html"))
    assert oct_[0][0] == D("2026-10-30") and oct_[-1][0] == D("2026-10-01")
    assert india.parse_tbills(text("rbi_tb_63956.html")) == [
        {"date": "2026-11-11", "days": 91, "value": 5.8594, "what": "91-day T-bill"},
        {"date": "2026-11-11", "days": 182, "value": 6.5059, "what": "182-day T-bill"},
        {"date": "2026-11-11", "days": 364, "value": 6.6176, "what": "364-day T-bill"}]
    d, secs = india.parse_gs_results(text("rbi_gs_63937.html"))
    assert d == D("2026-11-06") and secs == [("7.06% GS 2041", 7.3835), ("7.43% GS 2076", 7.7403)]
    ann = india.parse_announcement(text("rbi_ann_63902.html"))                         # two securities, row-spanned dates
    assert ann == [{"name": "7.06% GS 2041", "maturity": "2041-07-27", "auction": "2026-11-06", "settle": "2026-11-09"},
                   {"name": "7.43% GS 2076", "maturity": "2076-01-19", "auction": "2026-11-06", "settle": "2026-11-09"}]
    assert india.parse_announcement(text("rbi_ann_63952.html"))[0]["maturity"] == "2036-05-11"
    no_bid = india.parse_tbills(text("rbi_tb_63918.html"))                              # 4 Nov: the 182-day bill accepted no bid
    assert [(r["days"], r["value"]) for r in no_bid] == [(91, 5.8871), (364, 6.633)]
    assert india.parse_tbills(text("rbi_tb_63838_rejected.html")) == []                # 21 Oct 2026: every bid rejected
    na = text("rbi_gs_63937.html").replace("(WAY: 7.7403%)", "(WAY: NA)")                # seen live on 11 Nov 2026
    assert india.parse_gs_results(na)[1] == [("7.06% GS 2041", 7.3835)]
    with pytest.raises(ValueError):
        india.parse_gs_results(text("rbi_gs_63937.html").replace("(WAY: 7.7403%)", "(WAY: 7,74%)"))
    assert india.match("6.48% GS 2036", D("2026-11-13"), [{"name": "New GS 2036", "auction": "2026-11-13", "maturity": "2036-11-13", "settle": "2026-11-16"}])
    assert india.match("7.06% GS 2041", D("2026-11-07"), ann) is None                   # another day's auction


def test_Y24_india_months_listed_first_run_and_later():
    first = india.months_needed(india.spans(TODAY, None))           # one continuous range: no hole under the 1-year-earlier curve
    assert first[0] == (2025, 8) and first[-1] == (2026, 11) and len(first) == 16
    assert india.months_needed(india.spans(D("2026-11-16"), D("2026-11-09"))) == [(2026, 11)]
    assert india.months_needed(india.spans(D("2026-12-03"), D("2026-11-30"))) == [(2026, 11), (2026, 12)]
    assert india.spans(D("2027-06-01"), D("2026-11-09"))[0][0] == D("2027-06-01") - __import__("datetime").timedelta(days=127)


def test_Y24_india_fetch_pairs_results_with_announcements_and_reads_each_release_once():
    pages = {63956: "rbi_tb_63956.html", 63937: "rbi_gs_63937.html", 63902: "rbi_ann_63902.html", 63952: "rbi_ann_63952.html",
             63918: "rbi_tb_63918.html"}
    got = []

    def get(url, params):
        if "prid=" in url:
            pid = int(url.split("prid=")[1]); got.append(pid)
            return text(pages[pid]).encode() if pid in pages else None
        return text("rbi_list.html").encode()

    def post(url, data):
        got.append(("post", data["hdnYear"], data["hdnMonth"]))
        assert data["__VIEWSTATE"] and data["UsrFontCntr$btn"] == ""
        return text("rbi_list.html").encode()
    prev = {"listed_through": "2026-11-12", "seen": [], "auction_log": [], "announced": india.parse_announcement(text("rbi_ann_63902.html"))}

    class G(FakeGetter):
        def get(self, url, *, params=None, headers=None):
            return get(url, params)

        def post(self, url, data, *, headers=None):
            return post(url, data)
    raw = india.fetch(G({}), TODAY, prev=prev)                 # releases since 5 Nov: the 6 Nov result's announcement is in state
    assert ("post", "2026", "11") in got and sorted(p for p in got if isinstance(p, int)) == [63937, 63952, 63956]
    log = {(a["what"], a["days"]): a["value"] for a in raw.extra["auction_log"]}
    assert log == {("91-day T-bill", 91): 5.8594, ("182-day T-bill", 182): 6.5059, ("364-day T-bill", 364): 6.6176,
                   ("7.06% GS 2041", (D("2041-07-27") - D("2026-11-09")).days): 7.3835,
                   ("7.43% GS 2076", (D("2076-01-19") - D("2026-11-09")).days): 7.7403}
    pts = {t: core.point_at(raw, t, TODAY) for t in core.TENORS}
    assert pts["3M"]["value"] == 5.8594 and pts["6M"]["value"] == 6.5059 and pts["1Y"] == {"value": 6.6176, "date": "2026-11-11", "kind": "A", "days": 364}
    assert pts["10Y"] is None and pts["30Y"] is None and pts["1M"] is None             # 14.7 and 49.2 years left: no window
    assert any(a["name"] == "6.94% GS 2036" for a in raw.extra["announced"])           # waits for its 13 Nov result
    assert "unparsed_last_run" not in raw.extra
    got.clear()
    raw2 = india.fetch(G({}), D("2026-11-12"), prev=raw.extra)                          # lists from 4 Nov (a week of overlap)
    assert [p for p in got if isinstance(p, int)] == [63918]                           # only the release not read before
    assert len(raw2.extra["auction_log"]) == len(raw.extra["auction_log"]) + 2


# ---------------------------------------------------------------- Y25: the job knows the new countries

def test_Y25_new_adapters_are_registered_with_metadata_and_terms():
    for code, mod in (("it", it), ("au", au), ("in", india)):
        assert job.adapter(code) is mod and mod.META["code"] == code and code in job.COUNTRIES
        assert mod.META["terms"] and mod.META["status"] == "ok"
    assert "in writing" in india.META["terms"] and "profit" in it.META["terms"] and "CC BY 4.0" in au.META["terms"]


def test_Y24_india_one_unreadable_release_is_recorded_not_fatal():
    class G(FakeGetter):
        def get(self, url, *, params=None, headers=None):
            if "prid=63937" in url:
                return b"<html><table><tr><td>Auction Results</td><td>7.06% GS 2041</td></tr></table></html>"   # no WAY row
            if "prid=" in url:
                return text({63956: "rbi_tb_63956.html", 63952: "rbi_ann_63952.html"}[int(url.split("prid=")[1])]).encode()
            return text("rbi_list.html").encode()

        def post(self, url, data, *, headers=None):
            return text("rbi_list.html").encode()
    raw = india.fetch(G({}), TODAY, prev={"listed_through": "2026-11-12"})
    assert [a["days"] for a in raw.extra["auction_log"]] == [91, 182, 364]
    assert raw.extra["unreadable"] == {"63937": "results table: WAY row not found"} and 63937 not in raw.extra["seen"]
    assert "1 RBI release(s) could not be read" in raw.warnings[0]


def test_Y24_india_result_without_its_announcement_is_retried_until_the_announcement_is_read():
    pages = {63956: "rbi_tb_63956.html", 63937: "rbi_gs_63937.html", 63952: "rbi_ann_63952.html", 63918: "rbi_tb_63918.html"}
    got = []

    class G(FakeGetter):
        def get(self, url, *, params=None, headers=None):
            if "prid=" in url:
                pid = int(url.split("prid=")[1]); got.append(pid)
                return text(pages[pid]).encode()
            return text("rbi_list.html").encode()

        def post(self, url, data, *, headers=None):
            return text("rbi_list.html").encode()
    raw = india.fetch(G({}), TODAY, prev={"listed_through": "2026-11-12"})      # the 6 Nov result, its 2 Nov announcement unknown
    assert "63937" in raw.extra["unreadable"] and "no announcement found for 7.06% GS 2041" in raw.extra["unreadable"]["63937"]
    pages[63902] = "rbi_ann_63902.html"
    got.clear()
    state = dict(raw.extra, listed_through="2026-11-09")                         # the next run's overlap reaches 2 Nov
    raw2 = india.fetch(G({}), D("2026-11-12"), prev=state)
    assert 63937 in got and 63902 in got and raw2.extra["unreadable"] == {} and raw2.warnings == []
    assert any(a["what"] == "7.06% GS 2041" for a in raw2.extra["auction_log"])


def test_Y23_italy_1m_from_a_one_month_bot_reopening_and_gap_notes_only_when_empty():
    reopen = {"date": "2026-10-28", "settle": "2026-10-30", "maturity": "2026-12-14", "days": 45, "value": 2.567, "isin": "IT0005684888",
              "what": "12 MONTH BOTS (1 MONTH RESIDUAL MATURITY", "url": "u1"}
    btp30 = {"date": "2026-06-10", "settle": "2026-06-15", "maturity": "2055-10-01", "days": 10700, "value": 4.6, "isin": "X", "what": "BTP 30 YEARS", "url": "u2"}
    prev = {"auction_log": [reopen, btp30], "seen": ["u1", "u2"]}
    raw = it.fetch(FakeGetter({"dt.mef.gov.it": b"<html></html>"}), TODAY, prev=prev)
    assert core.point_at(raw, "1M", D("2026-10-30")) == {"value": 2.567, "date": "2026-10-28", "kind": "A", "days": 45}
    assert "1M" not in raw.gaps and "syndicate" in raw.gaps["30Y"]                    # the 30Y auction is 154 days old
    assert core.point_at(raw, "30Y", D("2026-07-01"))["days"] == 10700


def test_Y25_italy_excluded_instruments_in_any_case_and_warnings_reach_status_json(tmp_path, monkeypatch):
    for head in ("BTP ITALIA", "BTP VALORE", "BTP GREEN", "CCTEU", "BTP€I 10 YEARS"):
        assert it.parse_result(f"Auction Results: {head}\nAuction Date May 1, 2026") == []
    from test_yields import run_job, stub
    s = stub("aa")
    inner = s.fetch

    def fetch(g, today, env=None, prev=None):
        raw = inner(g, today, env, prev)
        raw.warnings.append("2 auction-result file(s) could not be read")
        return raw
    s.fetch = fetch
    run_job(tmp_path, {"aa": s}, monkeypatch)
    st = json.loads((tmp_path / "data" / "status.json").read_text())["sources"]["yield_curves"]
    assert st["warnings"] == ["aa: 2 auction-result file(s) could not be read"] and st["ok"] is True
