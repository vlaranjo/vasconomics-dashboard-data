"""Yield-curve job: auction rule (Y1), anchors (Y2), parsers (Y3-Y10), job behaviour (Y11-Y17)."""
import hashlib
import io
import json
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest

from conftest import FIX
from dashjobs import markets, publish, validate
from dashjobs.yields import br, ca, core, de, es, fr, jp, uk, us, ch
from dashjobs.yields import job
from dashjobs.yields.core import Auction, Raw, Series, Skipped
from dashjobs.yields.http import FakeGetter

YF = FIX / "yields"
D = date.fromisoformat
NOW = datetime(2026, 11, 6, 15, 47, tzinfo=timezone.utc)
TODAY = date(2026, 11, 6)


def tree_hash(p: Path):
    h = hashlib.sha256()
    for f in sorted(p.rglob("*")):
        if f.is_file():
            h.update(f.relative_to(p).as_posix().encode())
            h.update(f.read_bytes())
    return h.hexdigest()


# ---------------------------------------------------------------- Y1: the auction rule

@pytest.mark.parametrize("tenor,days,expect", [
    ("1M", 19, False), ("1M", 20, True), ("1M", 45, True), ("1M", 46, False),
    ("3M", 69, False), ("3M", 70, True), ("3M", 91, True), ("3M", 110, True), ("3M", 111, False),
    ("6M", 159, False), ("6M", 160, True), ("6M", 182, True), ("6M", 200, True), ("6M", 201, False),
])
def test_Y1_window_edges(tenor, days, expect):
    a = Auction(D("2026-10-21"), days, 1.5)
    assert (core.pick_auction([a], tenor, D("2026-10-30")) is a) is expect


def test_Y1_most_recent_in_window_wins_and_age_limit():
    old = Auction(D("2026-10-05"), 98, 2.586)
    new = Auction(D("2026-10-26"), 91, 2.60)
    out_of_window = Auction(D("2026-10-29"), 182, 2.70)       # newest, but a 6M bill: not a 3M auction
    after = Auction(D("2026-11-02"), 105, 2.67)               # after the reference date: not yet known
    got = core.pick_auction([old, new, out_of_window, after], "3M", D("2026-10-30"))
    assert got is new
    assert core.pick_auction([old], "3M", D("2026-10-30")) is old
    assert core.pick_auction([old], "3M", D("2027-01-04")) is None             # 91 days old > 90
    assert core.pick_auction([Auction(D("2026-07-30"), 91, 1.0)], "3M", D("2026-10-30")) is None


def test_Y1_point_carries_auction_date_and_residual_days():
    raw = Raw(auctions={"3M": [Auction(D("2026-10-21"), 91, 2.5)]})
    p = core.point_at(raw, "3M", D("2026-10-30"))
    assert p == {"value": 2.5, "date": "2026-10-21", "kind": "A", "days": 91}


# ---------------------------------------------------------------- Y2: curves and anchors

def test_Y2_anchors_and_lag_rules():
    pts = [(D("2026-10-30"), 4.0), (D("2026-09-30"), 3.5), (D("2026-07-30"), 3.0), (D("2025-10-30"), 2.0)]
    raw = Raw(series={"1Y": [Series("D", pts, max_lag=4)], "3Y": [Series("D", [(D("2026-10-30"), 4.4), (D("2026-09-20"), 9.0)], max_lag=4)]})
    as_of = core.curve_date(raw)
    assert as_of == D("2026-10-30")
    cur = {c["id"]: c for c in core.build_curves(raw, as_of)}
    assert [cur[k]["date"] for k in ("latest", "1m", "3m", "1y")] == ["2026-10-30", "2026-09-30", "2026-07-30", "2025-10-30"]
    assert cur["1m"]["points"]["1Y"]["value"] == 3.5 and cur["1y"]["points"]["1Y"]["value"] == 2.0
    assert "3Y" not in cur["1m"]["points"]                    # 10 days old > max_lag: left empty, not stretched
    assert set(cur["latest"]["points"]) == {"1Y", "3Y"}


