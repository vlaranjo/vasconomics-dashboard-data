"""Entry point: python jobs/run_yields.py [--data-dir data] [--work-dir work] [--today YYYY-MM-DD] [--countries us,uk,...]

Exit 0 on success (a country carried forward as stale, or skipped for a missing optional secret, is still success).
Exit 1 when every attempted country fails or a document fails validation at the manifest/status level.
Never writes into data/ except by the final atomic swap."""
import argparse
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dashjobs import validate  # noqa: E402
from dashjobs.yields import job  # noqa: E402
from dashjobs.yields.http import Getter  # noqa: E402


def main(argv=None) -> int:
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(root / "config" / "yields.yaml"))
    ap.add_argument("--data-dir", default=str(root / "data"))
    ap.add_argument("--work-dir", default=str(root / "work"))
    ap.add_argument("--today", default=None)
    ap.add_argument("--countries", default=None, help="comma list, for a partial local run")
    a = ap.parse_args(argv)
    cfg = yaml.safe_load(Path(a.config).read_text(encoding="utf-8"))
    today = date.fromisoformat(a.today) if a.today else datetime.now(timezone.utc).date()
    only = [c.strip() for c in a.countries.split(",")] if a.countries else None
    g = Getter(delay=cfg.get("delay_seconds", 2.0))
    try:
        res = job.run(cfg, g, today=today, data_dir=a.data_dir, work_dir=a.work_dir, env=dict(os.environ), only=only)
    except (job.NothingFetched, validate.ValidationError) as e:
        print(f"FAILED, nothing published: {e}", file=sys.stderr)
        return 1
    print(f"published: {len(res['ok'])} countr{'y' if len(res['ok']) == 1 else 'ies'} fresh ({', '.join(res['ok'])})")
    for f in res["failed"]:
        print(f"  kept previous / failed: {f}")
    for s in res["skipped"]:
        print(f"  skipped: {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
