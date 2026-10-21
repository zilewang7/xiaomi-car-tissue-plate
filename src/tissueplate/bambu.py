"""Bambu Studio presets and CLI: flatten system presets, apply the project overrides, slice, parse results.

Rules from the design doc (v3.2 sections 3.2-16 and 5):
- system presets are flattened (inherits chain + include templates) before they are passed to the CLI;
- AMS slots 1 white, 2 azure, 3 navy; filament shrink 99.4 %; textured PEI plate;
- wipe tower inside the bed (default 165/250 is outside the P1S bed); flush volumes: the values Bambu Studio's colour
  defaults give for the three AMS colours (FLUSH_VOLUMES).
The CLI (webui design 6.3): TISSUEPLATE_BAMBU_STUDIO (executable) / TISSUEPLATE_BAMBU_PROFILES (its profiles/BBL), else
the install location of the platform (Linux has none: point the variable to squashfs-root/AppRun of the extracted
AppImage); it must start once (`--help`). Otherwise slicer() raises SlicerUnavailable and the build goes on without
the 3MF (no-slicer mode, 6.4).
"""
from __future__ import annotations

import json
import math
import os
import plistlib
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .params import OUT_DIR

APP_VERSION = "02.08.02.61"          # the preset names and export3mf.APPLICATION are those of this version
ENV_STUDIO = "TISSUEPLATE_BAMBU_STUDIO"
ENV_PROFILES = "TISSUEPLATE_BAMBU_PROFILES"
MAC_APPS = (Path("/Applications/BambuStudio.app"), Path.home() / "Applications" / "BambuStudio.app")
MACHINE_PRESET = "Bambu Lab P1S 0.4 nozzle"
PROCESS_PRESET = "0.20mm Standard @BBL X1C"
FILAMENT_PRESET = "Bambu ABS @BBL P1S 0.4 nozzle"
BED_TYPE = "Textured PEI Plate"
AMS_SLOTS = {1: ("white", "#FFFFFF"), 2: ("azure", "#489FDF"), 3: ("navy", "#0C2340")}
SLOT = {name: slot for slot, (name, _) in AMS_SLOTS.items()}
FILAMENT_SHRINK = "99.4%"
WIPE_TOWER_XY = (205.0, 170.0)
# flush volumes (mm^3) Bambu Studio sets by default for white / azure / navy on the 0.4 hot end: row = from slot,
# column = to slot, flattened as Bambu stores it
FLUSH_VOLUMES = ("0", "264", "209",
                 "513", "0", "218",
                 "642", "468", "0")
INCLUDE_SKIP = {"name", "instantiation", "type", "from", "setting_id", "inherits", "include"}

# per-object process settings used by the plates (values in Bambu's string format)
STRUCT_SETTINGS = {"wall_loops": "4", "sparse_infill_density": "25%", "sparse_infill_pattern": "gyroid"}
SMALL_SETTINGS = {"wall_loops": "4", "sparse_infill_density": "40%", "sparse_infill_pattern": "gyroid"}
PANEL_SETTINGS = {"sparse_infill_density": "100%", "sparse_infill_pattern": "zig-zag"}

# far pin P (Ø6 x 13 upright, 23 mm^2 on the bed): auto_brim gives it none, so it gets a 3 mm outer brim (review INT-6)
PIN_BRIM = {"brim_type": "outer_only", "brim_width": "3"}

# cooling tube Q (knob-cooling design doc): its own walls / fills at 20 mm/s take ~11.5 s per layer, so the slicer
# does not slow the whole layer (uniform cooling slowdown) and the knob beside it keeps its normal speeds
COOLING_SPEEDS = {key: "20" for key in ("outer_wall_speed", "inner_wall_speed", "gap_infill_speed",
                                        "sparse_infill_speed", "internal_solid_infill_speed")}

# production plates 1-3 (spec 4.2 / 5; brims as in concept/v3.1/run_slice.py); plate-0 coupons keep the sets above.
# "brim_ears" is Bambu's "Painted" brim: only the ear points stored in the 3MF get a brim (export3mf writes them).
PRODUCTION_SETTINGS = {
    "panel": {**PANEL_SETTINGS, "brim_type": "brim_ears"},
    "struct": {**STRUCT_SETTINGS, "brim_type": "outer_only", "brim_width": "5"},
    "small": {**SMALL_SETTINGS, "brim_type": "auto_brim"},
    "pin": {**SMALL_SETTINGS, **PIN_BRIM},
    "cooling": {**SMALL_SETTINGS, "brim_type": "auto_brim", **COOLING_SPEEDS},
}


