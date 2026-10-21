"""Check 7: magnet model (port of concept/v3.1 sections 5a-5c; v3.3 tab mount after concept/v3.3/tabs4/mount22.py
tab_wrench and review/lid_set.py).

Mount (v3.3 2.1): each tab has two stacks of mount_stack x N52 8 x 3 on their 0.8 floors, the lower one (dotted face
toward the box) mount_delta above the base magnet point, the upper one (undotted face toward the box) upper_delta
above the lid magnet point (plate 0: the base magnets attract the dotted face, the lid magnets the undotted one).
Both box magnets act on both stacks (cross terms included), in world coordinates: box face Y = 0, box magnet axes
along Y behind a wall at the tab's X, our stacks at their CAD positions. Candidate set (both points equal): base
magnet BASES x WALLS; lid magnet = base (same magnet and wall: the design corners) or LIDS x WALLS (Ø5-8: the lid
magnet centre is 4.62 above the seam, so it is at most about Ø9.2), 285 boxes. The forces are sums over the box
magnets, so every box magnet is evaluated once per plate position and a box is a sum. 80 / 90 C = reversible x
irreversible (tab_irrev of the stack). Per tab: pull = +Fy (toward the box), down = -Fz (> 0 pulls the plate onto
the lid). The lid magnet Z is only known to +-LID_BAND (single-magnet measurement): corners and the smallest shear
of the full set are also given there.
Detent: 3 knob lobes x knob_stack + 1 stator, face gap from the CAD magnets; torque sweep, friction
(thrust boss + journals), peak / friction, dead zone, pocket-floor bulge, snap dynamics.
Seating (review M3, v3.3 2.4): the axial force that presses each detent magnet onto its printed floor / wall over a
full 0-120 deg step. Where it reverses, the magnet pushes on its retainer instead: the stator on the press-fit
spacer S, a knob lobe stack on its cap (glued all round). The tab stacks are pulled onto their floors at rest; while
the plate slides down the box face (vertical install) the lid magnets push the stacks onto their caps (glued all
round).
Magnet positions come from model.hardware (the CAD solids), not from the parameter formulas.
"""
import math
from dataclasses import replace

import numpy as np

from .common import centre, item, section
from .magnet_model import Disc, calibrate_br, force_torque, interact

# base magnet candidates (spec 4.3: 8x2 N35 .. 15x3 N38, behind a 2-3 mm wall): name, d, t, Br
BASES = (("8x2 N35", 8.0, 2.0, 1.17), ("10x2 N35", 10.0, 2.0, 1.17), ("10x3 N38", 10.0, 3.0, 1.23),
         ("12x3 N38", 12.0, 3.0, 1.23), ("15x3 N38", 15.0, 3.0, 1.23))
WALLS = (2.0, 2.5, 3.0)
TYPICAL, WEAKEST, STRONGEST = (BASES[1], 2.5), (BASES[0], 3.0), (BASES[4], 2.0)
CORNERS = {"weakest": WEAKEST, "typical": TYPICAL, "strongest": STRONGEST}    # lid magnet = base magnet
# lid magnet candidates besides "= base" (v3.3 2.1, review/lid_set.py): name, d, t, Br
LIDS = (("8x3 N52", 8.0, 3.0, 1.43), ("8x2 N35", 8.0, 2.0, 1.17), ("8x1.5 N35", 8.0, 1.5, 1.17),
        ("6x3 N35", 6.0, 3.0, 1.17), ("6x2 N35", 6.0, 2.0, 1.17), ("5x2 N35", 5.0, 2.0, 1.17))
LID_BAND = 1.5                  # mm: a single test magnet stops anywhere within about +-1.5 of the lid point
STACKS = {"lower": "mag_tab", "upper": "mag_tabU"}      # CAD prefix; side and index follow ("mag_tabU+_1")
STACK_SENSE = {"lower": -1.0, "upper": 1.0}             # moment (S -> N) along Y: plate-0 polarity
BOX_SENSE = {"base": -1.0, "lid": 1.0}
LIFT_HEIGHTS = (0, 1, 2, 3, 4, 5, 6, 8, 10, 14)
INSTALL_DZ = tuple(float(dz) for dz in np.round(np.arange(0.0, 20.0001, 0.25), 3))   # plate lowered along the face
V32_HOLE_NEAR = 6.30            # v3.2 nominal near hole, for the detent friction-model note
RATIO_MIN = 2.5                 # spec 7-7: peak / friction
FLOOR_E = (2000.0, 300.0, 100.0)
SNAP_MAX_S = 1.5
SEATING_STEP = 2.5              # deg, seating-force sweep over one detent step (0-120)


