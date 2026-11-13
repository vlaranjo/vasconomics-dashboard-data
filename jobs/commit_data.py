"""Commit and push what a data job wrote into data/, only when it is worth a commit (decisions S4, S5).

    python jobs/commit_data.py --job markets|pe|yields|volatility --message "data: markets 123" --branch dev

1. Nothing changed in data/: nothing to do.
2. Something changed, but only volatile stamps (generated_at, heartbeat, run, last_attempt, started/finished, fetched_at, and for
   markets every last_success): the change is DISCARDED, unless the last commit that touched data/ is older than HEARTBEAT_HOURS,
   in which case one heartbeat commit is made (the 60-day keep-alive and the page's "last update run" need no more).
3. A real change: commit.
Then push. Another job may have pushed meanwhile (each workflow has its own concurrency group, so two jobs can finish at once):
a rejected push is retried by re-applying this job's own files on top of the new remote state; manifest.json and status.json,
which every job edits, are merged by ownership (this job's manifest blocks and its source block in status.json replace the
remote's, everything else is the remote's). No git conflict can arise, and neither job's data is lost.

Writes `changed=true|false` to $GITHUB_OUTPUT: the Pages deploy runs only when it is true. Exit 1 if the push still fails."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

HEARTBEAT_HOURS = 16      # about one a day; low enough that the first run of a no-change weekday still refreshes last_success
VOLATILE = {"generated_at", "heartbeat", "run", "last_attempt", "started_at", "finished_at", "fetched_at"}
# job -> (manifest blocks it owns, its source block in status.json, keys that are volatile everywhere in its files)
OWN = {"markets": ({"sections", "history", "indicators"}, "yahoo_markets", {"last_success"}),
       "pe": ({"pe"}, "worldperatio", set()),
       "yields": ({"yields"}, "yield_curves", set()),
       # Volatility page (13 Nov 2026): like markets, every file's last_success moves on every run, so it is a stamp; so is
       # vx-history's archive_last (the last date in Cboe's CSVs, which moves each morning when Cboe rewrites them, without any
       # figure on the page changing)
       "volatility": ({"volatility"}, "volatility", {"last_success", "archive_last"})}
SHARED = ("data/manifest.json", "data/status.json")


def git(*args: str, check: bool = True, cwd=None, text: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], check=check, cwd=cwd, capture_output=True, text=text)


def _strip(o, volatile: set, in_status: bool):
    if isinstance(o, dict):
        out = {}
        for k, v in o.items():
            if k in volatile:
                continue
            if in_status and k == "last_success":
                continue                         # status.json: the source blocks' last_success moves on every run
            out[k] = _strip(v, volatile, in_status)
        return out
    if isinstance(o, list):
        return [_strip(x, volatile, in_status) for x in o]
    return o


def normalised(path: str, blob: bytes | None, job: str):
    if blob is None:
        return None
    if not path.endswith(".json"):
        return blob
    try:
        return _strip(json.loads(blob), VOLATILE | OWN[job][2], path == "data/status.json")
    except ValueError:
        return blob


def meaningful(job: str, cwd=None) -> bool:
    """Does the staged change differ from HEAD by more than volatile stamps?"""
    rows = git("diff", "--cached", "--name-status", "--no-renames", "--", "data", cwd=cwd).stdout.split("\n")
    for row in filter(None, rows):
        st, path = row.split("\t", 1)
        if st != "M":
            return True                          # a file added or removed
        old = git("show", f"HEAD:{path}", cwd=cwd, text=False).stdout
        new = git("show", f":{path}", cwd=cwd, text=False).stdout
        if normalised(path, old, job) != normalised(path, new, job):
            return True
    return False


def last_data_commit_age_hours(now: float, cwd=None) -> float:
    out = git("log", "-1", "--format=%ct", "--", "data", cwd=cwd).stdout.strip()
    return (now - int(out)) / 3600 if out else 1e9


def merge_shared(path: str, job: str, theirs: bytes, mine: bytes) -> bytes:
    blocks, source, _ = OWN[job]
    t, m = json.loads(theirs), json.loads(mine)
    if path.endswith("manifest.json"):
        for b in blocks:
            if b in m:
                t[b] = m[b]
        t["generated_at"] = max(t.get("generated_at", ""), m.get("generated_at", ""))
    else:
        t.setdefault("sources", {})
        if source in m.get("sources", {}):
            t["sources"][source] = m["sources"][source]
        if m.get("generated_at", "") >= t.get("generated_at", ""):
            for k in ("run", "heartbeat", "generated_at"):
                t[k] = m[k]
    return (json.dumps(t, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def reapply_on_remote(job: str, message: str, branch: str, cwd=None) -> bool:
    """Rebuild my commit on top of origin/<branch>. Returns False when it adds nothing to the remote."""
    changed = [r.split("\t", 1) for r in git("diff", "--name-status", "--no-renames", "HEAD~1", "HEAD", cwd=cwd).stdout.split("\n") if r]
    mine = {p: (None if st == "D" else git("show", f"HEAD:{p}", cwd=cwd, text=False).stdout) for st, p in changed}
    git("reset", "--hard", f"origin/{branch}", cwd=cwd)
    root = cwd or "."
    for p, blob in mine.items():
        full = os.path.join(root, p)
        if blob is None:
            if os.path.exists(full):
                os.remove(full)
            continue
        if p in SHARED and os.path.exists(full):
            blob = merge_shared(p, job, open(full, "rb").read(), blob)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        open(full, "wb").write(blob)
    git("add", "-A", "data", cwd=cwd)
    if not git("diff", "--cached", "--name-only", cwd=cwd).stdout.strip():
        return False
    git("commit", "-q", "-m", message, cwd=cwd)
    return True


def set_output(changed: bool) -> None:
    line = f"changed={'true' if changed else 'false'}"
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    print(line)


def run(job: str, message: str, branch: str, *, cwd=None, now: float | None = None, sleep=time.sleep, retries: int = 4) -> bool:
    """Returns True when a commit was pushed (or nothing needed pushing after a merge)."""
    now = time.time() if now is None else now
    git("add", "-A", "data", cwd=cwd)
    if not git("diff", "--cached", "--name-only", cwd=cwd).stdout.strip():
        print("data/ is unchanged: nothing to commit")
        return False
    if not meaningful(job, cwd):
        age = last_data_commit_age_hours(now, cwd)
        if age < HEARTBEAT_HOURS:
            git("reset", "-q", cwd=cwd)
            git("checkout", "--", "data", cwd=cwd)
            git("clean", "-fdq", "data", cwd=cwd)
            print(f"only stamps changed and the last data commit is {age:.1f} h old: discarded, no commit")
            return False
        message += " (heartbeat)"
        print(f"only stamps changed, but the last data commit is {age:.1f} h old: heartbeat commit")
    git("commit", "-q", "-m", message, cwd=cwd)
    for attempt in range(1, retries + 1):
        if git("push", "origin", f"HEAD:{branch}", check=False, cwd=cwd).returncode == 0:
            print(f"pushed ({attempt} attempt{'s' if attempt > 1 else ''})")
            return True
        print(f"push rejected (attempt {attempt}): another job pushed first; re-applying on the new state")
        git("fetch", "-q", "origin", branch, cwd=cwd)
        if not reapply_on_remote(job, message, branch, cwd):
            print("nothing left to add after the merge")
            return False
        sleep(3)
    raise SystemExit("push failed after retries")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True, choices=sorted(OWN))
    ap.add_argument("--message", required=True)
    ap.add_argument("--branch", required=True)
    a = ap.parse_args(argv)
    set_output(run(a.job, a.message, a.branch))
    return 0


if __name__ == "__main__":
    sys.exit(main())
