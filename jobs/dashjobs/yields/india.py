"""India (country code "in"; the module is india.py because `in` is a Python keyword): Reserve Bank of India press releases
(checked 11 Nov 2026: www.rbi.org.in answers plain requests from Europe; GitHub's servers are outside India too, see the
probe-sources workflow). CCIL and FBIL stay out (geo-block, captcha), so India has no daily official source this job can read and
every tenor comes from auctions (decisions of 11 Nov 2026: the auction rule, extended to long tenors by remaining maturity).

  "Treasury Bills: Full Auction Result" (weekly, Wednesdays): 91-, 182- and 364-day bills, weighted average yield (WAY).
      91 days is a 3M auction, 182 days 6M, 364 days 1Y (0.997 years).
  "Government Stock - Full Auction Results" (weekly, Fridays): one column per security ("7.06% GS 2041"), its WAY.
  "Auction of Government of India Dated Securit(y|ies)" (the announcement, a few days earlier): each security's Date of
      Repayment, Auction Date and Settlement Date. A result is used only when its announcement is found (remaining maturity
      = repayment - settlement); a new security announced as "New GS 2036" is matched by auction date and year.
Floating rate (FRB), green (SGrB) and inflation-indexed bonds are never used; State Government Securities are not central
government. 1M is a gap: Cash Management Bills are irregular (none in October 2026).

The press-release list is an ASP.NET page: the current list is a GET; a month of the archive is the page's own form posted back
with hdnYear/hdnMonth (what its month links do). The log of auctions, the announcements still waiting for a result and the
press releases already read are kept in the document's `state`, so a weekly run reads one or two month lists plus the new
releases only.
"""
from __future__ import annotations

import html as htmllib
import re
from datetime import date, datetime, timedelta

from .core import Auction, Raw, window_start

META = {
    "code": "in", "name": "India", "source": "Reserve Bank of India (Treasury bill and Government Stock auction results)",
    "source_url": "https://www.rbi.org.in/",
    "terms": "No reuse licence stated. RBI's terms: caching, linking and framing are prohibited except that the home page may be "
             "linked after notifying the RBI in writing; deep links need prior permission.",
    "status": "ok",
}
LIST = "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx"
PR = LIST + "?prid={id}"
TB_DAYS = {"91": 91, "182": 182, "364": 364}
TENORS = ["3M", "6M", "1Y", "3Y", "5Y", "10Y", "30Y"]
GAPS = {"1M": "India issues no regular one-month bill (Cash Management Bills are irregular); left empty."}
KEEP_DAYS = 480
EXCLUDE = re.compile(r"FRB|SGrB|IIB|CIB|Floating|Green|Index", re.I)


def _date(s: str) -> date:
    s = re.sub(r"\s+", " ", s.strip())
    for f in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            pass
    raise ValueError(f"not a date: {s!r}")


def _text(s: str) -> str:
    return htmllib.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s))).strip()


def _rows(table_html: str) -> list[list[str]]:
    return [[_text(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, flags=re.S)]
            for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, flags=re.S)]


def _tables(page: str) -> list[list[list[str]]]:
    """Innermost tables only (the release body sits inside layout tables)."""
    return [_rows(t) for t in re.findall(r"<table[^>]*>((?:(?!<table).)*?)</table>", page, flags=re.S)]


def release_date(page: str) -> date:
    m = re.search(r"Date\s*:\s*([A-Z][a-z]{2,8}\s+\d{1,2},\s+\d{4})", _text(page))
    if not m:
        raise ValueError("press release date not found")
    return _date(m.group(1))


def form_fields(page: str) -> dict:
    f = {n: htmllib.unescape(v) for n, v in re.findall(r'<input type="hidden" name="([^"]+)" id="[^"]+" value="([^"]*)"', page)}
    btn = re.search(r'<input type="submit" name="([^"]+)" value="([^"]*)" id="btn"', page)
    if "__VIEWSTATE" not in f or not btn:
        raise ValueError("RBI press-release list: form fields not found (layout changed)")
    f[btn.group(1)] = btn.group(2)
    return f


def parse_list(page: str) -> list[tuple[date, int, str]]:
    """(listing date, prid, title) for every release in a list page, in page order."""
    out, cur = [], None
    for m in re.finditer(r'class="tableheader"[^>]*>(?:\s*<b>)?\s*([A-Z][a-z]{2} \d{1,2}, \d{4})|prid=(\d+)[^>]*>(.*?)</a>', page, flags=re.S):
        if m.group(1):
            cur = _date(m.group(1))
        elif cur:
            out.append((cur, int(m.group(2)), _text(m.group(3))))
    return out


