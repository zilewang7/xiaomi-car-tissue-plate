#!/usr/bin/env python3
"""Leak check before publishing (v3.4 design 7): search a folder for the numbers and texts of a config.toml.

    python -I scripts/leak_check.py FOLDER [CONFIG]       CONFIG defaults to config.toml in the project

Reads [numbers] a / b and [text] a / b / l of CONFIG (never printed) and searches every file under FOLDER, by content
(UTF-8 and UTF-16 text, also inside zip / 3MF members) and by name: a number also with spaces, dots, dashes or
brackets between its digits, a text case-insensitively. Prints only the files with hits (a hit in a name shown as •••)
and how many; exit 1 then. Numbers drawn in images, PDFs, meshes and G-code are not text: those files are listed for
a look of your own. Files under .git are not searched; exit 1 also when no file is left to search.
"""
import re
import sys
import tomllib
import zipfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
UNREADABLE = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".stl", ".step", ".stp", ".3mf", ".gcode")


def patterns(config_path):
    with open(config_path, "rb") as handle:
        data = tomllib.load(handle)
    numbers = [v for v in data.get("numbers", {}).values() if isinstance(v, str)]
    texts = [v for v in data.get("text", {}).values() if isinstance(v, str) and v.strip()]
    found = [re.compile(r"[\s.()\-]*".join(re.escape(digit) for digit in number)) for number in numbers]
    return found + [re.compile(re.escape(text), re.IGNORECASE) for text in texts]


def decoded(data):
    return [data.decode("utf-8", errors="ignore"), data.decode("utf-16-le", errors="ignore"),
            data.decode("utf-16-be", errors="ignore")]


def contents(path):
    data = path.read_bytes()
    texts = decoded(data)
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for member in archive.namelist():
                texts += [member] + decoded(archive.read(member))
    return texts


def masked(text, found):
    for pattern in found:
        text = pattern.sub("•••", text)
    return text


def main(arguments):
    if not arguments:
        raise SystemExit(__doc__)
    folder = Path(arguments[0])
    found = patterns(Path(arguments[1]) if len(arguments) > 1 else PROJECT_DIR / "config.toml")
    files = [path for path in sorted(folder.rglob("*")) if path.is_file() and ".git" not in path.parts]
    if not files:
        raise SystemExit(f"no files under {folder}: nothing was searched")
    hits = {}
    for path in files:
        for text in [str(path.relative_to(folder))] + contents(path):
            count = sum(len(pattern.findall(text)) for pattern in found)
            if count:
                hits[path] = hits.get(path, 0) + count
    for path, count in hits.items():
        print(f"hit: {masked(str(path.relative_to(folder)), found)} ({count})")
    print(f"{len(files)} files searched, {len(hits)} with hits")
    unreadable = [path for path in files if path.suffix.lower() in UNREADABLE]
    if unreadable:
        print(f"{len(unreadable)} files hold pictures or shapes, where a drawn number is not text and cannot be found: "
              "look at each, or leave it out")
        for path in unreadable:
            print(f"  {masked(str(path.relative_to(folder)), found)}")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
