"""Entry point: python jobs/run_characteristics.py [--data-dir data] [--work-dir work] [--today YYYY-MM-DD]

Weekly. Reads each enabled issuer's fund pages (plain requests, 5 s apart), validates, swaps data/ atomically. Exit 0 on success,
including funds kept stale; exit 1 when validation of the whole file fails (nothing published)."""
import argparse
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dashjobs import characteristics, validate  # noqa: E402


def main(argv=None) -> int:
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(root / "config" / "characteristics.yaml"))
    ap.add_argument("--universe", default=str(root / "config" / "universe.yaml"))
    ap.add_argument("--data-dir", default=str(root / "data"))
    ap.add_argument("--work-dir", default=str(root / "work"))
    ap.add_argument("--today", default=None)
    a = ap.parse_args(argv)
    cfg = yaml.safe_load(Path(a.config).read_text(encoding="utf-8"))
    universe = yaml.safe_load(Path(a.universe).read_text(encoding="utf-8"))
    today = date.fromisoformat(a.today) if a.today else datetime.now(timezone.utc).date()
    getter = characteristics.Getter()
    try:
        res = characteristics.run(cfg, universe, getter, today=today, data_dir=a.data_dir, work_dir=a.work_dir)
    except validate.ValidationError as e:
        print(f"VALIDATION FAILED, nothing published: {e}", file=sys.stderr)
        return 1
    print(f"published: {res['ok']}/{res['tried']} funds read; requests: {len(getter.log)}")
    for line in getter.log:
        print("  ", line)
    for p in res["problems"]:
        print("  problem:", p)
    for iss, why in res["refused"].items():
        print(f"  STOPPED asking {iss}: {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
