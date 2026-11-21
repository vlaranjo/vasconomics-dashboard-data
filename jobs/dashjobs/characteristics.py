"""Fixed-income characteristics (21 Nov 2026): yield to maturity, duration, average credit rating and option-adjusted spread of each
bond fund on the Fixed Income page, as each ISSUER publishes them, with the issuer's as-of date. Research: docs/fi-characteristics.md.

One adapter per issuer that can be read (State Street SPDR, Vanguard); an issuer that cannot be read (iShares: HTTP 403 from Akamai;
Invesco: HTTP 406, both 21 Nov 2026) is switched off in config/characteristics.yaml and its funds show "n/a" with the reason. A
measure an issuer does not publish for a fund is "n/a" with the reason too. Nothing is ever computed here: every number is the issuer's.

Rules (as for the other jobs): plain requests, one at a time, 5 s apart; a refusal (401/403/406/429) or a challenge page stops every
further request to that issuer for the run; per fund, a failure (fetch, changed layout, validation) keeps the last good figures,
marked stale; a figure is never replaced by one with an earlier as-of date; everything is validated before the atomic swap."""
from __future__ import annotations

import json
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path

from . import publish, status, validate

MEASURES = ("ytm", "duration", "rating", "oas")
USER_AGENT = "vasconomics-dashboard/1.0 (personal, non-commercial; weekly job; github.com/vlaranjo/vasconomics-dashboard-data)"
CHALLENGE = re.compile(r"captcha|cf-chl|challenge-platform|<title>\s*Access Denied|Request unsuccessful|Pardon Our Interruption|are you a robot", re.I)
REFUSAL_CODES = (401, 403, 406, 429)
_MON = {m: i for i, m in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}
RATING = re.compile(r"^(AAA|AA[+-]?|A[+-]?|BBB[+-]?|BB[+-]?|B[+-]?|CCC[+-]?|CC|C|D)$")


class FetchError(Exception):
    pass


class Refused(FetchError):
    """The issuer refused the request or answered with a challenge: no further request to it in this run."""


class LayoutError(ValueError):
    """The page no longer has the expected structure (or names another fund): keep the last good figures."""


class Getter:
    """Polite: one request at a time, `delay` seconds apart; one retry on a network error or 5xx, NEVER on a refusal."""

    def __init__(self, delay: float = 5.0, timeout: int = 60, sleep=time.sleep):
        import requests
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en"})
        self.delay, self.timeout, self.sleep, self._first = delay, timeout, sleep, True
        self.log: list[str] = []

    def get(self, url: str) -> bytes:
        last = None
        for attempt in (1, 2):
            if not self._first:
                self.sleep(self.delay * attempt)
            self._first = False
            try:
                r = self.s.get(url, timeout=self.timeout)
            except Exception as e:  # noqa: BLE001
                last = FetchError(f"{type(e).__name__} for {url}")
                continue
            self.log.append(f"GET {r.status_code} {url}")
            if r.status_code in REFUSAL_CODES:
                raise Refused(f"HTTP {r.status_code} for {url}")
            if r.status_code >= 500:
                last = FetchError(f"HTTP {r.status_code} for {url}")
                continue
            if r.status_code >= 400:
                raise FetchError(f"HTTP {r.status_code} for {url}")
            if CHALLENGE.search(r.text[:20000]):
                raise Refused(f"challenge page at {url}")
            return r.content
        raise last or FetchError(url)


# ---- adapters: (html bytes, expected ISIN) -> {measure: {"value", "as_of", "name"}} for the measures the issuer publishes ------------
def _num(text: str) -> float:
    m = re.fullmatch(r"\s*(-?[0-9]+(?:\.[0-9]+)?)\s*%?\s*", text.replace(",", ""))
    if not m:
        raise LayoutError(f"not a number: {text!r}")
    return float(m.group(1))


def _dmy(text: str) -> str:
    m = re.search(r"(\d{1,2}) ([A-Z][a-z]{2}) (\d{4})", text)
    if not m or m.group(2) not in _MON:
        raise LayoutError(f"no date in {text!r}")
    return date(int(m.group(3)), _MON[m.group(2)], int(m.group(1))).isoformat()