class SlicerUnavailable(RuntimeError):
    """No usable Bambu Studio CLI (not found, presets missing, does not start, or build_all --no-slicer)."""


@dataclass(frozen=True)
class Slicer:
    cli: Path
    profiles: Path               # profiles/BBL
    version: str | None          # None when it cannot be read


_disabled = None                 # reason set by disable()


def disable(reason: str) -> None:
    """Every later slicer() call raises SlicerUnavailable(reason) (build_all --no-slicer)."""
    global _disabled
    _disabled = reason
    slicer.cache_clear()


def _mac_version(cli: Path) -> str | None:
    try:
        with open(cli.parents[1] / "Info.plist", "rb") as handle:
            return plistlib.load(handle).get("CFBundleShortVersionString")
    except (OSError, plistlib.InvalidFileException, IndexError):
        return None


def _windows_version(cli: Path) -> str | None:
    """File version of the exe (its product version is empty), as 02.08.02.61."""
    import ctypes
    from ctypes import wintypes
    api = ctypes.windll.version
    size = api.GetFileVersionInfoSizeW(str(cli), None)
    buffer = ctypes.create_string_buffer(size)
    pointer, length = ctypes.c_void_p(), wintypes.UINT()
    if not size or not api.GetFileVersionInfoW(str(cli), 0, size, buffer) or not api.VerQueryValueW(
            buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)):
        return None
    info = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint32 * 13)).contents      # VS_FIXEDFILEINFO
    high, low = info[2], info[3]                                                     # dwFileVersionMS / LS
    return f"{high >> 16:02d}.{high & 0xFFFF:02d}.{low >> 16:02d}.{low & 0xFFFF:02d}"


