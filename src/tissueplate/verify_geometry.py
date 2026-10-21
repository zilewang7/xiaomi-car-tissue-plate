"""Geometry verification after a build (writes out/parts/geometry_report.json).

1. validity: every body is a valid solid (or compound of disjoint valid solids) with positive volume and a
   B-rep volume that agrees with its own tessellation (catches faces OCCT cannot integrate);
2. print poses: every part sits on Z = 0, inlay colours stay inside their first layers, bed contact areas;
3. interference at rest: every pair of installed bodies, magnets, pads, lid and base intersects in 0 mm^3,
   except the intended press fits (PRESS_FITS), whose common volume is reported and must stay small, and the
   coupon-calibrated fits (CALIBRATED_FITS, v3.3 A.1): the plate-0 strip picks are smaller than the CAD shafts, so
   shaft and hole overlap on purpose. A calibrated pair passes when (a) its overlap lies inside the shaft cylinder
   over the hole length (<= ZERO_VOLUME outside), (b) the volume equals the analytic overlap (shaft circle minus
   the 72-gon teardrop as cradle.py cuts it, x the hole length) within 5 %, (c) the hole Ø is a strip grade;
4. v3.1 parity (the three fit constants are copied into the v3.1 reference first, v3.3 A.1; a config that differs
   from the v3.1 defaults only in V31_RESET is compared through a second model built with those reset, nothing
   exported; any other difference skips it): parameters, typography / layout of the example numbers, and volume
   (B-rep and mesh) / bounding box / symmetric difference of every part against concept/v3.1/verify_v3_1.py
   build_parts(), with the intended v3.2 / v3.3 deltas listed. Parts without an intended delta must match within
   1 % and be identical; intended deltas must stay within their own bound (INTENDED). The volume criterion uses
   mesh volumes (v3.1's front bar B-rep volume integral is 0.35 % high).
trimmed_model() is the model for the assembly paths (checks/paths.py): every calibrated shaft trimmed to the
inscribed circle of its hole polygon over the length that slides through the hole, everything else as built.
"""
import contextlib
import dataclasses
import importlib.util
import io
import json
import math
import time

import build123d as bd
import numpy as np

from .model import build_model
from .params import V31_SCRIPT
from .shapes import fuse_all, teardrop_pts, x_cyl
from .text_layout import number_layout

ZERO_VOLUME = 1e-3          # mm^3: contacts give ~0
MESH_VOLUME_PCT = 0.1       # B-rep volume vs its own tessellation
# intended press fits at rest: shape pair -> (reason, largest allowed common volume mm^3)
PRESS_FITS = {
    ("cradle.navy", "spacer.navy"): ("spacer S Ø8.4 pressed into the Ø8.3 stator pocket (review M3)", 5.0),
}
STRIP_H = (5.85, 6.35)          # plate-0 teardrop strip H: the grades a calibrated hole may take
CALIBRATED_VOLUME_TOL = 0.05    # overlap volume vs the analytic value
# coupon-calibrated fits at rest (v3.3 A.1): (hole shape, shaft shape) -> Params names of the shaft Ø, hole Ø, hole
# X range and the shaft X range that slides through the hole when it is put in
CALIBRATED_FITS = {
    ("cradle.navy", "knob.navy"): dict(fit="near journal", shaft_d="pin_d", hole_d="hole_near", hole_x="near_block_x",
                                       slide_x="near_block_x",
                                       reason="running: Ø6.00 knob journal in the near teardrop (strip H: tightest that "
                                              "turns freely)"),
    ("cradle.navy", "far_pin.navy"): dict(fit="far journal", shaft_d="pin_d", hole_d="hole_far", hole_x="far_block_x",
                                          slide_x="far_pin_slide_x",
                                          reason="running: Ø6.00 far pin journal in the far teardrop (v3.4: P turns "
                                                 "with the rotor; the hex passes the hole untrimmed)"),
}
EXAMPLE_NUMBERS = ("13900139000", "13800138000", "11611112222", "14444444444")   # v3.1 examples, never config


def _bbox(shape):
    box = shape.bounding_box(optimal=True)
    return [round(v, 4) for v in (box.min.X, box.min.Y, box.min.Z, box.max.X, box.max.Y, box.max.Z)]


def _boxes_touch(a, b, tol=0.01):
    return all(a[i] <= b[i + 3] + tol and b[i] <= a[i + 3] + tol for i in range(3))


def _common_volume(a, b):
    common = a & b
    return 0.0 if common is None else abs(common.volume)


