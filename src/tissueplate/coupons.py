"""Plate-0 test coupons (design doc v3.2 section 3.2, tests 1-6), built in print orientation.

Geometry comes from the v3.1 reference script (concept/v3.1/verify_v3_1.py, imported as a module):
real cradle / knob / plugs / pin, and its parameters for the tab, panel section, holes and hex. The caps keep the
sizes plate 0 was printed with (PLATE0_CAPS: the v3.2 production sizes after the build review m4), so the plate stays
reproducible after v3.3 changed them; the stator spacer uses the package params (review M3), and two dowel-hole
strips test the press fit of 1.75 filament dowels (review INT-3 / m5).
Every coupon is returned centred on XY = 0 with its lowest point at Z = 0, ready to be placed on the bed.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import build123d as bd
import numpy as np

from tissueplate.bambu import PANEL_SETTINGS, PRODUCTION_SETTINGS, SLOT, SMALL_SETTINGS, STRUCT_SETTINGS
from tissueplate.params import make_params

PROJECT_DIR = Path(__file__).resolve().parents[2]
REFERENCE_SCRIPT = PROJECT_DIR / "concept/v3.1/verify_v3_1.py"
LOGO_GEOMETRY = PROJECT_DIR / "concept/v3/logo/final/geometry.json"
FONT = PROJECT_DIR / "fonts/MiSans-Bold.ttf"

# test parameters from the design doc (section 3.2)
TEARDROP_DIAMETERS = [round(5.85 + 0.05 * i, 2) for i in range(11)]     # 5.85 .. 6.35
BORE_DIAMETERS = [6.05, 6.10, 6.15, 6.20]
HEX_FLATS = [5.00, 5.05, 5.10]
DOWEL_HOLE_DIAMETERS = [1.70, 1.75, 1.80, 1.85, 1.90]   # 1.75 filament dowels; production holes were Ø1.9 (v3.2)
PLATE0_DOWEL_D = 1.9                                     # v3.2 production dowel hole when plate 0 was printed
PLATE0_CAPS = {"cap_tab": (8.1, 0.8), "cap_knob": (8.1, 0.4), "cap_hub": (6.2, 0.4)}   # Ø, thickness as printed
DOWEL_PITCH, DOWEL_MARGIN = 9.0, 5.0
WHITE_LAYERS = [3, 4, 5]
LAYER_HEIGHT = 0.2
LADDER_WIDTHS = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
PANEL_DIGITS = "48"                       # sample digits only (no phone number on plate 0)
TAB_COUPON_LENGTH = 40.0                  # beam segment length
TUBE_LENGTH = 30.0                        # glue rehearsal tube
SLICE_X = (70.0, 96.5)                    # near-block slice of the cradle (end block X 91..96)

LABEL_DEPTH = 0.5
STRING_HOLE_D = 2.2                       # test-fixture holes for strings (pull-off / slide-up measurement)
TUNNEL_OFFSET = 8.15                      # pull-off bridle tunnels above / below the magnet centre
PAD_GROOVE_W, PAD_GROOVE_DEPTH = 0.6, 0.3
LADDER_INLAY = 0.8                        # 4 white layers
LADDER_T = 1.6                            # 4 white + 4 navy layers
SLED_T = 1.6


@dataclass
class Coupon:
    name: str
    test: str                                   # plate-0 test number
    parts: list[tuple[str, object, int]]        # (part name, solid in print orientation, AMS slot)
    settings: dict[str, str] = field(default_factory=dict)


def load_reference():
    """Import the v3.1 reference script as a module (its import only defines parameters and functions)."""
    spec = importlib.util.spec_from_file_location("verify_v3_1", REFERENCE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    with contextlib.redirect_stdout(io.StringIO()):
        spec.loader.exec_module(module)
    return module


# ------------------------------------------------------------------ small geometry helpers
def box(x_range, y_range, z_range):
    return bd.Pos(x_range[0], y_range[0], z_range[0]) * bd.Box(
        x_range[1] - x_range[0], y_range[1] - y_range[0], z_range[1] - z_range[0], align=(bd.Align.MIN,) * 3)


def z_cylinder(radius, z0, z1, x=0.0, y=0.0):
    return bd.Pos(x, y, z0) * bd.Cylinder(radius, z1 - z0, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN))


def teardrop_outline(radius, top_ratio, n=72):
    """2D teardrop: circle with a 45-degree roof toward +v, roof cut flat at top_ratio * radius."""
    k = radius * (math.sqrt(2) - top_ratio)
    points = [(k, top_ratio * radius), (-k, top_ratio * radius)]
    for angle in np.linspace(135.0, 405.0, n, endpoint=False):
        points.append((radius * math.cos(math.radians(angle)), radius * math.sin(math.radians(angle))))
    return points


def prism_on_plane(points, plane, length):
    """Extrude a 2D outline drawn on `plane` along its normal."""
    return bd.extrude(plane * bd.Polygon(*points, align=None), length)


def to_print(solids, rotation=(0.0, 0.0, 0.0)):
    """Rotate solids together, then centre their common bounding box on XY = 0 with min Z = 0."""
    rotated = [bd.Rot(*rotation) * solid for solid in solids]
    boxes = [solid.bounding_box() for solid in rotated]
    x_mid = 0.5 * (min(b.min.X for b in boxes) + max(b.max.X for b in boxes))
    y_mid = 0.5 * (min(b.min.Y for b in boxes) + max(b.max.Y for b in boxes))
    z_min = min(b.min.Z for b in boxes)
    return [bd.Pos(-x_mid, -y_mid, -z_min) * solid for solid in rotated]


def text_sketch(text, size, align=(bd.Align.CENTER, bd.Align.CENTER)):
    return bd.Text(text, font_size=size, font_path=str(FONT), align=align)


def deboss(body, text, size, origin, x_dir, normal, depth=LABEL_DEPTH):
    """Cut text into the face through `origin` (outward `normal`); x_dir = reading direction seen from outside."""
    start = tuple(o + 0.01 * n for o, n in zip(origin, normal))
    plane = bd.Plane(origin=start, x_dir=x_dir, z_dir=normal)
    letters = bd.extrude(plane * text_sketch(text, size), amount=depth + 0.01, dir=tuple(-n for n in normal))
    return body - letters


def single(name, test, solid, rotation, settings):
    """One-part navy coupon, rotated into print orientation."""
    (placed,) = to_print([solid], rotation)
    return Coupon(name, test, [("navy", placed, SLOT["navy"])], dict(settings))


# ------------------------------------------------------------------ test 1: tabs + pad sled
def tab_coupon(ref, stack):
    """40 mm front-bar segment with one tab (real stack-derived thickness and pocket) under a lip segment
    that rests on the lid like the real cradle; string holes for the force tests; pad positions grooved."""
    tab_t = ref.MOUNT_FLOOR + 3.2 * stack + ref.CAP_T          # 8.0 (stack 2) / 4.8 (stack 1)
    y_front = -tab_t
    half = TAB_COUPON_LENGTH / 2
    lip_z = (ref.Z0, ref.Z0 + ref.LIP_T)
    lip = box((-half, half), (y_front, ref.LIP_Y[1]), lip_z)
    beam = box((-half, half), (y_front, ref.BEAM_Y[1]), ref.BEAM_Z)
    outline = ref.hull([ref.circle(0.0, ref.TAB_ZC, ref.TAB_W / 2),
                        np.array([(-ref.TAB_W / 2, ref.TAB_TOP), (ref.TAB_W / 2, ref.TAB_TOP)])])
    tab = ref.xz_prism(outline, y_front, 0.0)
    tab = bd.chamfer(tab.faces().sort_by(bd.Axis.Y)[-1].edges(), ref.TAB_LEADIN)      # back-face lead-in
    body, chamfered = ref.front_face_chamfer(lip + beam + tab)
    if not chamfered:
        raise RuntimeError("front-face chamfer failed on the tab coupon")
    body = body - ref.y_cyl(ref.MAG_POCKET_D / 2, y_front - 0.1, -ref.MOUNT_FLOOR, 0.0, ref.MOUNT_Z)

    # slide-up strings: two vertical holes through lip + beam beside the tab (knot under the beam)
    beam_mid_y = 0.5 * (y_front + ref.BEAM_Y[1])
    hole = teardrop_outline(STRING_HOLE_D / 2, ref.TEAR_TOP)                      # roof toward +Y (print up)
    for x in (-15.0, 15.0):
        plane = bd.Plane(origin=(x, beam_mid_y, ref.BEAM_Z[0] - 0.1), x_dir=(1, 0, 0), z_dir=(0, 0, 1))
        body = body - prism_on_plane(hole, plane, lip_z[1] - ref.BEAM_Z[0] + 0.2)
    # pull-off bridle: two tunnels along X through the tab, symmetric about the magnet centre
    for z in (ref.MOUNT_Z + TUNNEL_OFFSET, ref.MOUNT_Z - TUNNEL_OFFSET):
        plane = bd.Plane(origin=(-ref.TAB_W / 2 - 1.0, y_front / 2, z), x_dir=(0, 0, -1), z_dir=(1, 0, 0))
        body = body - prism_on_plane(hole, plane, ref.TAB_W + 2.0)
    # pad strip positions (real lip: Y 3.5-12.5 and 17-27) as shallow grooves on the lip underside
    for (_, (y0, y1)) in ref.PADS:
        for y in (y0, y1):
            body = body - box((-half - 1, half + 1), (y - PAD_GROOVE_W / 2, y + PAD_GROOVE_W / 2),
                              (lip_z[0] - 0.1, lip_z[0] + PAD_GROOVE_DEPTH))
    body = deboss(body, f"S{stack}", 7.0, (0.0, 20.0, lip_z[1]), (1, 0, 0), (0, 0, 1))
    return single(f"T{stack}_tab_stack{stack}", "1", body, (90, 0, 0), STRUCT_SETTINGS)    # front face down


def pad_sled(ref):
    """Lip-sized plate for the tilt test: strips go on the bed face at the real pad positions."""
    half = TAB_COUPON_LENGTH / 2
    depth = ref.LIP_Y[1] - ref.LIP_Y[0]                         # 36 = real lip depth
    body = box((-half, half), (0.0, depth), (0.0, SLED_T))
    for (_, (y0, y1)) in ref.PADS:
        for y in (y0, y1):
            yy = y - ref.LIP_Y[0]
            body = body - box((-half - 1, half + 1), (yy - PAD_GROOVE_W / 2, yy + PAD_GROOVE_W / 2), (-0.1, 0.2))
    body = deboss(body, "MU", 5.0, (-12.0, depth - 5.0, SLED_T), (1, 0, 0), (0, 0, 1), depth=0.4)
    return single("PAD_mu_sled", "1", body, (0, 0, 0), STRUCT_SETTINGS)


# ------------------------------------------------------------------ test 2: detent
def detent_coupons(ref, parts):
    near_slice = parts["cradle"] & box(SLICE_X, (-30.0, 40.0), (-5.0, 50.0))
    return [
        single("N_near_block_slice", "2", near_slice, (0, 0, 0), PRODUCTION_SETTINGS["struct"]),   # lip down, brim 5
        single("K_knob", "2", parts["knob"], (0, 90, 0), SMALL_SETTINGS),                     # outer face down
        single("EN_near_plug_detent", "2", parts["plug_near"], (0, -90, 0), SMALL_SETTINGS),   # thrust face up
    ]


def caps_and_spacer(p):
    """Caps for the tab pockets (2) and knob pockets (3), hub cap (PLATE0_CAPS), stator spacer (params p): one object,
    flat discs."""
    (tab_d, tab_t), (knob_d, knob_t), (hub_d, hub_t) = (PLATE0_CAPS[key] for key in ("cap_tab", "cap_knob", "cap_hub"))
    discs = [("cap_tab", tab_d / 2, tab_t)] * 2 + [("cap_knob", knob_d / 2, knob_t)] * 3 + [
        ("cap_hub", hub_d / 2, hub_t), ("spacer", p.spacer_d / 2, p.stator_spacer_t)]
    solids = []
    for index, (_, radius, thickness) in enumerate(discs):
        row, column = divmod(index, 4)
        solids.append(z_cylinder(radius, 0.0, thickness, column * 11.0, row * 11.0))
    merged = solids[0]
    for solid in solids[1:]:
        merged = merged + solid
    return single("D_caps_spacer", "1+2", merged, (0, 0, 0), SMALL_SETTINGS)


# ------------------------------------------------------------------ test 3: holes, bores, hex
def teardrop_strip(ref):
    """Horizontal teardrop holes 5.85-6.35 through a 5 mm wall (= end block thickness), as printed in the cradle."""
    thickness = ref.FAR_B[1] - ref.FAR_B[0]
    pitch, margin, height, hole_z = 9.5, 5.5, 15.0, 6.2
    length = 2 * margin + pitch * (len(TEARDROP_DIAMETERS) - 1)
    body = box((0.0, length), (-thickness / 2, thickness / 2), (0.0, height))
    body = body + box((0.0, length), (thickness / 2, thickness / 2 + 6.0), (0.0, 1.6))      # foot on the back only
    for index, diameter in enumerate(TEARDROP_DIAMETERS):
        x = margin + index * pitch
        # x_dir -X so that the outline's +v (roof) maps to +Z: the roof points up in the print
        plane = bd.Plane(origin=(x, -thickness / 2 - 0.1, hole_z), x_dir=(-1, 0, 0), z_dir=(0, 1, 0))
        body = body - prism_on_plane(teardrop_outline(diameter / 2, ref.TEAR_TOP), plane, thickness + 0.2)
        body = deboss(body, f"{diameter * 100:.0f}", 3.6, (x, -thickness / 2, 12.0), (1, 0, 0), (0, -1, 0))
    return single("H_teardrop_strip", "3", body, (0, 0, 0), STRUCT_SETTINGS)


def bore_strip(ref):
    """Vertical blind bores 6.05-6.20, depth = far plug bore, open at the top like the far plug print."""
    pitch, margin, half_width = 10.0, 6.0, 6.0
    height, depth = ref.PLUG_LEN_FAR, ref.FAR_BORE_DEPTH
    length = 2 * margin + pitch * (len(BORE_DIAMETERS) - 1)
    body = box((0.0, length), (-half_width, half_width), (0.0, height))
    for index, diameter in enumerate(BORE_DIAMETERS):
        x = margin + index * pitch
        body = body - z_cylinder(diameter / 2, height - depth, height + 0.1, x, 0.0)
        body = deboss(body, f"{diameter * 100:.0f}", 3.6, (x, -half_width, 4.2), (1, 0, 0), (0, -1, 0))
    return single("V_bore_strip", "3", body, (0, 0, 0), STRUCT_SETTINGS)


def keyed_hex_z(ref, across_flats, z0, z1, x, y):
    """Knob hex along Z with one corner (+Y) flattened, as ref.keyed_hex does along X."""
    corner_r = across_flats / math.sqrt(3)
    points = [(x + corner_r * math.cos(math.radians(30 + 60 * k)), y + corner_r * math.sin(math.radians(30 + 60 * k)))
              for k in range(6)]
    plane = bd.Plane(origin=(0, 0, z0), x_dir=(1, 0, 0), z_dir=(0, 0, 1))
    hexagon = prism_on_plane(points, plane, z1 - z0)
    key_cut = box((x - 5, x + 5), (y + ref.HEX_KEY * corner_r, y + 5), (z0 - 1, z1 + 1))
    return hexagon - key_cut


def hex_peg(ref, across_flats):
    """Knob journal + keyed hex (+ screw bore) on a labelled foot; printed upright like the knob."""
    journal_len = ref.NEAR_B[1] - ref.NEAR_B[0]              # 5
    hex_len = ref.NEAR_B[0] - ref.KNOB_HEX_END               # 9.2
    x_axis = 6.0
    foot_t = 2.0
    body = box((0.0, 20.0), (-6.0, 6.0), (0.0, foot_t))
    body = body + z_cylinder(ref.PIN_D / 2, foot_t - 0.01, foot_t + journal_len, x_axis, 0.0)
    body = body + keyed_hex_z(ref, across_flats, foot_t + journal_len - 0.01, foot_t + journal_len + hex_len, x_axis, 0.0)
    body = body - z_cylinder(ref.SCREW_BORE / 2, -0.1, foot_t + journal_len + hex_len + 0.1, x_axis, 0.0)
    body = deboss(body, f"{across_flats * 100:.0f}", 4.0, (14.6, 0.0, foot_t), (1, 0, 0), (0, 0, 1), depth=0.4)
    return single(f"X_hex_AF{across_flats * 100:.0f}", "3", body, (0, 0, 0), SMALL_SETTINGS)


def pin_coupons(parts, count=2):
    """Far pins upright, outer end down, with the production 3 mm brim (review INT-6)."""
    return [single(f"P_far_pin_{i + 1}", "3", parts["far_pin"], (0, -90, 0), PRODUCTION_SETTINGS["pin"])
            for i in range(count)]


def dowel_hole_positions():
    return [DOWEL_MARGIN + DOWEL_PITCH * i for i in range(len(DOWEL_HOLE_DIAMETERS))]


def dowel_holes_beam(ref):
    """Front-bar segment (real beam section) with the dowel holes as in F: 3 mm deep from the beam top, teardrop
    roof toward +Y; printed front face down like F, so the holes are horizontal. Labels (x100) on the back face."""
    length = 2 * DOWEL_MARGIN + DOWEL_PITCH * (len(DOWEL_HOLE_DIAMETERS) - 1)
    y_front, y_back = ref.TAB_Y[0], ref.BEAM_Y[1]
    body = box((0.0, length), (y_front, y_back), ref.BEAM_Z)
    hole_y = 0.5 * (y_front + y_back)
    top = ref.BEAM_Z[1]
    for x, diameter in zip(dowel_hole_positions(), DOWEL_HOLE_DIAMETERS):
        plane = bd.Plane(origin=(x, hole_y, top - 3.0), x_dir=(1, 0, 0), z_dir=(0, 0, 1))   # local +v = world +Y
        body = body - prism_on_plane(teardrop_outline(diameter / 2, ref.TEAR_TOP), plane, 3.0 + 0.1)
        # x_dir +X: upright in the top view of the print (back face up)
        body = deboss(body, f"{diameter * 100:.0f}", 3.2, (x, y_back, top - 6.5), (1, 0, 0), (0, 1, 0), depth=0.4)
    return single("JB_dowel_holes_beam", "3", body, (90, 0, 0), STRUCT_SETTINGS)


def dowel_holes_lip(ref):
    """Lip segment (2.0 thick) with blind round dowel holes 1.4 deep from the underside, as in C; printed lip down."""
    length = 2 * DOWEL_MARGIN + DOWEL_PITCH * (len(DOWEL_HOLE_DIAMETERS) - 1)
    body = box((0.0, length), (0.0, 12.0), (0.0, ref.LIP_T))
    for x, diameter in zip(dowel_hole_positions(), DOWEL_HOLE_DIAMETERS):
        body = body - z_cylinder(diameter / 2, -0.1, 1.4, x, 4.0)
        body = deboss(body, f"{diameter * 100:.0f}", 3.2, (x, 9.0, ref.LIP_T), (1, 0, 0), (0, 0, 1), depth=0.4)
    return single("JL_dowel_holes_lip", "3", body, (0, 0, 0), STRUCT_SETTINGS)


# ------------------------------------------------------------------ test 4: white layers + logo ladder
def panel_section(ref):
    """Panel cross-section (across the face, up from the face): flat, half chamfer land at 60 deg, 30 deg mitres."""
    half_flat = ref.FACE_FLAT / 2
    land = ref.CHAMFER / 2
    y_land, z_land = half_flat + land * math.cos(math.radians(60)), land * math.sin(math.radians(60))
    y_top = ref.S_SIDE / 2 - ref.T_PANEL / math.tan(math.radians(30))
    return [(-half_flat, 0.0), (half_flat, 0.0), (y_land, z_land), (y_top, ref.T_PANEL), (-y_top, ref.T_PANEL),
            (-y_land, z_land)]


def panel_prism(ref, length):
    """Panel segment in print orientation: X along the rotor, face on the bed (Z = 0)."""
    return ref.yz_prism(panel_section(ref), -length / 2, length / 2)


def face_plane(z=0.0):
    """Plane on the bed face that reads correctly for a viewer outside the face (under the bed)."""
    return bd.Plane(origin=(0, 0, z), x_dir=(-1, 0, 0), z_dir=(0, 0, -1))


def digit_sketch(ref, typo, text):
    """Proportional layout (ink gap = INK_GAP) of a short digit string, ink band centred on the face."""
    em, bounds = typo["em"], typo["bounds"]
    widths = [(bounds[ch][2] - bounds[ch][0]) * em * ref.DIGIT_COND for ch in text]
    total = sum(widths) + ref.INK_GAP * (len(text) - 1)
    baseline = -typo["h_band"] / 2 - typo["ymin"] * em
    u = -total / 2
    glyphs = None
    for ch, width in zip(text, widths):
        glyph = bd.Text(ch, font_size=em, font_path=str(FONT), align=(bd.Align.NONE, bd.Align.NONE))
        glyph = bd.scale(glyph, by=(ref.DIGIT_COND, 1, 1))
        bb = glyph.bounding_box()
        base_local = bb.min.Y - bounds[ch][1] * em
        glyph = bd.Pos(u + width / 2 - (bb.min.X + bb.max.X) / 2, baseline - base_local) * glyph
        glyphs = glyph if glyphs is None else glyphs + glyph
        u += width + ref.INK_GAP
    return glyphs


def panel_segments(ref, typo):
    length = 36.0
    sketch = digit_sketch(ref, typo, PANEL_DIGITS)
    coupons = []
    for layers in WHITE_LAYERS:
        depth = layers * LAYER_HEIGHT
        panel = panel_prism(ref, length)
        white = bd.extrude(face_plane() * sketch, amount=depth, dir=(0, 0, 1)) & panel
        navy = panel - white
        navy = deboss(navy, f"{layers}L", 5.0, (12.0, 0.0, ref.T_PANEL), (1, 0, 0), (0, 0, 1), depth=0.4)
        coupons.append(Coupon(f"W{layers}_panel_white_{layers}_layers", "4",
                              [("navy", navy, SLOT["navy"]), ("white", white, SLOT["white"])], dict(PANEL_SETTINGS)))
    return coupons


def ring_area(points):
    x, y = np.asarray(points).T
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def final_logo_text_sketch(offset_u, offset_v):
    """The final 'YU7 PRO' (white rings of geometry.json inside its text box), moved by (offset_u, offset_v)."""
    geometry = json.loads(LOGO_GEOMETRY.read_text(encoding="utf-8"))
    rings = [np.asarray(ring) for ring in geometry["white"]]
    text_rings = [r for r in rings if r[:, 0].min() > 74.0 and r[:, 0].max() < 119.0 and r[:, 1].max() < 11.0]
    u_min = min(r[:, 0].min() for r in text_rings)
    outers, holes = None, None
    for ring in text_rings:
        if np.allclose(ring[0], ring[-1]):
            ring = ring[:-1]
        points = [(u - u_min + offset_u, v + offset_v) for u, v in ring]
        face = bd.Polygon(*points, align=None)
        if ring_area(ring) > 0:
            outers = face if outers is None else outers + face
        else:
            holes = face if holes is None else holes + face
    return outers - holes if holes is not None else outers


def logo_ladder():
    """Navy plate with white features (one object, two parts). Face view: missing corner at top-left,
    every row runs 0.5 -> 1.0 mm from left to right."""
    width, height = 80.0, 38.0
    features = []
    for i, w in enumerate(LADDER_WIDTHS):                                   # row 1 left: white lines
        u = 6.0 + 4.0 * i
        features.append(bd.Pos(u, 31.5) * bd.Rot(0, 0, 90) * bd.SlotCenterToCenter(6.0, w))
    for i, gap in enumerate(LADDER_WIDTHS):                                 # row 1 right: navy gaps
        u0 = 33.0 + 6.0 * i
        features.append(bd.Pos(u0 + 0.6, 31.5) * bd.Rectangle(1.2, 7.0))
        features.append(bd.Pos(u0 + 1.2 + gap + 0.6, 31.5) * bd.Rectangle(1.2, 7.0))
    for i, diameter in enumerate(LADDER_WIDTHS):                            # row 2 left: navy holes
        u = 6.0 + 5.5 * i
        features.append(bd.Pos(u, 21.0) * bd.Rectangle(4.0, 4.0) - bd.Pos(u, 21.0) * bd.Circle(diameter / 2))
    features.append(bd.Pos(40.0, 17.6) * text_sketch("YU7 PRO", 8.0, (bd.Align.MIN, bd.Align.MIN)))   # hard limit
    features.append(final_logo_text_sketch(4.0, 0.0))                       # row 3: final logo text, real size
    sketch = features[0]
    for feature in features[1:]:
        sketch = sketch + feature
    sketch = bd.Pos(-width / 2, -height / 2) * sketch                       # face-view coordinates centred
    plate = box((-width / 2, width / 2), (-height / 2, height / 2), (0.0, LADDER_T))
    # orientation mark: corner cut at face-view top-left = print +X / +Y corner (the face view mirrors X)
    corner = bd.Pos(width / 2, height / 2, 0) * bd.Rot(0, 0, 45) * bd.Box(7.0, 7.0, 10.0)
    plate = plate - corner
    white = bd.extrude(face_plane() * sketch, amount=LADDER_INLAY, dir=(0, 0, 1)) & plate
    navy = plate - white
    return Coupon("L_logo_ladder", "4", [("navy", navy, SLOT["navy"]), ("white", white, SLOT["white"])],
                  dict(PANEL_SETTINGS))


# ------------------------------------------------------------------ test 5: glue rehearsal tube
def tube_panel(ref, letter):
    """30 mm panel (real section) labelled on the inner face; the triangle points to the digit-top edge."""
    panel = panel_prism(ref, TUBE_LENGTH)
    panel = deboss(panel, letter, 6.0, (-5.0, -1.5, ref.T_PANEL), (1, 0, 0), (0, 0, 1), depth=0.4)
    # this plane maps local -v to world +Y, so the apex (0, -4) points to +Y = digit-top edge
    arrow_plane = bd.Plane(origin=(5.0, 3.0, ref.T_PANEL + 0.01), x_dir=(1, 0, 0), z_dir=(0, 0, -1))
    panel = panel - prism_on_plane([(-2.5, 0.0), (0.0, -4.0), (2.5, 0.0)], arrow_plane, 0.41)
    return single(f"G{letter}_tube_panel_{letter}", "5", panel, (0, 0, 0), PANEL_SETTINGS)


def tube_coupons(ref, parts):
    coupons = [tube_panel(ref, letter) for letter in ("A", "B", "L")]
    coupons.append(single("GN_near_plug_tube", "5", parts["plug_near"], (0, -90, 0), SMALL_SETTINGS))
    coupons.append(single("GF_far_plug_tube", "5", parts["plug_far"], (0, 90, 0), SMALL_SETTINGS))
    return coupons


# ------------------------------------------------------------------ all coupons
def build_plate0_coupons():
    """All plate-0 coupons in print orientation. Returns (coupons, reference module)."""
    ref = load_reference()
    with contextlib.redirect_stdout(io.StringIO()):
        parts, _ = ref.build_parts()
        typo = ref.check_typography(ref.FACE_FLAT)
    coupons = [tab_coupon(ref, 2), tab_coupon(ref, 1), pad_sled(ref)]
    coupons += detent_coupons(ref, parts)
    coupons.append(caps_and_spacer(make_params()))
    coupons += [teardrop_strip(ref), bore_strip(ref)] + [hex_peg(ref, af) for af in HEX_FLATS] + pin_coupons(parts)
    coupons += [dowel_holes_beam(ref), dowel_holes_lip(ref)]
    coupons += panel_segments(ref, typo) + [logo_ladder()]
    coupons += tube_coupons(ref, parts)
    return coupons, ref