def test_Y2_exact_series_then_bucket_fallback_spain_style():
    exact = Series("D", [(D("2026-10-29"), 3.0)], max_lag=0)
    bucket = Series("B", [(D("2026-10-29"), 2.9), (D("2026-10-30"), 2.947)], max_lag=4, label="6-12 month bucket")
    raw = Raw(series={"1Y": [exact, bucket]})
    assert core.point_at(raw, "1Y", D("2026-10-29"))["kind"] == "D"
    p = core.point_at(raw, "1Y", D("2026-10-30"))
    assert p["kind"] == "B" and p["value"] == 2.947 and p["label"] == "6-12 month bucket"


# ---------------------------------------------------------------- Y3: United States

US_XML = (YF / "us_202610.xml").read_bytes()


def test_Y3_us_parse_and_fetch_pulls_the_anchor_months():
    got = us.parse_month(US_XML)
    assert sorted(got) == [D("2026-10-28"), D("2026-10-29"), D("2026-10-30")]
    assert got[D("2026-10-30")] == {"1M": 4.06, "3M": 4.16, "6M": 4.25, "1Y": 4.36, "3Y": 4.65, "5Y": 4.71, "10Y": 4.94, "30Y": 5.31}
    asked = []

    def route(url, params):
        asked.append(url.rsplit("=", 1)[1])
        return US_XML                                       # same body for every month: enough to check the calls
    raw = us.fetch(FakeGetter({"treasury.gov": route}), D("2026-11-06"))
    assert sorted(set(asked)) == ["202510", "202607", "202609", "202610", "202611"]
    assert raw.series["10Y"][0].last_date == D("2026-10-30")


# ---------------------------------------------------------------- Y4: United Kingdom

