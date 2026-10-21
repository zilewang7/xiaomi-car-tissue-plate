"""Check 8: 3D rigid-body limit LP of the mounted plate (port of concept/v3.1 section 6b), plus the refill
statics of v3.1 section 6c extended to the v3.2 refill (the whole box is carried with the plate on it) and the
v3.4 refill (the plate is taped to the lid: the lid is lifted with it, only the base magnets hold it back).

Contacts: the pad zones on the lid top (v3.4: tape; the bare lip footprint when pad_t = 0) and the tab backs on the box
front face (lead-in on the sides and the round bottom, flat up to flat_back_top, v3.3); unilateral normal forces with
inscribed Coulomb pyramids. Fixed loads: weight at the CoG and, per tab stack (lower and upper of both tabs, v3.3
2.1), its own magnet force (pull toward the box, downward shear; checks/magnets.py) at its CAD centre.
lp_cap = largest extra load along a direction (or couple) the contacts can still carry. The 80 C weakest LP is
repeated with the lid magnet off by +-LID_BAND (information).
"""
import math

import numpy as np
from scipy.optimize import linprog
from scipy.spatial import ConvexHull

from .common import centre, item
from .magnets import LID_BAND, STACKS, boss_mean_radius, detent_friction

LP_STEP, LP_K = 2.0, 12            # contact sampling step (mm), friction pyramid facets
GESTURES = {"next = cabin corner": (30.0, -1), "prev = windshield corner": (150.0, +1)}
LEAN_FULL = (0, 10, 20, 25, 30, 35, 40, 45, 50)
LEAN_SHORT = (0, 20, 30, 40)
MU_BOX_LOW = 0.25
LIMITS = dict(documented=1.5, vertical=2.0, pinch=1.5, braking_g=1.5, lift_off_g=3.0)   # spec 7-8
TILT_MAX = 90.0                    # deg; reported as ">= 90" when the plate still holds there
TILT_DIRECTIONS = {"front down": (0.0, -1.0), "front up": (0.0, 1.0), "driver end down": (1.0, 0.0),
                   "far end down": (-1.0, 0.0)}


# ---------------- contacts and LP ----------------
def rect_boundary(x0, x1, y0, y1, step):
    xs, ys = np.arange(x0, x1 + 1e-9, step), np.arange(y0, y1 + 1e-9, step)
    return [(x, y0) for x in xs] + [(x1, y) for y in ys] + [(x, y1) for x in xs[::-1]] + [(x0, y) for y in ys[::-1]]


def lid_flat_boundary(p, y0, y1, step):
    """Boundary of the lid-top flat (plan rounded rectangle offset by the top fillet) within Y y0..y1."""
    half_flat, corner_r = p.box_l / 2 - p.top_fillet, p.box_corner_r - p.top_fillet
    cx, cy = p.box_l / 2 - p.box_corner_r, p.box_corner_r
    points = [(x, y0) for x in np.arange(-cx, cx + 1e-9, step)]
    points += [(side * (cx + corner_r * math.cos(math.radians(a))), cy + corner_r * math.sin(math.radians(a)))
               for side in (-1, 1) for a in np.linspace(-90, 0, 31)]
    points += [(side * half_flat, y) for side in (-1, 1) for y in np.arange(cy, y1 + 1e-9, step)]
    points += [(x, y1) for x in np.arange(-half_flat, half_flat + 1e-9, step)]
    return points


def hull_vertices(points):
    """Convex-hull vertices of a planar contact patch. Every point of a patch has the same normal and friction
    pyramid and its wrench is linear in the point, so the hull vertices span exactly the same wrench cone as
    all sampled points (same LP optimum, far fewer columns)."""
    points = np.asarray(points, float)
    return points[ConvexHull(points).vertices]


