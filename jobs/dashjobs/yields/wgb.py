"""worldgovernmentbonds.com (decided 11 Nov 2026, round 17): each country page read as a normal visitor would, in a real
Chromium with the browser's own defaults (no header, user agent or cookie set by us), one page at a time, at least 5 s apart.
The page's own script fills the yield-curve table; we read the table it displays and never call the site's JSON endpoint.

From the table alone, per country:
  - latest           = Last (each row has its own date, "10 Nov");
  - 1 month earlier  = Last - Chg 1M,
  - 6 months earlier = Last - Chg 6M,
  - 1 year earlier   = Last - Chg 12M.
The change columns are in basis points and mean "Last minus the value that long ago" (verified 11 Nov 2026 against the US
Treasury, Bundesbank, Bank of England, Banque de France, Bank of Canada and Banco de Espana values a month and a year earlier:
Last - Chg matched within a few bp, Last + Chg was off by 20-300 bp). A missing change leaves that tenor empty on that earlier
curve; it is never guessed.

A challenge, captcha or 403 stops every further page load of the run (Challenge); a table that no longer looks as expected
raises LayoutChanged. Either way the country keeps its last good file and goes stale (job.py)."""
from __future__ import annotations

import re
import time
from datetime import date, datetime, timedelta

from dateutil.relativedelta import relativedelta

from .core import TENORS, Raw, Series

SITE = "https://www.worldgovernmentbonds.com"
DATA_ENDPOINT = "/wp-json/country/v1/main"           # the page's own request for the table (only its status is watched)
PAGE = SITE + "/country/{slug}/"
SOURCE = "World Government Bonds (worldgovernmentbonds.com), data from Investing.com and TradingEconomics"
TERMS = ("World Government Bonds: all rights reserved; the site credits Investing.com and TradingEconomics.com for its data. "
         "Read once a week per country as a normal visitor, in a browser.")
COUNTRIES = {
    "us": ("united-states", "United States"), "uk": ("united-kingdom", "United Kingdom"), "ca": ("canada", "Canada"),
    "jp": ("japan", "Japan"), "de": ("germany", "Germany"), "es": ("spain", "Spain"), "ch": ("switzerland", "Switzerland"),
    "br": ("brazil", "Brazil"), "fr": ("france", "France"), "it": ("italy", "Italy"), "au": ("australia", "Australia"),
    "in": ("india", "India"), "cn": ("china", "China"),
}
# Our tenors, as the site names its rows.
ROWS = {"1 month": "1M", "3 months": "3M", "6 months": "6M", "1 year": "1Y", "3 years": "3Y", "5 years": "5Y",
        "10 years": "10Y", "30 years": "30Y"}
# (curve offset, the site's change column, words for the tooltip)
CHANGES = [(relativedelta(months=1), "Chg 1M", "1-month"), (relativedelta(months=6), "Chg 6M", "6-month"),
           (relativedelta(years=1), "Chg 12M", "12-month")]
HEAD = ["Last", "Chg 1M", "Chg 6M", "Chg 12M"]       # the Annualized Yield columns, in this order
MAX_LAG = 7                                         # a row more than a week older than the newest row is left out
MIN_GAP_S = 5.0                                     # at least this long between two page loads
# Checked in the title always, and in the visible text only when the page has no yield table (a normal page may mention
# reCAPTCHA in a footer; a challenge page never shows the table).
CHALLENGE_MARKERS = ("just a moment", "cf-chl", "challenge-platform", "captcha", "verify you are human",
                     "attention required", "checking your browser", "are you a robot", "access denied")
ROW_DATE_SLACK = timedelta(days=2)                   # a row may be dated a day or two after the GMT update date (site time zone)
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


class Challenge(Exception):
    """The site answered with a challenge, a captcha or a refusal: stop loading its pages for the rest of the run."""


class LayoutChanged(ValueError):
    """The page no longer has the table we read, or its columns or units changed."""


def meta(code: str) -> dict:
    slug, name = COUNTRIES[code]
    return {"code": code, "name": name, "source": SOURCE, "source_url": PAGE.format(slug=slug), "terms": TERMS}


def _text(html: str) -> tuple[str, str]:
    from bs4 import BeautifulSoup

    s = BeautifulSoup(html, "html.parser")
    title = s.title.get_text(" ", strip=True) if s.title else ""
    for x in s(["script", "style", "noscript", "svg"]):
        x.decompose()
    return title, s.get_text(" ", strip=True)


def _has_table(html: str) -> bool:
    from bs4 import BeautifulSoup

    tb = BeautifulSoup(html, "html.parser").find("table", id="table-curve")
    return bool(tb and len(tb.find_all("td")) > 13)


