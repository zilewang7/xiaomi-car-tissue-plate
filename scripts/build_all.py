#!/usr/bin/env python3
"""Parking plate v3.4 - one command: build -> verify geometry -> STL / STEP -> checks -> 3MF + slice
-> renders -> out/report.md.

    .venv/bin/python -I -X utf8 -u scripts/build_all.py
        [--config FILE] [--no-v31] [--geometry-only] [--no-slicer]

Hooks are called when their modules provide them: checks.run_all(model), export3mf.write_production_plates(model),
render.render_all(model), report.write(model); each return value is stored in model.results.
Every step starts with a line "[stage i/7] <name>" (the web UI's progress). Exit codes (webui design 4.4):
    0  done
    1  the geometry verification, a hard check (checks.run_all()["ok"]) or a slicing check
       (write_production_plates()["ok"]) failed, or out/report.md was not written
    2  config error (also found while building: a [text] face that cannot be laid out or cut)
    3  done without slicing: no usable Bambu Studio, or --no-slicer (no 3MF; checks, renders, card, report as usual)
    4  unexpected internal error: the full traceback is in <out>/build_error.log
Every hook runs first, so the report lists the failures. "all done" is printed only for a clean build.
Outputs only under out/ (or TISSUEPLATE_OUT_DIR). The phone numbers and texts come from config.toml and are never
printed.
"""
import argparse
import importlib
import os
import sys
import time
import traceback
from pathlib import Path

# before numpy is imported: numpy's and scipy's OpenBLAS each start one thread per core, and check 10's many small
# solves then run 3-27x slower on Windows / Linux (webui design 6.2); macOS uses Accelerate
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))          # python -I ignores the script directory

from tissueplate import bambu, verify_geometry  # noqa: E402
from tissueplate.config import ConfigError, load_config  # noqa: E402
from tissueplate.export_parts import export_parts  # noqa: E402
from tissueplate.model import build_model  # noqa: E402
from tissueplate.params import OUT_DIR, font_is_authors  # noqa: E402

# (module, function, model.results key, stage number)
HOOKS = (("checks", "run_all", "checks", 4), ("export3mf", "write_production_plates", "plates", 5),
         ("render", "render_all", "renders", 6), ("report", "write", "report", 7))
STAGES = {1: "config and model", 2: "geometry verification", 3: "STL / STEP export", 4: "checks 1-10",
          5: "plates and Bambu Studio CLI slicing", 6: "renders and assembly card", 7: "report"}
ERROR_LOG = "build_error.log"


def stage(number):
    print(f"[stage {number}/{len(STAGES)}] {STAGES[number]}", flush=True)


def shown(path):
    """A path for the messages: project-relative when inside the project, with /."""
    path = Path(path).resolve()
    return (path.relative_to(PROJECT_DIR) if path.is_relative_to(PROJECT_DIR) else path).as_posix()


def call_hook(module_name, function_name, model):
    try:
        module = importlib.import_module(f"tissueplate.{module_name}")
    except ModuleNotFoundError as error:
        if error.name != f"tissueplate.{module_name}":
            raise
        print(f"  {module_name}: module not present, skipped")
        return None
    function = getattr(module, function_name, None)
    if function is None:
        print(f"  {module_name}.{function_name}: not provided yet, skipped")
        return None
    if getattr(module, "STUB", False):
        print(f"  {module_name}.{function_name}: stub (no-op)")
    started = time.time()
    result = function(model)
    print(f"  {module_name}.{function_name}: done in {time.time() - started:.0f} s")
    return result


def print_geometry_summary(report):
    validity, poses, clash = report["validity"], report["print_poses"], report["interference"]
    print(f"  valid bodies: {sum(r['valid'] for r in validity['bodies'].values())}/{len(validity['bodies'])}; "
          f"print poses ok: {poses['ok']}")
    print(f"  interference at rest: {clash['pairs_tested']} pairs, max common volume "
          f"{clash['max_common_volume']:.2e} mm^3, offenders {clash['offenders'] or 'none'}")
    for pair, fit in clash.get("press_fits", {}).items():
        print(f"  intended press fit {pair}: {fit['volume']} mm^3 (<= {fit['limit']}), ok {fit['ok']}")
    for name, fit in clash.get("calibrated_fits", {}).items():
        print(f"  calibrated fit {name} ({fit['pair']}): {fit['common_volume']} mm^3 (analytic {fit['expected_volume']}, "
              f"outside the zone {fit['outside_zone_volume']}), ok {fit['ok']}")
    parity = report.get("v31_parity")
    if parity is None:
        print("  v3.1 parity: not run")
    elif parity.get("skipped"):
        print(f"  v3.1 parity: skipped ({parity['skipped']})")
    else:
        deltas = {name: row["volume_diff_pct"] for name, row in parity["parts"].items() if row["intended"]}
        reset = ", ".join(f"{name} {ours:g} -> {theirs:g}" for name, (ours, theirs) in parity["reset_to_v31"].items())
        print(f"  v3.1 parity ok: {parity['ok']}; unexpected differences {parity['unexpected_differences'] or 'none'}; "
              f"intended deltas (volume %): {deltas}")
        if reset:
            print(f"  v3.1 parity compared a second model (not exported) with {reset}")