def lp_contacts(p, pads, mu_lid, mu_box, step=LP_STEP):
    """(point, normal, mu): lid support + chamfered tab backs on the box face."""
    contacts = []
    if pads:
        for (xr, yr) in p.pad_zones:
            patch = hull_vertices(rect_boundary(xr[0], xr[1], yr[0], yr[1], step))
            contacts += [((x, y, 0.0), (0, 0, 1.0), mu_lid) for x, y in patch]
    else:
        patch = hull_vertices(lid_flat_boundary(p, p.top_fillet, p.lip_y[1], step))
        contacts += [((x, y, 0.0), (0, 0, 1.0), mu_lid) for x, y in patch]
    half, z_top = p.tab_w / 2 - p.tab_leadin, p.flat_back_top
    for side in (-1, 1):
        cx = side * p.base_mag_x
        points = [(x, z_top) for x in np.arange(cx - half, cx + half + 1e-9, step)]
        points += [(cx + s * half, z) for s in (-1, 1) for z in np.arange(p.tab_zc, z_top + 1e-9, step)]
        points += [(cx + half * math.cos(math.radians(a)), p.tab_zc + half * math.sin(math.radians(a)))
                   for a in np.linspace(180, 360, 19)]
        contacts += [((x, 0.0, z), (0, -1.0, 0), mu_box) for x, z in hull_vertices(points)]
    return contacts


def lp_matrix(contacts, k=LP_K):
    columns = []
    for point, normal, mu in contacts:
        point, normal = np.array(point), np.array(normal)
        helper = np.array([1.0, 0, 0]) if abs(normal[0]) < 0.9 else np.array([0, 1.0, 0])
        t1 = np.cross(normal, helper)
        t1 /= np.linalg.norm(t1)
        t2 = np.cross(normal, t1)
        mu_inscribed = mu * math.cos(math.pi / k)
        for i in range(k):
            f = normal + mu_inscribed * (math.cos(2 * math.pi * i / k) * t1 + math.sin(2 * math.pi * i / k) * t2)
            columns.append(np.r_[f, np.cross(point, f)])
    return np.array(columns).T


def tab_points(model):
    """CAD centre of every tab stack: {(side, stack): point}."""
    return {(side, stack): np.mean([centre(s) for n, s in model.hardware.items() if n.startswith(f"{prefix}{side}_")],
                                   axis=0)
            for side in ("-", "+") for stack, prefix in STACKS.items()}


def tab_loads(points, forces):
    """[(point, force)] per stack of both tabs; forces = magnets.tab_forces of one tab (the other is its mirror; Fx = 0,
    the box magnets share the stacks' X)."""
    return [(point, np.array([0.0, forces[stack]["pull"], -forces[stack]["down"]]))
            for (_, stack), point in points.items()]


def lp_fixed(weight, cog, loads, gravity=(0.0, 0.0, -1.0)):
    """Weight at the CoG and the magnet loads [(point, force)] as the LP's fixed 6-vector."""
    g = weight * np.asarray(gravity, float) / np.linalg.norm(gravity)
    fixed = np.r_[g, np.cross(cog, g)]
    for point, force in loads:
        fixed += np.r_[force, np.cross(point, force)]
    return fixed


def lp_cap(A, fixed, d=None, pt=None, couple=None):
    if couple is not None:
        load = np.r_[np.zeros(3), np.asarray(couple, float)]
    else:
        d = np.asarray(d, float) / np.linalg.norm(d)
        load = np.r_[d, np.cross(np.asarray(pt, float), d)]
    r = linprog(np.r_[np.zeros(A.shape[1]), -1.0], A_eq=np.c_[A, load], b_eq=-fixed,
                bounds=[(0, None)] * A.shape[1] + [(0, 1e4)], method="highs")
    if r.status != 0:
        return float("nan")
    return float("inf") if r.x[-1] > 9e3 else float(r.x[-1])


def lp_feasible(A, fixed):
    r = linprog(np.zeros(A.shape[1]), A_eq=A, b_eq=-fixed, bounds=[(0, None)] * A.shape[1], method="highs")
    return r.status == 0


# ---------------- gestures ----------------
def knob_centre_x(p):
    return 0.5 * (p.knob_x[0] + p.knob_x[1])


