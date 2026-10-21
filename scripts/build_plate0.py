"""Plate 0 (test coupons, design doc v3.2 section 3.2): build -> arrange -> Bambu 3MF -> CLI slice -> test card.

Run from the project directory:
    .venv/bin/python -I scripts/build_plate0.py
Outputs (out/plate0/): plate0_coupons.3mf, slice/ (G-code, result.json), slice_summary.json, presets/,
<YYYY-MMDD-HHMM>-盘0试验卡.md. No phone numbers are used on this plate.
Exit code 1 when a slicing check fails (one object per coupon, no warning, G-code changes = result.json,
first-layer brim on the coupons that set one).
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from string import Template

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))

from tissueplate import bambu, coupons, export3mf  # noqa: E402
from tissueplate.params import OUT_DIR as BUILD_OUT_DIR, make_params  # noqa: E402

OUT_DIR = BUILD_OUT_DIR / "plate0"           # follows TISSUEPLATE_OUT_DIR
PROJECT_PATH = OUT_DIR / "plate0_coupons.3mf"
CARD_TEMPLATE = PROJECT_DIR / "scripts" / "templates" / "plate0_card.md"
CARD_SUFFIX = "-盘0试验卡.md"

# bed layout (mm): margins, gap between objects, P1S front-left exclusion, wipe tower keep-out
BED_W, BED_D = export3mf.BED_SIZE
MARGIN, GAP = 6.0, 7.0
FRONT_LEFT_EXCLUDE = (18.0, 28.0)
TOWER_KEEP_OUT = (bambu.WIPE_TOWER_XY[0] - 8.0, bambu.WIPE_TOWER_XY[1] - 8.0)   # x >= / y >= this is reserved


def brim_width(coupon):
    """Outer brim width (mm) set on the coupon, 0 without one."""
    if coupon.settings.get("brim_type") != "outer_only":
        return 0.0
    return float(coupon.settings.get("brim_width", "0"))


def footprint(coupon):
    """(width, depth) of the coupon on the bed, its outer brim included."""
    boxes = [solid.bounding_box() for _, solid, _ in coupon.parts]
    brim = 2 * brim_width(coupon)
    return (max(b.max.X for b in boxes) - min(b.min.X for b in boxes) + brim,
            max(b.max.Y for b in boxes) - min(b.min.Y for b in boxes) + brim)


def row_x_limits(y0, depth):
    x_start = FRONT_LEFT_EXCLUDE[0] + GAP if y0 < FRONT_LEFT_EXCLUDE[1] + GAP else MARGIN
    x_end = TOWER_KEEP_OUT[0] if y0 + depth > TOWER_KEEP_OUT[1] else BED_W - MARGIN
    return x_start, x_end


def arrange(coupon_list):
    """Shelf packing, deepest coupons first, front to back. Returns {name: (x, y)} of footprint centres."""
    items = sorted(coupon_list, key=lambda c: (-footprint(c)[1], -footprint(c)[0]))
    positions = {}
    y0, row_depth, x = MARGIN, None, None
    for coupon in items:
        width, depth = footprint(coupon)
        if row_depth is not None:
            x_start, x_end = row_x_limits(y0, row_depth)
            if x + width > x_end:
                y0, row_depth = y0 + row_depth + GAP, None
        if row_depth is None:
            row_depth = depth
            x, _ = row_x_limits(y0, row_depth)
        x_start, x_end = row_x_limits(y0, row_depth)
        if x + width > x_end or y0 + depth > BED_D - MARGIN:
            raise RuntimeError(f"plate 0 layout does not fit at {coupon.name}")
        positions[coupon.name] = (x + width / 2, y0 + depth / 2)
        x += width + GAP
    return positions


def brim_points_per_coupon(coupon_list, positions, gcode_path):
    """First-layer brim points inside the footprint of every coupon that has an outer brim set (review INT-6)."""
    scan = bambu.scan_gcode(gcode_path, ("Brim",))
    points = [(x, y) for layer, _, x, y in scan.points["Brim"] if layer == 1]
    counts = {}
    for coupon in coupon_list:
        if brim_width(coupon) <= 0:
            continue
        (cx, cy), (width, depth) = positions[coupon.name], footprint(coupon)
        counts[coupon.name] = sum(1 for x, y in points if abs(x - cx) <= width / 2 and abs(y - cy) <= depth / 2)
    return counts


def plate_objects(coupon_list, positions):
    objects = []
    for coupon in coupon_list:
        parts = [export3mf.Part(name, export3mf.mesh_from_shape(solid), slot) for name, solid, slot in coupon.parts]
        objects.append(export3mf.PlateObject(coupon.name, parts, positions[coupon.name], coupon.settings))
    return objects


def size_text(diameter, thickness):
    return f"Ø{diameter:g}×{round(thickness, 2):g}"


def write_card(summary, coupon_list):
    plate = summary["plates"][0]
    minutes = plate["minutes"]
    p = make_params()           # spacer and knob gap; the caps and the dowel hole as plate 0 was printed (coupons)
    holes = coupons.DOWEL_HOLE_DIAMETERS
    values = {
        "tab_cap": size_text(*coupons.PLATE0_CAPS["cap_tab"]),
        "knob_cap": size_text(*coupons.PLATE0_CAPS["cap_knob"]),
        "hub_cap": size_text(*coupons.PLATE0_CAPS["cap_hub"]),
        "spacer": size_text(p.spacer_d, p.stator_spacer_t),
        "knob_gap": f"{p.knob_pocket_allowance:g}",
        "pin_brim": bambu.PIN_BRIM["brim_width"],
        "dowel_range": f"Ø{holes[0]:.2f}…{holes[-1]:.2f}",
        "dowel_labels": f"{holes[0] * 100:.0f}…{holes[-1] * 100:.0f}",
        "dowel_now": f"{coupons.PLATE0_DOWEL_D:g}",
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "time_text": f"{int(minutes // 60)} h {minutes % 60:.0f} min（{minutes:.0f} min）",
        "grams_navy": f"{plate['grams'].get('navy', 0.0):.1f}",
        "grams_white": f"{plate['grams'].get('white', 0.0):.1f}",
        "grams_total": f"{plate['grams_total']:.1f}",
        "changes": str(plate["filament_changes"]),
        "warning": plate["warning"] or "无",
        "object_count": str(len(plate["objects"])),
        "coupon_count": str(len(coupon_list)),
    }
    for old in OUT_DIR.glob(f"*{CARD_SUFFIX}"):
        old.unlink()
    card_path = OUT_DIR / f"{datetime.now().strftime('%Y-%m%d-%H%M')}{CARD_SUFFIX}"
    card_path.write_text(Template(CARD_TEMPLATE.read_text(encoding="utf-8")).substitute(values), encoding="utf-8")
    return card_path


def main():
    started = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    coupon_list, _ = coupons.build_plate0_coupons()
    print(f"built {len(coupon_list)} coupons in {time.time() - started:.0f} s")

    positions = arrange(coupon_list)
    objects = plate_objects(coupon_list, positions)
    presets = bambu.plate_presets()
    preset_files = bambu.write_presets(presets, OUT_DIR / "presets")
    project_settings = bambu.export_project_settings(preset_files, OUT_DIR / "presets")
    export3mf.write_bambu_3mf(PROJECT_PATH, [export3mf.Plate("plate0_coupons", objects)], project_settings,
                              title="Parking plate: plate 0 test coupons")
    print(f"wrote {PROJECT_PATH}")

    summary = bambu.slice_project(PROJECT_PATH, OUT_DIR / "slice")       # embedded project settings only
    plate = summary["plates"][0]
    multi_part = [c.name for c in coupon_list if len(c.parts) > 1]
    brim_counts = brim_points_per_coupon(coupon_list, positions, OUT_DIR / "slice" / "plate_1.gcode")
    summary["brim_points"] = brim_counts
    summary["checks"] = {
        "one_slicer_object_per_coupon": sorted(plate["objects"]) == sorted(c.name for c in coupon_list),
        "multi_colour_objects": multi_part,
        "gcode_tool_changes_match": plate["tool_changes_in_gcode"] == plate["filament_changes"],
        "no_warning": not plate["warning"],
        "brim_on_coupons_that_set_one": all(count > 0 for count in brim_counts.values()),
    }
    summary["positions"] = {name: [round(v, 1) for v in xy] for name, xy in positions.items()}
    (OUT_DIR / "slice_summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
    card_path = write_card(summary, coupon_list)
    print(json.dumps({k: plate[k] for k in ("minutes", "grams", "grams_total", "filament_changes", "warning")},
                     ensure_ascii=False))
    print("checks:", summary["checks"])
    print(f"card: {card_path}")
    failed = [name for name, value in summary["checks"].items() if isinstance(value, bool) and not value]
    if failed:
        print(f"plate 0 checks FAILED: {failed} - see {OUT_DIR / 'slice_summary.json'}")
        return 1
    print(f"done in {time.time() - started:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