# ---------------- mount (two stacks per tab on the base and lid magnets) ----------------
def tab_geometry(model):
    """Per stack of the +X tab (the -X tab is its mirror): CAD centres, magnet count, floor (box face -> first magnet
    face) and offset (stack centre above its box magnet point)."""
    p = model.params
    box_points = {"lower": p.base_mag_z, "upper": p.lid_mag_z}
    out = {}
    for name, prefix in STACKS.items():
        shapes = [shape for key, shape in model.hardware.items() if key.startswith(f"{prefix}+_")]
        centres = [centre(shape) for shape in shapes]
        out[name] = dict(centres=centres, magnets=len(shapes), floor=-max(s.bounding_box().max.Y for s in shapes),
                         offset=float(np.mean([c[2] for c in centres])) - box_points[name])
    return out


def stack_discs(p, br52, geometry, dz=0.0):
    """Our discs per stack, the plate raised by dz."""
    return {name: [Disc(c + np.array([0.0, 0.0, dz]), (0, STACK_SENSE[name], 0), p.magnet_d, p.magnet_t, br52)
                   for c in geometry[name]["centres"]] for name in STACKS}


def box_disc(p, magnet, wall, z, kind):
    """Box magnet of kind 'base' / 'lid': axis along Y behind 'wall' (box face Y = 0), at the tab's X and height z."""
    _, d, t, br = magnet
    return Disc((p.base_mag_x, wall + t / 2, z), (0, BOX_SENSE[kind], 0), d, t, br)


def magnet_forces(source, discs):
    """Force (N, 3-vector) of one box magnet on each of our stacks."""
    return {name: sum(interact(source, disc)[0] for disc in stack) for name, stack in discs.items()}


def source_table(p, discs, magnets, z, kind):
    """{(magnet name, wall): per-stack forces} of every magnet behind every wall at one box point."""
    return {(magnet[0], wall): magnet_forces(box_disc(p, magnet, wall, z, kind), discs)
            for magnet in magnets for wall in WALLS}


def box_forces(base_table, lid_table, base_key, lid_key):
    """Per-stack forces of one box: base magnet base_key + lid magnet lid_key."""
    return {name: base_table[base_key][name] + lid_table[lid_key][name] for name in STACKS}


def tab_forces(per_stack, factor=1.0):
    """Per tab: {stack: {pull, down}} plus the whole-tab pull and down (N)."""
    stacks = {name: dict(pull=factor * float(force[1]), down=-factor * float(force[2]))
              for name, force in per_stack.items()}
    return dict(stacks, pull=sum(s["pull"] for s in stacks.values()), down=sum(s["down"] for s in stacks.values()))


def corner_key(which):
    magnet, wall = CORNERS[which]
    return magnet[0], wall


def candidate_rows(base_table, lid_table):
    """The full set at one lid point, BASES x WALLS x (lid = base, LIDS x WALLS) = 285 boxes: 20 C, per tab."""
    rows = []
    for base in BASES:
        for wall in WALLS:
            lids = [("= base", (base[0], wall))] + [(f"{lid[0]} @{lid_wall}", (lid[0], lid_wall))
                                                    for lid in LIDS for lid_wall in WALLS]
            for label, lid_key in lids:
                forces = tab_forces(box_forces(base_table, lid_table, (base[0], wall), lid_key))
                rows.append(dict(case=f"lid {label} | base {base[0]} @{wall}", lid_equals_base=label == "= base",
                                 pull=forces["pull"], down=forces["down"],
                                 **{f"{name}_{key}": forces[name][key] for name in STACKS for key in ("pull", "down")}))
    return rows