def _solids_overlap(solids):
    """Largest common volume between two solids of one body (an inlay body must be disjoint solids)."""
    boxes = [_bbox(s) for s in solids]
    worst = 0.0
    for i in range(len(solids)):
        for j in range(i + 1, len(solids)):
            if _boxes_touch(boxes[i], boxes[j]):
                worst = max(worst, _common_volume(solids[i], solids[j]))
    return worst


def mesh_volume(shape):
    """Volume of the tessellated shape: cross-checks OCCT's B-rep volume integral. All-planar shapes mesh
    exactly at any deflection, so they use a coarse one (much faster for the logo panel)."""
    planar = all(face.geom_type == bd.GeomType.PLANE for face in shape.faces())
    points, triangles = shape.tessellate(0.1 if planar else 0.001, 0.05)
    vertices = np.array([(q.X, q.Y, q.Z) for q in points])
    corners = vertices[np.array(triangles)]
    return float(np.einsum("ij,ij->i", corners[:, 0], np.cross(corners[:, 1], corners[:, 2])).sum() / 6.0)


def check_validity(model):
    """Valid solids, positive volume, disjoint solids inside one body, B-rep volume = mesh volume (0.1 %)."""
    rows, ok = {}, True
    for part in model.parts.values():
        for colour, body in part.bodies.items():
            solids = body.solids()
            overlap = _solids_overlap(solids)
            volume, volume_mesh = body.volume, mesh_volume(body)
            mesh_diff_pct = 100 * (volume - volume_mesh) / volume
            valid = (body.is_valid and len(solids) > 0 and all(s.is_valid for s in solids) and volume > 0
                     and overlap <= ZERO_VOLUME and abs(mesh_diff_pct) <= MESH_VOLUME_PCT)
            ok &= valid
            rows[f"{part.name}.{colour}"] = dict(valid=valid, solids=len(solids), volume=round(volume, 3),
                                                 volume_mesh=round(volume_mesh, 3), brep_vs_mesh_pct=round(mesh_diff_pct, 4),
                                                 solids_overlap=round(overlap, 4), bbox=_bbox(body))
    for name, shape in {**model.hardware, **model.reference}.items():
        valid = shape.is_valid and shape.volume > 0
        ok &= valid
        rows[name] = dict(valid=valid, solids=len(shape.solids()), volume=round(shape.volume, 3))
    return dict(ok=bool(ok), bodies=rows)


def _bed_area(shape):
    """Area of the planar faces lying on Z = 0."""
    area = 0.0
    for face in shape.faces():
        box = face.bounding_box()
        if abs(box.max.Z) < 1e-6 and abs(box.min.Z) < 1e-6:
            area += face.area
    return area


def check_print_poses(model):
    p = model.params
    depth = {"white": p.white_depth, "azure": p.azure_depth}
    rows, ok = {}, True
    for part in model.parts.values():
        whole = part.printed()
        box = whole.bounding_box(optimal=True)
        row = dict(plate=part.plate, process=part.process, rotation=part.print_rotation,
                   size=[round(box.size.X, 3), round(box.size.Y, 3), round(box.size.Z, 3)],
                   z_min=round(box.min.Z, 6), bed_area={})
        part_ok = abs(box.min.Z) < 1e-6 and abs(box.center().X) < 1e-6 and abs(box.center().Y) < 1e-6
        for colour in part.colours:
            body = part.printed(colour)
            row["bed_area"][colour] = round(_bed_area(body), 3)
            if colour != "navy" and "navy" in part.bodies:       # inlays: from the bed up, inside the first layers
                body_box = body.bounding_box(optimal=True)
                row[f"{colour}_z"] = [round(body_box.min.Z, 4), round(body_box.max.Z, 4)]
                part_ok &= abs(body_box.min.Z) < 1e-6 and body_box.max.Z <= depth[colour] + 1e-6
        row["ok"] = bool(part_ok)
        ok &= part_ok
        rows[part.name] = row
    return dict(ok=bool(ok), parts=rows)


def fit_zone(p, fit, grow=0.001):
    """Where a calibrated overlap may lie: the shaft cylinder over the hole length."""
    return x_cyl(getattr(p, fit["shaft_d"]) / 2 + grow, *getattr(p, fit["hole_x"]), *p.axis)