def locate() -> Slicer:
    """The CLI and its profiles (not run yet); SlicerUnavailable when they are not there. A variable that is set
    but points nowhere counts as not found (no further search)."""
    if os.environ.get(ENV_STUDIO):
        candidates = [Path(os.environ[ENV_STUDIO])]
        where = f"{ENV_STUDIO} = {candidates[0]}"
    elif sys.platform == "darwin":
        candidates = [app / "Contents" / "MacOS" / "BambuStudio" for app in MAC_APPS]
        where = " or ".join(str(app) for app in MAC_APPS)
    elif sys.platform == "win32":
        candidates = [Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Bambu Studio" / "bambu-studio.exe"]
        where = str(candidates[0])
    else:
        candidates, where = [], f"no install location on Linux: set {ENV_STUDIO} to squashfs-root/AppRun"
    cli = next((path for path in candidates if path.is_file()), None)
    if cli is None:
        raise SlicerUnavailable(f"Bambu Studio not found ({where})")
    if os.environ.get(ENV_PROFILES):
        profiles = Path(os.environ[ENV_PROFILES])
    else:       # Windows / AppImage: <dir>/resources/profiles/BBL; macOS: Contents/Resources/profiles/BBL
        options = [cli.parent / "resources" / "profiles" / "BBL", cli.parent.parent / "Resources" / "profiles" / "BBL"]
        profiles = next((path for path in options if path.is_dir()), options[0])
    if not profiles.is_dir():
        raise SlicerUnavailable(f"the Bambu Studio profiles folder {profiles} was not found (set {ENV_PROFILES})")
    for category, name in (("machine", MACHINE_PRESET), ("process", PROCESS_PRESET), ("filament", FILAMENT_PRESET)):
        if not (profiles / category / f"{name}.json").is_file():
            raise SlicerUnavailable(f"Bambu Studio preset {category}/{name}.json not found in {profiles}: these "
                                    f"presets are those of Bambu Studio {APP_VERSION}")
    readers = {"darwin": _mac_version, "win32": _windows_version}
    return Slicer(cli, profiles, readers[sys.platform](cli) if sys.platform in readers else None)


def _cli_environment(temp: Path) -> dict:
    return dict(os.environ, TMPDIR=str(temp), TEMP=str(temp), TMP=str(temp))     # TEMP / TMP on Windows


def trial_run(found: Slicer, temp: Path | None = None) -> Slicer:
    """Start the CLI once (`--help`, in the scratch folder temp, default out/.bambu_tmp: it writes result.json into
    the working folder). One that cannot start (Linux without the GUI libraries: exit 127) is unusable. The version
    comes from the help text when the platform gave none."""
    temp = temp or OUT_DIR / ".bambu_tmp"
    shutil.rmtree(temp, ignore_errors=True)
    temp.mkdir(parents=True)
    try:
        completed = subprocess.run([str(found.cli), "--help"], cwd=temp, env=_cli_environment(temp),
                                   capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SlicerUnavailable(f"Bambu Studio at {found.cli} does not start ({type(error).__name__}: {error})") from None
    finally:
        shutil.rmtree(temp, ignore_errors=True)
    output = (completed.stdout + completed.stderr).decode("utf-8", "replace")
    if completed.returncode != 0:
        missing = re.findall(r"error while loading shared libraries: ([^:\s]+)", output)
        reason = f"missing system library {missing[0]}" if missing else f"exit code {completed.returncode}"
        raise SlicerUnavailable(f"Bambu Studio at {found.cli} does not start ({reason})")
    if found.version is None:
        match = re.search(r"BambuStudio-(\d+(?:\.\d+){3})", output)
        found = Slicer(found.cli, found.profiles, match.group(1) if match else None)
    return found


@lru_cache(maxsize=1)
def slicer() -> Slicer:
    """The CLI every call below uses, found and tried once per process; SlicerUnavailable with the reason."""
    if _disabled:
        raise SlicerUnavailable(_disabled)
    return trial_run(locate())


@dataclass
class Presets:
    machine: dict
    process: dict
    filaments: list[dict]      # one per AMS slot, slot order


@dataclass
class PresetFiles:
    machine: Path
    process: Path
    filaments: list[Path]


def _load_preset(category: str, name: str) -> dict:
    with open(slicer().profiles / category / f"{name}.json", encoding="utf-8") as handle:
        return json.load(handle)


def flatten_preset(category: str, name: str) -> dict:
    """Resolve the 'inherits' chain and the 'include' templates of a Bambu system preset."""
    own = _load_preset(category, name)
    merged: dict = {}
    parent = own.get("inherits", "")
    if parent:
        merged.update(flatten_preset(category, parent))
    for template_name in own.get("include", []):
        template = _load_preset(category, template_name)
        merged.update({key: value for key, value in template.items() if key not in INCLUDE_SKIP})
    merged.update({key: value for key, value in own.items() if key not in ("inherits", "include")})
    return merged


def plate_presets(process_overrides: dict | None = None) -> Presets:
    """Flattened P1S / 0.20 Standard / Bambu ABS presets with the project overrides."""
    machine = flatten_preset("machine", MACHINE_PRESET)
    process = flatten_preset("process", PROCESS_PRESET)
    process.update({
        "wipe_tower_x": [f"{WIPE_TOWER_XY[0]:g}"],
        "wipe_tower_y": [f"{WIPE_TOWER_XY[1]:g}"],
        "enable_prime_tower": "1",
        "flush_volumes_matrix": list(FLUSH_VOLUMES),
        "flush_multiplier": ["1"],
    })
    process.update(process_overrides or {})
    base_filament = flatten_preset("filament", FILAMENT_PRESET)
    filaments = []
    for _, (_, colour) in sorted(AMS_SLOTS.items()):
        filament = dict(base_filament)
        filament["filament_colour"] = [colour]
        filament["filament_shrink"] = [FILAMENT_SHRINK]
        filaments.append(filament)
    return Presets(machine, process, filaments)


def write_presets(presets: Presets, directory: Path) -> PresetFiles:
    directory.mkdir(parents=True, exist_ok=True)

    def dump(name: str, data: dict) -> Path:
        path = directory / name
        path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        return path
    return PresetFiles(machine=dump("machine.json", presets.machine), process=dump("process.json", presets.process),
                       filaments=[dump(f"filament_{i + 1}.json", f) for i, f in enumerate(presets.filaments)])


def _preset_arguments(files: PresetFiles) -> list[str]:
    return ["--load-settings", f"{files.machine};{files.process}",
            "--load-filaments", ";".join(str(path) for path in files.filaments)]


def _run_cli(arguments: list[str], log_path: Path, timeout: int) -> int:
    """Run the CLI with its temp directory in out/.bambu_tmp (v3.4 7 item 7: it leaves a backup folder in the temp
    directory on every call, with the 3MF path in it), removed afterwards and before use (a killed run's leftovers)."""
    cli = slicer().cli
    temp = OUT_DIR / ".bambu_tmp"
    shutil.rmtree(temp, ignore_errors=True)
    temp.mkdir(parents=True)
    try:
        with open(log_path, "wb") as log:            # the CLI's own bytes (Windows: empty, see result.json)
            completed = subprocess.run([str(cli), "--debug", "2"] + arguments, stdout=log, stderr=subprocess.STDOUT,
                                       timeout=timeout, env=_cli_environment(temp))
    finally:
        shutil.rmtree(temp, ignore_errors=True)
    return completed.returncode


def _result_error(directory: Path) -> str:
    """'; <error_string>' from the CLI's result.json in its --outputdir (the only diagnosis on Windows)."""
    try:
        error = json.loads((directory / "result.json").read_text(encoding="utf-8")).get("error_string", "")
    except (OSError, ValueError):
        return ""
    return f"; {error}" if error else ""


def export_project_settings(files: PresetFiles, directory: Path, timeout: int = 300) -> dict:
    """Let the CLI merge machine + process + filaments into the full project config (for the 3MF)."""
    directory.mkdir(parents=True, exist_ok=True)
    out_path = directory / "project_settings.json"
    code = _run_cli(_preset_arguments(files) + ["--curr-bed-type", BED_TYPE, "--export-settings", str(out_path),
                                               "--outputdir", str(directory)],
                    directory / "export_settings_log.txt", timeout)
    if code != 0 or not out_path.exists():
        raise RuntimeError(f"Bambu CLI --export-settings failed (code {code}{_result_error(directory)}), see "
                           f"{directory / 'export_settings_log.txt'}")
    return json.loads(out_path.read_text(encoding="utf-8"))


def count_tool_changes(gcode_path: Path) -> int:
    """Filament changes in a Bambu G-code file: AMS switch blocks after the first load."""
    loads = 0
    with open(gcode_path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if re.match(r"M620 S\d+A", line):
                loads += 1
    return max(loads - 1, 0)


def slice_project(project_path: Path, out_dir: Path, files: PresetFiles | None = None, timeout: int = 1800) -> dict:
    """Slice all plates of a 3MF with the CLI and return a summary per plate.

    Without preset files the CLI uses the project settings embedded in the 3MF (what the GUI will see)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in list(out_dir.glob("plate_*.gcode")) + [out_dir / "result.json"]:
        stale.unlink(missing_ok=True)
    arguments = (_preset_arguments(files) if files else []) + [
        "--curr-bed-type", BED_TYPE, "--slice", "0", "--outputdir", str(out_dir), str(project_path)]
    started = time.time()
    code = _run_cli(arguments, out_dir / "slice_log.txt", timeout)
    result_path = out_dir / "result.json"
    if not result_path.exists():
        raise RuntimeError(f"Bambu CLI slicing failed (code {code}), see {out_dir / 'slice_log.txt'}")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    summary = {"return_code": result.get("return_code", code), "error_string": result.get("error_string", ""),
               "cli_seconds": round(time.time() - started, 1), "plates": []}
    for plate in result.get("sliced_plates", []):
        gcode = out_dir / f"plate_{plate['id']}.gcode"
        summary["plates"].append({
            "plate": plate["id"],
            "minutes": round(plate["total_predication"] / 60, 1),
            "grams": {AMS_SLOTS[f["id"]][0]: round(f["total_used_g"], 2) for f in plate["filaments"]},
            "grams_total": round(sum(f["total_used_g"] for f in plate["filaments"]), 2),
            "filament_changes": plate.get("filament_change_times", 0),
            "tool_changes_in_gcode": count_tool_changes(gcode) if gcode.exists() else None,
            "objects": [obj["name"] for obj in plate.get("objects", [])],
            "warning": plate.get("warning_message", ""),
        })
    if summary["return_code"] != 0:
        raise RuntimeError(f"Bambu CLI slicing error: {summary['error_string']} (see {out_dir / 'slice_log.txt'})")
    return summary


# ------------------------------------------------------------------ production plates (export3mf.write_production_plates)
def production_settings(process: str, layer_height: float) -> dict[str, str]:
    """Per-object settings of a production part; the layer height is pinned so the inlays stay whole layers."""
    settings = dict(PRODUCTION_SETTINGS[process])
    settings["layer_height"] = f"{layer_height:g}"
    return settings


def roundtrip_3mf(project_path: Path, out_path: Path, timeout: int = 600) -> Path:
    """Load a project in the CLI and save it again without slicing: the copy shows what Bambu Studio read.

    The CLI joins --outputdir and the --export-3mf name, and fails unless the directory is absolute."""
    out_dir = out_path.parent.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / out_path.name
    out_path.unlink(missing_ok=True)
    log_path = out_dir / f"{out_path.stem}_log.txt"
    code = _run_cli(["--curr-bed-type", BED_TYPE, "--export-3mf", out_path.name, "--outputdir", str(out_dir),
                     str(Path(project_path).resolve())], log_path, timeout)
    if code != 0 or not out_path.exists():
        raise RuntimeError(f"Bambu CLI --export-3mf failed (code {code}{_result_error(out_dir)}), see {log_path}")
    return out_path


def sliced_plate_details(out_dir: Path, plate_id: int = 1) -> dict:
    """Object boxes (bed mm, before shrink compensation) and model-only grams per colour from result.json."""
    result = json.loads((out_dir / "result.json").read_text(encoding="utf-8"))
    plate = {p["id"]: p for p in result["sliced_plates"]}[plate_id]
    boxes = {}
    for obj in plate.get("objects", []):
        box = obj["bbox"]
        boxes[obj["name"]] = (box["x"], box["y"], box["x"] + box["width"], box["y"] + box["depth"], box["height"])
    model_grams = {AMS_SLOTS[f["id"]][0]: round(f["main_used_g"], 2) for f in plate["filaments"]}
    return {"boxes": boxes, "model_grams": model_grams}


GCODE_WORD = re.compile(r"([XYZIJEF])(-?\d*\.?\d+)")
DWELL_WORD = re.compile(r"([SP])(-?\d*\.?\d+)")
SAMPLE_STEP = 1.0             # mm between sampled points along extrusion moves


def _line_points(start, end):
    """Points along a straight move every <= SAMPLE_STEP, start and end included."""
    steps = max(1, math.ceil(math.dist(start, end) / SAMPLE_STEP))
    return [(start[0] + (end[0] - start[0]) * k / steps, start[1] + (end[1] - start[1]) * k / steps)
            for k in range(steps + 1)]


def _arc_sweep(start, end, i, j, clockwise):
    """Centre, radius, start angle and signed sweep of a G2 (clockwise) / G3 arc; start == end is a full circle."""
    cx, cy = start[0] + i, start[1] + j
    radius = math.hypot(i, j)
    a0 = math.atan2(start[1] - cy, start[0] - cx)
    sweep = math.atan2(end[1] - cy, end[0] - cx) - a0
    if clockwise and sweep >= 0:
        sweep -= 2 * math.pi
    if not clockwise and sweep <= 0:
        sweep += 2 * math.pi
    return cx, cy, radius, a0, sweep


def _arc_points(start, end, i, j, clockwise):
    """Points along a G2 (clockwise) / G3 arc every <= SAMPLE_STEP; start == end is a full circle."""
    cx, cy, radius, a0, sweep = _arc_sweep(start, end, i, j, clockwise)
    steps = max(1, math.ceil(radius * abs(sweep) / SAMPLE_STEP))
    return [(cx + radius * math.cos(a0 + sweep * k / steps), cy + radius * math.sin(a0 + sweep * k / steps))
            for k in range(steps + 1)]


@dataclass
class GcodeScan:
    change_layers: list[int]                     # layer (1-based) of every AMS filament change after the first load
    points: dict[str, list[tuple[int, int, float, float]]]   # feature -> (layer, AMS slot, x, y) along its moves, bed mm
    layers: int
    extruder_offset: tuple[float, float]
    layer_z: dict[int, float]                    # layer -> its print Z ('; Z_HEIGHT')
    layer_seconds: dict[int, float]              # layer -> move time from F (no acceleration) + G4 dwells, machine end
                                                 # G-code excluded


def scan_gcode(gcode_path: Path, features: tuple[str, ...] = ("Brim", "Prime tower")) -> GcodeScan:
    """One pass over a Bambu G-code file (relative E): filament-change layers, XY paths of some features, and per
    layer its Z and its time as the slicer's cooling slowdown estimates it: XYZ length / F of every move (|E| for
    extruder-only moves) plus G4 dwells; the machine end G-code is not part of the last layer.

    G-code XY = bed XY - extruder_offset (P1S: 0x2), so points are shifted back into the bed / 3MF frame.
    "T<n>" selects AMS slot n + 1 (the first one is indented in the start G-code; T255 / T1000 are not slots).
    Pure E moves (flushing in the purge chute during a change) are not paths and are skipped."""
    layer, feature, slot = 0, "", 0
    position, z, feed = (0.0, 0.0), 0.0, 0.0          # feed in mm/min
    relative = False                                  # G91: X, Y and Z relative
    machine_end = False
    offset = (0.0, 0.0)
    loads: list[int] = []
    points: dict[str, list[tuple[int, int, float, float]]] = {name: [] for name in features}
    layer_z: dict[int, float] = {}
    seconds: dict[int, float] = {}
    with open(gcode_path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith("; CHANGE_LAYER"):
                layer += 1
            elif line.startswith("; Z_HEIGHT:"):
                layer_z[layer] = float(line.split(":")[1])
            elif line.startswith("; MACHINE_END_GCODE_START"):
                machine_end = True
            elif line.startswith("; FEATURE: "):
                feature = line[len("; FEATURE: "):].strip()
            elif line.startswith("; extruder_offset = "):
                offset_x, offset_y = line.split("=")[1].split(",")[0].strip().split("x")
                offset = (float(offset_x), float(offset_y))
            elif re.match(r"M620 S\d+A", line):
                loads.append(layer)
            elif re.fullmatch(r"\s*T\d+\s*", line):
                tool = int(line.strip()[1:])
                if tool + 1 in AMS_SLOTS:
                    slot = tool + 1
            elif line.startswith(("G90", "G91")):
                relative = line.startswith("G91")
            elif line.startswith("G4 ") and not machine_end:
                words = dict(DWELL_WORD.findall(line.split(";")[0]))
                dwell = float(words["S"]) if "S" in words else float(words.get("P", 0.0)) / 1000.0
                seconds[layer] = seconds.get(layer, 0.0) + dwell
            elif line.startswith(("G0 ", "G1 ", "G2 ", "G3 ")):
                words = dict(GCODE_WORD.findall(line.split(";")[0]))
                feed = float(words.get("F", feed))
                if relative:
                    end = (position[0] + float(words.get("X", 0.0)), position[1] + float(words.get("Y", 0.0)))
                    end_z = z + float(words.get("Z", 0.0))
                else:
                    end = (float(words.get("X", position[0])), float(words.get("Y", position[1])))
                    end_z = float(words.get("Z", z))
                arc = line.startswith(("G2 ", "G3 "))
                if feed > 0 and not machine_end:
                    if arc:          # an arc without X / Y is a full circle (Bambu's spiral lift)
                        _, _, radius, _, sweep = _arc_sweep(position, end, float(words.get("I", 0.0)),
                                                            float(words.get("J", 0.0)), line.startswith("G2 "))
                        flat = radius * abs(sweep)
                    else:
                        flat = math.dist(position, end)
                    length = math.hypot(flat, end_z - z) or abs(float(words.get("E", 0.0)))
                    seconds[layer] = seconds.get(layer, 0.0) + length / (feed / 60.0)
                z = end_z
                if "X" not in words and "Y" not in words:
                    continue
                if feature in points and float(words.get("E", 0.0)) > 0:
                    if arc:
                        path = _arc_points(position, end, float(words.get("I", 0.0)), float(words.get("J", 0.0)),
                                           clockwise=line.startswith("G2 "))
                    else:
                        path = _line_points(position, end)
                    points[feature].extend((layer, slot, x + offset[0], y + offset[1]) for x, y in path)
                position = end
    return GcodeScan(change_layers=loads[1:], points=points, layers=layer, extruder_offset=offset, layer_z=layer_z,
                     layer_seconds={n: seconds.get(n, 0.0) for n in layer_z})