def kind_of(title: str) -> str | None:
    if title.startswith("Treasury Bills: Full Auction Result"):
        return "tb"
    if title.startswith("Government Stock - Full Auction Result"):
        return "gs"
    if title.startswith("Auction of Government of India Dated Securit"):
        return "ann"
    return None


def _results_table(page: str) -> tuple[list[str], list[float | None]]:
    """(column names, WAY percent per column) of a Full Auction Result table. A column with no weighted average shows "-" (the
    182-day bill on 4 Nov 2026 accepted no bid) or "(WAY: NA)" in the WAY row: None, and that security is skipped."""
    for rows in _tables(page):
        names = next((r[1:] for r in rows if r and r[0] == "Auction Results"), None)
        if names:
            names = [n for n in names if n]
            row = next((r for r in rows if any("WAY:" in c for c in r)), None)
            if row is None and any(r and "Weighted Average" in " ".join(r) and all(c in ("-", "") for c in r[2:]) for r in rows):
                return names, [None] * len(names)        # every bid rejected (T-bills, 21 Oct 2026): an auction without a result
            if row is None or len(row) < len(names):
                raise ValueError("results table: WAY row not found")
            way = []
            for c in row[-len(names):]:
                m = re.fullmatch(r"\(?WAY:\s*(-?[\d.]+)\s*%\)?", c.strip())
                if not m and not re.fullmatch(r"-?|\(?WAY:\s*(NA|N\.A\.|-)\s*\)?", c.strip(), flags=re.I):
                    raise ValueError(f"results table: WAY cell not recognised: {c!r}")
                way.append(float(m.group(1)) if m else None)
            return names, way
    raise ValueError("results table not found")


def parse_tbills(page: str) -> list[dict]:
    d = release_date(page)
    names, way = _results_table(page)
    out = []
    for n, w in zip(names, way):
        m = re.match(r"(\d+)-Day", n)
        if not m or m.group(1) not in TB_DAYS:
            raise ValueError(f"T-bill column not recognised: {n!r}")
        if w is not None:
            out.append({"date": d.isoformat(), "days": TB_DAYS[m.group(1)], "value": w, "what": f"{m.group(1)}-day T-bill"})
    return out


def parse_gs_results(page: str) -> tuple[date, list[tuple[str, float]]]:
    names, way = _results_table(page)
    return release_date(page), [(n, w) for n, w in zip(names, way) if w is not None]


def parse_announcement(page: str) -> list[dict]:
    """Securities of one announcement: {name, maturity, auction, settle} (ISO dates). Row-spanned dates carry down."""
    for rows in _tables(page):
        if not rows or "Date of Repayment" not in " ".join(rows[0]):
            continue
        out, auc, sett = [], None, None
        for r in rows[1:]:
            if len(r) < 3 or not re.search(r"\bGS\b|SGrB|FRB", r[1]):
                continue
            dates = re.findall(r"[A-Z][a-z]{2,8}\s+\d{1,2},\s+\d{4}", " ".join(r[2:]))
            if len(dates) >= 3:                 # repayment, [notification date,] auction, settlement
                auc, sett = _date(dates[-2]), _date(dates[-1])
            if not dates or auc is None:
                raise ValueError(f"announcement row not recognised: {r[:3]}")
            out.append({"name": r[1], "maturity": _date(dates[0]).isoformat(), "auction": auc.isoformat(), "settle": sett.isoformat()})
        return out
    raise ValueError("announcement table not found")


def match(name: str, auction: date, announced: list[dict]) -> dict | None:
    same_day = [a for a in announced if a["auction"] == auction.isoformat()]
    exact = [a for a in same_day if a["name"] == name]
    if exact:
        return exact[0]
    yr = re.search(r"(\d{4})\s*$", name)
    by_year = [a for a in same_day if yr and a["name"].endswith(yr.group(1))]
    return by_year[0] if len(by_year) == 1 else None


def spans(today: date, listed_through: date | None) -> list[tuple[date, date]]:
    """Date ranges of releases to read. First run (nothing listed yet): one continuous range back to the 1-year-earlier curve
    plus the 90-day rule and a week for announcements (a range with a hole would leave the 1-year-earlier curve without its
    auctions a few months later, since later runs only read forward). Later runs: from the last listed date (at most 120 days
    back), with a week of overlap."""
    if listed_through is None:
        return [(today - timedelta(days=467), today)]
    return [(max(listed_through, today - timedelta(days=120)) - timedelta(days=7), today)]