def challenge_reason(html: str, status: int | None = None, api_statuses=()) -> str | None:
    """Why this page is a challenge or refusal, or None. Looks at the HTTP status of the page and of the page's own data
    request for the table (DATA_ENDPOINT; other requests on the page are ignored), at the title, and, when the page shows no
    yield table, at the visible text (never at scripts)."""
    if status in (401, 403, 429, 503):
        return f"HTTP {status} on the page"
    bad = [s for s in api_statuses if s in (401, 403, 429, 503)]
    if bad:
        return f"HTTP {bad[0]} on the page's own data request ({DATA_ENDPOINT})"
    title, text = _text(html)
    hay = title.lower() if _has_table(html) else (title + " " + text[:20000]).lower()
    hit = [m for m in CHALLENGE_MARKERS if m in hay]
    return f"challenge text on the page ({hit[0]!r})" if hit else None


def _num(cell: str, unit: str, what: str) -> float | None:
    c = cell.strip().replace("−", "-")
    if c in ("", "-", "--", "n/a", "N/A"):
        return None
    m = re.fullmatch(r"([+-]?\d{1,3}(?:,\d{3})*(?:\.\d+)?|[+-]?\d+(?:\.\d+)?)\s*" + re.escape(unit), c)
    if not m:
        raise LayoutChanged(f"{what} {cell!r} is not a number in {unit!r}")
    return float(m.group(1).replace(",", ""))


def _row_date(cell: str, updated: date) -> date:
    m = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]{3})", cell.strip())
    if not m or m.group(2).lower() not in MONTHS:
        raise LayoutChanged(f"row date {cell!r} not recognised")
    d = date(updated.year, MONTHS[m.group(2).lower()], int(m.group(1)))
    if d <= updated + ROW_DATE_SLACK:              # "11 Nov" on a page updated "10 Nov, 23:30 GMT" is this year's
        return d
    return date(updated.year - 1, d.month, d.day)  # "28 Dec" read on 3 Jan is last year's


def parse_page(html: str) -> dict:
    """{'updated': datetime (UTC), 'rows': [{'maturity', 'tenor' or None, 'date', 'last', 'Chg 1M', 'Chg 6M', 'Chg 12M'}]}.
    Raises LayoutChanged when the yield-curve table or the page's update time is not where it was on 11 Nov 2026."""
    from bs4 import BeautifulSoup

    s = BeautifulSoup(html, "html.parser")
    tb = s.find("table", id="table-curve")
    if tb is None:
        raise LayoutChanged("no yield-curve table (#table-curve) on the page")
    trs = tb.find_all("tr")
    heads = [[c.get_text(" ", strip=True) for c in tr.find_all("th")] for tr in trs if tr.find("th")]
    top = " | ".join(heads[0]) if heads else ""
    if len(heads) < 2 or "Residual Maturity" not in top or "Annualized Yield" not in top or heads[1][:4] != HEAD:
        raise LayoutChanged(f"yield-curve table header changed: {heads[:2]}")
    _, text = _text(html)
    m = re.search(r"Last Update:\s*(\d{1,2}) ([A-Za-z]{3}) (\d{4}), (\d{1,2}):(\d{2})\s*GMT\+0", text)
    if not m or m.group(2).lower() not in MONTHS:
        raise LayoutChanged("the page's 'Last Update: <date>, <time> GMT+0' line was not found")
    updated = datetime(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)), int(m.group(4)), int(m.group(5)))
    rows = []
    for tr in trs:
        cells = [c.get_text(" ", strip=True) for c in tr.find_all("td")]
        if not cells:
            continue
        if len(cells) < 13:
            raise LayoutChanged(f"a yield-curve row has {len(cells)} cells, expected 13: {cells[:3]}")
        mat = re.sub(r"\s+", " ", cells[1]).strip()
        rows.append({"maturity": mat, "tenor": ROWS.get(mat.lower()), "date": _row_date(cells[12], updated.date()),
                     "last": _num(cells[2], "%", f"{mat} Last"),
                     **{h: _num(cells[3 + i], "bp", f"{mat} {h}") for i, h in enumerate(HEAD[1:])}})
    if not rows:
        raise LayoutChanged("the yield-curve table has no rows")
    return {"updated": updated, "rows": rows}


def earlier(last: float | None, chg_bp: float | None) -> float | None:
    """The value on an earlier date: Last minus the change (bp -> percentage points). None if either is missing."""
    if last is None or chg_bp is None:
        return None
    return round(last - chg_bp / 100.0, 4)