def parse_ssga(html: bytes, isin: str) -> dict:
    """State Street SPDR fund page (server-rendered). The block "Fund Characteristics  as of 19 Nov 2026" is a key/value table."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    blocks = {}
    for sec in soup.select("section[data-fundcomponent], section[data-fundComponent]"):
        h = sec.find(["h2", "h3"])
        title = " ".join(h.get_text(" ").split()) if h else ""
        rows = {" ".join(th.get_text(" ").split()): " ".join(td.get_text(" ").split())
                for tr in sec.select("tr") for th, td in [(tr.find("th"), tr.find("td"))] if th and td}
        if rows:
            blocks[title] = rows
    info = next((r for t, r in blocks.items() if t.startswith("Fund Information")), None)
    if not info or info.get("ISIN") != isin:
        raise LayoutError(f"the page does not name ISIN {isin} in its Fund Information block")
    title, ch = next(((t, r) for t, r in blocks.items() if t.startswith("Fund Characteristics")), (None, None))
    if ch is None:
        raise LayoutError("no 'Fund Characteristics' block")
    as_of = _dmy(title)
    out = {}
    for key, measure in (("Yield to Maturity", "ytm"), ("Effective Duration", "duration")):
        if key not in ch:
            raise LayoutError(f"'{key}' is missing from Fund Characteristics")
        out[measure] = {"value": _num(ch[key]), "as_of": as_of, "name": key}
    for key in ("Option Adjusted Spread", "OAS"):                   # not published today; taken if it ever appears
        if key in ch:
            out["oas"] = {"value": _num(ch[key]), "as_of": as_of, "name": key}
    return out


def parse_vanguard(html: bytes, isin: str) -> dict:
    """Vanguard UK professional fund page (Angular, server-rendered). The figures shown on the page are also in the transfer-state
    JSON <script id="serverApp-state">: monthly analytics of the FUND (not the benchmark, which sits alongside)."""
    text = html.decode("utf-8", "replace")
    if isin not in text:
        raise LayoutError(f"the page does not name ISIN {isin}")
    m = re.search(r'<script id="serverApp-state" type="application/json">(.*?)</script>', text, re.S)
    if not m:
        raise LayoutError("no serverApp-state JSON on the page")
    try:
        state = json.loads(m.group(1))
    except ValueError as e:
        raise LayoutError("serverApp-state is not JSON") from e
    fund_list, yield_list = [], []
    for entry in state.values():
        try:
            monthly = entry["b"]["data"]["polarisAnalyticsHistory"][0]["monthly"]
        except (KeyError, IndexError, TypeError):
            continue
        try:
            codes = monthly["analytics"]["fund"]["items"][0]["codes"]
            if codes.get("AVGDURADJ"):
                fund_list.append(codes)
        except (KeyError, IndexError, TypeError):
            pass
        try:
            codes = monthly["yields"]["fund"]["items"][0]["codes"]
            if codes.get("YLDMAT"):
                yield_list.append(codes)
        except (KeyError, IndexError, TypeError):
            pass
    if not fund_list or not yield_list:
        raise LayoutError("fund analytics (AVGDURADJ) or fund yields (YLDMAT) not found in serverApp-state")
    # Exactly one of each (21 Nov 2026: one per page). More would mean another fund's figures are on the page (a related fund, a
    # second share class): refuse rather than guess which one is this fund.
    if len(fund_list) != 1 or len(yield_list) != 1:
        raise LayoutError(f"ambiguous: {len(fund_list)} fund analytics and {len(yield_list)} fund yields in serverApp-state")
    fund_codes, yield_codes = fund_list[0], yield_list[0]

    def rec(codes, k, name, conv):
        r = codes.get(k)
        if not r or r.get("analyticValue") in (None, "") or not r.get("effectiveDate"):
            raise LayoutError(f"{k} has no value")
        return {"value": conv(r["analyticValue"]), "as_of": str(r["effectiveDate"])[:10], "name": name}

    out = {"ytm": rec(yield_codes, "YLDMAT", "YTM (Yield to Maturity) effective", lambda v: float(v)),
           "duration": rec(fund_codes, "AVGDURADJ", "Average duration", lambda v: float(v))}
    if fund_codes.get("AVGQLYTFTO"):
        out["rating"] = rec(fund_codes, "AVGQLYTFTO", "Average quality", lambda v: str(v).strip())
    # The page shows the same figures rounded to one decimal ("YTM (Yield to Maturity) effective 3.9%", "Average Duration 6.8"):
    # they must agree, so the JSON read is the fund the page displays.
    shown = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>", " ", text, flags=re.S)))
    for label, v in (("YTM \\(Yield to Maturity\\) effective", out["ytm"]["value"]), ("Average Duration", out["duration"]["value"])):
        if not re.search(f"{label} {v:.1f}\\b", shown, re.I):
            raise LayoutError(f"the page does not display {label.replace(chr(92), '')} {v:.1f}: the embedded figures may be another fund's")
    return out


ADAPTERS = {"ssga": parse_ssga, "vanguard": parse_vanguard}


# ---- the job ---------------------------------------------------------------------------------------------------------------------
def _round(measure: str, v):
    if measure == "rating":
        return v
    return round(float(v), 0 if measure == "oas" else 2)


def check_fund(fid: str, measures: dict, *, today: date, max_age_days: int) -> None:
    """Sanity of one fund's figures (any failure keeps the last good ones)."""
    lim = {"ytm": (-2.0, 30.0), "duration": (0.0, 30.0), "oas": (-100.0, 3000.0)}
    for k, m in measures.items():
        if m.get("value") is None:
            continue
        d = date.fromisoformat(m["as_of"])
        if d > today:
            raise validate.ValidationError(f"{fid} {k}: as of {d} is in the future")
        if (today - d).days > max_age_days:
            raise validate.ValidationError(f"{fid} {k}: as of {d} is {(today - d).days} days old (limit {max_age_days})")
        if k == "rating":
            if not RATING.match(m["value"]):
                raise validate.ValidationError(f"{fid} rating: {m['value']!r} is not a rating")
        elif not lim[k][0] <= m["value"] <= lim[k][1]:
            raise validate.ValidationError(f"{fid} {k}: {m['value']} is outside {lim[k]}")


