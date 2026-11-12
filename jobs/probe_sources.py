"""Manual probe: from wherever this runs (GitHub's servers when run by the probe-sources workflow), fetch ONE small
page or file from Yahoo, worldperatio and every yield-curve source in docs/yield-sources.md, and report which were
reachable. Publishes nothing; always exits 0 (the report is the result)."""
from __future__ import annotations

import os
import re
import sys
import time
from datetime import date, timedelta

import requests

UA = "Mozilla/5.0 (compatible; vasconomics-source-probe/1.0; personal non-commercial)"
TIMEOUT = 40
today = date.today()
ym = today.strftime("%Y%m")
since = (today - timedelta(days=10)).isoformat()


def _get(url, **kw):
    headers = {"User-Agent": UA, **kw.pop("headers", {})}
    return requests.get(url, headers=headers, timeout=TIMEOUT, **kw)


def _stream_head(url, n=2048):
    r = _get(url, stream=True)
    chunk = next(r.iter_content(n), b"")
    r.close()
    r._content = chunk  # noqa: SLF001 - keep only the first bytes
    return r


def p_yahoo():
    from yahooquery import Ticker
    h = Ticker("SXR8.DE").history(period="5d")
    if isinstance(h, dict) or h is None or len(h) == 0:
        raise RuntimeError(f"no rows: {h}")
    return 200, f"{len(h)} daily rows, last {h.index.get_level_values(-1).max()}"


def p_worldperatio():
    r = _get("https://worldperatio.com/index/sp-500/")
    ok = "detailPE_data" in r.text
    return r.status_code, f"{len(r.content)} bytes; detailPE_data {'present' if ok else 'MISSING'}", ok


def p_snb_efv():
    page = _get("https://marketoperations.snb.ch/en/mmdrc").text
    m = re.search(r'https://www\.efv\.admin\.ch/dam/[^"\']+resultate-gmbf\.xlsx', page)
    if not m:
        return 200, "SNB page reachable but the EFV link was not found", False
    r = _stream_head(m.group(0))
    return r.status_code, f"{m.group(0)} first bytes {r.content[:2]!r}", r.content[:2] == b"PK"


def p_anbima():
    """Try the last few weekdays: a Brazilian holiday returns an empty file, which is not a failure of the source."""
    r = None
    d = today
    for _ in range(4):
        d -= timedelta(days=1)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        r = requests.post("https://www.anbima.com.br/informacoes/est-termo/CZ-down.asp",
                          data={"Idioma": "PT", "Dt_Ref": d.strftime("%d/%m/%Y"), "saida": "csv"},
                          headers={"User-Agent": UA}, timeout=TIMEOUT)
        if "PREFIXADOS" in r.text:
            return r.status_code, f"{len(r.content)} bytes; curve params present for {d.isoformat()}", True
        time.sleep(2)
    return r.status_code, f"{len(r.content)} bytes; no curve in the last 4 weekdays", False


_WGB = {}          # one headless Chromium for every worldgovernmentbonds.com probe (pages 5 s apart; a challenge stops the rest)


def _wgb_pager():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from dashjobs.yields import wgb

    if "pager" not in _WGB:
        _WGB["pager"] = wgb.BrowserPager()
    return wgb, _WGB["pager"]


# Fewest of our tenors for "reachable": the US page has all 8; South Africa, the thinnest, had 4 on 12 Nov 2026.
WGB_MIN_TENORS = {"us": 6}


def p_wgb(code: str = "us"):
    """worldgovernmentbonds.com: one country page in a headless Chromium (browser defaults), the table read as the job reads it."""
    def probe():
        wgb, pager = _wgb_pager()
        try:
            html = pager.load(wgb.meta(code)["source_url"])
        except wgb.Challenge as e:
            if pager.blocked and str(e).startswith("not loaded"):
                return "-", f"not requested: {e}", False                  # an earlier page was the challenge
            return 403, f"challenge or refusal: {e}", False
        page = wgb.parse_page(html)
        ours = [r["tenor"] for r in page["rows"] if r["tenor"]]
        need = WGB_MIN_TENORS.get(code, 3)
        return 200, f"{len(page['rows'])} rows, our tenors {ours}, page updated {page['updated']:%d %b %Y %H:%M} UTC", len(ours) >= need
    return probe


