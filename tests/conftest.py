import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "jobs"))
FIX = Path(__file__).resolve().parent / "fixtures"


def load_csv(symbol: str, upto: date | None = None):
    out = []
    for line in (FIX / "yahoo" / f"{symbol}.csv").read_text().splitlines()[1:]:
        d, c = line.split(",")[:2]
        d = date.fromisoformat(d)
        if upto is None or d <= upto:
            out.append((d, float(c)))
    return out


@pytest.fixture
def cfg():
    import yaml
    return yaml.safe_load((ROOT / "tests" / "fixtures" / "config" / "universe_m1.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def pe_cfg():
    import yaml
    return yaml.safe_load((ROOT / "tests" / "fixtures" / "config" / "pe_index_map_m1.yaml").read_text(encoding="utf-8"))


def fixture_fetch(upto: date | None = None, fail: set[str] = frozenset()):
    def fetch(symbol):
        if symbol in fail:
            raise RuntimeError("simulated fetch failure")
        return load_csv(symbol, upto)
    return fetch


def seed_markets(tmp_path, cfg, today: date = date(2026, 11, 4)):
    """A published markets run in tmp_path/data: every job now needs the universe config and a complete manifest to merge into."""
    from datetime import datetime, timezone
    from dashjobs import markets
    markets.run(cfg, fixture_fetch(today), today=today, now=datetime(2026, 11, 4, 22, 41, tzinfo=timezone.utc),
                data_dir=tmp_path / "data", work_dir=tmp_path / "seedwork", sleep=lambda s: None, retry_wait=0)
    return cfg