def extremes(rows, f80):
    """Candidate-set extremes per tab (20 C; the minima also at 80 C) and how often the upper stack alone / the whole
    tab is pushed up."""
    out = dict(n=len(rows), upper_pushed_up=sum(1 for r in rows if r["upper_down"] < 0),
               tab_pushed_up=sum(1 for r in rows if r["down"] < 0))
    for key in ("pull", "down", "lower_pull", "upper_pull", "upper_down"):
        low = min(rows, key=lambda r: r[key])
        out[f"min_{key}"] = dict(value_20C=low[key], value_80C=f80 * low[key], case=low["case"])
    for key in ("pull", "down"):
        high = max(rows, key=lambda r: r[key])
        out[f"max_{key}"] = dict(value_20C=high[key], case=high["case"])
    return out


def corner_forces(p, br52, geometry, which, dz):
    """Per-stack forces of a design corner (lid magnet = base magnet, same wall), the plate raised by dz."""
    discs = stack_discs(p, br52, geometry, dz)
    magnet, wall = CORNERS[which]
    base = magnet_forces(box_disc(p, magnet, wall, p.base_mag_z, "base"), discs)
    lid = magnet_forces(box_disc(p, magnet, wall, p.lid_mag_z, "lid"), discs)
    return {name: base[name] + lid[name] for name in STACKS}


def lift_table(p, br52, geometry):
    """Whole-tab pull / down of the weakest and the strongest corner with the plate lifted by h (20 C, per tab)."""
    rows = []
    for h in LIFT_HEIGHTS:
        weak = tab_forces(corner_forces(p, br52, geometry, "weakest", h))
        strong = tab_forces(corner_forces(p, br52, geometry, "strongest", h))
        rows.append(dict(h=h, weak_pull=weak["pull"], weak_down=weak["down"], strong_pull=strong["pull"],
                         strong_down=strong["down"]))
    return rows


def lid_lift(p, br52, geometry):
    """Refill with the plate taped to the lid (v3.4): extra hand force to lift the lid with the plate on it. Only the
    base magnets hold the plate back (the lid magnets go up with it): per design corner the largest
    2 x (down + mu_pu[0] x pull) of both tabs over the plate raised INSTALL_DZ above its seat (20 C, N; the plate
    weight comes on top)."""
    rows = {}
    for which, (magnet, wall) in CORNERS.items():
        base = box_disc(p, magnet, wall, p.base_mag_z, "base")
        needs = []
        for dz in INSTALL_DZ:
            forces = tab_forces(magnet_forces(base, stack_discs(p, br52, geometry, dz)))
            needs.append(2 * (forces["down"] + p.mu_pu[0] * max(forces["pull"], 0.0)))
        k = int(np.argmax(needs))
        rows[which] = dict(force_N=needs[k], at_dz=INSTALL_DZ[k])
    return rows


def install_push(p, br52, geometry):
    """Vertical install (plate lowered along the box face, INSTALL_DZ above its seat), strongest corner, 20 C: the
    smallest normal force on each stack (N per tab, < 0 = pushed off its floor onto its cap) and where."""
    rows = [tab_forces(corner_forces(p, br52, geometry, "strongest", dz)) for dz in INSTALL_DZ]
    out = {}
    for name in STACKS:
        pulls = [row[name]["pull"] for row in rows]
        k = int(np.argmin(pulls))
        out[name] = dict(min_pull=pulls[k], at_dz=INSTALL_DZ[k])
    return out