def near_journal_share(p):
    """Share of a radial load at the knob carried by the near journal (lever rule about the far journal)."""
    x_near = 0.5 * (p.near_block_x[0] + p.near_block_x[1])
    x_far = 0.5 * sum(p.far_block_x)
    return (knob_centre_x(p) - x_far) / (x_near - x_far)


def gesture_rows(p, det, w_rot, phi0, sense, push, kdet):
    """Finger force needed along the switching path (line through the lobe centre, fixed direction push):
    detent restoring torque + friction incl. the finger's own load on the boss and the near journal."""
    thetas, torque, force = np.array(det["theta"]), np.array(det["torque"]), np.array(det["F"])
    exit_deg = 60 + det["dead_zone_halfwidth"]["dry"]
    push = np.asarray(push, float) / np.linalg.norm(push)
    share, r_boss = near_journal_share(p), boss_mean_radius(p)
    ay, az = p.axis
    rows = []
    for i, t in enumerate(thetas):
        if t > exit_deg or (t > 30 and t % 5):
            continue
        phi = math.radians(phi0 + sense * t)
        lobe = np.array([ay + p.knob_mag_r * math.cos(phi), az + p.knob_mag_r * math.sin(phi)])
        r = lobe - np.array([ay, az])
        arm = sense * (r[0] * push[2] - r[1] * push[1])
        if arm <= 0.5:
            continue
        f = 0.0
        for _ in range(40):
            axial = kdet * (-force[i, 0]) - f * push[0]
            radial = np.array([kdet * force[i, 1], kdet * force[i, 2] - 0.5 * w_rot]) + share * f * push[1:]
            friction = (p.mu_abs * abs(axial) * r_boss + p.mu_abs * np.linalg.norm(radial) * p.pin_d / 2
                        + p.mu_abs * 0.5 * w_rot * p.pin_d / 2)
            f = (kdet * torque[i] + friction) / arm
        if f > 0.05:
            rows.append((t, f, np.array([knob_centre_x(p), *(lobe - p.knob_lobe_r * push[1:])]), push))
    return rows


def gesture_margin(A, fixed, rows):
    worst = (float("inf"), None, None, None)
    for t, need, point, push in rows:
        cap = lp_cap(A, fixed, push, point)
        if cap / need < worst[0]:
            worst = (cap / need, t, need, cap)
    return worst


def lean_dir(alpha, toward, beta=0.0):
    """Unit push: alpha from vertical toward -Y (toward = -1, forward) or +Y (+1, toward the driver); beta inward."""
    a, b = math.radians(alpha), math.radians(beta)
    d = np.array([-math.sin(b), toward * math.sin(a) * math.cos(b), -math.cos(a) * math.cos(b)])
    return d / np.linalg.norm(d)


def lean_limits(gestures):
    """Forward-lean angle where each gesture's margin drops to 1.5 and 1.0 (linear interpolation)."""
    limits = {}
    for gesture in GESTURES:
        points = sorted((a, v[0]) for (g, label, a), v in gestures.items() if g == gesture and label in ("vertical", "lean fwd"))
        for threshold in (1.5, 1.0):
            found = None
            for (a0, m0), (a1, m1) in zip(points, points[1:]):
                if m0 >= threshold > m1:
                    found = a0 + (a1 - a0) * (m0 - threshold) / (m0 - m1)
                    break
            key = f"{gesture} fwd lean @{threshold}x"
            limits[key] = round(found, 1) if found is not None else (f">{points[-1][0]}" if points[-1][1] >= threshold else "<0")
    return limits


# ---------------- conditions ----------------
def conditions(p, mount):
    """name: (per-stack tab forces, pads, mu_lid, mu_box, detent factor)."""
    pads = p.pad_t > 0
    mu_lid = p.mu_pad if pads else p.mu_pu[0]
    return {
        "20C typical": (mount["typical_20C"], pads, mu_lid, p.mu_pu[0], 1.0),
        "80C weakest": (mount["weakest_80C"], pads, mu_lid, p.mu_pu[0], p.hot80),
        "90C weakest+irr": (mount["weakest_90C"], pads, mu_lid, p.mu_pu[0], p.hot90 * p.n52_irrev),
        f"80C weakest, mu_box {MU_BOX_LOW}": (mount["weakest_80C"], pads, mu_lid, MU_BOX_LOW, p.hot80),
        "80C weakest, NO pads": (mount["weakest_80C"], False, p.mu_pu[0], p.mu_pu[0], p.hot80),
    }