def months_needed(rng: list[tuple[date, date]]) -> list[tuple[int, int]]:
    out = []
    for a, b in rng:
        y, m = a.year, a.month
        while (y, m) <= (b.year, b.month):
            if (y, m) not in out:
                out.append((y, m))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def fetch(g, today: date, env=None, prev=None) -> Raw:
    prev = prev or {}
    log = list(prev.get("auction_log", []))
    seen = set(prev.get("seen", []))
    unreadable = {int(k): v for k, v in prev.get("unreadable", {}).items()}     # prid -> reason; retried every run
    announced = list(prev.get("announced", []))
    lt = prev.get("listed_through")
    rng = spans(today, date.fromisoformat(lt) if lt else None)
    page = g.get(LIST).decode("utf-8", errors="replace")
    items = parse_list(page)
    fields = form_fields(page)
    for y, m in months_needed(rng):
        items += parse_list(g.post(LIST, fields | {"hdnYear": str(y), "hdnMonth": str(m)}).decode("utf-8", errors="replace"))
    todo, dated = {}, {}
    for d, prid, title in items:
        k = kind_of(title)
        if k and prid not in seen and (any(a <= d <= b for a, b in rng) or prid in unreadable):
            todo[prid], dated[prid] = k, d
    # announcements first, so that this run's results find them
    # A fetch error fails the country (last good file kept, marked stale, retried next run). A release the parser cannot read
    # is not marked as read: it is retried every run and counted in status.json's warnings until it parses or is 60 days old.
    pages = {}
    for prid, k in sorted(todo.items(), key=lambda x: (x[1] != "ann", x[0])):
        pages[prid] = g.get(PR.format(id=prid)).decode("utf-8", errors="replace")
        if k == "ann":
            try:
                announced += parse_announcement(pages[prid])
                seen.add(prid)
                unreadable.pop(prid, None)
            except ValueError as e:
                unreadable[prid] = str(e)[:80]
    for prid, k in sorted(todo.items()):
        if k == "ann":
            continue
        try:
            if k == "tb":
                log += parse_tbills(pages[prid])
            else:
                d, secs = parse_gs_results(pages[prid])
                lost = []
                for name, way in secs:
                    if EXCLUDE.search(name):
                        continue
                    a = match(name, d, announced)
                    if a is None:
                        lost.append(name)
                        continue
                    days = (date.fromisoformat(a["maturity"]) - date.fromisoformat(a["settle"])).days
                    log.append({"date": d.isoformat(), "days": days, "value": way, "what": name, "settle": a["settle"],
                                "maturity": a["maturity"]})
                if lost:
                    raise ValueError(f"no announcement found for {', '.join(lost)} (auction {d.isoformat()})")
            seen.add(prid)
            unreadable.pop(prid, None)
        except ValueError as e:
            unreadable[prid] = str(e)[:80]
    old = today - timedelta(days=60)
    for prid in [p for p in unreadable if dated.get(p, today) < old]:
        seen.add(prid)                     # given up after 60 days: older than any curve's auction window needs
        unreadable.pop(prid)
    cutoff = (today - timedelta(days=KEEP_DAYS)).isoformat()
    uniq = {(a["date"], a["what"]): a for a in log if a["date"] >= cutoff}
    log = sorted(uniq.values(), key=lambda a: (a["date"], a["days"]))
    if not log:
        raise ValueError("no Indian auction result could be read")
    raw = Raw(gaps=dict(GAPS), auction_dated=True)
    aus = [Auction(date.fromisoformat(a["date"]), a["days"], a["value"]) for a in log]
    raw.auctions = {t: aus for t in TENORS}
    keep_ann = (today - timedelta(days=40)).isoformat()
    raw.extra = {"auction_log": log, "seen": sorted(seen)[-2000:], "listed_through": today.isoformat(),
                 "announced": [a for a in announced if a["auction"] >= keep_ann], "unreadable": {str(k): v for k, v in unreadable.items()}}
    if unreadable:
        raw.warnings.append(f"{len(unreadable)} RBI release(s) could not be read (retried each run): "
                            + "; ".join(f"{k}: {v}" for k, v in list(unreadable.items())[:3]))
    return raw