def mount(model, br52):
    """Tab forces per tab (module docstring): design corners, candidate set, lid band, lift table, lid lift, vertical
    install."""
    p = model.params
    geometry = tab_geometry(model)
    at_80, at_90 = p.tab_irreversible(p.mount_stack)
    f80, f90 = p.hot80 * at_80, p.hot90 * at_90
    discs = stack_discs(p, br52, geometry)
    base_table = source_table(p, discs, BASES, p.base_mag_z, "base")
    lid_magnets = tuple({magnet[0]: magnet for magnet in BASES + LIDS}.values())
    band = {}
    for shift in (-LID_BAND, 0.0, LID_BAND):
        lid_table = source_table(p, discs, lid_magnets, p.lid_mag_z + shift, "lid")
        band[shift] = dict(lid_z=p.lid_mag_z + shift, lid_table=lid_table, rows=candidate_rows(base_table, lid_table),
                           corners={which: box_forces(base_table, lid_table, corner_key(which), corner_key(which))
                                    for which in CORNERS})
    design = band[0.0]
    corners = design["corners"]
    typical = corner_key("typical")
    full = extremes(design["rows"], f80)
    weak, typ = tab_forces(corners["weakest"]), tab_forces(corners["typical"])
    split = {name: {source: dict(pull=float(table[typical][name][1]), down=-float(table[typical][name][2]))
                    for source, table in (("base", base_table), ("lid", design["lid_table"]))} for name in STACKS}
    return dict(
        geometry={name: {k: v for k, v in g.items() if k != "centres"} for name, g in geometry.items()},
        lid_z=p.lid_mag_z, factors=dict(f80=f80, f90=f90, irreversible=(at_80, at_90)),
        weakest_20C=weak, typical_20C=typ, strongest_20C=tab_forces(corners["strongest"]),
        weakest_80C=tab_forces(corners["weakest"], f80), weakest_90C=tab_forces(corners["weakest"], f90),
        slide_up_20C=dict(weakest=weak["down"] + p.mu_pu[0] * weak["pull"],
                          typical=typ["down"] + p.mu_pu[0] * typ["pull"]),
        split_typical_20C=split, lid_equals_base=extremes([r for r in design["rows"] if r["lid_equals_base"]], f80), full_set=full,
        check10_shear_80C=full["min_down"]["value_80C"],
        lid_band={f"{shift:+.1f}": dict(shift=shift, lid_z=b["lid_z"], weakest_20C=tab_forces(b["corners"]["weakest"]),
                                        weakest_80C=tab_forces(b["corners"]["weakest"], f80),
                                        full_set_min_down_80C=f80 * min(r["down"] for r in b["rows"]))
                  for shift, b in band.items()},
        lift_table=lift_table(p, br52, geometry), lid_lift=lid_lift(p, br52, geometry),
        install=install_push(p, br52, geometry), rows=design["rows"])


# ---------------- detent ----------------
def detent_geometry(model):
    """Stator and knob-lobe stacks relative to the rotor axis: x (world), r, phi (deg), thickness."""
    p = model.params
    ay, az = p.axis

    def polar(point):
        return math.hypot(point[1] - ay, point[2] - az), math.degrees(math.atan2(point[2] - az, point[1] - ay))

    stator_shape = model.hardware["mag_stator"]
    box = stator_shape.bounding_box()
    r, phi = polar(centre(stator_shape))
    stator = dict(x=0.5 * (box.min.X + box.max.X), r=r, phi=phi, t=box.max.X - box.min.X, face_x=box.max.X)
    lobes = []
    for lobe_phi in p.knob_phi:
        stack = [s for n, s in model.hardware.items() if n.startswith(f"mag_knob{int(lobe_phi)}_")]
        x0 = min(s.bounding_box().min.X for s in stack)
        x1 = max(s.bounding_box().max.X for s in stack)
        r, phi = polar(centre(stack[0]))
        lobes.append(dict(x=0.5 * (x0 + x1), r=r, phi=phi, t=x1 - x0, face_x=x0))
    gap = min(lobe["face_x"] for lobe in lobes) - stator["face_x"]
    return dict(stator=stator, lobes=lobes, gap=gap)


def detent_sweep(p, br, thetas, geometry):
    """Torque about the axis on the knob magnets and their force, per rotor angle (deg)."""
    s = geometry["stator"]
    a = math.radians(s["phi"])
    stator = [Disc((s["x"], s["r"] * math.cos(a), s["r"] * math.sin(a)), (1, 0, 0), p.magnet_d, s["t"], br)]
    torques, forces = [], []
    for theta in thetas:
        rotor = []
        for lobe in geometry["lobes"]:
            b = math.radians(lobe["phi"] + theta)
            rotor.append(Disc((lobe["x"], lobe["r"] * math.cos(b), lobe["r"] * math.sin(b)), (1, 0, 0),
                              p.magnet_d, lobe["t"], br))
        force, torque = force_torque(stator, rotor)
        torques.append(torque)
        forces.append(force)
    return np.array(torques), np.array(forces)


