"""Stage -> validate -> atomic swap (m1-plan section 4). Nothing is ever written into data/ while working."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path


COMPACT_DIRS = ("history/", "indicators/")      # long numeric arrays: written without indentation to keep the files small


def write_json(path: Path, obj, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    text = (json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False) if compact
            else json.dumps(obj, ensure_ascii=False, indent=1, allow_nan=False))
    tmp.write_text(text + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path):
    p = Path(path)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


MANIFEST_BLOCKS = ("sections", "history", "indicators", "pe", "yields")


def merge_manifest(prev: dict | None, *, generated_at: str, updates: dict[str, dict], keep: dict[str, set] | None = None) -> dict:
    """The new manifest = the published one, with ONLY the blocks this job owns replaced entry by entry.

    Every job goes through here, so no job can drop another job's entries: the starting point is a copy of what is published
    (all blocks, and any key this code does not know), `updates` adds or replaces entries by id, and `keep` (block -> ids still
    in the job's own config) removes entries of rows the config no longer has. Nothing is ever rebuilt from scratch.
    Tests M1-M3 in tests/test_publish_validate.py."""
    m = {k: v for k, v in (prev or {}).items()}
    for b in MANIFEST_BLOCKS:
        m[b] = dict(m.get(b) or {})
    for b, entries in updates.items():
        if b not in MANIFEST_BLOCKS:
            raise ValueError(f"unknown manifest block {b!r}")
        m[b].update(entries)
    for b, ids in (keep or {}).items():
        m[b] = {k: v for k, v in m[b].items() if k in ids}
    m.update({"schema_version": 1, "generated_at": generated_at, "status": "status.json"})
    return m


def stage(data_dir: Path, out_dir: Path) -> None:
    """Fresh copy of the published data into the staging folder."""
    data_dir, out_dir = Path(data_dir), Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    if data_dir.exists():
        shutil.copytree(data_dir, out_dir)
    else:
        out_dir.mkdir(parents=True)


def write_outputs(out_dir: Path, files: dict[str, object], manifest: dict) -> list[str]:
    """Write data files, then manifest.json LAST. Returns the write order (test V6)."""
    order = []
    for rel, obj in files.items():
        write_json(Path(out_dir) / rel, obj, compact=rel.startswith(COMPACT_DIRS))
        order.append(rel)
    write_json(Path(out_dir) / "manifest.json", manifest)
    order.append("manifest.json")
    return order


def atomic_swap(data_dir: Path, out_dir: Path) -> None:
    """Replace data_dir with out_dir by renames, restoring the old folder if anything goes wrong."""
    data_dir, out_dir = Path(data_dir), Path(out_dir)
    old = data_dir.with_name(data_dir.name + ".old")
    if old.exists():
        shutil.rmtree(old)
    had = data_dir.exists()
    if had:
        os.rename(data_dir, old)
    try:
        os.rename(out_dir, data_dir)
    except Exception:
        if had:
            if data_dir.exists():
                shutil.rmtree(data_dir)
            os.rename(old, data_dir)
        raise
    if had:
        shutil.rmtree(old)
