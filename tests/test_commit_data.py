"""jobs/commit_data.py: commit only real changes (plus one heartbeat a day) and merge two jobs finishing at once (C1-C6)."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "jobs"))
import commit_data as cd  # noqa: E402

NOW = 1_800_000_000.0


def sh(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def put(root: Path, rel: str, obj):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


def seed(root: Path):
    put(root, "data/manifest.json", {"schema_version": 1, "generated_at": "2026-11-09T10:00:00Z", "status": "status.json",
                                    "sections": {"fx": {"as_of": "2026-11-06"}}, "history": {}, "indicators": {}, "pe": {"a": {"last_point": "2026-10"}},
                                    "yields": {"us": {"as_of": "2026-11-06"}}})
    put(root, "data/status.json", {"schema_version": 1, "generated_at": "2026-11-09T10:00:00Z", "heartbeat": "2026-11-09T10:00:00Z",
                                  "run": {"workflow": "markets", "run_id": 1}, "sources": {
                                      "yahoo_markets": {"last_attempt": "t0", "last_success": "t0", "ok": True, "failed": []},
                                      "yield_curves": {"last_attempt": "t0", "last_success": "t0", "ok": True, "failed": []},
                                      "worldperatio": {"last_attempt": "t0", "last_success": "t0", "ok": True, "failed": []}}})
    put(root, "data/sections/fx.json", {"generated_at": "2026-11-09T10:00:00Z", "as_of": "2026-11-06",
                                       "rows": [{"id": "x", "last_close": "2026-11-06", "last_success": "2026-11-09T10:00:00Z"}]})
    put(root, "data/yields/us.json", {"fetched_at": "2026-11-09T10:00:00Z", "last_success": "2026-11-09T10:00:00Z", "as_of": "2026-11-06"})


@pytest.fixture
def world(tmp_path):
    """A bare 'origin' and two clones (two runners), all on branch dev with the same seed commit made at NOW - 1 h."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "dev", str(origin)], check=True)
    a = tmp_path / "a"
    subprocess.run(["git", "clone", "-q", str(origin), str(a)], check=True, capture_output=True)
    sh(a, "config", "user.email", "t@t"), sh(a, "config", "user.name", "t")
    sh(a, "checkout", "-q", "-b", "dev")
    seed(a)
    sh(a, "add", "-A")
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=a, check=True, env={**__import__("os").environ, "GIT_COMMITTER_DATE": f"{int(NOW) - 3600} +0000", "GIT_AUTHOR_DATE": f"{int(NOW) - 3600} +0000"})
    sh(a, "push", "-q", "origin", "dev")
    b = tmp_path / "b"
    subprocess.run(["git", "clone", "-q", "-b", "dev", str(origin), str(b)], check=True, capture_output=True)
    sh(b, "config", "user.email", "t@t"), sh(b, "config", "user.name", "t")
    return origin, a, b


def commits(repo):
    return int(sh(repo, "rev-list", "--count", "HEAD"))


def stamp_only(root: Path, tag: str):
    """What a markets run with nothing newer writes: new stamps everywhere, same data."""
    m = json.loads((root / "data/manifest.json").read_text()); m["generated_at"] = tag
    put(root, "data/manifest.json", m)
    s = json.loads((root / "data/status.json").read_text())
    s.update(generated_at=tag, heartbeat=tag, run={"workflow": "markets", "run_id": 2})
    s["sources"]["yahoo_markets"].update(last_attempt=tag, last_success=tag)
    put(root, "data/status.json", s)
    f = json.loads((root / "data/sections/fx.json").read_text()); f["generated_at"] = tag
    f["rows"][0]["last_success"] = tag
    put(root, "data/sections/fx.json", f)


def test_C1_nothing_changed_makes_no_commit(world):
    _, a, _ = world
    assert cd.run("markets", "m", "dev", cwd=a, now=NOW) is False and commits(a) == 1


def test_C2_stamp_only_change_is_discarded_within_a_day(world):
    _, a, _ = world
    stamp_only(a, "2026-11-09T17:47:00Z")
    assert cd.run("markets", "m", "dev", cwd=a, now=NOW) is False
    assert commits(a) == 1 and sh(a, "status", "--porcelain") == ""            # the stamps are gone from the working tree too