def boss_mean_radius(p):
    """Mean radius of the boss / inner-ring annulus (near hole edge .. boss radius)."""
    return 0.5 * (p.hole_near / 2 + p.boss_r)


def detent_friction(p, force_row, w_rot, mu_thrust, mu_journal):
    """Friction torque: thrust face (axial magnet force) + near journal (radial force and half the rotor
    weight) + far journal (half the weight)."""
    half_weight = 0.5 * w_rot
    radial = math.hypot(force_row[1], force_row[2] - half_weight)
    return (mu_thrust * abs(force_row[0]) * boss_mean_radius(p) + mu_journal * radial * p.pin_d / 2
            + mu_journal * half_weight * p.pin_d / 2)


def dead_edge(thetas, restoring, friction):
    """First angle (20..60 deg) where the restoring torque drops below friction."""
    fine = np.linspace(20, 60, 801)
    diff = np.interp(fine, thetas, restoring) - np.interp(fine, thetas, friction)
    below = np.where(diff < 0)[0]
    return float(fine[below[0]]) if len(below) else 60.0


def detent(model, br52, mass):
    p = model.params
    geometry = detent_geometry(model)
    thetas = np.arange(0.0, 71.0, 1.0)
    torque, force = detent_sweep(p, br52, thetas, geometry)
    restoring = -torque
    stiffness = restoring[1] / thetas[1]
    window = thetas <= 60
    peak = restoring[window].max()
    peak_theta = thetas[np.argmax(restoring[window])]
    axial_rest, fz_rest, fy_rest = -force[0, 0], force[0, 2], force[0, 1]
    w_rot = mass["rotor_assembly_g"] * p.g_newton_per_gram
    t_thrust = p.mu_abs * axial_rest * boss_mean_radius(p)
    t_near = p.mu_abs * math.hypot(fy_rest, fz_rest - 0.5 * w_rot) * p.pin_d / 2
    t_far = p.mu_abs * 0.5 * w_rot * p.pin_d / 2
    friction = t_thrust + t_near + t_far
    friction_ptfe = p.mu_ptfe / p.mu_abs * t_thrust + t_near + t_far
    dry = np.array([detent_friction(p, f, w_rot, p.mu_abs, p.mu_abs) for f in force])
    ptfe = np.array([detent_friction(p, f, w_rot, p.mu_ptfe, p.mu_abs) for f in force])
    rough = np.array([detent_friction(p, f, w_rot, 0.45, 0.45) for f in force])
    edge_dry, edge_ptfe, edge_rough = (dead_edge(thetas, restoring, f) for f in (dry, ptfe, rough))
    nominal = replace(p, hole_near=V32_HOLE_NEAR)       # only the thrust-ring inner radius of the model changes
    ratio_v32_hole = (peak / detent_friction(nominal, force[0], w_rot, p.mu_abs, p.mu_abs),
                      peak / detent_friction(nominal, force[0], w_rot, 0.45, 0.45))
    reverse = thetas[(-force[:, 0] < 0) & window]
    switch_torque = float(np.max(restoring[window] + dry[window]))
    floor = p.det_floor
    pressure = axial_rest / (math.pi * (p.magnet_d / 2) ** 2)
    pocket_r = p.mag_pocket_d / 2
    stress = 0.75 * pressure * pocket_r ** 2 / floor ** 2
    bulge = {e: pressure * pocket_r ** 4 / (64 * e * floor ** 3 / (12 * (1 - 0.35 ** 2))) for e in FLOOR_E}
    return dict(theta=list(thetas), torque=list(restoring), axial=list(-force[:, 0]), F=force.tolist(),
                gap=geometry["gap"], stator_r=geometry["stator"]["r"], peak=peak, peak_theta=peak_theta,
                peak_hot=p.hot80 * peak, peak_hot_worst=p.hot80 * p.n52_irrev * peak, stiffness=stiffness,
                axial_rest=axial_rest, radial_preload=fz_rest,
                friction=dict(thrust=t_thrust, near=t_near, far=t_far, total=friction, total_ptfe=friction_ptfe),
                ratio=peak / friction, ratio_mu045=peak / rough[0], ratio_v32_hole=ratio_v32_hole,
                stop_error=friction / stiffness,
                stop_error_ptfe=friction_ptfe / stiffness,
                dead_zone_halfwidth=dict(dry=60 - edge_dry, ptfe=60 - edge_ptfe, mu045=60 - edge_rough),
                switch_torque=switch_torque,
                reverse_axial=dict(from_deg=float(reverse.min()) if len(reverse) else None,
                                   max_N=float(force[:, 0].max())),
                floor=dict(stress_MPa=stress, bulge_mm=bulge), magnets=sum(1 for n in model.hardware
                                                                          if n.startswith(("mag_knob", "mag_stator"))),
                friction_tables=dict(dry=list(dry), ptfe=list(ptfe)))


