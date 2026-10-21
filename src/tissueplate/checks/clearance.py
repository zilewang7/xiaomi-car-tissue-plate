"""Checks 2-4: sweep radius, static interference, clearances at rest and over one 120 deg period, envelope
(port of concept/v3.1 sections 1 and 3a-3d onto the package model).

The rotating set (rotor = tube + plugs, knob) is turned about the rotor axis; the angles are a 6 deg grid plus
the exact angles where a chamfer corner points straight down at the lip (the true minimum). Running
clearances exclude the bearing contacts by design: knob boss on the near block face, knob journal in the
near hole, far pin journal in the far hole (v3.4). The coupon-calibrated fits (v3.3 A.1: near journal, far journal)
are judged by the geometry verification and listed here.
"""
import math

import numpy as np

from ..shapes import rotate_about_x_axis, x_cyl
from ..verify_geometry import check_interference
from .common import ZERO_VOLUME, bbox_list, item, section, solid_of

LIP_CLEARANCE_MIN = 1.0       # spec 7-2
RUNNING_GAP_MIN = 0.2         # smallest designed running gap (near axial gap, spec 4.4)
Y_MIN = -32.0                 # spec 7-4 (room in front of the box in the author's YU7)
LENGTH_MAX = 200.0            # spec 7-4
SWEEP_STEP = 6                # deg (v3.1)
KNOB_STEP = 10                # deg (v3.1)


def corner_angles(model):
    """Rotor angles in [0, 120) where a tube corner vertex points straight down (-Z)."""
    p = model.params
    ay, az = p.axis
    angles = set()
    for vertex in model.reference["tube"].vertices():
        radius = math.hypot(vertex.Y - ay, vertex.Z - az)
        if abs(radius - p.r_sweep) < 1e-6:
            phi = math.degrees(math.atan2(vertex.Z - az, vertex.Y - ay))
            angles.add(round((270.0 - phi) % 120.0, 6))
    return sorted(angles)


def sweep_radius(model):
    """Section 2: true sweep radius (chamfer corner) measured on the tube vertices vs the analytic value."""
    p = model.params
    ay, az = p.axis
    measured = max(math.hypot(v.Y - ay, v.Z - az) for v in model.reference["tube"].vertices())
    lip_top = p.z0 + p.lip_t
    analytic_clearance = p.axis_z - p.r_sweep - lip_top
    return dict(r_sweep=p.r_sweep, r_sweep_measured=measured, sharp_r=p.r_c, axis=(ay, az),
                sweep_circle_y=(ay - p.r_sweep, ay + p.r_sweep), sweep_circle_z=(az - p.r_sweep, az + p.r_sweep),
                lip_top_z=lip_top, clearance_to_lip_top=analytic_clearance)


def rest_clearances(model):
    p, ref = model.params, model.reference
    front_bar, knob, cradle = solid_of(model.parts["front_bar"]), solid_of(model.parts["knob"]), solid_of(model.parts["cradle"])
    near_block_face = ref["near_block"] - x_cyl(p.hole_near / 2, 80, 100, *p.axis)
    return {
        "rotor-lip (radial)": ref["tube"].distance_to(ref["lip"]),
        "rotor-near block (axial)": ref["rotor"].distance_to(near_block_face),
        "rotor-far block (axial)": ref["rotor"].distance_to(ref["far_block"]),
        "rotor-cradle (min, incl. inner thrust ring)": ref["rotor"].distance_to(cradle),
        "rotor-front bar": ref["rotor"].distance_to(front_bar),
        "rotor-box": ref["rotor"].distance_to(ref["box"]),
        "knob body-near block (axial, boss gap)": ref["knob_body"].distance_to(ref["near_block"]),
        "knob-box": knob.distance_to(ref["box"]),
        "knob-front bar": knob.distance_to(front_bar),
        "beam-lid (relief)": ref["beam"].distance_to(ref["lid"]),
        "tabs-base (contact)": front_bar.distance_to(ref["base"]),
    }


def sweeps(model):
    """Minimum distances over one 120 deg period: {name: (min, angle at min)}."""
    p, ref = model.params, model.reference
    ay, az = p.axis
    front_bar, knob, cradle = solid_of(model.parts["front_bar"]), solid_of(model.parts["knob"]), solid_of(model.parts["cradle"])
    rotor_angles = sorted(set(range(0, 120, SWEEP_STEP)) | set(corner_angles(model)))
    pairs = {
        "rotor-lip": (ref["rotor"], ref["lip"], rotor_angles),
        "rotor-cradle (running gap, incl. thrust ring)": (ref["rotor"], cradle, rotor_angles),
        "rotor-front bar": (ref["rotor"], front_bar, rotor_angles),
        "rotor-far block": (ref["rotor"], ref["far_block"], rotor_angles),
        "knob-box": (knob, ref["box"], range(0, 120, KNOB_STEP)),
        "knob-front bar": (knob, front_bar, range(0, 120, KNOB_STEP)),
        "knob body-near block": (ref["knob_body"], ref["near_block"], range(0, 120, KNOB_STEP)),
    }
    result = {}
    for name, (moving, fixed, angles) in pairs.items():
        distances = [(rotate_about_x_axis(moving, angle, ay, az).distance_to(fixed), angle) for angle in angles]
        result[name] = min(distances)
    return result, rotor_angles


