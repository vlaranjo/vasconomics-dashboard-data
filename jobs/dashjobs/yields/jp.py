"""Japan: MOF constant-maturity JGB yields (1Y, 3Y, 5Y, 10Y, 30Y daily) plus Treasury discount bill auctions from the
Ministry's per-auction result pages (3M and 6M; the old XLS was about six weeks behind). A result page is
.../tbill/tbill_nyusatsu/resulYYYYMMDD.htm, posted the same day, UTF-8, 404 on days without an auction."""
from __future__ import annotations

import csv
import io
import re
from datetime import date, timedelta

from .core import Auction, Raw, Series, window_start

META = {
    "code": "jp", "name": "Japan", "source": "Ministry of Finance Japan (JGB yields; Treasury discount bill auction results)",
    "source_url": "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/index.htm",
    "terms": "Copyright Ministry of Finance Japan; Public Data License 1.0 where no other right is stated (attribution wording not confirmed).",
}
CME = "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/historical/jgbcme_all.csv"
RESULT = "https://www.mof.go.jp/jgbs/auction/calendar/tbill/tbill_nyusatsu/resul{d}.htm"
COLS = {"1Y": "1Y", "3Y": "3Y", "5Y": "5Y", "10Y": "10Y", "30Y": "30Y"}
INITIAL_DAYS = 190          # first run: enough for the 3-months-earlier curve plus the 90-day auction rule
KEEP_DAYS = 400
GAPS = {"1M": "Japan issues no Treasury discount bill of about one month."}


def parse_cme(blob: bytes) -> dict[str, list[tuple[date, float]]]:
    text = blob.decode("cp932", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))
    hi = next(i for i, r in enumerate(rows) if r and r[0].strip() == "Date")
    head = [c.strip() for c in rows[hi]]
    idx = {t: head.index(c) for t, c in COLS.items()}
    out = {t: [] for t in COLS}
    for r in rows[hi + 1:]:
        if not r or not re.match(r"^\d{4}/\d{1,2}/\d{1,2}$", r[0].strip()):
            continue
        y, m, d = (int(x) for x in r[0].strip().split("/"))
        for t, i in idx.items():
            if i < len(r) and r[i].strip() not in ("", "-"):
                out[t].append((date(y, m, d), float(r[i])))
    return out


def _era(s: str) -> date:
    m = re.search(r"令和(\d+)年(\d+)月(\d+)日", s)
    return date(2018 + int(m.group(1)), int(m.group(2)), int(m.group(3)))


def parse_result(blob: bytes) -> dict:
    """{'no','issue','maturity','days','value'} from one result page. Raises ValueError if the layout changed."""
    t = blob.decode("utf-8", errors="replace")
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", t, flags=re.S)
    t = re.sub(r"[\|\s]*\|[\|\s]*", " | ", re.sub(r"<[^>]+>", "|", t))
    try:
        no = int(re.search(r"国庫短期証券（第(\d+)回）", t).group(1))
        issue = _era(re.search(r"発行日 \| (令和\d+年\d+月\d+日)", t).group(1))
        mat = _era(re.search(r"償還期限 \| (令和\d+年\d+月\d+日)", t).group(1))
        y = float(re.search(r"募入平均利回り\） \| （(-?[\d.]+)％）", t).group(1))
    except AttributeError as e:
        raise ValueError("MOF result page layout not recognised") from e
    return {"no": no, "issue": issue, "maturity": mat, "days": (mat - issue).days, "value": y}


def scan(g, start: date, end: date, sleep=None) -> list[dict]:
    out = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            blob = g.get_or_none(RESULT.format(d=d.strftime("%Y%m%d")))
            if blob:
                r = parse_result(blob)
                out.append({"date": d.isoformat(), "no": r["no"], "issue": r["issue"].isoformat(), "days": r["days"],
                            "value": r["value"]})
        d += timedelta(days=1)
    return out


def fetch(g, today: date, env=None, prev=None) -> Raw:
    cme = parse_cme(g.get(CME))
    log = list((prev or {}).get("auction_log", []))
    done = (prev or {}).get("scanned_through")
    start = date.fromisoformat(done) + timedelta(days=1) if done else today - timedelta(days=INITIAL_DAYS)
    old_delay = getattr(g, "delay", None)
    if old_delay is not None:
        g.delay = min(old_delay, 1.0)          # up to ~135 plain page probes on a first run
    try:
        new = scan(g, start, today)
    finally:
        if old_delay is not None:
            g.delay = old_delay
    seen = {(a["date"], a["no"]) for a in log}
    log += [a for a in new if (a["date"], a["no"]) not in seen]
    cutoff = (today - timedelta(days=KEEP_DAYS)).isoformat()
    log = sorted((a for a in log if a["date"] >= cutoff), key=lambda a: (a["date"], a["no"]))
    raw = Raw(gaps=dict(GAPS))
    keep_from = window_start(today)
    for t, pts in cme.items():
        raw.series[t] = [Series("D", [p for p in pts if p[0] >= keep_from], max_lag=5)]
    aus = [Auction(date.fromisoformat(a["date"]), a["days"], a["value"], date.fromisoformat(a["issue"])) for a in log]
    raw.auctions = {"1M": aus, "3M": aus, "6M": aus}
    raw.extra = {"auction_log": log, "scanned_through": (today - timedelta(days=1)).isoformat()}
    return raw
