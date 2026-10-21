#!/usr/bin/env python3
"""Panel self-check (v3.4 design 6.12): did a rebuild change the printed panels PA / PB / PL?

    python -I scripts/panel_hash.py              first run: store the hashes of out/parts/print in out/panel_hashes.json;
                                                 later runs: compare out/parts/print with the stored hashes
    python -I scripts/panel_hash.py DIR          compare DIR (a parts/print folder) with the stored hashes
    python -I scripts/panel_hash.py DIR_A DIR_B  compare two folders

Prints only "相同" / "不同" per panel and colour, never a hash (the panels carry the numbers and texts; the hash file
stays in out/, which is gitignored). A hash covers the print-pose mesh as exported: its vertex set (STL values on a
GRID mm grid, sorted, so neither the vertex nor the triangle order matters) and its triangle count. Moving a panel in
the assembly (another [mount] set) leaves float noise on the bed face (Z 1e-7 instead of 0) and can flip a few
diagonals of the same vertices: the grid and leaving the triangles out keep such a rebuild "相同". To start over,
delete out/panel_hashes.json.
"""
import hashlib
import json
import struct
import sys
from pathlib import Path

import numpy as np

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DIR = PROJECT_DIR / "out" / "parts" / "print"
HASH_FILE = PROJECT_DIR / "out" / "panel_hashes.json"
PANELS = {"A": "PA", "B": "PB", "L": "PL"}
COLOURS = {"white": "白", "azure": "天蓝", "navy": "藏青"}
GRID = 1e-5                                   # mm


def read_triangles(path):
    """(n, 3, 3) float32 vertices of a binary or ASCII STL, as stored."""
    data = path.read_bytes()
    if len(data) >= 84:
        count = struct.unpack_from("<I", data, 80)[0]
        if 84 + 50 * count == len(data):
            record = np.dtype([("normal", "<f4", 3), ("v", "<f4", (3, 3)), ("attr", "<u2")])
            return np.frombuffer(data, dtype=record, count=count, offset=84)["v"]
    values = [line.split()[1:4] for line in data.decode().splitlines() if line.strip().startswith("vertex")]
    return np.array(values, dtype=np.float32).reshape(-1, 3, 3)


def mesh_hash(path):
    triangles = read_triangles(path)
    grid = np.round(triangles.reshape(-1, 3).astype(np.float64) / GRID).astype(np.int64)
    digest = hashlib.sha256(np.ascontiguousarray(np.unique(grid, axis=0), dtype="<i8").tobytes())
    digest.update(str(len(triangles)).encode())
    return digest.hexdigest()


def panel_hashes(folder):
    """{"panel_A.white": hash, ...} of the panel files in a parts/print folder."""
    files = sorted(folder.glob("panel_*.stl"))
    if not files:
        raise SystemExit(f"no panel_*.stl in {folder}: build first (scripts/build_all.py) or give a parts/print folder")
    return {path.stem: mesh_hash(path) for path in files}


def label(name):
    panel, colour = name.split(".")
    return f"{PANELS.get(panel.removeprefix('panel_'), panel)} {COLOURS.get(colour, colour)}"


def compare(old, new):
    """Print one line per panel colour; True when all are the same."""
    same = True
    for name in sorted(set(old) | set(new)):
        if name not in old or name not in new:
            print(f"{label(name)} 不同（只在{'新' if name in new else '旧'}的一边有）")
            same = False
        else:
            print(f"{label(name)} {'相同' if old[name] == new[name] else '不同'}")
            same &= old[name] == new[name]
    return same


def main(arguments):
    if len(arguments) == 2:
        return 0 if compare(panel_hashes(Path(arguments[0])), panel_hashes(Path(arguments[1]))) else 1
    folder = Path(arguments[0]) if arguments else DEFAULT_DIR
    if not HASH_FILE.exists():
        if arguments:
            raise SystemExit(f"{HASH_FILE.name} not found: run without a folder first to store the hashes")
        hashes = panel_hashes(folder)
        HASH_FILE.write_text(json.dumps(dict(version=1, hashes=hashes), indent=1), encoding="utf-8")
        print(f"已存下 {len(hashes)} 个面板网格的哈希（out/{HASH_FILE.name}）：重建以后再运行一次比对")
        return 0
    stored = json.loads(HASH_FILE.read_text(encoding="utf-8"))["hashes"]
    return 0 if compare(stored, panel_hashes(folder)) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