def seating_forces(p, br, geometry):
    """Axial force (N) pressing each detent magnet onto its printed floor / wall, rotor angle 0-120 deg.

    Knob lobe stacks: + = toward their 0.8 floor (-X, toward the stator); stator: + = toward its 0.8 wall
    (+X, toward the knob) = the reaction of the sum over the lobes."""
    s = geometry["stator"]
    a = math.radians(s["phi"])
    stator = Disc((s["x"], s["r"] * math.cos(a), s["r"] * math.sin(a)), (1, 0, 0), p.magnet_d, s["t"], br)
    thetas = np.arange(0.0, 120.0 + SEATING_STEP / 2, SEATING_STEP)
    lobes = []
    for theta in thetas:
        row = []
        for lobe in geometry["lobes"]:
            b = math.radians(lobe["phi"] + theta)
            disc = Disc((lobe["x"], lobe["r"] * math.cos(b), lobe["r"] * math.sin(b)), (1, 0, 0), p.magnet_d,
                        lobe["t"], br)
            row.append(-interact(stator, disc)[0][0])
        lobes.append(row)
    lobes = np.array(lobes)
    stator_seat = lobes.sum(axis=1)
    reversed_at = thetas[stator_seat < 0]
    return dict(theta=list(thetas), stator=list(stator_seat), lobes=lobes.tolist(),
                stator_min=float(stator_seat.min()), stator_min_theta=float(thetas[np.argmin(stator_seat)]),
                stator_reversed_deg=(float(reversed_at.min()), float(reversed_at.max())) if len(reversed_at) else None,
                lobe_min=float(lobes.min()), lobe_min_at_rest=float(lobes[0].min()))


def snap_run(thetas, restoring, friction, inertia, start_deg, speed, damping):
    """Rotor released at start_deg (past the dead zone) with speed rad/s: overshoot, reversals, settle time."""
    angle, w, dt, t = math.radians(start_deg), speed, 2e-6, 0.0
    reversals, overshoot = 0, 0.0
    while t < SNAP_MAX_S:
        x = (math.degrees(angle) + 60) % 120 - 60
        magnet = -math.copysign(1, x) * np.interp(abs(x), thetas, restoring)
        resist = np.interp(abs(x), thetas, friction)
        if abs(w) < 1e-3 and abs(magnet) <= resist:
            break
        rub = -math.copysign(resist, w) if abs(w) >= 1e-3 else -math.copysign(resist, magnet)
        w_new = w + (magnet + rub - damping * w) / inertia * dt
        if w != 0 and w_new * w < 0:
            reversals += 1
            w_new = 0.0
        w = w_new
        angle += w * dt
        t += dt
        overshoot = max(overshoot, math.degrees(angle) - 120)
    return dict(overshoot=overshoot, reversals=reversals, settle_ms=1000 * t, settled=t < SNAP_MAX_S,
                final_err=math.degrees(angle) - 120)


def snap_dynamics(det, inertia_kgm2):
    inertia = inertia_kgm2 * 1e3                  # kg m^2 -> N mm s^2
    thetas, restoring = det["theta"], det["torque"]
    dry, ptfe = det["friction_tables"]["dry"], det["friction_tables"]["ptfe"]
    start_dry = 60 + det["dead_zone_halfwidth"]["dry"] + 0.5
    start_ptfe = 60 + det["dead_zone_halfwidth"]["ptfe"] + 0.5
    cases = (("dry, released", start_dry, 0.0, dry, 0.0, det["stop_error"]),
             ("dry, finger 2 rad/s", start_dry, 2.0, dry, 0.0, det["stop_error"]),
             ("PTFE, released", start_ptfe, 0.0, ptfe, 0.0, det["stop_error_ptfe"]),
             ("PTFE + damping grease c=1.0", start_ptfe, 0.0, ptfe, 1.0, det["stop_error_ptfe"]))
    runs = {}
    for label, start, speed, friction, damping, band in cases:
        run = snap_run(thetas, restoring, friction, inertia, start, speed, damping)
        run.update(start_deg=start, stop_band=band)
        runs[label] = run
    return runs


