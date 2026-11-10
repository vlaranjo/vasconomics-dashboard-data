"""P1-P4: worldperatio parsing and validation."""
import json
from datetime import date, datetime, timezone

import pytest

from conftest import FIX, seed_markets
from dashjobs import pe, worldperatio as w


def page(slug):
    return (FIX / "pe" / f"{slug}.html").read_text(encoding="utf-8")


def test_P1_parse_fixtures_first_last_and_month_offset():
    s = w.parse_series(page("sp-500"))
    assert s[0] == ("1871-01", 11.1) and s[-1][0] == "2026-11" and len(s) == 1871  # Date.UTC month 0 -> "01"
    e = w.parse_series(page("sp-500-energy"))
    assert e[0][0] == "1995-02" and e[-1][0] == "2026-11" and len(e) == 382


def test_P2_parse_failure_marks_that_index_stale_others_publish(pe_cfg, cfg, tmp_path):
    pages = {i["url"]: page(i["slug"]) for i in pe_cfg["indices"]}
    kw = dict(today=date(2026, 11, 5), data_dir=tmp_path / "data", work_dir=tmp_path / "work", sleep=lambda s: None, universe=seed_markets(tmp_path, cfg))
    pe.run(pe_cfg, lambda u: pages[u], now=datetime(2026, 11, 1, 3, 7, tzinfo=timezone.utc), **kw)
    broken = dict(pages)
    broken["https://worldperatio.com/sector/sp-500-energy"] = "<html>no data variable</html>"
    res = pe.run(pe_cfg, lambda u: broken[u], now=datetime(2026, 11, 8, 3, 7, tzinfo=timezone.utc), **kw)
    energy = json.loads((tmp_path / "data/pe/sp-500-energy.json").read_text())
    sp = json.loads((tmp_path / "data/pe/sp-500.json").read_text())
    assert res["ok"] == 1 and energy["stale"] is True and sp["stale"] is False
    assert energy["last_success"] == "2026-11-01T03:07:00Z" and sp["last_success"] == "2026-11-08T03:07:00Z"


def test_P2b_every_index_failing_is_a_failed_run(pe_cfg, cfg, tmp_path):
    before = (seed_markets(tmp_path, cfg) and (tmp_path / "data" / "manifest.json").read_bytes())
    with pytest.raises(pe.NothingFetched):
        pe.run(pe_cfg, lambda u: "<html></html>", today=date(2026, 11, 5), data_dir=tmp_path / "data",
               work_dir=tmp_path / "work", sleep=lambda s: None, universe=cfg)
    assert (tmp_path / "data" / "manifest.json").read_bytes() == before and not (tmp_path / "data" / "pe").exists()


def test_P3_averages_are_exact_means():
    s = w.parse_series(page("sp-500"))
    vals = [v for _, v in s]
    a10, afull = w.averages(s)
    assert a10 == round(sum(vals[-120:]) / 120, 2) and afull == round(sum(vals) / len(vals), 2)
    flat = [(f"{2000 + i // 12}-{i % 12 + 1:02d}", float(i)) for i in range(300)]
    assert w.averages(flat)[0] == round(sum(range(180, 300)) / 120, 2)
    assert w.averages(flat)[1] == round(sum(range(300)) / 300, 2)


def test_P4_last_point_must_be_recent():
    s = w.parse_series(page("sp-500"))
    w.validate_series(s, date(2026, 11, 5), "1871-01")  # fine
    with pytest.raises(w.ParseError, match="too old"):
        w.validate_series(s[:-14], date(2026, 11, 5))  # ends 2025-09
    with pytest.raises(w.ParseError, match="only"):
        w.validate_series(s[:100], date(2026, 11, 5))


def test_P5_manifest_entries_carry_name_group_and_pages_for_the_selector(tmp_path, pe_cfg, cfg):
    pe_cfg2 = dict(pe_cfg)
    pe_cfg2["indices"] = [dict(i, group="G", pages=["us-sectors"]) if i["slug"] == "sp-500-energy" else i for i in pe_cfg2["indices"]]
    pages = {i["url"]: page(i["slug"]) for i in pe_cfg2["indices"]}
    pe.run(pe_cfg2, lambda u: pages[u], today=date(2026, 11, 5), data_dir=tmp_path / "data", work_dir=tmp_path / "work", sleep=lambda s: None,
           universe=seed_markets(tmp_path, cfg))
    man = json.loads((tmp_path / "data" / "manifest.json").read_text())
    assert man["pe"]["sp-500-energy"]["name"] and man["pe"]["sp-500-energy"]["group"] == "G" and man["pe"]["sp-500-energy"]["pages"] == ["us-sectors"]
