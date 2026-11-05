"""Stage -> validate -> atomic swap (m1-plan section 4). Nothing is ever written into data/ while working."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path):
    p = Path(path)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


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
        write_json(Path(out_dir) / rel, obj)
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