def close_wgb():
    if "pager" in _WGB:
        _WGB.pop("pager").close()


# (group, name, callable returning (status, detail[, ok]))
PROBES = [
    ("Prices", "Yahoo Finance (yahooquery, SXR8.DE 5d)", p_yahoo),
    ("Yield", "worldgovernmentbonds.com US page in a headless browser (the source of every country since round 17)", p_wgb("us")),
    *[("Yield", f"worldgovernmentbonds.com {n} page in the same browser (round 18)", p_wgb(c))
      for c, n in (("pl", "Poland"), ("pt", "Portugal"), ("ru", "Russia"), ("tr", "Turkey"), ("za", "South Africa"))],
    ("P/E", "worldperatio.com S&P 500 page", p_worldperatio),
    ("Yield", "US Treasury par curve XML (current month)",
     lambda: (lambda r: (r.status_code, f"{len(r.content)} bytes; {'BC_10YEAR' in r.text and 'BC_10YEAR present' or 'no BC_10YEAR'}", 'BC_10YEAR' in r.text))(
         _get(f"https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value_month={ym}"))),
    ("Yield", "Bank of England GLC zip (latest month)",
     lambda: (lambda r: (r.status_code, f"{len(r.content)} bytes (stream head); zip magic {r.content[:2]!r}", r.content[:2] == b'PK'))(
         _stream_head("https://www.bankofengland.co.uk/-/media/boe/files/statistics/yield-curves/latest-yield-curve-data.zip"))),
    ("Yield", "Bank of Canada Valet, benchmark bonds",
     lambda: (lambda r: (r.status_code, f"{len(r.content)} bytes", '"observations"' in r.text))(
         _get(f"https://www.bankofcanada.ca/valet/observations/group/bond_yields_benchmark/json?start_date={since}"))),
    ("Yield", "Bank of Canada Valet, T-bills",
     lambda: (lambda r: (r.status_code, f"{len(r.content)} bytes", '"observations"' in r.text))(
         _get(f"https://www.bankofcanada.ca/valet/observations/V80691342,V80691344,V80691345,V80691346/json?start_date={since}"))),
    ("Yield", "Japan MOF jgbcme.csv",
     lambda: (lambda r: (r.status_code, f"{len(r.content)} bytes", b'30Y' in r.content))(
         _get("https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/jgbcme.csv"))),
    ("Yield", "Japan MOF per-auction result page (6 Nov 2026, a permanent page; the job probes recent dates)",
     lambda: (lambda r: (r.status_code, f"{len(r.content)} bytes", r.status_code == 200 and "国庫短期証券".encode() in r.content))(
         _get("https://www.mof.go.jp/jgbs/auction/calendar/tbill/tbill_nyusatsu/resul20261106.htm"))),
    ("Yield", "Japan MOF jgbcme_all.csv (history, head only)",
     lambda: (lambda r: (r.status_code, f"stream head {len(r.content)} bytes", b'Date' in r.content or b'Interest' in r.content))(
         _stream_head("https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/historical/jgbcme_all.csv", 4096))),
    ("Yield", "UK DMO Treasury bill data report (expect bot protection; not used)",
     lambda: (lambda r: (r.status_code, "BOT-PROTECTED (captcha page)" if "ShieldSquare" in r.text else f"{len(r.content)} bytes", "ShieldSquare" not in r.text and r.status_code == 200))(
         _get("https://www.dmo.gov.uk/data/XmlDataReport?reportCode=D2.2A"))),
    ("Yield", "Bundesbank BBSIS 10Y (csv)",
     lambda: (lambda r: (r.status_code, f"{len(r.content)} bytes", r.status_code == 200 and b'R10XX' in r.content))(
         _get(f"https://api.statistiken.bundesbank.de/rest/data/BBSIS/D.I.ZST.ZI.EUR.S1311.B.A604.R10XX.R.A.A._Z._Z.A?startPeriod={since}&format=csv&lang=en"))),
    ("Yield", "Finanzagentur Bubill auction results xlsx",
     lambda: (lambda r: (r.status_code, f"stream head {r.content[:2]!r}", r.content[:2] == b'PK'))(
         _stream_head("https://www.deutsche-finanzagentur.de/fileadmin/user_upload/Institutionelle-investoren/auktionen/emissionsergebnisse_aktuell_en.xlsx"))),
    ("Yield", "Banque de France Webstat Explore API (anonymous call is refused: 401/403/404)",
     lambda: (lambda r: (r.status_code, "reachable; refused without a key, as expected" if r.status_code in (401, 403, 404) else r.text[:60], r.status_code in (200, 401, 403, 404)))(
         _get("https://webstat.banque-france.fr/api/explore/v2.1/catalog/datasets/observations/records?limit=1"))),
    ("Yield", "Webstat 13-week BTF monthly series (France 3M; anonymous call is refused, as above)",
     lambda: (lambda r: (r.status_code, "reachable; refused without a key, as expected" if r.status_code in (401, 403, 404) else r.text[:60], r.status_code in (200, 401, 403, 404)))(
         _get("https://webstat.banque-france.fr/api/explore/v2.1/catalog/datasets/observations/records?limit=1&where=series_key%3D%22FM.M.FR.EUR.FR2.MM.TMB.HSTA%22"))),
    ("Yield", "Ministry of Finance mirror of AFT pages (expect a certificate for its 'unavailable' host; not used)",
     lambda: (lambda r: (r.status_code, f"{len(r.content)} bytes", r.status_code == 200))(_get("https://applis.finances.gouv.fr/en/node/12995"))),
    ("Yield", "Italy MEF auction results page, 10-year BTP (PDF links)",
     lambda: (lambda r: (r.status_code, f"{len(r.content)} bytes; {r.text.count('Auction-Results')} result-PDF links listed", 'Auction-Results' in r.text))(
         _get("https://www.dt.mef.gov.it/en/debito_pubblico/emissioni_titoli_di_stato_interni/risultati_aste/risultati_aste_btp_10_anni/index.html", params={"selezione-anno": str(today.year)}))),
    ("Yield", "RBA table F2 (Australia 3Y, 5Y, 10Y; head only)",
     lambda: (lambda r: (r.status_code, f"stream head {len(r.content)} bytes", b'FCMYGBAG10D' in r.content or b'CAPITAL MARKET YIELDS' in r.content))(
         _stream_head("https://www.rba.gov.au/statistics/tables/csv/f2-data.csv", 4096))),
    ("Yield", "RBA table F16 (Australia 1Y and 30Y bond buckets; head only)",
     lambda: (lambda r: (r.status_code, f"stream head {len(r.content)} bytes", b'INDICATIVE MID RATES' in r.content))(
         _stream_head("https://www.rba.gov.au/statistics/tables/csv/f16-data.csv", 4096))),
    ("Yield", "AOFM Treasury Notes page (no answer to plain requests on 11 Nov 2026; not used)",
     lambda: (lambda r: (r.status_code, f"{len(r.content)} bytes", r.status_code == 200))(_get("https://www.aofm.gov.au/securities/treasury-notes"))),
    ("Yield", "RBI press releases (India T-bill and Government Stock auction results)",
     lambda: (lambda r: (r.status_code, f"{len(r.content)} bytes; {r.text.count('Full Auction Result')} 'Full Auction Result' links", 'Full Auction Result' in r.text))(
         _get("https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx"))),
    ("Yield", "Banca d'Italia Infostat (expects a protected page)",
     lambda: (lambda r: (r.status_code, f"{len(r.content)} bytes; {'protected resource page' if 'Risorsa Protetta' in r.text else 'other'}", r.status_code == 200 and 'Risorsa Protetta' not in r.text))(
         _get("https://a2a.bancaditalia.it/infostat/dataservices/rest/dataflow"))),
    ("Yield", "Banco de España ti_1_3.csv",
     lambda: (lambda r: (r.status_code, f"stream head {len(r.content)} bytes", b'D_DTES00B7' in r.content or b'DTES' in r.content))(
         _stream_head("https://www.bde.es/webbe/es/estadisticas/compartido/datos/csv/ti_1_3.csv", 4096))),
    ("Yield", "SNB data portal cube rendeiduebd (since date)",
     lambda: (lambda r: (r.status_code, f"{len(r.content)} bytes", b'rendeiduebd' in r.content))(
         _get(f"https://data.snb.ch/api/cube/rendeiduebd/data/csv/en?fromDate={since}&dimSel=D0(CHF)"))),
    ("Yield", "SNB/EFV money market claims results (xlsx link found on SNB page)", p_snb_efv),
    ("Yield", "ANBIMA ETTJ (form POST, csv)", p_anbima),
    ("Yield", "CCIL India tenor-wise yields (expect geo-block)",
     lambda: (lambda r: (r.status_code, f"{len(r.content)} bytes; {'GEO-BLOCKED' if r.status_code == 403 else 'reachable'}", r.status_code == 200))(
         _get("https://www.ccilindia.com/web/ccil/tenorwise-indicative-yields"))),
    ("Yield", "FBIL home (JavaScript application)",
     lambda: (lambda r: (r.status_code, f"{len(r.content)} bytes", r.status_code == 200))(_get("https://www.fbil.org.in/"))),
    ("Yield", "ChinaBond yield page (terms forbid reproduction without permission; not used)",
     lambda: (lambda r: (r.status_code, f"{len(r.content)} bytes", r.status_code == 200))(
         _get("https://yield.chinabond.com.cn/cbweb-mn/yield_main?locale=en_US"))),
    ("Yield", "CFETS ChinaMoney English home (terms forbid reproduction and scraping; not used)",
     lambda: (lambda r: (r.status_code, f"{len(r.content)} bytes", r.status_code == 200))(_get("https://www.chinamoney.com.cn/english/"))),
]


