"""Entry point: python jobs/run_volatility.py [--data-dir data] [--work-dir work] [--today YYYY-MM-DD] [--cache-dir DIR]

^VIX, ^SKEW, ^MOVE from Yahoo Finance and the VX futures curve from Cboe (plain HTTP). Exit 0 on success, including a series kept
as published and marked stale. Exit 1 when nothing at all could be fetched and nothing is published, or a manifest/status check
fails. Never writes into data/ except by the final atomic swap.
--cache-dir (local runs only): keeps the CSVs of contracts that expired more than a week ago, which never change, so a local
re-run from an empty data folder does not read Cboe's whole archive again."""
import argparse
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dashjobs import validate, volatility  # noqa: E402
from dashjobs.yields.http import Getter  # noqa: E402


def load_universe(root: Path) -> dict:
    """The markets config: the manifest must keep an entry for every section in it, whichever job runs."""
    return yaml.safe_load((root / "config" / "universe.yaml").read_text(encoding="utf-8"))


def main(argv=None) -> int:
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(root / "config" / "volatility.yaml"))
    ap.add_argument("--data-dir", default=str(root / "data"))
    ap.add_argument("--work-dir", default=str(root / "work"))
    ap.add_argument("--today", default=None)
    ap.add_argument("--cache-dir", default=None)
    a = ap.parse_args(argv)
    cfg = yaml.safe_load(Path(a.config).read_text(encoding="utf-8"))
    today = date.fromisoformat(a.today) if a.today else datetime.now(timezone.utc).date()
    from dashjobs import yahoo
    g = Getter(delay=cfg.get("delay_seconds", 1.5))
    try:
        res = volatility.run(cfg, yahoo.fetch_history, g, today=today, data_dir=a.data_dir, work_dir=a.work_dir, universe=load_universe(root),
                             cache_dir=Path(a.cache_dir) if a.cache_dir else None)
    except (volatility.NothingFetched, validate.ValidationError) as e:
        print(f"FAILED, nothing published: {e}", file=sys.stderr)
        return 1
    print(f"published: {res['ok']}/{res['total']} series fresh")
    if res["vx"]:
        print(f"  Cboe: {res['vx']['requests']} requests; rebuilt from {res['vx']['rebuilt_from']}; "
              f"day's settlement file used for {', '.join(res['vx']['daily_dates']) or 'no date'}")
    for r in res["rows"].values():
        print(f"  {r['name']:<18} {r['latest']:>8} on {r['date']}" + ("  STALE" if r["stale"] else ""))
    for f in res["failed"]:
        print(f"  kept previous / failed: {f}")
    for n in res["notes"]:
        print(f"  note: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