def run(cfg: dict, universe: dict, getter, *, today: date, now: datetime | None = None, data_dir, work_dir, env=None) -> dict:
    now = now or datetime.now(timezone.utc)
    started, now_iso = now, status.iso(now)
    data_dir, work_dir = Path(data_dir), Path(work_dir)
    sec = next(s for s in universe["sections"] if s["id"] == cfg["section"])
    rows = {r["id"]: r for r in sec["rows"]}
    if set(cfg["funds"]) != set(rows):
        raise validate.ValidationError(f"config/characteristics.yaml funds {sorted(set(cfg['funds']) ^ set(rows))} do not match the section rows")
    rel = f"characteristics/{cfg['section']}.json"
    prev = publish.read_json(data_dir / rel) or {}
    prev_funds = {f["id"]: f for f in prev.get("funds", [])}
    prev_manifest = publish.read_json(data_dir / "manifest.json") or {}
    prev_status = publish.read_json(data_dir / "status.json")
    refused: dict[str, str] = {}                        # issuer -> why we stopped asking it in this run
    problems: list[str] = []
    out_funds, n_ok, n_tried = [], 0, 0

    for fid in [r["id"] for r in sec["rows"]]:         # the section's order
        row, fc = rows[fid], cfg["funds"][fid]
        iss = cfg["issuers"][fc["issuer"]]
        base = {"id": fid, "label": row["label"], "isin": row["isin"], "issuer": fc["issuer"], "issuer_name": iss["name"],
                "source_url": fc.get("url")}
        not_pub = {k: v for k, v in (iss.get("not_published") or {}).items()}
        not_pub.update(fc.get("not_published") or {})
        if not iss.get("enabled"):
            reason = iss["reason"]
            out_funds.append({**base, "status": "unavailable", "stale": False, "stale_reason": None, "last_success": None, "as_of": None,
                              "measures": {k: {"value": None, "reason": reason} for k in MEASURES}})
            continue
        n_tried += 1
        old = prev_funds.get(fid)
        try:
            if fc["issuer"] in refused:
                raise Refused(f"not asked: {refused[fc['issuer']]}")
            got = ADAPTERS[fc["issuer"]](getter.get(fc["url"]), row["isin"])
            measures = {}
            for k in MEASURES:
                om = ((old or {}).get("measures") or {}).get(k) or {}
                if k in got:
                    measures[k] = {"value": _round(k, got[k]["value"]), "as_of": got[k]["as_of"], "name": got[k]["name"]}
                elif k not in not_pub and om.get("value") is not None:
                    measures[k] = om                    # published before, missing today: keep the last figure, do not claim "not published"
                    problems.append(f"{fid} {k}: missing on the issuer's page today; the figure of {om['as_of']} is kept")
                else:
                    measures[k] = {"value": None, "reason": not_pub.get(k) or f"{iss['name']} does not publish this figure for this fund."}
            check_fund(fid, measures, today=today, max_age_days=iss["max_age_days"])
            if old:                                     # never go backwards: a figure older than the published one is not used
                for k, m in measures.items():
                    om = (old.get("measures") or {}).get(k) or {}
                    if m.get("value") is not None and om.get("value") is not None and m["as_of"] < om["as_of"]:
                        measures[k] = om
                        problems.append(f"{fid} {k}: kept as published ({om['as_of']}); the issuer now shows {m['as_of']}")
            dates = [m["as_of"] for m in measures.values() if m.get("value") is not None]
            out_funds.append({**base, "status": "ok", "stale": False, "stale_reason": None, "last_success": now_iso,
                              "as_of": max(dates) if dates else None, "measures": measures})
            n_ok += 1
        except Exception as e:  # noqa: BLE001 - one fund failing never blocks the others
            reason = ("refused" if isinstance(e, Refused) else "layout_changed" if isinstance(e, LayoutError)
                      else "validation_failed" if isinstance(e, validate.ValidationError) else "fetch_failed")
            if isinstance(e, Refused) and fc["issuer"] not in refused:
                refused[fc["issuer"]] = str(e)[:160]
            problems.append(f"{fid} ({iss['name']}): {reason}: {str(e)[:160]}")
            if old and old.get("last_success"):          # read successfully at some point: keep those figures
                kept = dict(old)
                kept.update(base)                       # names and links follow the current config
                kept.update(stale=True, stale_reason=reason)
                out_funds.append(kept)
            else:
                msg = f"{iss['name']}'s page could not be read on {today.isoformat()} ({reason.replace('_', ' ')})."
                out_funds.append({**base, "status": "unavailable", "stale": True, "stale_reason": reason, "last_success": None, "as_of": None,
                                  "measures": {k: {"value": None, "reason": msg} for k in MEASURES}})

    dates = [f["as_of"] for f in out_funds if f.get("as_of")]
    doc = {"schema_version": 1, "section": cfg["section"], "generated_at": now_iso, "source": "fund issuers' published data",
           "as_of": max(dates) if dates else today.isoformat(), "measures": {k: cfg["measure_names"][k] for k in MEASURES},
           "issuers": {k: {"name": v["name"], "enabled": bool(v.get("enabled")), "terms_url": v.get("terms_url"),
                           **({"reason": v["reason"]} if not v.get("enabled") else {})} for k, v in cfg["issuers"].items()},
           "funds": out_funds}
    validate.validate_characteristics(doc, section_ids=set(rows))
    last_success = (prev_status or {}).get("sources", {}).get("fund_issuers", {}).get("last_success")
    if n_ok:
        last_success = now_iso
    st = status.merge_status(prev_status, "fund_issuers",
                             status.source_block(now=now, last_success=last_success, items_ok=n_ok, items_total=n_tried, failed=problems,
                                                 cadence_hours=24 * 7, stale=n_ok < n_tried),
                             status.run_info("characteristics", started, now, env), now)
    validate.validate_status(st)
    manifest = publish.merge_manifest(prev_manifest, generated_at=now_iso,
                                      updates={"characteristics": {cfg["section"]: {"path": rel, "as_of": doc["as_of"]}}},
                                      keep={"characteristics": {cfg["section"]}})
    validate.validate_manifest(manifest, universe=universe)
    out_dir = work_dir / "out"
    publish.stage(data_dir, out_dir)
    publish.write_outputs(out_dir, {rel: doc, "status.json": st}, manifest)
    validate.validate_manifest_files(out_dir, manifest)
    publish.atomic_swap(data_dir, out_dir)
    return {"ok": n_ok, "tried": n_tried, "problems": problems, "refused": refused, "doc": doc}
