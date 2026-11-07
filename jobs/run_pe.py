"""Entry point: python jobs/run_pe.py [--data-dir data] [--work-dir work] [--today YYYY-MM-DD] [--fixture-dir DIR]

Exit 1 only if no index could be fetched at all or validation fails. One stale index is shown on the page."""
import argparse
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dashjobs import pe, validate, worldperatio  # noqa: E402


def main(argv=None) -> int:
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(root / "config" / "pe_index_map.yaml"))
    ap.add_argument("--data-dir", default=str(root / "data"))
    ap.add_argument("--work-dir", default=str(root / "work"))
    ap.add_argument("--today", default=None)
    ap.add_argument("--fixture-dir", default=None, help="read <slug>.html instead of the network")
    a = ap.parse_args(argv)
    cfg = yaml.safe_load(Path(a.config).read_text(encoding="utf-8"))
    today = date.fromisoformat(a.today) if a.today else datetime.now(timezone.utc).date()
    sleep_fn = lambda s: None  # noqa: E731
    if a.fixture_dir:
        by_url = {i["url"]: Path(a.fixture_dir) / f"{i['slug']}.html" for i in cfg["indices"]}
        fetch = lambda url: by_url[url].read_text(encoding="utf-8")  # noqa: E731
    else:
        import time
        sleep_fn = time.sleep
        fetch = lambda url: worldperatio.fetch_page(url, cfg["user_agent"])  # noqa: E731
    try:
        res = pe.run(cfg, fetch, today=today, data_dir=a.data_dir, work_dir=a.work_dir, sleep=sleep_fn)
    except (pe.NothingFetched, validate.ValidationError) as e:
        print(f"FAILED, nothing published: {e}", file=sys.stderr)
        return 1
    print(f"published: {res['ok']} index file(s) fresh")
    for f in res["failed"]:
        print(f"  kept previous / failed: {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
