"""Check 10: detent couple loop (port of concept/v3.1 section 6d) with the v3.3 joint judgement (v3.3 2.5).

Rotor equilibrium: the detent magnets pull the knob onto the near block (axial couple between the stator
and the boss contact) and the knob magnet down toward the stator; with the rotor weight this gives the near
and far journal forces and the vertical car acceleration at which the far journal force changes sign
(a possible "tick").
Cradle: lip + front bar as a beam on the compression-only pad foundation, loaded by the weights (4 tab magnets per
tab), the tab shear, the journal forces and the couple; the result is how far the near end of the lip lifts off the
pads. Tab shear (v3.3 2.5): the smallest 80 C down force per tab over the full box candidate set (checks/magnets.py,
lid magnets Ø5-8 included) at the configured lid magnet point, used at every temperature as in v3.1; the shear pulls
the plate down, so the smallest one lifts most.
Joint between the lip and the beam (v3.3 2.5): the high-temperature stiffness comes from the continuous epoxy line
(no dowels since 10-18: the front bar is glued to the lip directly). Judged (hard): glue intact = one composite
section ("glued", v3.1), near-end lift at 90 C, ABS E 100 <= 0.20 by two decimals. Information: soft but continuous
glue (two-layer partial-interaction beam, shear stiffness G w / t per mm, G 1 MPa), no connection (v3.1 "spot", the
lower bound; without dowels it is also the debonded joint), and a segmented-section cross-check: in the tab segments the real CAD sections (beam, tab down to its round
bottom, both pockets) instead of the uniform lip + beam section. ABS E 2000 / 300 / 100 MPa as in v3.1 (100 = near the
heat deflection temperature).
"""
import numpy as np
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps

from .common import centre, item, section, solid_of
from .magnets import LID_BAND
from .printability import section_faces

PAD_FOUNDATION = 300.0        # N/mm per mm of length under the pads (v3.1)
E_VALUES = (2000.0, 300.0, 100.0)
NODES = 385
LIFT_LIMIT = 0.205            # spec 3.2-9 / 4.3, v3.3 2.5: near-end lip lift <= 0.20 at 90 C, E 100, two decimals
TEMPERATURES = ("20C", "80C", "90C", "90C+irr")
MAX_ITERATIONS = 200
GLUE_T = 0.2                  # mm, epoxy line
GLUE_G_SOFT = 1.0             # MPa: rubbery epoxy past its glass transition (literature 1-10, v3.3 2.5)


# ---------------- rotor equilibrium (v3.1 'rotor') ----------------
def loop_geometry(model, mass):
    p = model.params
    bottom_lobe = [s for n, s in model.hardware.items() if n.startswith("mag_knob270_")]
    knob_magnet = np.mean([centre(s) for s in bottom_lobe], axis=0)
    stator = centre(model.hardware["mag_stator"])
    return dict(x_near=0.5 * sum(p.near_block_x), x_far=0.5 * sum(p.far_block_x),
                x_knob_magnet=knob_magnet[0], z_knob_magnet=knob_magnet[2], x_stator=stator[0], z_stator=stator[2],
                rotor_weight=mass["rotor_assembly_g"] * p.g_newton_per_gram, rotor_cog_x=mass["rotor_cog"][0])


def journal_forces(p, geo, axial, radial, z_boss, gravity=1.0):
    """(near N, far N, car acceleration g at which the far force changes sign); forces on the rotor, up +."""
    weight = geo["rotor_weight"]
    m_magnets = ((geo["z_knob_magnet"] - p.axis_z) * (-axial) - (geo["x_knob_magnet"] - geo["x_near"]) * (-radial)
                 + (z_boss - p.axis_z) * axial)
    m_weight = (geo["rotor_cog_x"] - geo["x_near"]) * weight
    far = (m_magnets + m_weight * gravity) / (geo["x_far"] - geo["x_near"])
    return radial + weight * gravity - far, far, -m_magnets / m_weight - 1.0


def temperature_factors(p):
    return {"20C": 1.0, "80C": p.hot80, "90C": p.hot90, "90C+irr": p.hot90 * p.n52_irrev}