def test_C3_stamp_only_change_after_a_day_is_one_heartbeat_commit(world, monkeypatch):
    origin, a, _ = world
    monkeypatch.setenv("GIT_COMMITTER_DATE", f"{int(NOW) + 24 * 3600} +0000")           # the commit is made at the fake 'now'
    stamp_only(a, "2026-11-10T17:47:00Z")
    assert cd.run("markets", "m", "dev", cwd=a, now=NOW + 24 * 3600) is True
    assert commits(a) == 2 and sh(a, "log", "-1", "--format=%s") == "m (heartbeat)"
    assert sh(origin, "rev-list", "--count", "dev") == "2"
    stamp_only(a, "2026-11-10T19:47:00Z")                                       # the next run, two hours later: no second commit
    assert cd.run("markets", "m", "dev", cwd=a, now=NOW + 26 * 3600) is False and commits(a) == 2


def test_C4_a_real_change_commits_and_pushes(world):
    origin, a, _ = world
    f = json.loads((a / "data/sections/fx.json").read_text()); f["as_of"] = "2026-11-09"; f["rows"][0]["last_close"] = "2026-11-09"
    put(a, "data/sections/fx.json", f)
    stamp_only_tag = "2026-11-09T17:47:00Z"
    m = json.loads((a / "data/manifest.json").read_text()); m["sections"]["fx"]["as_of"] = "2026-11-09"; m["generated_at"] = stamp_only_tag
    put(a, "data/manifest.json", m)
    assert cd.run("markets", "m", "dev", cwd=a, now=NOW) is True
    assert sh(origin, "log", "-1", "--format=%s", "dev") == "m"


def test_C5_a_row_going_stale_is_a_real_change(world):
    _, a, _ = world
    f = json.loads((a / "data/sections/fx.json").read_text()); f["rows"][0]["stale"] = True
    put(a, "data/sections/fx.json", f)
    assert cd.run("markets", "m", "dev", cwd=a, now=NOW) is True


def test_C6_two_jobs_finishing_at_once_both_survive(world):
    """markets (clone a) and yields (clone b) both edit manifest.json and status.json from the same base; b pushes second."""
    origin, a, b = world
    f = json.loads((a / "data/sections/fx.json").read_text()); f["as_of"] = "2026-11-09"
    put(a, "data/sections/fx.json", f)
    m = json.loads((a / "data/manifest.json").read_text()); m["sections"]["fx"]["as_of"] = "2026-11-09"; m["generated_at"] = "2026-11-09T17:47:00Z"
    put(a, "data/manifest.json", m)
    s = json.loads((a / "data/status.json").read_text()); s["generated_at"] = "2026-11-09T17:47:30Z"; s["sources"]["yahoo_markets"]["items_ok"] = 112
    put(a, "data/status.json", s)

    u = json.loads((b / "data/yields/us.json").read_text()); u["as_of"] = "2026-11-09"; u["last_success"] = "2026-11-09T17:47:10Z"
    put(b, "data/yields/us.json", u)
    m = json.loads((b / "data/manifest.json").read_text()); m["yields"]["us"]["as_of"] = "2026-11-09"; m["generated_at"] = "2026-11-09T17:47:10Z"
    put(b, "data/manifest.json", m)
    s = json.loads((b / "data/status.json").read_text()); s["generated_at"] = "2026-11-09T17:47:10Z"; s["sources"]["yield_curves"]["items_ok"] = 9
    s["run"] = {"workflow": "yields", "run_id": 9}
    put(b, "data/status.json", s)

    assert cd.run("markets", "data: markets", "dev", cwd=a, now=NOW, sleep=lambda s: None) is True        # a pushes first
    assert cd.run("yields", "data: yields", "dev", cwd=b, now=NOW, sleep=lambda s: None) is True         # b is rejected, re-applies, pushes
    final = tmp = origin.parent / "check"
    subprocess.run(["git", "clone", "-q", "-b", "dev", str(origin), str(final)], check=True, capture_output=True)
    man = json.loads((final / "data/manifest.json").read_text())
    st = json.loads((final / "data/status.json").read_text())
    assert man["sections"]["fx"]["as_of"] == "2026-11-09" and man["yields"]["us"]["as_of"] == "2026-11-09"     # both jobs' blocks
    assert st["sources"]["yahoo_markets"]["items_ok"] == 112 and st["sources"]["yield_curves"]["items_ok"] == 9
    assert json.loads((final / "data/sections/fx.json").read_text())["as_of"] == "2026-11-09"
    assert json.loads((final / "data/yields/us.json").read_text())["as_of"] == "2026-11-09"
    assert man["generated_at"] == "2026-11-09T17:47:10Z" or man["generated_at"] > "2026-11-09T17:47:00Z"
    assert sh(final, "rev-list", "--count", "HEAD") == "3"                                                    # seed + one commit each, no merge commits