def evaluate(p, A, fixed, weight, cog, det, w_rot, kdet, full, lobe_point):
    th, force = np.array(det["theta"]), np.array(det["F"])
    switch = max(kdet * det["torque"][i] + detent_friction(p, kdet * force[i], w_rot, p.mu_abs, p.mu_abs)
                 for i in range(len(th)) if th[i] <= 60)
    r = dict(switch_torque=switch)
    r["pinch_next"] = lp_cap(A, fixed, couple=(-1, 0, 0))
    r["pinch_prev"] = lp_cap(A, fixed, couple=(1, 0, 0))
    r["push_top_fwd_mid_N"] = lp_cap(A, fixed, (0, -1, 0), (0, p.axis_y, p.axis_z + p.r_sweep))
    r["push_top_fwd_knob_N"] = lp_cap(A, fixed, (0, -1, 0), lobe_point)
    r["push_inward_knob_N"] = lp_cap(A, fixed, (-1, 0, 0), lobe_point)
    r["braking_g"] = lp_cap(A, fixed, (0, -1, 0), cog) / weight
    r["lift_off_g"] = lp_cap(A, fixed, (0, 0, 1), cog) / weight          # downward acceleration that unloads it
    r["lateral_g"] = min(lp_cap(A, fixed, (1, 0, 0), cog), lp_cap(A, fixed, (-1, 0, 0), cog)) / weight
    gestures = {}
    for name, (phi0, sense) in GESTURES.items():
        for toward, label in ((-1, "lean fwd"), (+1, "lean to driver")):
            for alpha in (LEAN_FULL if full else LEAN_SHORT):
                if alpha == 0 and toward > 0:
                    continue
                rows = gesture_rows(p, det, w_rot, phi0, sense, lean_dir(alpha, toward), kdet)
                gestures[(name, label if alpha else "vertical", alpha)] = gesture_margin(A, fixed, rows)
        if full:
            rows = gesture_rows(p, det, w_rot, phi0, sense, lean_dir(30, -1, 20), kdet)
            gestures[(name, "fwd 30 + inward 20", 30)] = gesture_margin(A, fixed, rows)
    r["lean_limits_deg"] = lean_limits(gestures)
    r["gestures"] = gestures
    return r


def documented_margins(gestures):
    """Spec 4.5: next = vertical or toward the driver (<= 50 deg); prev = vertical or forward lean <= 20 deg."""
    next_rows = [v[0] for (g, label, a), v in gestures.items()
                 if g.startswith("next") and label in ("vertical", "lean to driver")]
    prev_rows = [v[0] for (g, label, a), v in gestures.items()
                 if g.startswith("prev") and (label == "vertical" or (label == "lean fwd" and a <= 20))]
    vertical = [v[0] for (g, label, a), v in gestures.items() if label == "vertical"]
    return min(next_rows + prev_rows), min(vertical)