def main() -> int:
    try:
        return _main()
    finally:
        close_wgb()


def _main() -> int:
    rows = []
    for group, name, fn in PROBES:
        t0 = time.time()
        try:
            res = fn()
            status, detail = res[0], res[1]
            ok = res[2] if len(res) > 2 else (status == 200)
            verdict = "reachable" if ok else ("blocked/needs attention" if status in (401, 403, 429) else "unexpected")
        except Exception as e:  # noqa: BLE001
            status, detail, verdict = "-", f"{type(e).__name__}: {str(e)[:120]}", "error"
        rows.append((group, name, status, verdict, detail, round(time.time() - t0, 1)))
        print(f"[{verdict:>22}] {name}: {status} {detail}", flush=True)
        time.sleep(2)  # one request at a time, politely
    lines = ["## probe-sources report", "", f"Run date {today.isoformat()} (UTC). Publishes nothing.", "",
             "| Group | Source | HTTP | Result | Detail | s |", "|---|---|---|---|---|---|"]
    lines += [f"| {g} | {n} | {s} | {v} | {d} | {t} |" for g, n, s, v, d, t in rows]
    text = "\n".join(lines) + "\n"
    summ = os.environ.get("GITHUB_STEP_SUMMARY")
    if summ:
        with open(summ, "a", encoding="utf-8") as f:
            f.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
