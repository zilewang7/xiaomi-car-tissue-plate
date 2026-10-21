"""run_all(model): every automatic check of spec section 7 on the package model (build_all hook "checks").

Returns (and writes to out/checks/checks_report.json):
    ok             all hard items pass (build_all exits non-zero otherwise)
    hard_failures  ["<section>: <item>", ...]
    warnings       failing warn items (reported, never fail the build)
    sections       {"1_typography": {title, ok, items, numbers}, ... "11_slicing": ...}; 11_slicing has ok = None
                   (not judged here: the slicing step runs after the checks and judges it, see model.results["plates"]
                   and out/report.md)
    mass           masses, CoG, rotating assembly (input of checks 7, 8, 10)
    seconds        per section and total
Item: {name, value, limit, level: hard | warn | info, ok, note}. No phone number is ever written: the
configured numbers only appear as layout statistics.
For the report (v3.3): the coupon-calibrated fits are sections["3_interference_sweep"]["numbers"]["interference"]
["calibrated_fits"] ({fit: {pair, hole_d, shaft_d, radial_overlap, common_volume, expected_volume, rules, ok}}); the
check 10 levels are sections["10_couple_loop"]["numbers"]["levels_90C_E100"] ({level: (boss low edge, boss centre)
lift mm}, only "glue intact, min shear (hard)" is judged).
"""
import json
import time

from ..params import OUT_DIR
from . import clearance, couple_loop, magnets, mass, paths, printability, statics, typography, visibility
from .common import item, rounded, section

REPORT_PATH = OUT_DIR / "checks" / "checks_report.json"


def slicing_status(model):
    """Check 11 belongs to the slicing step (export3mf / bambu), which runs after the checks: not judged here."""
    plates = model.results.get("plates")
    note = ("per-plate CLI slicing (no warnings, one object per multi-colour part, time / grams / filament "
            "changes) is judged by the slicing step after these checks; see model.results['plates'] and report.md")
    items = [item("per-plate slicing sanity", "judged by the slicing step", level="info", note=note)]
    result = section("11 per-plate CLI slicing (judged by the slicing step)", items,
                     dict(plates_known_at_check_time=plates is not None))
    result["ok"] = None
    return result


def run_all(model):
    started = time.time()
    seconds = {}

    def timed(name, function, *args):
        t0 = time.time()
        value = function(*args)
        seconds[name] = round(time.time() - t0, 1)
        return value

    mass_props = timed("mass", mass.mass_properties, model)
    sections = {"1_typography": timed("1_typography", typography.run, model)}
    sections.update(timed("2-4_clearance", clearance.run, model))
    magnet_section, magnet_raw = timed("7_magnets", magnets.run, model, mass_props)
    statics_items, statics_numbers, lp = timed("8_statics", statics.statics, model, mass_props,
                                               magnet_raw["mount"], magnet_raw["detent"])
    refill_items, refill_numbers = timed("5_refill_statics", statics.refill, model, mass_props, magnet_raw["mount"], lp)
    sections["5_paths"] = timed("5_paths", paths.run, model, refill_items, refill_numbers)
    sections["6_visibility"] = timed("6_visibility", visibility.run, model)
    sections["7_magnets"] = magnet_section
    sections["8_statics"] = section("8 3D rigid-body LP at 80 C weakest (gestures, pinch, braking, lift-off)",
                                    statics_items, statics_numbers)
    sections["9_printability"] = timed("9_printability", printability.run, model)
    sections["10_couple_loop"] = timed("10_couple_loop", couple_loop.run, model, mass_props, magnet_raw)
    sections["11_slicing"] = slicing_status(model)
    sections = {key: sections[key] for key in sorted(sections, key=lambda k: int(k.split("_")[0]))}
    hard = [f"{key}: {entry['name']}" for key, sec in sections.items() for entry in sec["items"]
            if entry["level"] == "hard" and not entry["ok"]]
    warn = [f"{key}: {entry['name']} = {entry['value']} (limit {entry['limit']})" for key, sec in sections.items()
            for entry in sec["items"] if entry["level"] == "warn" and not entry["ok"]]
    seconds["total"] = round(time.time() - started, 1)
    result = dict(ok=not hard, hard_failures=hard, warnings=warn, sections=sections, mass=rounded(mass_props),
                  seconds=seconds, report_file=str(REPORT_PATH))
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=1, ensure_ascii=False, default=str)
    print_summary(result)
    return result


def print_summary(result):
    for key, sec in result["sections"].items():
        counted = [e for e in sec["items"] if e["level"] != "info"]
        failed_warn = sum(1 for e in sec["items"] if e["level"] == "warn" and not e["ok"])
        status = "N/A " if sec["ok"] is None else ("PASS" if sec["ok"] else "FAIL")
        print(f"    {status}  {sec['title']}  ({len(counted)} judged items"
              + (f", {failed_warn} warning(s))" if failed_warn else ")"))
    fits = result["sections"]["3_interference_sweep"]["numbers"]["interference"].get("calibrated_fits", {})
    print("    calibrated fits: " + "; ".join(f"{name} hole {fit['hole_d']:g} / shaft {fit['shaft_d']:g}, "
                                              f"{fit['common_volume']:g} mm^3, ok {fit['ok']}" for name, fit in fits.items()))
    levels = result["sections"]["10_couple_loop"]["numbers"]["levels_90C_E100"]
    print("    check 10 lip lift 90 C E 100 (low edge / centre, mm): "
          + "; ".join(f"{name} {low:.3f} / {mid:.3f}" for name, (low, mid) in levels.items()))
    for line in result["hard_failures"]:
        print(f"    HARD FAIL  {line}")
    for line in result["warnings"]:
        print(f"    WARNING    {line}")
    mass_props = result["mass"]
    print(f"    mass {mass_props['total_g']:.1f} g (CAD x fill), rotating {mass_props['rotor_assembly_g']:.1f} g; "
          f"checks {'PASSED' if result['ok'] else 'FAILED'}; report {result['report_file']}")