def mount_items(p, tabs):
    """Info items of the tab mount (v3.3 A.4 check 7)."""
    weak80, typ, full, same = tabs["weakest_80C"], tabs["typical_20C"], tabs["full_set"], tabs["lid_equals_base"]
    corner = f"base {WEAKEST[0][0]} behind {WEAKEST[1]:g}, lid = base, lid magnet Z {p.lid_mag_z:g}"
    split = {name: {source: (row["pull"], row["down"]) for source, row in sources.items()}
             for name, sources in tabs["split_typical_20C"].items()}
    band = {f"lid Z {row['lid_z']:g}": (row["weakest_80C"]["pull"], row["weakest_80C"]["down"],
                                        row["full_set_min_down_80C"]) for row in tabs["lid_band"].values()}
    return [
        item("tab pull / down per tab, 80 C weakest incl. irreversible (N)", (weak80["pull"], weak80["down"]),
             level="info", note=f"2 box magnets x 2 stacks incl. cross terms; {corner}"),
        item("tab pull / down per tab, 20 C range over BASES x WALLS with lid = base (N)",
             ((same["min_pull"]["value_20C"], same["max_pull"]["value_20C"]),
              (same["min_down"]["value_20C"], same["max_down"]["value_20C"])), level="info",
             note=f"typical {typ['pull']:.2f} / {typ['down']:.2f}"),
        item("per-stack split, typical corner 20 C: {stack: {source: (pull, down)}} (N)", split, level="info",
             note=f"stack totals lower {typ['lower']['pull']:.2f} / {typ['lower']['down']:.2f}, "
                  f"upper {typ['upper']['pull']:.2f} / {typ['upper']['down']:.2f}"),
        item(f"full candidate set ({full['n']} boxes incl. Ø5-8 lid magnets), 20 C per tab: min pull / max pull / "
             "min down (N)",
             (full["min_pull"]["value_20C"], full["max_pull"]["value_20C"], full["min_down"]["value_20C"]), level="info",
             note=f"min pull {full['min_pull']['case']}; min down {full['min_down']['case']}; "
                  f"whole tab pushed up in {full['tab_pushed_up']} boxes"),
        item("upper stack alone, full set: min down 20 C (N) / boxes where it is pushed up",
             (full["min_upper_down"]["value_20C"], full["upper_pushed_up"]), level="info",
             note=f"{full['min_upper_down']['case']}; the whole tab is still pulled down (min "
                  f"{full['min_down']['value_20C']:.2f} N)"),
        item(f"lid magnet Z {p.lid_mag_z:g} +-{LID_BAND:g}: 80 C weakest pull / down, full-set min down (N per tab)",
             band, level="info", note="pockets stay at the design Z; a single test magnet stops anywhere within about "
                                      f"+-{LID_BAND:g} (v3.3 2.1)"),
    ]