# ---------------- cradle beam ----------------
def beam_sections(p):
    """(area, I about own centroid, centroid Z) of the lip and of the beam (bending in the X-Z plane)."""
    lip_w, beam_w = p.lip_y[1] - p.lip_y[0], p.beam_y[1] - p.beam_y[0]
    lip = (lip_w * p.lip_t, lip_w * p.lip_t ** 3 / 12, p.z0 + p.lip_t / 2)
    beam = (beam_w * p.beam_h, beam_w * p.beam_h ** 3 / 12, p.z0 - p.beam_h / 2)
    return lip, beam


def composite_inertia(p):
    """I glued full length (one section) and I with no connection (sum of both)."""
    lip, beam = beam_sections(p)
    zc = (lip[0] * lip[2] + beam[0] * beam[2]) / (lip[0] + beam[0])
    glued = sum(i + a * (z - zc) ** 2 for a, i, z in (lip, beam))
    return glued, lip[1] + beam[1]


def mesh(p):
    x = np.linspace(p.lip_x[0], p.lip_x[1], NODES)
    if p.pad_t > 0:
        half = max(max(abs(xr[0]), abs(xr[1])) for xr, _ in p.pad_zones)
    else:
        half = p.box_l / 2 - p.top_fillet                   # bare lip on the lid-top flat
    support = [i for i in range(NODES) if abs(x[i]) <= half]
    return x, x[1] - x[0], support


def node(x, h, position):
    return int(round((position - x[0]) / h))


def cradle_loads(model, mass, magnets, geo, factor, z_boss, shear):
    """Vertical force and moment per node (v3.1 'loads'); shear = magnetic down force per tab (N)."""
    p = model.params
    det = magnets["detent"]
    x, h, _ = mesh(p)
    g = p.g_newton_per_gram
    axial, radial = factor * det["axial_rest"], -factor * det["F"][0][2]
    near, far, _ = journal_forces(p, geo, axial, radial, z_boss)
    cradle_g, bar_g = mass["parts_g"]["cradle"], mass["parts_g"]["front_bar"]
    force, moment = np.zeros(NODES), np.zeros(NODES)
    force += -(0.5 * cradle_g + bar_g) * g / (x[-1] - x[0]) * h          # lip + front bar, uniform
    for block in (p.far_block_x, p.near_block_x):
        force[node(x, h, 0.5 * sum(block))] += -0.25 * cradle_g * g        # end blocks
    tab_magnets = sum(1 for name in model.hardware if name.startswith(("mag_tab+_", "mag_tabU+_")))   # per tab
    for side in (-1, 1):
        force[node(x, h, side * p.base_mag_x)] += -shear - tab_magnets * p.magnet_g * g
    force[node(x, h, geo["x_stator"])] += radial - p.magnet_g * g        # stator pulled up toward the knob magnet
    force[node(x, h, geo["x_near"])] += -near
    force[node(x, h, geo["x_far"])] += -far
    moment[node(x, h, geo["x_stator"])] += -axial * (geo["z_stator"] - z_boss)   # stator +X at z_stator, boss -X
    return force, moment


def bending_element(ei, h):
    return ei / h ** 3 * np.array([[12, 6 * h, -12, 6 * h], [6 * h, 4 * h * h, -6 * h, 2 * h * h],
                                   [-12, -6 * h, 12, -6 * h], [6 * h, 2 * h * h, -6 * h, 4 * h * h]])


def foundation_stiffness(size, w_dofs, active, h):
    """Pad springs on the deflection DOFs of the nodes in contact."""
    K = np.zeros((size, size))
    for i in active:
        K[w_dofs[i], w_dofs[i]] += PAD_FOUNDATION * h
    return K


def next_contact(w, support):
    """Nodes pressed onto the pads (compression only); keep at least the lowest one."""
    pressed = {i for i in support if w[i] < 0}
    return pressed or {support[int(np.argmin([w[i] for i in support]))]}