def fit_analytic_overlap(p, fit):
    """Shaft circle minus the hole's 72-gon teardrop (as cradle.py cuts it), times the hole length (mm^3)."""
    hole = bd.Polygon(*teardrop_pts(getattr(p, fit["hole_d"]) / 2, 0.0, 0.0, p.tear_top), align=None).faces()[0]
    rest = bd.Circle(getattr(p, fit["shaft_d"]) / 2).faces()[0] - hole
    area = 0.0 if rest is None else sum(face.area for face in rest.faces())
    x0, x1 = getattr(p, fit["hole_x"])
    return area * (x1 - x0)


def polygon_inradius(points):
    """Smallest distance from the origin to the edges of a closed polygon."""
    start = np.asarray(points, float)
    edge = np.roll(start, -1, axis=0) - start
    t = np.clip(-np.einsum("ij,ij->i", start, edge) / np.einsum("ij,ij->i", edge, edge), 0.0, 1.0)
    return float(np.linalg.norm(start + edge * t[:, None], axis=1).min())


def fit_trim_ring(p, fit):
    """Shaft material outside the hole polygon's inscribed circle, over the shaft length that slides through it."""
    x0, x1 = getattr(p, fit["slide_x"])
    inner = polygon_inradius(teardrop_pts(getattr(p, fit["hole_d"]) / 2, 0.0, 0.0, p.tear_top)) - 1e-4
    return x_cyl(getattr(p, fit["shaft_d"]) / 2 + 0.5, x0, x1, *p.axis) - x_cyl(inner, x0 - 0.01, x1 + 0.01, *p.axis)


def trimmed_model(model):
    """Copy of the model for the assembly paths: each calibrated shaft trimmed by fit_trim_ring (the calibrated
    overlap removed); everything else moves as built, so a hex or shaft that cannot pass a hole is still caught."""
    p = model.params
    parts = dict(model.parts)
    for (_, shaft), fit in CALIBRATED_FITS.items():
        name, colour = shaft.split(".")
        bodies = dict(parts[name].bodies)
        bodies[colour] = bodies[colour] - fit_trim_ring(p, fit)
        parts[name] = dataclasses.replace(parts[name], bodies=bodies)
    return dataclasses.replace(model, parts=parts)


def judge_calibrated_fit(p, fit, pair, common):
    """The three rules of a calibrated pair (module docstring)."""
    volume = 0.0 if common is None else abs(common.volume)
    outside = 0.0
    if volume > ZERO_VOLUME:
        rest = common - fit_zone(p, fit)
        outside = 0.0 if rest is None else abs(rest.volume)
    expected = fit_analytic_overlap(p, fit)
    hole_d, shaft_d = getattr(p, fit["hole_d"]), getattr(p, fit["shaft_d"])
    rules = dict(inside_zone=outside <= ZERO_VOLUME,
                 analytic_volume=abs(volume - expected) <= CALIBRATED_VOLUME_TOL * expected + ZERO_VOLUME,
                 strip_grade=STRIP_H[0] - 1e-9 <= hole_d <= STRIP_H[1] + 1e-9)
    return dict(pair=pair, reason=fit["reason"], hole_d=hole_d, shaft_d=round(shaft_d, 4),
                radial_overlap=round(max(shaft_d - hole_d, 0.0) / 2, 4), common_volume=round(volume, 4),
                expected_volume=round(expected, 4), outside_zone_volume=round(outside, 5), rules=rules,
                ok=all(rules.values()))


def check_interference(model):
    p = model.params
    shapes = {}
    for part in model.installed_parts():
        for colour, body in part.bodies.items():
            shapes[f"{part.name}.{colour}"] = body
    shapes.update(model.hardware)
    shapes["lid"], shapes["base"] = model.reference["lid"], model.reference["base"]
    names = list(shapes)
    boxes = {name: _bbox(shapes[name]) for name in names}
    tested, offenders, worst, press_fits, calibrated_fits = 0, {}, 0.0, {}, {}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if not _boxes_touch(boxes[a], boxes[b]):
                continue
            tested += 1
            common = shapes[a] & shapes[b]
            volume = 0.0 if common is None else abs(common.volume)
            fit = PRESS_FITS.get((a, b)) or PRESS_FITS.get((b, a))
            if fit is not None:
                reason, limit = fit
                press_fits[f"{a} & {b}"] = dict(volume=round(volume, 4), limit=limit, reason=reason,
                                                ok=ZERO_VOLUME < volume <= limit)
                continue
            calibrated = CALIBRATED_FITS.get((a, b)) or CALIBRATED_FITS.get((b, a))
            if calibrated is not None:
                calibrated_fits[calibrated["fit"]] = judge_calibrated_fit(p, calibrated, f"{a} & {b}", common)
                continue
            worst = max(worst, volume)
            if volume > ZERO_VOLUME:
                offenders[f"{a} & {b}"] = round(volume, 4)
    missing = [fit["fit"] for fit in CALIBRATED_FITS.values() if fit["fit"] not in calibrated_fits]
    fits_ok = (all(row["ok"] for row in press_fits.values()) and all(row["ok"] for row in calibrated_fits.values())
               and not missing)
    return dict(ok=not offenders and fits_ok, shapes=len(names), pairs_tested=tested, max_common_volume=worst,
                offenders=offenders, press_fits=press_fits, calibrated_fits=calibrated_fits,
                calibrated_fits_not_found=missing)