def statics(model, mass, mount, det):
    p = model.params
    weight = mass["total_g"] * p.g_newton_per_gram
    cog = np.array(mass["cog"])
    w_rot = mass["rotor_assembly_g"] * p.g_newton_per_gram
    points = tab_points(model)
    lobe_point = (knob_centre_x(p), p.axis_y + p.knob_mag_r * math.cos(math.radians(30)),
                  p.axis_z + p.knob_mag_r * math.sin(math.radians(30)))
    matrices, out = {}, {}
    for name, (forces, pads, mu_lid, mu_box, kdet) in conditions(p, mount).items():
        key = (pads, mu_lid, mu_box)
        if key not in matrices:
            matrices[key] = lp_matrix(lp_contacts(p, pads, mu_lid, mu_box))
        fixed = lp_fixed(weight, cog, tab_loads(points, forces))
        full = name in ("20C typical", "80C weakest", "90C weakest+irr")
        r = evaluate(p, matrices[key], fixed, weight, cog, det, w_rot, kdet, full, lobe_point)
        r.update(pull=forces["pull"], down=forces["down"], pads=pads, mu_lid=mu_lid, mu_box=mu_box, detent_factor=kdet)
        out[name] = r
    worst = out["80C weakest"]
    documented, vertical = documented_margins(worst["gestures"])
    pinch = min(worst["pinch_next"], worst["pinch_prev"]) / worst["switch_torque"]
    band = lid_band(p, mount, matrices[(worst["pads"], worst["mu_lid"], worst["mu_box"])], weight, cog, det, w_rot,
                    points, lobe_point)
    press_rows = gesture_rows(p, det, w_rot, 30.0, -1, (0, 0, -1), 1.0)
    press_force = max(f for _, f, _, _ in press_rows)
    items = [
        item("documented gestures, worst margin (80 C weakest)", documented, documented >= LIMITS["documented"],
             f">= {LIMITS['documented']}x"),
        item("vertical press on a corner, worst margin (80 C weakest)", vertical, vertical >= LIMITS["vertical"],
             f">= {LIMITS['vertical']}x"),
        item("pinch capacity / switching torque (80 C weakest)", pinch, pinch >= LIMITS["pinch"], f">= {LIMITS['pinch']}x"),
        item("braking (80 C weakest, g)", worst["braking_g"], worst["braking_g"] >= LIMITS["braking_g"],
             f">= {LIMITS['braking_g']} g"),
        item("lift-off needs downward acceleration (80 C weakest, g)", worst["lift_off_g"],
             worst["lift_off_g"] >= LIMITS["lift_off_g"], f">= {LIMITS['lift_off_g']} g"),
        item("forward-lean limits (80 C weakest, deg)", worst["lean_limits_deg"], level="info"),
        item("push forward on the prism top (80 C weakest / 20 C typical / no pads, N)",
             (worst["push_top_fwd_mid_N"], out["20C typical"]["push_top_fwd_mid_N"],
              out["80C weakest, NO pads"]["push_top_fwd_mid_N"]), level="info"),
        item("lateral (80 C weakest, g)", worst["lateral_g"], level="info"),
        item("vertical press force needed at 20 C (N)", press_force, level="info"),
        item(f"80 C weakest, lid magnet Z +-{LID_BAND:g}: documented / vertical / pinch (x), braking / lift-off (g)",
             {label: (row["documented"], row["vertical"], row["pinch"], row["braking_g"], row["lift_off_g"])
              for label, row in band.items()}, level="info", note="the pockets stay at the design Z (v3.3 2.1)"),
    ]
    for r in out.values():
        r["gestures"] = {f"{g} | {label} {a}": dict(margin=v[0], worst_theta=v[1], need_N=v[2], capacity_N=v[3])
                         for (g, label, a), v in r["gestures"].items()}
    numbers = dict(weight_N=weight, cog=tuple(cog), conditions=out, press_force_20C_N=press_force,
                   near_journal_share=near_journal_share(p), lid_band=band)
    return items, numbers, dict(weight=weight, cog=cog, points=points, matrices=matrices)


def lid_band(p, mount, A, weight, cog, det, w_rot, points, lobe_point):
    """80 C weakest LP (pads, mu_pu box) with the lid magnet LID_BAND below / above the configured point."""
    band = {}
    for row in mount["lid_band"].values():
        if row["shift"] == 0.0:
            continue
        r = evaluate(p, A, lp_fixed(weight, cog, tab_loads(points, row["weakest_80C"])), weight, cog, det, w_rot,
                     p.hot80, True, lobe_point)
        documented, vertical = documented_margins(r["gestures"])
        band[f"lid Z {row['lid_z']:g}"] = dict(documented=documented, vertical=vertical,
                                               pinch=min(r["pinch_next"], r["pinch_prev"]) / r["switch_torque"],
                                               braking_g=r["braking_g"], lift_off_g=r["lift_off_g"],
                                               tab_pull_N=row["weakest_80C"]["pull"],
                                               tab_down_N=row["weakest_80C"]["down"])
    return band