def build_failures(model):
    """Reasons to fail the build, judged after every hook ran (the report already lists them)."""
    failures = []
    checks = model.results.get("checks")
    if checks is not None and not checks["ok"]:
        failures.append(f"hard checks FAILED ({len(checks['hard_failures'])}): {checks['hard_failures']} "
                        f"- see {shown(checks['report_file'])}")
    plates = model.results.get("plates")
    if plates is not None and plates["sliced"] and not plates["ok"]:
        per_plate = {number: [name for name, ok in entry["checks"].items() if not ok]
                     for number, entry in plates["plates"].items()}
        per_plate = {number: names for number, names in per_plate.items() if names}
        overall = [name for name, ok in plates["checks"].items() if not ok]
        failures.append(f"slicing checks FAILED: per plate {per_plate}, overall {overall} "
                        f"- see {shown(OUT_DIR / 'plates' / 'slice_report.json')}")
    report = model.results.get("report")
    if report is None or not Path(report).exists():
        failures.append(f"{shown(OUT_DIR / 'report.md')} was not written")
    return failures


def build(args):
    started = time.time()
    if args.no_slicer:
        bambu.disable("--no-slicer")
    stage(1)
    try:
        config = load_config(args.config)
    except ConfigError as error:
        print(f"config error: {error}")
        return 2
    for note in config.notes:
        print(f"config note: {note}")
    if not font_is_authors():
        print("font note: fonts/MiSans-Bold.ttf is not the author's MiSans 4.009: layouts may differ slightly")
    print("building model ...")
    try:
        model = build_model(config)
    except ConfigError as error:
        print(f"config error: {error}")
        return 2
    print(f"  {len(model.parts)} printed pieces, {len(model.hardware)} hardware items ({time.time() - started:.0f} s)")
    stage(2)
    print("verifying geometry ...")
    geometry = verify_geometry.run(model, OUT_DIR / "parts", compare_v31=not args.no_v31)
    model.results["geometry"] = geometry
    print_geometry_summary(geometry)
    if not geometry["ok"]:
        print(f"geometry verification FAILED - see {shown(OUT_DIR / 'parts' / 'geometry_report.json')}")
        return 1
    stage(3)
    print(f"exporting STL / STEP to {shown(OUT_DIR / 'parts')} ...")
    export_parts(model, OUT_DIR / "parts")
    if args.geometry_only:
        print(f"all done in {time.time() - started:.0f} s")
        return 0
    for module_name, function_name, key, number in HOOKS:
        stage(number)
        model.results[key] = call_hook(module_name, function_name, model)
    failures = build_failures(model)
    if failures:
        for line in failures:
            print(line)
        print(f"build FAILED after {time.time() - started:.0f} s")
        return 1
    print(f"report: {shown(model.results['report'])}")
    plates = model.results.get("plates")
    if plates is not None and not plates["sliced"]:
        print(f"done WITHOUT SLICING in {time.time() - started:.0f} s ({plates['reason']}): no 3MF; the assembly card "
              "lists the slicer settings to set by hand")
        return 3
    print(f"all done in {time.time() - started:.0f} s")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", help="config file (default: config.toml in the project)")
    parser.add_argument("--no-v31", action="store_true", help="skip the comparison with concept/v3.1")
    parser.add_argument("--geometry-only", action="store_true", help="build, verify and export STL / STEP only")
    parser.add_argument("--no-slicer", action="store_true",
                        help="do not use Bambu Studio: no 3MF and no slicing checks (exit code 3)")
    args = parser.parse_args()
    try:
        return build(args)
    except Exception as error:          # exit 4: type and place only (a message could quote a value), log for the rest
        frames = traceback.extract_tb(error.__traceback__)
        ours = [frame for frame in frames if Path(frame.filename).resolve().is_relative_to(PROJECT_DIR)]
        place = (ours or frames)[-1]
        log = OUT_DIR / ERROR_LOG
        try:
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(traceback.format_exc(), encoding="utf-8")
            where = f"the traceback is in {shown(log)}"
        except OSError as log_error:
            where = f"the traceback could not be written to {shown(log)} ({type(log_error).__name__})"
        print(f"internal error {type(error).__name__} at {Path(place.filename).name}:{place.lineno}; {where}")
        return 4


if __name__ == "__main__":
    sys.exit(main())