def boe_xlsx(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "4. spot curve"
    ws.append([None, "UK nominal spot curve"])
    ws.append([])
    ws.append(["Maturity"])
    ws.append(["years:", 0.5, 1, 1.5, 3, 5, 10, 30])
    ws.append(["#VALUE!"])
    for d, vals in rows:
        ws.append([datetime.combine(d, datetime.min.time())] + vals)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def test_Y4_uk_parse_merge_and_gaps():
    cur = boe_xlsx([(D("2026-11-02"), [4.20, 4.39, 4.5, 4.77, 4.89, 5.27, 5.72])])
    his = boe_xlsx([(D("2026-10-30"), [4.217, 4.425, 4.6, 4.774, 4.896, 5.277, 5.723]), (D("2025-10-30"), [3.9, 3.95, 4.0, 4.1, 4.2, 4.5, 5.2])])

    wrong = boe_xlsx([(D("2026-11-05"), [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0])])         # the Inflation file, same layout

    def zipped(name, blob, extra=None):
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as z:
            if extra:
                z.writestr(extra, wrong)           # listed first, as in the real zip
            z.writestr(name, blob)
        return b.getvalue()
    g = FakeGetter({"latest-yield-curve-data": zipped("GLC Nominal daily data current month.xlsx", cur, "GLC Inflation daily data current month.xlsx"),
                    "glcnominalddata": zipped("GLC Nominal daily data_2025 to present.xlsx", his)})
    raw = uk.fetch(g, TODAY)
    assert core.curve_date(raw) == D("2026-11-02")             # the current-month file is newer than the history file
    cur_ = {c["id"]: c for c in core.build_curves(raw, D("2026-11-02"))}
    assert cur_["latest"]["points"]["10Y"]["value"] == 5.27 and "1M" not in cur_["latest"]["points"] and "3M" not in cur_["latest"]["points"]
    assert cur_["1y"]["points"]["10Y"]["value"] == 4.5 and cur_["1y"]["points"]["10Y"]["date"] == "2025-10-30"
    assert set(raw.gaps) == {"1M", "3M"}


# ---------------------------------------------------------------- Y5: Canada

def test_Y5_canada_weekly_bills_and_long_term_label():
    bonds = {"observations": [{"d": "2026-10-30", "BD.CDN.3YR.DQ.YLD": {"v": "3.38"}, "BD.CDN.5YR.DQ.YLD": {"v": "3.51"},
                               "BD.CDN.10YR.DQ.YLD": {"v": "3.78"}, "BD.CDN.LONG.DQ.YLD": {"v": "4.11"}}]}
    bills = {"observations": [{"d": "2026-10-28", "V80691342": {"v": "2.46"}, "V80691344": {"v": "2.53"},
                               "V80691345": {"v": "2.77"}, "V80691346": {"v": "3.04"}}]}
    g = FakeGetter({"BD.CDN.3YR": json.dumps(bonds).encode(), "V80691342": json.dumps(bills).encode()})
    raw = ca.fetch(g, TODAY)
    c = core.build_curves(raw, core.curve_date(raw))[0]["points"]
    assert c["1M"] == {"value": 2.46, "date": "2026-10-28", "kind": "W", "label": "weekly observation"}
    assert c["30Y"]["kind"] == "B" and c["30Y"]["value"] == 4.11
    assert core.tenor_labels(raw) == {"30Y": "30Y (long-term benchmark)"}


# ---------------------------------------------------------------- Y6: Japan

def test_Y6_japan_curve_csv_and_result_page():
    cme = jp.parse_cme((YF / "jp_cme.csv").read_bytes())
    assert cme["10Y"][-1] == (D("2026-11-04"), 2.855) and cme["30Y"][-1][1] == 3.979 and cme["1Y"][0] == (D("2026-11-02"), 1.671)
    r = jp.parse_result((YF / "mof_result_20261106.htm").read_bytes())
    assert r == {"no": 1417, "issue": D("2026-11-09"), "maturity": D("2027-02-15"), "days": 98, "value": 1.241}
    with pytest.raises(ValueError):
        jp.parse_result(b"<html>nothing</html>")


def test_Y6_japan_scan_probes_only_new_weekdays_and_keeps_state():
    page = (YF / "mof_result_20261106.htm").read_bytes()
    calls = []

    def route(url, params):
        calls.append(url[-12:-4])
        return page if url.endswith("resul20261106.htm") else None            # everything else is a 404
    cme = (YF / "jp_cme.csv").read_bytes()
    g = FakeGetter({"jgbcme_all.csv": cme, "tbill_nyusatsu": route})
    raw = jp.fetch(g, TODAY, prev=None)
    assert 325 <= len(calls) <= 335                      # about 460 days of weekdays on a first run (once)
    assert raw.extra["scanned_through"] == "2026-11-05" and raw.extra["auction_log"][0]["value"] == 1.241
    calls.clear()
    raw2 = jp.fetch(g, D("2026-11-13"), prev=raw.extra)
    assert sorted(set(calls)) == [f"202611{n:02d}" for n in (6, 9, 10, 11, 12, 13)]    # resumes from the day after scanned_through
    assert len(raw2.extra["auction_log"]) == 1                                  # the re-probed day is not duplicated
    a = core.point_at(raw2, "3M", D("2026-11-13"))
    assert a == {"value": 1.241, "date": "2026-11-06", "kind": "A", "days": 98}
    assert core.point_at(raw2, "1M", D("2026-11-13")) is None and "1M" in raw2.gaps


def test_Y6_japan_first_run_reaches_back_far_enough_for_the_one_year_earlier_curve():
    page = (YF / "mof_result_20261106.htm").read_bytes()
    old = TODAY - timedelta(days=420)                                           # an auction 420 days ago (a weekday)
    while old.weekday() > 4:
        old -= timedelta(days=1)
    want = f"resul{old:%Y%m%d}.htm"
    g = FakeGetter({"jgbcme_all.csv": (YF / "jp_cme.csv").read_bytes(), "tbill_nyusatsu": lambda url, p: page if url.endswith(want) else None})
    raw = jp.fetch(g, TODAY, prev=None)
    assert jp.INITIAL_DAYS >= 455                                              # 365 days + the 90-day auction rule
    assert raw.extra["auction_log"][0]["date"] == old.isoformat()
    year_ago = TODAY - timedelta(days=365)
    p = core.point_at(raw, "3M", year_ago)
    assert p and p["kind"] == "A" and p["date"] == old.isoformat() and p["days"] == 98   # the old curve has its 3M point from run one


# ---------------------------------------------------------------- Y7: Germany

def bubill_xlsx(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([None] * 19)
    for auction, mat, y in rows:
        ws.append(["1", datetime.combine(auction, datetime.min.time()), "DE000BU0E378", "Bubill", None,
                   datetime.combine(mat, datetime.min.time()), "12 M", 2000, "R", "M-A", 1, 1, 1, 1, 99.0, 99.0, y, 1, 2.0])
    ws.append(["2", datetime(2026, 1, 6), "DE000BU22114", "Schatz", 0.02, datetime(2027, 12, 16), "2 Y", 6000, "R", "Auc", 1, 1, 1, 1, 99, 99, 2.11, 1, 1.9])
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def test_Y7_germany_curve_columns_and_bubill_reopening_is_3m():
    p = de.parse_bbk((YF / "bbk.csv").read_bytes())
    assert p["6M"][-1] == (D("2026-11-05"), 2.77) and (D("2026-10-31"), 2.0) not in p["6M"]
    assert [d for d, _ in p["10Y"]][:3] == [D("2026-10-27"), D("2026-10-28"), D("2026-10-29")] and len(p) == 6
    xl = bubill_xlsx([(D("2026-10-05"), D("2027-01-13"), 2.586), (D("2026-11-02"), D("2027-02-17"), 2.67),
                      (D("2026-10-12"), D("2027-04-14"), 2.717)])
    aus = de.parse_bubills(xl)
    assert [a.days for a in aus] == [98, 105, 182] and aus[1].settle == D("2026-11-04")         # auction + 2 business days
    g = FakeGetter({"bundesbank.de": (YF / "bbk.csv").read_bytes(), "emissionsergebnisse": xl})
    raw = de.fetch(g, TODAY)
    c = core.build_curves(raw, D("2026-10-30"))[0]["points"]
    assert c["3M"] == {"value": 2.586, "date": "2026-10-05", "kind": "A", "days": 98}   # 2 Nov is after the curve date
    assert c["6M"]["kind"] == "D"                                                     # 6M keeps the curve: it is fresher
    assert "1M" not in c


def test_Y7_germany_history_workbook_gives_the_one_year_earlier_3m_point_and_is_optional():
    cur = bubill_xlsx([(D("2026-11-02"), D("2027-02-17"), 2.67)])
    hist = bubill_xlsx([(D("2025-10-20"), D("2026-01-14"), 1.711), (D("2026-11-02"), D("2027-02-17"), 2.67), (D("2015-01-05"), D("2015-04-01"), 0.1)])
    bbk = (YF / "bbk.csv").read_bytes()
    raw = de.fetch(FakeGetter({"bundesbank.de": bbk, "emissionsergebnisse": cur, "emissionshistorie": hist}), TODAY)
    assert len([a for a in raw.auctions["3M"] if a.date == D("2026-11-02")]) == 1       # the overlap is not duplicated
    assert not [a for a in raw.auctions["3M"] if a.date.year == 2015]                  # old years are dropped
    p = core.point_at(raw, "3M", D("2025-11-05"))
    assert p == {"value": 1.711, "date": "2025-10-20", "kind": "A", "days": 84}
    def broken(url, params):
        raise OSError("download failed")
    raw2 = de.fetch(FakeGetter({"bundesbank.de": bbk, "emissionsergebnisse": cur, "emissionshistorie": broken}), TODAY)
    assert core.point_at(raw2, "3M", D("2026-11-05"))["value"] == 2.67                  # the latest 3M is unaffected
    assert core.point_at(raw2, "3M", D("2025-11-05")) is None and "not used" in raw2.extra["history_workbook"]


# ---------------------------------------------------------------- Y8: Spain

def test_Y8_spain_buckets_and_exact_1y_fallback():
    p = es.parse((YF / "es_ti_1_3.csv").read_bytes(), D("2025-01-01"))
    assert (D("2026-10-30"), 2.514) in p["3M"] and (D("2026-10-30"), 2.947) in p["1Y_bucket"]
    assert all(d != D("2026-10-30") for d, _ in p["1Y_exact"])                         # blank that day
    g = FakeGetter({"ti_1_3.csv": (YF / "es_ti_1_3.csv").read_bytes()})
    raw = es.fetch(g, TODAY)
    assert core.curve_date(raw) == D("2026-11-03")
    on30 = {t: core.point_at(raw, t, D("2026-10-30")) for t in ("3M", "1Y")}
    assert on30["3M"]["kind"] == "B" and on30["3M"]["label"] == "Letras 1-3 month bucket"
    assert on30["1Y"]["kind"] == "B" and on30["1Y"]["value"] == 2.947 and "6-12" in on30["1Y"]["label"]
    assert set(raw.gaps) == {"1M", "30Y"}


# ---------------------------------------------------------------- Y9: Switzerland

def efv_xlsx():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "2026"
    ws.append(["Auktion", "Liberierung", "Fälligkeit", "Laufzeit (Tage)", "ISIN", "a", "b", "c", "Preis", "Rendite p.a."])
    ws.append(["Auction", "Settlement", "Maturity", "Maturity period (days)", "ISIN", "a", "b", "c", "Price", "Yield p.a."])
    ws.append([datetime(2026, 10, 27), datetime(2026, 10, 29), datetime(2027, 1, 28), 91, "CH1", 1, 1, 1, 100.0, -0.001107])
    ws.append([datetime(2026, 9, 22), datetime(2026, 9, 24), datetime(2027, 3, 25), 182, "CH2", 1, 1, 1, 100.0, 0.000079])
    old = wb.create_sheet("2025")             # older sheets have an extra 'Series' column before the ISIN
    old.append(["Auction", "Settlement", "Maturity", "Maturity period (days)", "Series", "ISIN", "a", "b", "c", "Price", "Yield p.a."])
    old.append([datetime(2025, 1, 7), datetime(2025, 1, 9), datetime(2025, 4, 10), 91, 3.8065, "CH3", 1, 1, 1, 99.9, 0.003247])
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def test_Y9_switzerland_cube_and_auction_workbook():
    cube = ch.parse_cube((YF / "snb_cube.csv").read_bytes())
    assert cube["10Y"][-1] == (D("2026-10-30"), 0.505) and cube["30Y"][-1][1] == 0.508
    aus = ch.parse_auctions(efv_xlsx(), 2025)
    assert [(a.days, round(a.value, 4)) for a in aus] == [(91, -0.1107), (182, 0.0079), (91, 0.3247)]    # fraction -> percent
    page = b'<a href="https://www.efv.admin.ch/dam/en/sd-web/d9FElh8dV0db/resultate-gmbf.xlsx">x</a>'
    g = FakeGetter({"data.snb.ch": (YF / "snb_cube.csv").read_bytes(), "marketoperations": page, "resultate-gmbf": efv_xlsx()})
    raw = ch.fetch(g, TODAY)
    c = core.build_curves(raw, D("2026-10-30"))[0]["points"]
    assert c["3M"]["date"] == "2026-10-27" and c["3M"]["days"] == 91 and c["6M"]["date"] == "2026-09-22"
    with pytest.raises(ValueError, match="no longer links"):
        ch.fetch(FakeGetter({"data.snb.ch": (YF / "snb_cube.csv").read_bytes(), "marketoperations": b"<html></html>"}), TODAY)


# ---------------------------------------------------------------- Y10: Brazil and France

def test_Y10_brazil_vertices_and_holiday_retry():
    got = br.parse((YF / "anbima_20261030.csv").read_bytes())
    assert got[0] == D("2026-10-30") and got[1] == {"1M": 13.441, "3M": 13.6268, "6M": 13.8844, "1Y": 14.3249, "3Y": 15.2998, "5Y": 15.5646, "10Y": 15.3849}
    assert br.parse(b"Erro Titulo a Titulo") is None
    ok = (YF / "anbima_20261030.csv").read_bytes()
    asked = []

    def route(url, data):
        asked.append(data["Dt_Ref"])
        return ok if data["Dt_Ref"] == "30/10/2026" else b""                   # holidays and old dates come back empty
    raw = br.fetch(FakeGetter({"CZ-down.asp": route}), D("2026-11-02"))      # Monday: looks back over the last eight days
    assert "30/10/2026" in asked and "01/11/2026" not in asked and "31/10/2026" not in asked    # weekends are never asked
    assert core.curve_date(raw) == D("2026-10-30") and "30Y" in raw.gaps and "30Y" not in raw.series
    assert raw.extra["history"][0][0] == "2026-10-30"
    asked.clear()
    raw2 = br.fetch(FakeGetter({"CZ-down.asp": route}), D("2026-11-09"), prev=raw.extra)      # a week later: the history is kept
    assert core.curve_date(raw2) == D("2026-10-30") and "30/10/2026" not in asked              # (not asked again)
    assert core.point_at(raw2, "1Y", D("2026-10-30"))["value"] == 14.3249


def test_Y10_france_skipped_without_secret_and_sends_header_with_it():
    with pytest.raises(Skipped):
        fr.fetch(FakeGetter({}), TODAY, env={})
    j = lambda vals: json.dumps({"dataSets": [{"series": {"0:0": {"observations": {str(i): [v] for i, v in enumerate(vals)}}}}],
                                 "structure": {"dimensions": {"observation": [{"values": [{"id": "2026-10-29"}, {"id": "2026-10-30"}]}]}}}).encode()
    seen = {}

    class G(FakeGetter):
        def get(self, url, *, params=None, headers=None):
            seen[url] = headers
            return j([3.1, 3.2])
    raw = fr.fetch(G({}), TODAY, env={"FR_WEBSTAT_CLIENT_ID": "abc"})
    assert all(h["X-IBM-Client-Id"] == "abc" for h in seen.values()) and "X-IBM-Client-Secret" not in next(iter(seen.values()))
    assert set(raw.series) == {"1Y", "5Y", "10Y", "30Y"} and "3Y" in raw.gaps
    assert fr.META["status"] == "untested"
    assert any(u.endswith("FM.D.FR.EUR.FR2.BB.FRMOYTEC10.HSTA") for u in seen)


# ---------------------------------------------------------------- Y11-Y17: the job

def stub(code, last="2026-10-30", value=4.0, fail=None, skip=False, n=4):
    def fetch(g, today, env=None, prev=None):
        if skip:
            raise Skipped("no secret")
        if fail:
            raise RuntimeError(fail)
        d = D(last)
        raw = Raw()
        for t in core.TENORS[:n]:
            raw.series[t] = [Series("D", [(d, value), (date(d.year - 1, d.month, d.day), value - 1)], max_lag=5)]
        return raw
    return SimpleNamespace(fetch=fetch, META={"name": code.upper(), "source": "stub", "source_url": "https://x", "terms": "t"})


def run_job(tmp_path, stubs, monkeypatch, cfg=None, env=None, today=TODAY, now=NOW):
    monkeypatch.setattr(job, "adapter", lambda code: stubs[code])
    return job.run(cfg or {"countries": list(stubs)}, None, today=today, now=now, data_dir=tmp_path / "data",
                   work_dir=tmp_path / "work", env=env or {})


def test_Y11_all_countries_publish_manifest_and_status(tmp_path, monkeypatch):
    res = run_job(tmp_path, {"aa": stub("aa"), "bb": stub("bb", value=2.0)}, monkeypatch)
    assert res["ok"] == ["aa", "bb"] and res["order"][-1] == "manifest.json"
    man = json.loads((tmp_path / "data" / "manifest.json").read_text())
    assert man["yields"]["aa"] == {"path": "yields/aa.json", "as_of": "2026-10-30", "stale": False, "status": "ok", "name": "AA"}
    st = json.loads((tmp_path / "data" / "status.json").read_text())["sources"]["yield_curves"]
    assert st["items_ok"] == 2 and st["items_total"] == 2 and st["expected_cadence_hours"] == 168 and st["stale"] is False
    doc = json.loads((tmp_path / "data" / "yields" / "aa.json").read_text())
    assert [c["id"] for c in doc["curves"]] == ["latest", "1m", "3m", "1y"] and doc["curves"][3]["points"]["1M"]["value"] == 3.0


def test_Y12_one_country_failing_keeps_its_last_good_file_and_marks_it_stale(tmp_path, monkeypatch):
    run_job(tmp_path, {"aa": stub("aa"), "bb": stub("bb")}, monkeypatch)
    good = json.loads((tmp_path / "data" / "yields" / "bb.json").read_text())
    res = run_job(tmp_path, {"aa": stub("aa"), "bb": stub("bb", fail="boom")}, monkeypatch,
                  now=datetime(2026, 11, 13, 15, 47, tzinfo=timezone.utc), today=date(2026, 11, 13))
    assert res["ok"] == ["aa"] and res["failed"] == ["bb: boom"]
    bb = json.loads((tmp_path / "data" / "yields" / "bb.json").read_text())
    assert bb["stale"] is True and bb["stale_reason"] == "fetch_or_parse_failed"
    assert bb["curves"] == good["curves"] and bb["last_success"] == good["last_success"]
    man = json.loads((tmp_path / "data" / "manifest.json").read_text())
    assert man["yields"]["bb"]["stale"] is True
    st = json.loads((tmp_path / "data" / "status.json").read_text())["sources"]["yield_curves"]
    assert st["ok"] is False and st["stale"] is True and st["failed"] == ["bb: boom"]


def test_Y13_every_country_failing_publishes_nothing(tmp_path, monkeypatch):
    run_job(tmp_path, {"aa": stub("aa")}, monkeypatch)
    before = tree_hash(tmp_path / "data")
    with pytest.raises(job.NothingFetched):
        run_job(tmp_path, {"aa": stub("aa", fail="down")}, monkeypatch)
    assert tree_hash(tmp_path / "data") == before


def test_Y14_a_skipped_country_is_quiet_not_stale_not_counted(tmp_path, monkeypatch):
    res = run_job(tmp_path, {"aa": stub("aa"), "fr": stub("fr", skip=True)}, monkeypatch)
    assert res["skipped"] == ["fr: no secret"] and res["failed"] == []
    assert not (tmp_path / "data" / "yields" / "fr.json").exists()
    st = json.loads((tmp_path / "data" / "status.json").read_text())["sources"]["yield_curves"]
    assert st["items_total"] == 1 and st["ok"] is True and st["stale"] is False and st["skipped"] == ["fr: no secret"]
    man = json.loads((tmp_path / "data" / "manifest.json").read_text())
    assert "fr" not in man["yields"]


def test_Y15_validation_rejects_frozen_source_big_move_and_thin_curves(tmp_path, monkeypatch):
    with pytest.raises(job.NothingFetched, match="21 days old|days old"):
        run_job(tmp_path, {"aa": stub("aa", last="2026-09-01")}, monkeypatch)
    with pytest.raises(job.NothingFetched, match="only 2 tenors"):
        run_job(tmp_path, {"aa": stub("aa", n=2)}, monkeypatch)
    with pytest.raises(job.NothingFetched, match="outside -3..40"):
        run_job(tmp_path, {"aa": stub("aa", value=55.0)}, monkeypatch)
    run_job(tmp_path, {"aa": stub("aa")}, monkeypatch)
    res = run_job(tmp_path, {"aa": stub("aa", value=7.5, last="2026-11-05"), "bb": stub("bb")}, monkeypatch)
    assert res["failed"] == [f for f in res["failed"] if f.startswith("aa") and "moved" in f]    # +3.5 pp in a week: refused
    assert json.loads((tmp_path / "data" / "yields" / "aa.json").read_text())["stale"] is True


def test_Y16_markets_and_pe_runs_keep_the_yields_in_the_manifest(tmp_path, monkeypatch, cfg):
    from conftest import fixture_fetch
    run_job(tmp_path, {"aa": stub("aa")}, monkeypatch)
    today = date(2026, 11, 4)
    markets.run(cfg, fixture_fetch(today), today=today, now=datetime(2026, 11, 4, 22, 41, tzinfo=timezone.utc),
                data_dir=tmp_path / "data", work_dir=tmp_path / "work", delay=0, sleep=lambda s: None)
    man = json.loads((tmp_path / "data" / "manifest.json").read_text())
    assert "aa" in man["yields"] and "m1-demo" in man["sections"]
    st = json.loads((tmp_path / "data" / "status.json").read_text())["sources"]
    assert "yield_curves" in st and "yahoo_markets" in st                         # each job only touches its own block
    assert (tmp_path / "data" / "yields" / "aa.json").exists()


def test_Y17_files_are_staged_not_written_in_place(tmp_path, monkeypatch):
    run_job(tmp_path, {"aa": stub("aa")}, monkeypatch)
    before = tree_hash(tmp_path / "data")
    seen = {}

    def spy(code):
        def fetch(g, today, env=None, prev=None):
            seen["data_hash"] = tree_hash(tmp_path / "data")
            raise RuntimeError("stop")
        return SimpleNamespace(fetch=fetch, META={})
    monkeypatch.setattr(job, "adapter", spy)
    with pytest.raises(job.NothingFetched):
        job.run({"countries": ["aa"]}, None, today=TODAY, now=NOW, data_dir=tmp_path / "data", work_dir=tmp_path / "work", env={})
    assert seen["data_hash"] == before and tree_hash(tmp_path / "data") == before


def test_Y18_config_lists_the_launch_countries_and_every_adapter_imports():
    import yaml
    cfg = yaml.safe_load((Path(__file__).resolve().parent.parent / "config" / "yields.yaml").read_text())
    assert cfg["countries"] == ["us", "uk", "ca", "jp", "de", "es", "ch", "br", "fr"]
    for c in cfg["countries"]:
        m = job.adapter(c)
        assert {"name", "source", "source_url", "terms"} <= set(m.META) and callable(m.fetch)
    assert "it" not in cfg["countries"] and "in" not in cfg["countries"] and "cn" not in cfg["countries"]


# ---------------------------------------------------------------- Y19: Brazil history accumulates through the job

def test_Y19_brazil_weekly_snapshots_accumulate_and_earlier_curves_fill_in(tmp_path):
    """The real Brazil adapter through the real job, six Monday runs. The source serves only the last seven days of dates (as
    ANBIMA does), so each earlier curve can only appear once the job's own stored history reaches back far enough."""
    template = (YF / "anbima_20261030.csv").read_bytes().decode("latin-1")
    mondays = [date(2026, 10, 5), date(2026, 10, 12), date(2026, 10, 19), date(2026, 10, 26), date(2026, 11, 2), date(2026, 11, 9)]
    docs = []
    for run_day in mondays:
        def route(url, data, run_day=run_day):
            d = datetime.strptime(data["Dt_Ref"], "%d/%m/%Y").date()
            if not 1 <= (run_day - d).days <= 7 or d.weekday() > 4:
                return b""                                                      # older dates and weekends: empty file
            return template.replace("30/10/2026", d.strftime("%d/%m/%Y"), 1).encode("latin-1")
        job.run({"countries": ["br"]}, FakeGetter({"CZ-down.asp": route}), today=run_day,
                now=datetime(run_day.year, run_day.month, run_day.day, 15, 47, tzinfo=timezone.utc),
                data_dir=tmp_path / "data", work_dir=tmp_path / "work", env={})
        docs.append(json.loads((tmp_path / "data" / "yields" / "br.json").read_text()))
    first, last = docs[0], docs[-1]
    n_first, n_last = len(first["state"]["history"]), len(last["state"]["history"])
    assert n_last > n_first >= 3                                                # snapshots are stored and kept run after run
    assert [c["points"] == {} for c in first["curves"][1:]] == [True, True, True]      # nothing to compare with yet
    assert last["curves"][0]["date"] == "2026-11-06" and len(last["curves"][0]["points"]) == 7
    by = {c["id"]: c for c in last["curves"]}
    assert len(by["1m"]["points"]) == 7 and by["1m"]["date"] == "2026-10-06"          # a month of history is enough for the 1M curve
    assert by["3m"]["points"] == {} and by["1y"]["points"] == {}                      # not yet: left empty, never stretched
    assert "30Y" not in by["latest"]["points"]