def raw_from_page(code: str, page: dict, prev: dict | None = None) -> Raw:
    """Series for core.build_curves: per tenor the latest quote (kind D) and the three derived earlier values (kind C), each
    dated from its own row's date. Tenors the site does not list are gaps."""
    name = COUNTRIES[code][1]
    rows = {r["tenor"]: r for r in page["rows"] if r["tenor"] and r["last"] is not None}
    if len(rows) < 3:
        raise LayoutChanged(f"only {len(rows)} of our tenors in the table ({[r['maturity'] for r in page['rows']]})")
    raw = Raw()
    for t, r in rows.items():
        d = r["date"]
        derived, labels = [], {}
        for delta, col, words in CHANGES:
            v = earlier(r["last"], r[col])
            if v is not None:
                derived.append((d - delta, v))
                labels[d - delta] = f"derived from the site's {words} change column (latest minus {col})"
        raw.series[t] = [Series("D", [(d, r["last"])], max_lag=MAX_LAG),
                         Series("C", derived, max_lag=MAX_LAG, labels=labels)]
    raw.gaps = {t: f"World Government Bonds lists no {t} row for {name}." for t in TENORS if t not in rows}
    keep = {k: v for k, v in (prev or {}).items() if not k.startswith("wgb_")}      # an official adapter's state survives a switch
    raw.extra = keep | {"wgb_page_updated": page["updated"].strftime("%Y-%m-%dT%H:%MZ"),
                        "wgb_other_rows": [r["maturity"] for r in page["rows"] if not r["tenor"]]}
    return raw


def fetch(code: str, pager, today: date, prev: dict | None = None) -> Raw:
    page = parse_page(pager.load(meta(code)["source_url"]))
    if page["updated"].date() > today + timedelta(days=1):
        raise LayoutChanged(f"page update time {page['updated']} is after the run date {today}")
    return raw_from_page(code, page, prev)


class BrowserPager:
    """One headless Chromium for the whole run, opened on first use. Browser defaults only: no header, user agent or cookie
    of ours. Pages load one at a time, at least MIN_GAP_S apart. The first challenge or refusal blocks every later load."""

    def __init__(self, headless: bool = True, min_gap: float = MIN_GAP_S, sleep=time.sleep, clock=time.monotonic):
        self.headless, self.min_gap, self.sleep, self.clock = headless, min_gap, sleep, clock
        self.blocked: str | None = None
        self.broken: str | None = None             # the browser could not start: every later load fails at once with why
        self.loads = 0
        self._pw = self._browser = self._page = None
        self._last = None
        self._api: list[int] = []

    def _open(self):
        try:
            from playwright.sync_api import sync_playwright

            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=self.headless)
            self._page = self._browser.new_context().new_page()
        except Exception as e:
            self.broken = f"the browser could not start: {type(e).__name__}: {str(e)[:120]}"
            self.close()
            raise RuntimeError(self.broken) from e
        self._page.on("response", lambda r: self._api.append(r.status) if DATA_ENDPOINT in r.url else None)

    def load(self, url: str) -> str:
        if self.blocked:
            raise Challenge(f"not loaded: the run stopped at a challenge page ({self.blocked})")
        if self.broken:
            raise RuntimeError(self.broken)
        if self._page is None:
            self._open()
        if self._last is not None:
            wait = self.min_gap - (self.clock() - self._last)
            if wait > 0:
                self.sleep(wait)
        self._api.clear()
        try:
            resp = self._page.goto(url, wait_until="domcontentloaded", timeout=60000)
            try:      # the page's own script fills the table; a page without it is judged below (challenge or layout)
                self._page.wait_for_function(
                    "() => { const t = document.querySelector('#table-curve');"
                    " return t && t.querySelectorAll('td').length > 13 && t.innerText.includes('%'); }", timeout=30000)
            except Exception:  # noqa: BLE001
                pass
            html = self._page.content()
        finally:
            self._last = self.clock()
            self.loads += 1
        why = challenge_reason(html, resp.status if resp else None, list(self._api))
        if why:
            self.blocked = why
            raise Challenge(why)
        return html

    def close(self):
        """Never raises: a browser that will not close must not cost the run its results."""
        for step in (lambda: self._browser and self._browser.close(), lambda: self._pw and self._pw.stop()):
            try:
                step()
            except Exception:  # noqa: BLE001
                pass
        self._pw = self._browser = self._page = None


class FakePager:
    """Tests: url -> saved HTML (or an exception instance to raise). Same blocking rule as the real pager."""

    def __init__(self, pages: dict):
        self.pages, self.calls, self.blocked = pages, [], None

    def load(self, url: str) -> str:
        if self.blocked:
            raise Challenge(f"not loaded: the run stopped at a challenge page ({self.blocked})")
        self.calls.append(url)
        page = self.pages.get(url)
        if page is None:
            raise KeyError(f"FakePager has no page for {url}")
        if isinstance(page, Exception):
            raise page
        why = challenge_reason(page)
        if why:
            self.blocked = why
            raise Challenge(why)
        return page

    def close(self):
        pass