# ---------------- refill: the whole box is carried with the plate on it ----------------
def tilt_limit(A, weight, cog, loads, direction):
    """Largest box tilt (deg) at which the plate still rests in equilibrium (bisection)."""
    dx, dy = direction

    def holds(alpha):
        a = math.radians(alpha)
        gravity = (dx * math.sin(a), dy * math.sin(a), -math.cos(a))
        return lp_feasible(A, lp_fixed(weight, cog, loads, gravity))

    if not holds(0.0):
        return 0.0
    if holds(TILT_MAX):
        return TILT_MAX
    low, high = 0.0, TILT_MAX
    for _ in range(14):
        mid = 0.5 * (low + high)
        low, high = (mid, high) if holds(mid) else (low, mid)
    return low


def refill(model, mass, mount, lp):
    p = model.params
    cog = mass["cog"]
    slide = {mu: math.degrees(math.atan(mu)) for mu in (p.mu_pu[0], p.mu_pu[1], p.mu_pad)}
    tip = math.degrees(math.atan2(cog[1], cog[2]))
    lift = mount["lift_table"]           # whole-tab forces (both stacks)
    lid = [mount["lid_lift"][which] for which in ("weakest", "typical", "strongest")]   # base magnets only
    extra_weak = max(2 * (r["weak_down"] + p.mu_pu[0] * r["weak_pull"]) for r in lift) * mount["factors"]["f80"]
    extra_strong = max(2 * (r["strong_down"] + p.mu_pu[0] * r["strong_pull"]) for r in lift)
    relief = [math.degrees(math.asin(p.beam_relief / (z - p.parting_z))) for z in (p.beam_z[1], p.beam_z[0])]
    pads = p.pad_t > 0
    key = (pads, p.mu_pad if pads else p.mu_pu[0], p.mu_pu[0])
    A = lp["matrices"][key]
    tilts = {}
    for label, forces in (("20C typical", mount["typical_20C"]), ("80C weakest", mount["weakest_80C"])):
        loads = tab_loads(lp["points"], forces)
        tilts[label] = {name: tilt_limit(A, lp["weight"], lp["cog"], loads, d) for name, d in TILT_DIRECTIONS.items()}
    mu_support = p.mu_pad if pads else p.mu_pu[0]
    slide_limit = slide[mu_support]
    worst_tilt = min(tilts["80C weakest"].values())
    capped = "; holds at the 90 deg cap in every direction (the tab magnets alone carry it)" if worst_tilt >= TILT_MAX else ""
    items = [
        item("box tilt the plate survives while the whole box is carried (80 C weakest, deg)", worst_tilt,
             worst_tilt >= slide_limit - 1e-6, f">= friction-only slide angle atan({mu_support}) = {slide_limit:.1f} "
             "(spec 6: 39 with pads)", level="warn",
             note=f"LP with tilted gravity, front / back / both ends down{capped}"),
        item("extra force to lift the plate off the box (weak 80 C .. strong 20 C, N, plus weight)",
             (extra_weak, extra_strong), level="info"),
        item("extra force to lift the lid with the plate taped on, base magnets only: weakest / typical / strongest "
             "corner (20 C, both tabs, N, plus weight)", tuple(row["force_N"] for row in lid), level="info",
             note="largest over the lift height, at " + " / ".join(f"{row['at_dz']:g}" for row in lid)
                  + " mm above the seat"),
        item("lid tilted about its front skirt: beam relief closes after (deg)", relief, level="info",
             note="v3.2 lever only (v3.4: the plate is taped to the lid and comes up with it, lid-lift force above)"),
    ]
    numbers = dict(slide_deg=slide, tip_deg=tip, tilt_limits_deg=tilts, extra_lift_N=(extra_weak, extra_strong),
                   lid_lift_N=mount["lid_lift"],
                   weight_N=lp["weight"], tabs_below_parting=-(p.tab_bottom - p.parting_z),
                   peel_relief_closes_deg=relief)
    return items, numbers
