"""Writes docs/fund-names.md: for every fund row the ticker, Yahoo's longName and shortName, the name the dashboard shows, and a flag
where the name looks wrong. Reads Yahoo (the same call as the markets job), so run it politely and rarely.

    python jobs/report_fund_names.py [--out docs/fund-names.md] [--names-json FILE] [--notes-json FILE]
    (--names-json reuses a saved fetch instead of calling Yahoo; --notes-json = {ticker: hand-written remark})
"""
import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dashjobs.markets import _ENTITY_END, pick_name  # noqa: E402

OUTDATED = re.compile(r"lyxor|comstage|db x-?trackers|\bsource\b|deutsche|multi units", re.I)
DIST = re.compile(r"\b(dist|dis|distributing|distribution|income)\b|\(d\)", re.I)
ACC = re.compile(r"\b(acc|accumulating|accumulation|capitalisation|1c)\b|\(c\)|-c\b", re.I)
HEDGED = re.compile(r"hedg|\bh(eur|eo)\b|hgd|hdg", re.I)


def flags_for(meta: dict, long_name, short_name, shown: str, notes: dict) -> list[str]:
    out = []
    if not long_name:
        out.append("longName missing" + (" (shortName used)" if short_name else " (no name at all)"))
    if shown and (len(shown) <= 12 or shown.rstrip().endswith(("-", "/"))):
        out.append("looks truncated")
    if shown and not long_name and len(shown) >= 28:
        out.append("shortName is cut at 30 characters")
    if OUTDATED.search(shown):
        out.append("outdated brand")
    if not meta.get("etc") and meta.get("acc") is not None:
        if meta["acc"] and DIST.search(shown) and not ACC.search(shown):
            out.append("share class: name says distributing, config says Acc")
        if not meta["acc"] and ACC.search(shown) and not DIST.search(shown):
            out.append("share class: name says accumulating, config says Dist")
    if meta.get("hedged") is True and not HEDGED.search(shown):
        out.append("hedge: config says EUR-hedged, name does not")
    if meta.get("hedged") is False and HEDGED.search(shown) and "unhedged" not in shown.lower():
        out.append("hedge: name says hedged, config says not")
    if _ENTITY_END.search(shown.partition(" - ")[0].strip()) and " - " in shown:
        out.append("legal-entity prefix still in the name")
    if meta.get("name_override"):
        out.append("overridden: " + meta.get("name_reason", "NO REASON GIVEN"))
    if meta["ticker"] in notes:
        out.append(notes[meta["ticker"]])
    return out


def main(argv=None) -> int:
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(root / "config" / "universe.yaml"))
    ap.add_argument("--out", default=str(root / "docs" / "fund-names.md"))
    ap.add_argument("--names-json", default=None)
    ap.add_argument("--notes-json", default=None)
    a = ap.parse_args(argv)
    cfg = yaml.safe_load(Path(a.config).read_text(encoding="utf-8"))
    tickers = sorted({r["ticker"] for s in cfg["sections"] if s.get("kind", "funds") == "funds" for r in s["rows"]})
    if a.names_json:
        names = json.loads(Path(a.names_json).read_text(encoding="utf-8"))
    else:
        from dashjobs import yahoo
        names = yahoo.fetch_names(tickers)
    notes = json.loads(Path(a.notes_json).read_text(encoding="utf-8")) if a.notes_json else {}
    lines, n_flag, seen = [], 0, set()
    for sec in cfg["sections"]:
        if sec.get("kind", "funds") != "funds":
            continue
        for r in sec["rows"]:
            if r["ticker"] in seen:
                continue
            seen.add(r["ticker"])
            q = names.get(r["ticker"]) or {}
            shown = pick_name(r, q, None)
            fl = flags_for(r, q.get("longName"), q.get("shortName"), shown, notes)
            n_flag += bool(fl)

            def cell(x):
                return (x or "").replace("|", "/").strip()
            lines.append(f"| {r['ticker']} | {r['isin']} | {cell(q.get('longName')) or '(missing)'} | {cell(q.get('shortName')) or '(missing)'} | {cell(shown)} | "
                         f"{'; '.join(fl)} |")
    head = f"""# Fund names (from Yahoo)

Generated {date.today().isoformat()} by `jobs/report_fund_names.py`. The markets job reads each ticker's `longName` and `shortName` from Yahoo (the same
source as the prices) and shows `longName`, falling back to `shortName` only if `longName` is missing. A ticker can carry `name_override` plus a one-line
`name_reason` in `config/universe.yaml` for a name Yahoo has wrong. A legal-entity prefix ("iShares VII PLC - ", "Amundi Index Solutions - ") is stripped by a rule in the job (`clean_name`), not by overrides; the longName column below is Yahoo's raw text. Abbreviations are left as Yahoo has them. If Yahoo's name call fails in a run, the last published name is kept (never blanked).

{len(lines)} funds, {n_flag} with a flag. Flags are automatic (missing, truncated, outdated brand, share class or hedge contradicting the config, legal-entity
prefix still present) plus hand-written remarks from a comparison with the justETF profile name for the same ISIN (the names the config used before this round).

| Ticker | ISIN | longName | shortName | Name shown | Flag |
|---|---|---|---|---|---|
"""
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(head + "\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {a.out}: {len(lines)} funds, {n_flag} flagged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
