"""Brazil: ANBIMA prefixed ETTJ at the published Circular 3.361 vertices (business days; 252 = 1 year). A form POST that returns
CSV, one date per request; empty on holidays, and (checked 6 Nov 2026) only the last week of business days is served. So each
weekly run reads the last eight days and appends them to a history kept in the document's `state`; the 1-month, 3-month and 1-year
earlier curves fill in as that history grows. 30Y is not published (the table stops at 10Y) and is never extrapolated."""
from __future__ import annotations

import re
from datetime import date, timedelta

from .core import Raw, Series

META = {
    "code": "br", "name": "Brazil", "source": "ANBIMA, ETTJ (prefixed curve, Circular 3.361 vertices)",
    "source_url": "https://www.anbima.com.br/pt_br/informar/curvas-de-juros-fechamento.htm",
    "terms": "ANBIMA is a private association; terms not found, to be checked before any public use.",
}
URL = "https://www.anbima.com.br/informacoes/est-termo/CZ-down.asp"
VERT = {21: "1M", 63: "3M", 126: "6M", 252: "1Y", 756: "3Y", 1260: "5Y", 2520: "10Y"}
GAPS = {"30Y": "ANBIMA publishes the prefixed curve only to 10 years."}


def parse(blob: bytes):
    """(file date, {tenor: percent}) or None when the file has no Circular 3.361 table (holiday)."""
    text = blob.decode("latin-1")
    m = re.match(r"\s*(\d{2})/(\d{2})/(\d{4});", text)
    if "CIRCULAR 3.361" not in text or not m:
        return None
    d = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    block = text.split("CIRCULAR 3.361", 1)[1].splitlines()
    out = {}
    for line in block:
        parts = line.strip().split(";")
        if len(parts) >= 2 and re.match(r"^[\d.]+$", parts[0]):
            v = int(parts[0].replace(".", ""))
            if v in VERT:
                out[VERT[v]] = float(parts[1].replace(".", "").replace(",", "."))
        elif out and not line.strip():
            break
    return (d, out) if out else None


RECENT_DAYS = 8       # the download serves only about the last week of business days (checked 6 Nov 2026), so history accumulates
KEEP_DAYS = 400


def fetch(g, today: date, env=None, prev=None) -> Raw:
    hist = {date.fromisoformat(d): row for d, row in (prev or {}).get("history", [])}
    d = today
    while (today - d).days <= RECENT_DAYS:
        if d.weekday() < 5 and d not in hist:
            got = parse(g.post(URL, {"Idioma": "PT", "Dt_Ref": d.strftime("%d/%m/%Y"), "saida": "csv"}))
            if got:
                hist[got[0]] = got[1]
        d -= timedelta(days=1)
    if not hist:
        raise ValueError("ANBIMA returned no curve for the last eight days")
    cutoff = today - timedelta(days=KEEP_DAYS)
    hist = {k: v for k, v in hist.items() if k >= cutoff}
    raw = Raw(gaps=dict(GAPS))
    for t in VERT.values():
        raw.series[t] = [Series("D", [(k, row[t]) for k, row in hist.items() if t in row], max_lag=6)]
    raw.extra = {"history": [[k.isoformat(), hist[k]] for k in sorted(hist)]}
    return raw
