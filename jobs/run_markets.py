"""Entry point: python jobs/run_markets.py [--data-dir data] [--work-dir work] [--today YYYY-MM-DD] [--fixture-dir DIR]

Exit 0 on success (including a run with a carried-forward stale row). Exit 1 on a validation failure
or when too few tickers could be fetched. Never writes into data/ except by the final atomic swap."""
import argparse
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dashjobs import markets, validate  # noqa: E402


def csv_fetcher(fixture_dir: Path):
    def fetch(symbol: str):
        p = fixture_dir / f"{symbol}.csv"
        if not p.exists():
            raise FileNotFoundError(symbol)
        out = []
        for line in p.read_text().splitlines()[1:]:
            d, c = line.split(",")[:2]
            out.append((date.fromisoformat(d), float(c)))
        return out
    return fetch


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    root = Path(__file__).resolve().parent.parent
    ap.add_argument("--config", default=str(root / "config" / "universe.yaml"))
    ap.add_argument("--data-dir", default=str(root / "data"))
    ap.add_argument("--work-dir", default=str(root / "work"))
    ap.add_argument("--today", default=None)
    ap.add_argument("--fixture-dir", default=None, help="read <SYMBOL>.csv instead of calling Yahoo (tests/offline)")
    ap.add_argument("--delay", type=float, default=3.0)
    a = ap.parse_args(argv)
    cfg = yaml.safe_load(Path(a.config).read_text(encoding="utf-8"))
    today = date.fromisoformat(a.today) if a.today else datetime.now(timezone.utc).date()
    if a.fixture_dir:
        fetch, delay = csv_fetcher(Path(a.fixture_dir)), 0
    else:
        from dashjobs import yahoo
        fetch, delay = yahoo.fetch_history, a.delay
    try:
        res = markets.run(cfg, fetch, today=today, data_dir=a.data_dir, work_dir=a.work_dir, delay=delay)
    except validate.ValidationError as e:
        print(f"VALIDATION FAILED, nothing published: {e}", file=sys.stderr)
        return 1
    print(f"published: {res['n_fresh']}/{res['n_total']} fresh, as_of {res['as_of']}")
    for f in res["failed"]:
        print(f"  carried forward / failed: {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