def seating_items(p, seating, tabs):
    """Retainers of the magnets (review M3, v3.3 2.4): spacer S, knob caps, tab caps."""
    spacer_press_fit = p.spacer_d > p.mag_pocket_d
    knob_rim = math.pi * p.knob_cap_d * p.knob_cap_t
    tab_rim = math.pi * p.tab_cap_d * p.cap_t
    full, install = tabs["full_set"], tabs["install"]
    push = {name: max(-row["min_pull"], 0.0) for name, row in install.items()}
    return [
        item("stator seating force over 0-120 deg, min (N, + = onto its 0.8 wall)", seating["stator_min"],
             seating["stator_min"] >= 0 or spacer_press_fit,
             f">= 0, else carried by a press-fit spacer (S Ø{p.spacer_d:g} in the Ø{p.mag_pocket_d:g} pocket)",
             note=f"reversed {seating['stator_reversed_deg']} deg, pushes the stator onto the press-fit spacer S"),
        item("knob lobe stack seating force, min while shifting / at rest (N, + = onto its 0.8 floor)",
             (seating["lobe_min"], seating["lobe_min_at_rest"]), level="info",
             note=f"negative = the stack pushes on its cap: carried by the cap glued all round (rim {knob_rim:.1f} mm^2, "
                  f"{abs(min(seating['lobe_min'], 0.0)) / knob_rim:.2f} MPa)"),
        item("tab stacks at rest, full set: min pull lower / upper (N, + = onto the 0.8 floor)",
             (full["min_lower_pull"]["value_20C"], full["min_upper_pull"]["value_20C"]), level="info",
             note="both stacks of every tab are pulled onto their floors in every candidate box"),
        item("tab cap push while the plate slides down the box face (vertical install, strongest corner 20 C), "
             "lower / upper stack per cap (N)", (push["lower"], push["upper"]), level="info",
             note=f"carried by the tab caps glued all round (rim {tab_rim:.1f} mm^2, {push['lower'] / tab_rim:.2f} MPa at "
                  f"the lower cap); at {install['lower']['at_dz']:g} / {install['upper']['at_dz']:g} mm above the seat"),
    ]


def run(model, mass):
    p = model.params
    br52 = calibrate_br(p.magnet_d, p.magnet_t)
    tabs = mount(model, br52)
    det = detent(model, br52, mass)
    snap = snap_dynamics(det, mass["inertia_kgm2"])
    seating = seating_forces(p, br52, detent_geometry(model))
    bulge_100 = det["floor"]["bulge_mm"][100.0]
    ratio_dry, ratio_rough = det["ratio_v32_hole"]
    items = [
        item("detent peak / friction (dry mu 0.35)", det["ratio"], det["ratio"] >= RATIO_MIN, f">= {RATIO_MIN}",
             note=f"with the v3.2 Ø{V32_HOLE_NEAR:g} near hole the model gives {ratio_dry:.2f} (mu 0.45: "
                  f"{ratio_rough:.2f}): the friction model takes the thrust-ring inner radius as near_hole / 2, the "
                  "tighter journal fit adds friction that is not modelled, so read the ratio as unchanged (v3.3 2.3)"),
        item("detent peak / friction (layer-line faces mu 0.45)", det["ratio_mu045"], det["ratio_mu045"] >= RATIO_MIN,
             f">= {RATIO_MIN}", level="warn"),
        item("pocket floor bulge at E 100 MPa (mm)", bulge_100, bulge_100 < p.boss_h / 2, f"< boss gap / 2 = {p.boss_h / 2}"),
        item("detent magnet face gap (mm)", det["gap"], abs(det["gap"] - p.detent_gap) < 1e-6,
             f"= {p.detent_gap:.2f} (0.8 floor + boss + 0.8 wall)"),
    ]
    items += seating_items(p, seating, tabs)
    for label, r in snap.items():
        ok = r["settled"] and abs(r["final_err"]) <= r["stop_band"] + 1e-6
        items.append(item(f"snap settles in the next detent ({label})", r["final_err"], ok,
                          f"settles < {SNAP_MAX_S} s, |error| <= stop band {r['stop_band']:.1f} deg"))
    items += mount_items(p, tabs)
    items += [
        item("dead zone half width dry / PTFE (deg)",
             (det["dead_zone_halfwidth"]["dry"], det["dead_zone_halfwidth"]["ptfe"]), level="info"),
        item("detent peak 20 C / 80 C / 80 C + 15 % irreversible (N mm)",
             (det["peak"], det["peak_hot"], det["peak_hot_worst"]), level="info"),
    ]
    numbers = dict(br_eff=br52, mount=tabs, detent={k: v for k, v in det.items() if k not in ("F", "friction_tables")},
                   snap=snap, seating=seating)
    result = section("7 magnet model (tabs: 2 box magnets x 2 stacks, candidate set; detent, dead zone, snap, floors)",
                     items, numbers)
    return result, dict(br52=br52, mount=tabs, detent=det)      # raw values for checks 8 and 10