def interference(model):
    """Reuse the geometry verification of build_all when present (same pairs), else run it."""
    geometry = model.results.get("geometry")
    if geometry and "interference" in geometry:
        return geometry["interference"], "verify_geometry (build_all)"
    return check_interference(model), "verify_geometry.check_interference"


def envelope(model):
    p = model.params
    boxes = []
    for part in model.installed_parts():
        boxes += [bbox_list(body) for body in part.bodies.values()]
    boxes += [bbox_list(shape) for shape in model.hardware.values()]
    boxes = np.array(boxes)
    ay, az = p.axis
    knob_tip = p.knob_mag_r + p.knob_lobe_r
    x_min, x_max = boxes[:, 0].min(), boxes[:, 3].max()
    y_min = min(boxes[:, 1].min(), ay - p.r_sweep, ay - knob_tip)
    y_max = max(boxes[:, 4].max(), ay + p.r_sweep, ay + knob_tip)
    z_static = boxes[:, 5].max()
    return dict(x=(x_min, x_max), length=x_max - x_min, y_min=y_min, y_max=y_max, z_min=boxes[:, 2].min(),
                z_max_static=z_static, z_max_swept=max(z_static, az + p.r_sweep, az + knob_tip),
                margin_to_rule=y_min - p.rule_y, gap_to_tongue=y_min - p.tongue_y)


def run(model):
    p = model.params
    radius = sweep_radius(model)
    clash, clash_source = interference(model)
    rest = rest_clearances(model)
    swept, rotor_angles = sweeps(model)
    env = envelope(model)
    lip_sweep = swept["rotor-lip"][0]
    sweep_items = [
        item("true sweep radius measured on the tube corners (mm)", radius["r_sweep_measured"],
             abs(radius["r_sweep_measured"] - p.r_sweep) < 1e-6, f"= chamfer-corner radius {p.r_sweep:.3f}"),
        item("sweep circle -> lip top, analytic (mm)", radius["clearance_to_lip_top"],
             radius["clearance_to_lip_top"] >= LIP_CLEARANCE_MIN, f">= {LIP_CLEARANCE_MIN}"),
        item("rotor -> lip over 0-120 deg, CAD incl. corner-down angles (mm)", lip_sweep,
             lip_sweep >= LIP_CLEARANCE_MIN, f">= {LIP_CLEARANCE_MIN}"),
    ]
    clash_items = [
        item("static interference, max common volume (mm^3)", clash["max_common_volume"],
             clash["ok"] and clash["max_common_volume"] <= ZERO_VOLUME, f"<= {ZERO_VOLUME}",
             note=f"{clash['pairs_tested']} touching pairs of {clash['shapes']} shapes; source {clash_source}"),
    ]
    for name, (distance, angle) in swept.items():
        if name == "rotor-lip":
            continue
        clash_items.append(item(f"sweep {name}, min over 0-120 deg (mm)", distance, distance >= RUNNING_GAP_MIN - 1e-6,
                                f">= {RUNNING_GAP_MIN} running gap", note=f"at {angle:g} deg"))
    clash_items.append(item("clearances at rest (mm)", rest, level="info",
                            note="bearing contacts by design: boss on the near block, journal in the near hole, "
                                 "far pin journal in the far hole"))
    fits = {name: dict(hole_d=fit["hole_d"], shaft_d=fit["shaft_d"], radial_overlap=fit["radial_overlap"],
                       common_volume=fit["common_volume"], analytic_volume=fit["expected_volume"], ok=fit["ok"])
            for name, fit in clash.get("calibrated_fits", {}).items()}
    clash_items.append(item("coupon-calibrated fits at rest: plate-0 strip picks below the Ø6 shafts (mm, mm^3)", fits,
                            level="info", note=f"hex AF {p.hex_af:g} / far hex AF {p.far_hex_af:g} in the AF "
                                               f"{p.hex_socket_af:g} (EN) / {p.far_socket_af:g} (EF) sockets: "
                                               "clearance in CAD; judged in the geometry "
                                               "verification (overlap only on the shaft over the hole length, = "
                                               "analytic +-5 %, strip grade)"))
    env_items = [
        item("overall length X (mm)", env["length"], env["length"] <= LENGTH_MAX + 1e-6, f"<= {LENGTH_MAX}"),
        item("frontmost point Y incl. swept circles (mm)", env["y_min"], env["y_min"] >= Y_MIN, f">= {Y_MIN}"),
        item("frontmost point vs the Y -35 rule / tongue nose (mm)", (env["margin_to_rule"], env["gap_to_tongue"]),
             level="info"),
        item("height above the lid static / swept, lowest point (mm)", (env["z_max_static"], env["z_max_swept"], env["z_min"]),
             level="info"),
    ]
    sections = {
        "2_sweep_radius": section("2 sweep radius at the chamfer corners, clearance to the lip", sweep_items,
                                  dict(radius, lip_sweep_min=swept["rotor-lip"], rotor_angles=rotor_angles)),
        "3_interference_sweep": section("3 static interference 0, running clearances over 0-120 deg", clash_items,
                                        dict(interference=clash, rest=rest,
                                             sweep={k: dict(min=v[0], angle=v[1]) for k, v in swept.items()})),
        "4_envelope": section("4 envelope Y >= -32, length <= 200", env_items, env),
    }
    return sections