def solve_single(p, ei, force, moment):
    """v3.1 model: one Euler-Bernoulli beam (bending stiffness ei, one value or one per element) on the pads; returns
    w per node."""
    _, h, support = mesh(p)
    size = 2 * NODES
    ei_elements = np.broadcast_to(np.asarray(ei, float), (NODES - 1,))
    K = np.eye(size) * 1e-12
    for e in range(NODES - 1):
        idx = [2 * e, 2 * e + 1, 2 * e + 2, 2 * e + 3]
        K[np.ix_(idx, idx)] += bending_element(ei_elements[e], h)
    load = np.zeros(size)
    load[0::2], load[1::2] = force, moment
    w_dofs = list(range(0, size, 2))
    active = set(support)
    for _ in range(MAX_ITERATIONS):
        w = np.linalg.solve(K + foundation_stiffness(size, w_dofs, active, h), load)[0::2]
        contact = next_contact(w, support)
        if contact == active:
            return w
        active = contact
    raise RuntimeError("cradle contact iteration did not converge")


def solve_two_layer(p, E, force, moment, springs, glue=None):
    """Lip and beam with common deflection w and slope t, own axial displacements uL, uB (DOFs per node:
    w, t, uL, uB); interface slip s = uL - uB + r t. springs: [(node, K, clearance)], a spring carries
    K (|s| - clearance) once the play is taken up; glue: shear stiffness per mm of length (or None).
    Returns (w per node, slip per spring)."""
    _, h, support = mesh(p)
    (a_lip, i_lip, z_lip), (a_beam, i_beam, z_beam) = beam_sections(p)
    slip_row = np.array([z_lip - z_beam, 1.0, -1.0])           # on (t, uL, uB)
    size = 4 * NODES
    K = np.zeros((size, size))
    for e in range(NODES - 1):
        bend = [4 * e, 4 * e + 1, 4 * e + 4, 4 * e + 5]
        K[np.ix_(bend, bend)] += bending_element(E * (i_lip + i_beam), h)
        for offset, area in ((2, a_lip), (3, a_beam)):
            bar = [4 * e + offset, 4 * e + 4 + offset]
            K[np.ix_(bar, bar)] += E * area / h * np.array([[1, -1], [-1, 1]])
    middle = NODES // 2
    for offset, area in ((2, a_lip), (3, a_beam)):           # tiny axial ground: removes the free sliding mode
        K[4 * middle + offset, 4 * middle + offset] += 1e-9 * E * area / h

    def slip_dofs(i):
        return [4 * i + 1, 4 * i + 2, 4 * i + 3]

    if glue is not None:
        for i in range(NODES):
            K[np.ix_(slip_dofs(i), slip_dofs(i))] += glue * h * np.outer(slip_row, slip_row)
    load = np.zeros(size)
    load[0::4], load[1::4] = force, moment
    w_dofs = list(range(0, size, 4))
    active, bearing = set(support), tuple(1 for _ in springs)   # start: every dowel bearing, positive slip
    for _ in range(MAX_ITERATIONS):
        K_total = K + foundation_stiffness(size, w_dofs, active, h)
        f_total = load.copy()
        for (i, stiffness, clearance), sign in zip(springs, bearing):
            if sign != 0:
                K_total[np.ix_(slip_dofs(i), slip_dofs(i))] += stiffness * np.outer(slip_row, slip_row)
                f_total[slip_dofs(i)] += stiffness * sign * clearance * slip_row
        u = np.linalg.solve(K_total, f_total)
        w = u[0::4]
        slips = [float(slip_row @ u[slip_dofs(i)]) for i, _, _ in springs]
        new_bearing = tuple(0 if abs(s) <= c else int(np.sign(s)) for s, (_, _, c) in zip(slips, springs))
        contact = next_contact(w, support)
        if contact == active and new_bearing == bearing:
            return w, slips
        active, bearing = contact, new_bearing
    raise RuntimeError("two-layer cradle iteration did not converge")


def lift_off(p, w):
    _, _, support = mesh(p)
    return max(float(w[support].max()), 0.0), float(w[-1])


# ---------------- segmented-section cross-check ----------------
def section_inertia(faces):
    """Second moment (mm^4) of plane sections x = const about their common horizontal centroidal axis (composite)."""
    rows = []
    for face in faces:
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(face.wrapped, props)
        rows.append((props.Mass(), props.CentreOfMass().Z(), props.MatrixOfInertia().Value(2, 2)))
    area = sum(a for a, _, _ in rows)
    zc = sum(a * z for a, z, _ in rows) / area
    return sum(i + a * (z - zc) ** 2 for a, z, i in rows)