def load_v31():
    spec = importlib.util.spec_from_file_location("verify_v3_1", V31_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    with contextlib.redirect_stdout(io.StringIO()):
        spec.loader.exec_module(module)
    return module


V31_DEFAULTS = dict(pad_t="PAD_T", mount_stack="MOUNT_STACK", tab_bottom="TAB_BOTTOM", mount_delta="MOUNT_DELTA",
                    knob_stack="KNOB_STACK", boss_h="BOSS_H", top_fillet="LID_TOP_FILLET", condense="DIGIT_COND")
# coupon-calibrated fit constants: copied into the v3.1 reference before it is built (v3.3 A.1)
V31_FIT_CONSTANTS = dict(hole_near="HOLE_NEAR", hole_far="HOLE_FAR", hex_af="HEX_AF")
# v3.1 bakes these into its derived constants at import (Z0, ZA, MOUNT_Z, TAB_ZC ...), so they cannot be aligned like
# the fit constants: Params field -> value of the second model (v3.1's; upper_delta, which v3.1 lacks, the v3.3 one)
V31_RESET = dict(pad_t=0.5, mount_delta=1.75, upper_delta=1.75, tab_bottom=-40.0)

PARAMETER_PAIRS = {   # our derived value -> v3.1 constant
    "r_in": "R_IN", "r_c": "R_C", "r_sweep": "R_SW", "face_flat": "FACE_FLAT", "axis_y": "YA", "axis_z": "ZA",
    "z0": "Z0", "knob_t": "KNOB_T", "knob_x": "KNOB_X", "stator_spacer_t": "STATOR_SPACER_T",
    "detent_gap": "DETENT_GAP", "tab_t": "TAB_T", "tab_y": "TAB_Y", "lip_x": "LIP_X", "lip_y": "LIP_Y",
    "beam_x": "BEAM_X", "beam_y": "BEAM_Y", "beam_z": "BEAM_Z", "tab_zc": "TAB_ZC", "tab_top": "TAB_TOP",
    "mount_z": "MOUNT_Z", "mount_y": "MOUNT_Y", "base_mag_x": "BASE_MAG_X", "base_mag_z": "BASE_MAG_Z",
    "parting_z": "PARTING_Z", "far_pin_x": "FAR_PIN_X",
}
INTENDED = {     # name -> (why it differs from v3.1, largest volume / bbox difference allowed in %)
    "cradle": ("10-18: no dowel holes (v3.1 has three Ø1.9; the front bar is glued to the lip directly)", 1.0),
    "front_bar": ("v3.2: tab bottom true R10 arc instead of a 96-gon; azure line inlay split out of the navy body (sum "
                  "unchanged); v3.3: upper magnet pocket per tab, no lead-in on the tab top edge, one continuous line "
                  "above the upper pockets (option E); 10-18: no dowel holes (v3.1 has three Ø1.9)", 5.0),
    "knob": ("white A / B / ◆ letter inlays split out of the navy body (sum unchanged); v3.3: counterbore 3.0 -> "
             "screw_head_depth (M3 head k + 0.2 + 0.8 hub cap: 3.4 for k 2.4)", 1.0),
    "plug_near": ("v3.3: EN pilot 6.5 -> pilot_depth (6.9 for k 2.4), deepened with the knob counterbore; hex "
                  "socket AF 5.15 -> 5.20 (10-16 knob jam, knob-cooling design doc)", 1.0),
    "rotor": ("v3.3: tube + plugs, the EN pilot and hex socket as in plug_near; v3.4: EF hex socket", 1.0),
    "plug_far": ("v3.4: EF Ø6.1 bore -> regular hex socket AF far_socket_af (no key), floor at the far pin tip", 5.0),
    "far_pin": ("v3.4: Ø6.00 journal + cone + regular hex far_hex_af with a tip chamfer, no extraction hole, tip at "
                "-82.0 (14.0 long)", 10.0),
    "far_pin_x": ("v3.4: far pin to the EF socket floor -82.0", None),
    "caps": ("review m4: knob caps 0.6 -> 0.4 thick; v3.3: two upper tab caps, tab / knob caps Ø8.2 -> 8.25, hub cap "
             "Ø6.38 x 0.6 -> Ø6.40 x 0.8 (plate 0b picks), one Ø1.0 pry notch per cap", 40.0),
    "spacer": ("review M3: stator spacer Ø8.2 -> 8.4, press fit", 6.0),
    "logo": ("v3.3: logo tips 0.6 -> 0.7 round (panel L inlays); v3.1 had no logo, the panels are compared "
             "through the tube (panels_fill_tube)", None),
}


def _same(a, b):
    if isinstance(a, (tuple, list)):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return math.isclose(float(a), float(b), abs_tol=1e-9)


def _compare(mine, theirs):
    """Volume, bounding box (largest corner shift as % of the largest v3.1 box side) and symmetric difference."""
    volume_mine, volume_theirs = mine.volume, theirs.volume
    box_mine, box_theirs = _bbox(mine), _bbox(theirs)
    shift = max(abs(x - y) for x, y in zip(box_mine, box_theirs))
    largest_side = max(box_theirs[i + 3] - box_theirs[i] for i in range(3))
    mesh_mine, mesh_theirs = mesh_volume(mine), mesh_volume(theirs)
    extra = mine - theirs
    missing = theirs - mine
    return dict(volume=round(volume_mine, 3), volume_v31=round(volume_theirs, 3),
                volume_mesh=round(mesh_mine, 3), volume_mesh_v31=round(mesh_theirs, 3),
                volume_diff_pct=round(100 * (mesh_mine - mesh_theirs) / mesh_theirs, 4),
                brep_volume_diff_pct=round(100 * (volume_mine - volume_theirs) / volume_theirs, 4),
                bbox_max_shift=round(shift, 4), bbox_diff_pct=round(100 * shift / largest_side, 4),
                only_in_v32=round(extra.volume if extra is not None else 0.0, 3),
                only_in_v31=round(missing.volume if missing is not None else 0.0, 3))


def check_v31_parity(model):
    p = model.params
    v31 = load_v31()
    for name, constant in V31_FIT_CONSTANTS.items():
        setattr(v31, constant, getattr(p, name))
    differing = [name for name, constant in V31_DEFAULTS.items() if not _same(getattr(p, name), getattr(v31, constant))]
    if set(differing) - set(V31_RESET):
        return dict(ok=None, skipped=f"config differs from the v3.1 defaults in {differing}")
    reset = {name: (getattr(p, name), value) for name, value in V31_RESET.items() if not _same(getattr(p, name), value)}
    if reset:     # compare the same design with v3.1's tape / delta / tab values; the build keeps its own model
        overrides = dict(model.config.overrides, **{name: value for name, (_, value) in reset.items()})
        try:
            model = build_model(dataclasses.replace(model.config, overrides=overrides))
        except ValueError as error:
            return dict(ok=None, skipped=f"the model with {sorted(reset)} reset to v3.1 does not build: {error}")
        p = model.params
    parameters = {}
    for name, constant in PARAMETER_PAIRS.items():
        ours, theirs = getattr(p, name), getattr(v31, constant)
        parameters[name] = dict(ours=ours, v31=theirs, same=_same(ours, theirs))
    with contextlib.redirect_stdout(io.StringIO()):
        typo_v31 = v31.check_typography(v31.FACE_FLAT)
        parts_v31, mags_v31 = v31.build_parts()
    typo = model.typography
    typography = dict(em=(typo.em, typo_v31["em"]), glyph_w=(typo.glyph_w, typo_v31["glyph_w"]),
                      cells_same=_same([c for cell in typo.cells for c in cell],
                                       [c for cell in typo_v31["cells"] for c in cell]))
    layouts = {}
    for text in EXAMPLE_NUMBERS:
        ours, theirs = number_layout(text, typo, p), v31.number_layout(text, typo_v31)
        layouts[text] = dict(mode=(ours["mode"], theirs["mode"]), centres_same=_same(ours["centres"], theirs["centres"]))
    parts = model.parts
    # v3.2 splits the tube into PA / PB / PL with inlays: the three panels (all colours) fill the tube exactly
    # (volumes add up, the interference check shows no overlap); the tube itself must equal v3.1's
    panel_volume = sum(parts[name].volume for name in ("panel_A", "panel_B", "panel_L"))
    tube_volume = model.reference["tube"].volume
    panels_fill_tube = dict(panels=round(panel_volume, 3), tube=round(tube_volume, 3),
                            ok=abs(panel_volume - tube_volume) <= 1e-4 * tube_volume)
    pairs = {
        "tube": (model.reference["tube"], parts_v31["tube"]),
        "cradle": (parts["cradle"].bodies["navy"], parts_v31["cradle"]),
        "front_bar": (parts["front_bar"].bodies["navy"] + parts["front_bar"].bodies["azure"], parts_v31["front_bar"]),
        "knob": (parts["knob"].bodies["navy"] + parts["knob"].bodies["white"], parts_v31["knob"]),
        "plug_near": (parts["plug_near"].bodies["navy"], parts_v31["plug_near"]),
        "plug_far": (parts["plug_far"].bodies["navy"], parts_v31["plug_far"]),
        "far_pin": (parts["far_pin"].bodies["navy"], parts_v31["far_pin"]),
        "spacer": (parts["spacer"].bodies["navy"], parts_v31["spacer"]),
        "caps": (fuse_all([part.bodies["navy"] for part in parts.values() if part.name.startswith("cap_")]), parts_v31["caps"]),
    }
    for name in ("box", "lid", "base", "rotor", "lip", "beam", "far_block", "near_block"):
        pairs[name] = (model.reference[name], parts_v31[name])
    if "pad_front" in model.hardware:
        pairs["pads"] = (model.hardware["pad_front"] + model.hardware["pad_rear"], parts_v31["pads"])
    for key, magnet in mags_v31.items():
        prefix = {"mount-": "mag_tab-_", "mount+": "mag_tab+_", "stator": "mag_stator"}.get(key, f"mag_{key}_")
        ours = [shape for name, shape in model.hardware.items() if name.startswith(prefix)]
        pairs[f"magnet {key}"] = (fuse_all(ours), magnet)
    comparisons = {}
    for name, (ours, theirs) in pairs.items():
        row = _compare(ours, theirs)
        reason, bound = INTENDED.get(name, ("", 1.0))
        row["intended"] = reason
        row["bound_pct"] = bound
        row["match_1pct"] = abs(row["volume_diff_pct"]) <= 1.0 and row["bbox_diff_pct"] <= 1.0
        row["within_bound"] = abs(row["volume_diff_pct"]) <= bound and row["bbox_diff_pct"] <= bound
        row["identical"] = row["only_in_v32"] <= ZERO_VOLUME and row["only_in_v31"] <= ZERO_VOLUME
        comparisons[name] = row
    unexpected = [name for name, row in comparisons.items()
                  if not row["intended"] and not (row["match_1pct"] and row["identical"])]
    parameters_off = [name for name, row in parameters.items() if not row["same"] and name not in INTENDED]
    ok = (not unexpected and not parameters_off and typography["cells_same"] and panels_fill_tube["ok"]
          and all(v["centres_same"] for v in layouts.values()) and all(r["within_bound"] for r in comparisons.values()))
    aligned = {constant: getattr(p, name) for name, constant in V31_FIT_CONSTANTS.items()}
    return dict(ok=bool(ok), aligned_fit_constants=aligned, parameters=parameters, parameters_off=parameters_off,
                typography=typography,
                layouts=layouts, panels_fill_tube=panels_fill_tube, parts=comparisons,
                unexpected_differences=unexpected, reset_to_v31=reset)


def run(model, out_dir, compare_v31=True):
    t0 = time.time()
    report = dict(validity=check_validity(model), print_poses=check_print_poses(model),
                  interference=check_interference(model))
    if compare_v31 and V31_SCRIPT.exists():
        report["v31_parity"] = check_v31_parity(model)
    report["build_reports"] = model.reports
    report["seconds"] = round(time.time() - t0, 1)
    parity_ok = report.get("v31_parity", {}).get("ok", True) is not False
    report["ok"] = bool(report["validity"]["ok"] and report["print_poses"]["ok"] and report["interference"]["ok"]
                        and parity_ok)
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "geometry_report.json", "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=1, ensure_ascii=False, default=_json_default)
    return report


def _json_default(value):
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, bd.Vector):
        return [value.X, value.Y, value.Z]
    return str(value)