def segmented_inertia(model):
    """I per beam element: the uniform lip + beam section, except in the tab segments, where the CAD sections of the
    front bar (beam, tab, both pockets) and the lip are used."""
    p = model.params
    x, _, _ = mesh(p)
    solids = (solid_of(model.parts["front_bar"]), solid_of(model.parts["cradle"]))
    inertia = np.full(NODES - 1, composite_inertia(p)[0])
    for e in range(NODES - 1):
        middle = 0.5 * (x[e] + x[e + 1])
        if min(abs(middle - side * p.base_mag_x) for side in (-1, 1)) < p.tab_w / 2:
            inertia[e] = section_inertia([face for solid in solids
                                          for face in section_faces(solid, (middle, 0.0, 0.0), (1.0, 0.0, 0.0))])
    return inertia


# ---------------- run ----------------
def run(model, mass, magnets):
    p = model.params
    geo = loop_geometry(model, mass)
    det = magnets["detent"]
    tabs = magnets["mount"]
    shear = tabs["check10_shear_80C"]
    factors = temperature_factors(p)
    boss_heights = {"boss low edge": p.axis_z - p.boss_r, "boss centre": p.axis_z}
    journals = {}
    for temp, k in factors.items():
        for label, z_boss in boss_heights.items():
            near, far, flip = journal_forces(p, geo, k * det["axial_rest"], -k * det["F"][0][2], z_boss)
            journals[f"{temp}, {label}"] = dict(near_N=near, far_N=far, far_flips_at_g=flip)
    i_glued, i_spot = composite_inertia(p)
    glue = GLUE_G_SOFT * (p.beam_y[1] - p.beam_y[0]) / GLUE_T          # N/mm per mm of length
    lifts = {}
    for temp in TEMPERATURES:
        for label, z_boss in boss_heights.items():
            force, moment = cradle_loads(model, mass, magnets, geo, factors[temp], z_boss, shear)
            for E in E_VALUES:
                row = dict(glued=lift_off(p, solve_single(p, E * i_glued, force, moment))[0],
                           no_connection=lift_off(p, solve_single(p, E * i_spot, force, moment))[0])
                if temp != "20C":
                    row["soft glue"] = lift_off(p, solve_two_layer(p, E, force, moment, [], glue=glue)[0])[0]
                lifts[f"{temp}, {label}, E{E:.0f}"] = row
    spec_rows = [lifts[f"90C, {label}, E100"] for label in boss_heights]      # spec 4.3: 90 C, E 100

    def span(key):
        return tuple(row[key] for row in spec_rows)

    def hot_lifts(solve, tab_shear):
        """90 C, E 100, boss low edge / centre."""
        rows = []
        for z_boss in boss_heights.values():
            force, moment = cradle_loads(model, mass, magnets, geo, factors["90C"], z_boss, tab_shear)
            rows.append(lift_off(p, solve(force, moment))[0])
        return tuple(rows)

    def glued(force, moment):
        return solve_single(p, 100.0 * i_glued, force, moment)

    intact = span("glued")
    weakest = hot_lifts(glued, tabs["weakest_80C"]["down"])
    inertia = segmented_inertia(model)
    segmented = hot_lifts(lambda force, moment: solve_single(p, 100.0 * inertia, force, moment), shear)
    band_rows = [row for row in tabs["lid_band"].values() if row["shift"] != 0.0]
    band = {}
    for row in band_rows:
        band[f"lid Z {row['lid_z']:g}, min shear"] = hot_lifts(glued, row["full_set_min_down_80C"])
        band[f"lid Z {row['lid_z']:g}, weakest corner"] = hot_lifts(glued, row["weakest_80C"]["down"])
    # validation of the two-layer model against the single beam: no springs = no connection, very stiff glue = glued
    force, moment = cradle_loads(model, mass, magnets, geo, factors["90C"], p.axis_z, shear)
    reference = lifts["90C, boss centre, E100"]
    validation = dict(no_connection=(lift_off(p, solve_two_layer(p, 100.0, force, moment, [])[0])[0],
                                     reference["no_connection"]),
                      glued=(lift_off(p, solve_two_layer(p, 100.0, force, moment, [], glue=1e5)[0])[0],
                             reference["glued"]))
    full = tabs["full_set"]
    verdict = ("worse than the uniform section: report it (v3.3 2.1)" if max(segmented) > max(intact) + 1e-6
               else "not worse than the uniform section (the uniform model is conservative)")
    levels = {"glue intact, min shear (hard)": intact, "glue intact, weakest corner": weakest,
              f"soft glue G {GLUE_G_SOFT:g} MPa": span("soft glue"), "no connection": span("no_connection"),
              "segmented section, glue intact": segmented, **{f"glue intact, {key}": value for key, value in band.items()}}
    items = [
        item("far journal force 20 C, boss low edge / centre (N, up +)",
             (journals["20C, boss low edge"]["far_N"], journals["20C, boss centre"]["far_N"]), level="info"),
        item("vertical car acceleration that flips the far journal force, 20 C / 90 C+irr (boss low edge, g)",
             (journals["20C, boss low edge"]["far_flips_at_g"], journals["90C+irr, boss low edge"]["far_flips_at_g"]),
             level="info", note="spec 4.4 / 8: tightest far hole + grease against a 'tick'"),
        item("near-end lip lift 20 C, E 2000, epoxy rigid (mm)", lifts["20C, boss centre, E2000"]["glued"], level="info"),
        item("lip lift 90 C, E 100, glue intact (rigid), boss low edge / centre (mm)", intact,
             max(intact) < LIFT_LIMIT, "<= 0.20 by two decimals (< 0.205; v3.3 2.5)",
             note=f"tab shear {shear:.3f} N per tab: the smallest 80 C down force of the {full['n']} candidate boxes at "
                  f"lid Z {p.lid_mag_z:g} ({full['min_down']['case']})"),
        item("lip lift 90 C, E 100, glue intact, 80 C weakest-corner shear (mm)", weakest, level="info",
             note=f"tab shear {tabs['weakest_80C']['down']:.3f} N per tab"),
        item(f"lip lift 90 C, E 100, soft continuous glue G {GLUE_G_SOFT:g} MPa (mm)", span("soft glue"), level="info",
             note=f"glue line {GLUE_T:g} thick over the {p.beam_y[1] - p.beam_y[0]:g} wide beam top"),
        item("lip lift 90 C, E 100, no connection at all (mm)", span("no_connection"), level="info",
             note="also the debonded joint: no dowels since 10-18"),
        item("segmented-section cross-check, glue intact: tab segments with their real sections (mm)", segmented,
             level="info", note=f"uniform lip + beam section {intact[0]:.3f} / {intact[1]:.3f}: {verdict}"),
        item(f"lip lift 90 C, E 100, glue intact, lid magnet Z +-{LID_BAND:g}: full-set min shear / weakest corner (mm)",
             band, level="info",
             note="tab shear " + ", ".join(f"Z {row['lid_z']:g}: {row['full_set_min_down_80C']:.3f} / "
                                           f"{row['weakest_80C']['down']:.3f} N" for row in band_rows)),
        item("two-layer model vs single beam: no connection / glued (mm)",
             (validation["no_connection"], validation["glued"]), level="info"),
    ]
    numbers = dict(geometry=geo, journals=journals, I_glued=i_glued, I_no_connection=i_spot, lifts=lifts,
                   levels_90C_E100=levels, shear_80C_per_tab=shear, shear_case=full["min_down"]["case"],
                   segmented_I=dict(min=float(inertia.min()), max=float(inertia.max()),
                                    tab_elements=int(np.sum(inertia != i_glued))),
                   two_layer_validation=validation,
                   assumptions=dict(pad_foundation=PAD_FOUNDATION, glue_t=GLUE_T, glue_g_soft=GLUE_G_SOFT,
                                    shear="smallest 80 C down force of the full candidate set, at every temperature"))
    return section("10 detent couple loop: journals, far-force flip, lip lift (glue intact <= 0.20; soft / "
                   "unconnected as information)", items, numbers)
