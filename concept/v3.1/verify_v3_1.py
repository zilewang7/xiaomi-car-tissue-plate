#!/usr/bin/env python3
"""YU7 tissue-box rotating parking-number plate - v3.1 (v3 + review fixes): numerical verification.

Re-run (from the project dir, venv with build123d / fontTools / numpy / scipy / trimesh / matplotlib):
    cd <project dir>
    .venv/bin/python -I concept/v3.1/verify_v3_1.py            # all checks (~2-4 min)
    .venv/bin/python -I concept/v3.1/verify_v3_1.py --render   # + pyvista renders
Outputs: console report, concept/v3.1/out/report.json, STL files in concept/v3.1/out/stl/.
Slicing check (Bambu Studio CLI, print-oriented STLs of the changed parts): concept/v3.1/run_slice.py.

v3.1 changes (2026-10-13 review): floor-backed detent pockets (knob 2x N52 per lobe, gap 2.2),
blind hex socket + M3 axis screw (rotor axial chain), stationary far pin (rotor bore runs on it),
teardrop horizontal holes, silicone pads under the lip (3D LP), beam Z -10, tab lead-in,
tab geometry derived from the magnet stack, dowel holes, knob tactile ribs, lift-off = lam/W,
heat check = rotor-equilibrium loop model.

Coordinates (same as the brief): X along the box, +X = driver side; Y from windshield to cabin,
box front face at Y = 0; Z up, lid top at Z = 0. Rotation angle theta is about +X (right-hand),
i.e. counter-clockwise when looking from the driver side, with +Y to the right and +Z up.
No phone numbers are used here: layout checks use worst-case glyphs, renders use the brief's
example number only.
"""
import json
import math
import os
import sys
import time

import numpy as np

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
FONT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "fonts", "MiSans-Bold.ttf"))
os.makedirs(os.path.join(OUT, "stl"), exist_ok=True)
REPORT = {}
S3 = math.sqrt(3.0)

# =====================================================================================
# 0. Parameters (mm, N, g). Values marked "est." are estimates, not measurements.
# =====================================================================================
# box (user measurements 2026-10-13 + brief)
BOX_L, BOX_D, BOX_H = 172.5, 107.35, 77.5
BOX_CORNER_R = 18.0          # plan-view outer corner radius (est. +-1.5)
LID_TOP_FILLET = 2.5         # lid top-edge fillet (est. 2-3)
PARTING_Z = -13.62           # lid / base parting line (measured 2026-10-13, photo 095859)
BASE_MAG_X, BASE_MAG_Z = 86.25 - 47.04, -21.07   # front base magnet points (measured)
TONGUE_Y = -38.36            # leather tongue nose at ~lid-top height (measured)
RULE_Y = -35.0               # hard rule: all parts at Y >= -35

# silicone anti-slip strips under the lip (v3.1, MLH-1 / VU-1): the plate rides 0.5 mm higher on them
PAD_T = 0.5                  # strip thickness
MU_PAD = 0.8                 # silicone on PU leather (est.; plate-0 tilt test, pass >= 0.6)
PADS = (((-72.0, 72.0), (3.5, 12.5)), ((-82.0, 82.0), (17.0, 27.0)))   # (X, Y) ranges inside the lid-top flat
Z0 = PAD_T                   # lip underside Z

# rotor (mitred tube of 3 panels + 2 triangular end plugs)
S_SIDE = 30.0                # sharp equilateral side
CHAMFER = 1.2                # vertex land: chamfer leg along each face
T_PANEL = 2.4
ROT_X = (-90.5, 90.5)        # tube length 181.0
PLUG_LEN_NEAR, PLUG_LEN_FAR, PLUG_CLR = 16.0, 10.0, 0.2   # near plug carries the blind hex socket + screw pilot
LIP_T = 2.0                  # cradle lip plate thickness
RAD_CLR = 1.2                # target radial clearance rotor sweep -> lip top
YA = 12.0                    # rotor axis Y

# derived section numbers
R_IN = S_SIDE / (2 * S3)                       # inradius (face plane distance)
R_C = S_SIDE / S3                              # sharp circumradius
R_SW = math.hypot(R_IN, S_SIDE / 2 - CHAMFER)  # true sweep radius = chamfer corner
FACE_FLAT = S_SIDE - 2 * CHAMFER
ZA = round(Z0 + LIP_T + RAD_CLR + R_SW, 1)     # rotor axis Z (20.0 on the pads)

# end blocks, knob, pins
FAR_B, NEAR_B = (-96.0, -91.0), (91.0, 96.0)
BOSS_H, BOSS_R = 0.6, 4.6    # thrust boss on the knob inner face (0.6: two 0.8 floors may creep 0.12 each)
INNER_RING_H = 0.3           # thrust ring on the near block inner face (rotor near gap 0.5 -> 0.2)
DET_FLOOR = 0.8              # printed floor between each detent magnet and the gap: attraction presses magnets onto it
KNOB_STACK = 2               # N52 8x3 per knob lobe (floor-backed pocket opens at the knob outer face)
KNOB_CAP_T = 0.6             # azure cap closing each knob pocket
KNOB_T = DET_FLOOR + 3.0 * KNOB_STACK + KNOB_CAP_T          # 7.4
KNOB_X = (NEAR_B[1] + BOSS_H, NEAR_B[1] + BOSS_H + KNOB_T)   # 96.6 .. 104.0
KNOB_MAG_R, KNOB_LOBE_R = 11.0, 5.6
KNOB_PHI = (30.0, 150.0, 270.0)                # lobes = the "nabla" corners at rest
STATOR_R, STATOR_PHI = 11.5, 270.0             # 0.5 mm outward offset -> radial preload
STATOR_SPACER_T = (NEAR_B[1] - NEAR_B[0]) - DET_FLOOR - 3.0  # 1.2: printed spacer behind the stator (pocket opens inward)
DETENT_GAP = DET_FLOOR + BOSS_H + DET_FLOOR    # magnet face gap 2.2
HOLE_NEAR, HOLE_FAR, PIN_D = 6.3, 6.0, 6.0     # horizontal teardrops; near = running, far = press fit (pin stationary)
FAR_BORE, FAR_BORE_DEPTH = 6.1, 8.5            # far plug bore (vertical print, round) runs on the stationary pin
TEAR_TOP = 1.15                                # teardrop roof truncated flat at 1.15 r
HEX_AF, HEX_SOCKET_AF = 5.0, 5.15
HEX_KEY = 0.86                                 # key flat at 0.86 x corner radius (keeps 0.8 mm around the screw bore)
FAR_PIN_X = (FAR_B[0], -83.0)
KNOB_HEX_END = 81.8                            # hex tip = blind socket bottom -> sets the near gap
SCREW_BORE, SCREW_PILOT, PILOT_DEPTH = 3.3, 2.5, 6.5   # M3x25 self-tapper on the axis, knob -> near plug
SCREW_HEAD_D, SCREW_HEAD_DEPTH, HUB_CAP_T = 6.4, 3.0, 0.6

# cradle lip and front bar
MOUNT_STACK = 2                                # N52 8x3 per tab; 1 only if < 8 mm free in front of the tabs or pull > 6 N/point
MAG_POCKET_D, MOUNT_FLOOR, CAP_T = 8.3, 0.8, 0.8
TAB_T = MOUNT_FLOOR + 3.2 * MOUNT_STACK + CAP_T   # 4.8 (stack 1) / 8.0 (stack 2)
TAB_Y = (-TAB_T, 0.0)
LIP_X, LIP_Y = (FAR_B[0], NEAR_B[1]), (TAB_Y[0], 28.0)
BEAM_H = 10.0                                  # v3: 6; deeper beam stiffens the cradle loop (MLH-4), still above the parting line
BEAM_X, BEAM_Y, BEAM_Z = (FAR_B[0], NEAR_B[1]), (TAB_Y[0], -0.4), (Z0 - BEAM_H, Z0)   # front face flush with the tabs
TAB_W, TAB_BOTTOM = 20.0, -40.0                # U-shaped tab; bottom is a config value (clearance unmeasured)
TAB_ZC, TAB_TOP = TAB_BOTTOM + TAB_W / 2, Z0 - 3.0
TAB_LEADIN = 1.5                               # 45 deg lead-in chamfer around the tab back face
MOUNT_DELTA = 1.75                             # our magnet centre ABOVE the base point
MOUNT_Z = BASE_MAG_Z + MOUNT_DELTA             # world Z: the pads raise the plate, the pockets move down with it
MOUNT_Y = -(MOUNT_FLOOR + 1.5 * MOUNT_STACK)   # magnet stack centre
DOWEL_D, DOWEL_X = 1.9, (-93.5, 0.0, 93.5)     # 1.75 filament dowels: front bar -> lip
DOWEL_Y = 0.5 * (BEAM_Y[0] + BEAM_Y[1])

# materials
RHO_ABS = 1.05e-3            # g/mm^3
MAGNET_G = 1.13              # N52 8x3
G = 9.81e-3                  # N per g
MU_ABS, MU_PTFE = 0.35, 0.15
MU_PU = (0.35, 0.5)          # ABS on PU leather (est.)
HOT = 0.861                  # reversible Br loss of both magnets at 80 C (0.928^2)
HOT90 = 0.839                # reversible at 90 C (0.916^2)
N52_IRREV = 0.85             # extra pessimistic factor for irreversible loss at 80-90 C (est.)
TAB_IRREV = {1: (0.90, 0.85), 2: (0.98, 0.98)}   # tab magnets, irreversible factor at 80 / 90 C by stack (demag screen)


def section(title):
    print("\n" + "=" * 88 + f"\n{title}\n" + "=" * 88)


def rec(key, value):
    REPORT[key] = value
    return value


# =====================================================================================
# 1. Section geometry (analytic)
# =====================================================================================
def tri_vertices(r_in, yc=YA, zc=ZA, rot=0.0):
    R = 2 * r_in
    return [np.array([yc + R * math.cos(math.radians(a + rot)), zc + R * math.sin(math.radians(a + rot))])
            for a in (90.0, 210.0, 330.0)]


def tri_pts(r_in, chamfer, yc=YA, zc=ZA, rot=0.0):
    """Chamfered equilateral triangle in (Y, Z); bottom face horizontal at rot = 0."""
    V = tri_vertices(r_in, yc, zc, rot)
    if chamfer <= 0:
        return [tuple(v) for v in V]
    pts = []
    for i in range(3):
        v, vp, vn = V[i], V[i - 1], V[(i + 1) % 3]
        pts.append(tuple(v + (vp - v) / np.linalg.norm(vp - v) * chamfer))
        pts.append(tuple(v + (vn - v) / np.linalg.norm(vn - v) * chamfer))
    return pts


def check_section():
    section("1. Prism section, axis, envelope (analytic)")
    fb = np.array([YA - S_SIDE / 2, ZA - R_IN])          # front-bottom sharp vertex
    up = np.array([0.5, S3 / 2])                          # along the display face, upward
    normal_deg = 150.0                                    # display face normal (Y, Z) angle
    rec("section", dict(side=S_SIDE, chamfer=CHAMFER, face_flat=FACE_FLAT, r_in=R_IN, r_c=R_C,
                        r_sweep=R_SW, panel_t=T_PANEL, inner_side=S_SIDE - 2 * S3 * T_PANEL,
                        axis_y=YA, axis_z=ZA, clearance_sweep_to_lip=ZA - R_SW - LIP_T))
    print(f"side {S_SIDE}, chamfer leg {CHAMFER} -> face flat {FACE_FLAT:.2f}; r_in {R_IN:.3f}, sharp R {R_C:.3f}, "
          f"true sweep R (chamfer corner) {R_SW:.3f}")
    print(f"axis (Y {YA}, Z {ZA}); sweep circle Y {YA - R_SW:.2f}..{YA + R_SW:.2f}, Z {ZA - R_SW:.2f}..{ZA + R_SW:.2f}; "
          f"radial clearance to lip top {ZA - R_SW - LIP_T:.3f}")
    print(f"rest: bottom face horizontal at Z {ZA - R_IN:.2f}; display normal {90 - (normal_deg - 90):.0f} deg above "
          f"horizontal, facing the windshield; front-bottom sharp vertex at Y {fb[0]:.2f}, Z {fb[1]:.2f}")
    return fb, up


# =====================================================================================
# 2. Typography: MiSans Bold metrics, layout, stroke printability
# =====================================================================================
from fontTools.ttLib import TTFont
from fontTools.pens.basePen import BasePen
from fontTools.pens.boundsPen import BoundsPen

DIGIT_COND, CELL_GAP, GROUP_GAP = 0.86, 1.8, 3.5
END_MARGIN_NEAR = 2.0          # min cell-box margin to the rotor end at the knob end
LAYOUT_SHIFT = -1.0            # cell box shifted toward -X (first digit is always a narrow '1')


class FlattenPen(BasePen):
    """Flatten glyph outlines into closed polylines (font units)."""

    def __init__(self, glyphset, steps=12):
        super().__init__(glyphset)
        self.contours, self.cur, self.steps = [], [], steps

    def _moveTo(self, p):
        self.cur = [p]

    def _lineTo(self, p):
        self.cur.append(p)

    def _curveToOne(self, p1, p2, p3):
        p0 = self.cur[-1]
        for t in np.linspace(0, 1, self.steps + 1)[1:]:
            u = 1 - t
            self.cur.append(tuple(u ** 3 * np.array(p0) + 3 * u * u * t * np.array(p1) + 3 * u * t * t * np.array(p2) + t ** 3 * np.array(p3)))

    def _qCurveToOne(self, p1, p2):
        p0 = self.cur[-1]
        for t in np.linspace(0, 1, self.steps + 1)[1:]:
            u = 1 - t
            self.cur.append(tuple(u * u * np.array(p0) + 2 * u * t * np.array(p1) + t * t * np.array(p2)))

    def _closePath(self):
        if self.cur:
            self.contours.append(np.array(self.cur, float))
        self.cur = []

    _endPath = _closePath


def check_typography(face_flat):
    section("2. Typography (MiSans Bold, fontTools)")
    f = TTFont(FONT)
    upm = f["head"].unitsPerEm
    gs, cmap = f.getGlyphSet(), f.getBestCmap()
    bounds, outlines = {}, {}
    for d in "0123456789":
        g = cmap[ord(d)]
        bp = BoundsPen(gs)
        gs[g].draw(bp)
        bounds[d] = [v / upm for v in bp.bounds]
        fp = FlattenPen(gs)
        gs[g].draw(fp)
        outlines[d] = [c / upm for c in fp.contours]
    wmax = max(b[2] - b[0] for b in bounds.values())
    widest = max(bounds, key=lambda k: bounds[k][2] - bounds[k][0])
    flat = bounds["1"][3] - bounds["1"][1]
    ymin = min(b[1] for b in bounds.values())
    ymax = max(b[3] for b in bounds.values())
    band = ymax - ymin
    rot_len = ROT_X[1] - ROT_X[0]
    # largest em with the worst-case cell box inside the rotor face with END_MARGIN_NEAR at the knob end
    # layout length L = 11*w + 10*gap + 2*group, centred at LAYOUT_SHIFT; right end <= ROT_X[1] - margin
    L_max = 2 * (ROT_X[1] - END_MARGIN_NEAR - LAYOUT_SHIFT)
    em_len = (L_max - 10 * CELL_GAP - 2 * GROUP_GAP) / (11 * wmax * DIGIT_COND)
    em_face = (face_flat - 2 * 3.0) / band              # >= 3.0 mm top/bottom margin
    em = math.floor(min(em_len, em_face) * 100) / 100
    glyph_w = wmax * em * DIGIT_COND
    L = 11 * glyph_w + 10 * CELL_GAP + 2 * GROUP_GAP
    x0 = LAYOUT_SHIFT - L / 2
    cells = []
    x = x0
    for i in range(11):
        cells.append((x, x + glyph_w))
        x += glyph_w + CELL_GAP + (GROUP_GAP if i in (2, 6) else 0.0)
    h_flat, h_band = flat * em, band * em
    vmargin = (face_flat - h_band) / 2
    # ink extents: first digit '1', last digit worst case = widest
    one_w = (bounds["1"][2] - bounds["1"][0]) * em * DIGIT_COND
    ink_left = cells[0][0] + (glyph_w - one_w) / 2
    ink_right_worst = cells[-1][1]
    print(f"metrics: flat '1' {flat:.3f} em, ink band {ymin:+.3f}..{ymax:.3f} = {band:.3f} em, widest '{widest}' {wmax:.3f} em")
    print(f"em {em:.2f} mm (length limit {em_len:.2f}, face limit {em_face:.2f}), condense {DIGIT_COND}")
    print(f"digit height: flat {h_flat:.2f} mm, max (round) {h_band:.2f} mm; glyph cell {glyph_w:.2f} + gap {CELL_GAP}, "
          f"groups 3-4-4 +{GROUP_GAP}")
    print(f"cell box X {cells[0][0]:.2f}..{cells[-1][1]:.2f} (L {L:.1f}) on rotor {ROT_X[0]}..{ROT_X[1]}; margins: far end "
          f"{cells[0][0] - ROT_X[0]:.2f} (ink of '1' {ink_left - ROT_X[0]:.2f}), knob end {ROT_X[1] - cells[-1][1]:.2f}")
    print(f"face margins top/bottom {vmargin:.2f} mm on the {face_flat:.2f} mm flat")

    # stroke printability: rasterize each digit at real size (0.04 mm pixels)
    from matplotlib.path import Path as MPath
    from scipy import ndimage
    px = 0.04
    res = {}
    stem = None
    for d in "0123456789":
        contours = [np.c_[(c[:, 0] - bounds[d][0]) * em * DIGIT_COND, (c[:, 1] - ymin) * em] for c in outlines[d]]
        W = (bounds[d][2] - bounds[d][0]) * em * DIGIT_COND + 1.0
        H = band * em + 1.0
        xs = np.arange(-0.5, W, px)
        ys = np.arange(-0.5, H, px)
        XX, YY = np.meshgrid(xs, ys)
        Q = np.c_[XX.ravel(), YY.ravel()]
        ink = np.zeros(len(Q), bool)
        for c in contours:                                          # even-odd fill: counters become holes
            ink ^= MPath(c).contains_points(Q)
        ink = ink.reshape(XX.shape)
        min_px = int(0.1 / px ** 2)                                 # ignore specks < 0.1 mm^2 (corner artefacts)

        def count(mask):
            lab, n = ndimage.label(mask)
            return int(sum(1 for k in range(1, n + 1) if (lab == k).sum() >= min_px))
        n0 = count(ink)
        holes0 = count(~ink)
        disk = lambda r: (np.hypot(*np.mgrid[-int(r / px):int(r / px) + 1, -int(r / px):int(r / px) + 1]) * px <= r)
        er = ndimage.binary_erosion(ink, structure=disk(0.5))       # 1.0 mm feature survives?
        dl = ndimage.binary_dilation(ink, structure=disk(0.3))      # 0.6 mm counters stay open?
        n_er = count(er)
        holes_dl = count(~dl)
        r_ok = 0.5
        for r_try in (0.8, 1.1, 1.4, 1.7):
            if count(ndimage.binary_erosion(ink, structure=disk(r_try))) == n0:
                r_ok = r_try
            else:
                break
        res[d] = dict(components=n0, after_erosion_1mm=n_er, background_regions=holes0, after_dilation_0p6mm=holes_dl,
                      min_stroke_ge=2 * r_ok)
        if d == "1":
            row = ink[int((0.35 * band * em) / px)]
            runs = np.diff(np.r_[0, row.astype(int), 0])
            starts, ends = np.where(runs == 1)[0], np.where(runs == -1)[0]
            stem = max((e - s) for s, e in zip(starts, ends)) * px
    ok = all(v["components"] == v["after_erosion_1mm"] and v["background_regions"] == v["after_dilation_0p6mm"] for v in res.values())
    for d, v in res.items():
        if not (v["components"] == v["after_erosion_1mm"] and v["background_regions"] == v["after_dilation_0p6mm"]):
            print(f"   digit '{d}': {v}")
    print(f"stroke check (1.0 mm erosion keeps every stroke, 0.6 mm dilation keeps every counter): {'PASS' if ok else 'FAIL'}; "
          f"'1' stem width {stem:.2f} mm; every digit survives erosion to a stroke of >= "
          f"{min(v['min_stroke_ge'] for v in res.values()):.1f} mm")
    rec("typography", dict(em=em, condense=DIGIT_COND, flat_height=h_flat, max_height=h_band, glyph_cell=glyph_w,
                           layout_len=L, cell_box=(cells[0][0], cells[-1][1]), far_margin=cells[0][0] - ROT_X[0],
                           knob_margin=ROT_X[1] - cells[-1][1], face_margin=vmargin, stroke_ok=ok, stem_1=stem,
                           ink_left_with_1=ink_left, ink_right_worst=ink_right_worst))
    return dict(em=em, cells=cells, glyph_w=glyph_w, band=band, ymin=ymin, bounds=bounds, h_band=h_band)


INK_GAP, INK_GAP_MIN, GROUP_GAP_MAX = 2.8, 1.8, 9.0     # proportional layout (VU-5)


def number_layout(text, typo):
    """Proportional 3-4-4 layout inside the worst-case cell box: equal ink gaps inside a group, wider group gaps.
    Falls back to the fixed cells if the number cannot keep group gap >= 2 x ink gap."""
    em, b = typo["em"], typo["bounds"]
    w = [(b[ch][2] - b[ch][0]) * em * DIGIT_COND for ch in text]
    L = typo["cells"][-1][1] - typo["cells"][0][0]
    centre = 0.5 * (typo["cells"][0][0] + typo["cells"][-1][1])
    g = min(INK_GAP, (L - sum(w)) / 12.0)                 # 8 inner gaps + 2 group gaps of >= 2 g
    if g < INK_GAP_MIN:
        return dict(mode="fixed", centres=[0.5 * (c0 + c1) for c0, c1 in typo["cells"]], inner_gap=None, group_gap=None,
                    ratio=None, length=L)
    G = min(GROUP_GAP_MAX, (L - sum(w) - 8 * g) / 2)
    total = sum(w) + 8 * g + 2 * G
    x = centre - total / 2
    centres = []
    for i, wi in enumerate(w):
        centres.append(x + wi / 2)
        x += wi + (G if i in (2, 6) else g)
    return dict(mode="proportional", centres=centres, inner_gap=g, group_gap=G, ratio=G / g, length=total,
                ink=(centres[0] - w[0] / 2, centres[-1] + w[-1] / 2))


def check_layout(typo):
    section("2b. Number layout (proportional ink spacing, 3-4-4 groups)")
    ex = []
    for text in ("13900139000", "13800138000", "11611112222", "14444444444"):
        r = number_layout(text, typo)
        ex.append(dict(text=text, **{k: v for k, v in r.items() if k != "centres"}))
        if r["mode"] == "proportional":
            print(f"   {text}: ink gap {r['inner_gap']:.2f}, group gap {r['group_gap']:.2f} mm (x{r['ratio']:.1f}), ink X "
                  f"{r['ink'][0]:.1f}..{r['ink'][1]:.1f} (length {r['length']:.1f})")
        else:
            print(f"   {text}: fixed-cell fallback")
    ok = all(e["mode"] == "fixed" or e["ratio"] >= 2.0 - 1e-6 for e in ex)
    print(f"group gap >= 2 x ink gap for every proportional layout: {'PASS' if ok else 'FAIL'} "
          "(checks use example / worst-case numbers only; real numbers stay in config.toml)")
    rec("layout", dict(examples=ex, ok=ok))


# =====================================================================================
# 3. CAD (build123d): reference box + all parts at rest
# =====================================================================================
import build123d as bd
from scipy.spatial import ConvexHull


def yz_prism(pts, x0, x1):
    face = bd.Plane.YZ * bd.Polygon(*pts, align=None)
    return bd.Pos(x0, 0, 0) * bd.extrude(face, x1 - x0, dir=(1, 0, 0))


def xz_prism(pts, y0, y1):
    """Extrude an (X, Z) polygon along +Y from y0 to y1."""
    pl = bd.Plane(origin=(0, y0, 0), x_dir=(1, 0, 0), z_dir=(0, 1, 0))
    face = pl * bd.Polygon(*[(p[0], -p[1]) for p in pts], align=None)
    return bd.extrude(face, y1 - y0, dir=(0, 1, 0))


def x_cyl(r, x0, x1, y=YA, z=ZA):
    c = bd.Cylinder(r, x1 - x0, rotation=(0, 90, 0), align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN))
    return bd.Pos(x0, y, z) * c


def y_cyl(r, y0, y1, x, z):
    c = bd.Cylinder(r, y1 - y0, rotation=(-90, 0, 0), align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN))
    return bd.Pos(x, y0, z) * c


def circle(cy, cz, r, n=96):
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return np.c_[cy + r * np.cos(t), cz + r * np.sin(t)]


def hull(P):
    P = np.vstack(P)
    h = ConvexHull(P)
    return [tuple(P[i]) for i in h.vertices]


def rot_x(shape, deg, y=YA, z=ZA):
    return bd.Pos(0, y, z) * bd.Rot(deg, 0, 0) * bd.Pos(0, -y, -z) * shape


def z_cyl(r, z0, z1, x, y):
    c = bd.Cylinder(r, z1 - z0, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN))
    return bd.Pos(x, y, z0) * c


def teardrop_pts(r, y=YA, z=ZA, top=TEAR_TOP, n=72):
    """Circle + 45 deg roof pointing up (+Z = up in the lip-down print), roof cut flat at top * r."""
    k = r * (math.sqrt(2) - top)
    pts = [(y + k, z + top * r), (y - k, z + top * r)]
    for a in np.linspace(135.0, 405.0, n, endpoint=False):
        pts.append((y + r * math.cos(math.radians(a)), z + r * math.sin(math.radians(a))))
    return pts


def x_teardrop(r, x0, x1, y=YA, z=ZA):
    return yz_prism(teardrop_pts(r, y, z), x0, x1)


def keyed_hex(af, x0, x1):
    """Hexagon (across flats af) with one corner flattened -> one insertion phase only."""
    R = af / S3
    pts = [(YA + R * math.cos(math.radians(30 + 60 * k)), ZA + R * math.sin(math.radians(30 + 60 * k))) for k in range(6)]
    hexs = yz_prism(pts, x0, x1)
    cut = bd.Pos((x0 + x1) / 2, YA, ZA + HEX_KEY * R + 5.0) * bd.Box(abs(x1 - x0) + 2, 20, 10)   # flat on the +Z corner
    return hexs - cut


def end_block_profile():
    return hull([np.array(tri_pts(R_IN, CHAMFER)),
                 np.array([(LIP_Y[0], Z0), (LIP_Y[1], Z0), (LIP_Y[1], Z0 + LIP_T), (LIP_Y[0], Z0 + LIP_T)])])


def knob_profile(rot=0.0):
    pts = [circle(YA + KNOB_MAG_R * math.cos(math.radians(p + rot)), ZA + KNOB_MAG_R * math.sin(math.radians(p + rot)),
                  KNOB_LOBE_R) for p in KNOB_PHI]
    return hull(pts)


# tactile code on the knob's three flats (VU-4): flat normal angle -> rib offsets along the flat (mm); None = wide bar
KNOB_TACTILE = {90.0: ("A", (0.0,)), 210.0: ("B", (-4.0, 4.0)), 330.0: ("Logo", None)}


def knob_ribs():
    """Ribs along X on the flats (print vertical, no overhang): A one R1 rib, B two, Logo an 8 mm bar; 0.8 / 0.6 proud."""
    d_flat = KNOB_MAG_R * math.cos(math.radians(60)) + KNOB_LOBE_R          # 11.1
    polys = []
    for psi, (_, offs) in KNOB_TACTILE.items():
        n = np.array([math.cos(math.radians(psi)), math.sin(math.radians(psi))])
        t = np.array([-n[1], n[0]])
        mid = np.array([YA, ZA]) + d_flat * n
        if offs is None:
            c0, c1 = mid - 0.4 * n - 4.0 * t, mid - 0.4 * n + 4.0 * t
            polys.append(hull([circle(*c0, 1.0, 24), circle(*c1, 1.0, 24)]))
        else:
            for o in offs:
                polys.append([tuple(q) for q in circle(*(mid - 0.2 * n + o * t), 1.0, 24)])
    return polys


def front_face_chamfer(front, size=0.4):
    """0.4 x 45 deg on the outline of the bed-side front face (eats the elephant foot, hides the glue line)."""
    try:
        f = front.faces().sort_by(bd.Axis.Y)[0]
        return bd.chamfer(f.outer_wire().edges(), size), True
    except Exception as e:  # keep the unchamfered part, report it
        print(f"   front-face chamfer skipped: {e}")
        return front, False


def build_parts():
    t0 = time.time()
    plan = bd.Pos(0, BOX_D / 2) * bd.RectangleRounded(BOX_L, BOX_D, BOX_CORNER_R)
    box = bd.Pos(0, 0, -BOX_H) * bd.extrude(plan, BOX_H)
    box = bd.fillet(box.edges().group_by(bd.Axis.Z)[-1], LID_TOP_FILLET)
    lid = box & bd.Pos(0, 0, PARTING_Z / 2) * bd.Box(400, 400, -PARTING_Z)
    base = box - lid

    # rotor: tube + plugs (near: blind keyed hex socket + screw pilot; far: blind bore running on the stationary pin)
    tube = yz_prism(tri_pts(R_IN, CHAMFER), *ROT_X) - yz_prism(tri_pts(R_IN - T_PANEL, 0), ROT_X[0] - 1, ROT_X[1] + 1)
    plug_pts = tri_pts(R_IN - T_PANEL - PLUG_CLR, 0.8)
    plug_n = yz_prism(plug_pts, ROT_X[1] - PLUG_LEN_NEAR, ROT_X[1]) - keyed_hex(HEX_SOCKET_AF, KNOB_HEX_END, ROT_X[1] + 1)
    plug_n = plug_n - x_cyl(SCREW_PILOT / 2, KNOB_HEX_END - PILOT_DEPTH, KNOB_HEX_END + 0.01)
    plug_f = yz_prism(plug_pts, ROT_X[0], ROT_X[0] + PLUG_LEN_FAR) - x_cyl(FAR_BORE / 2, ROT_X[0] - 1, ROT_X[0] + FAR_BORE_DEPTH)
    rotor = tube + plug_n + plug_f

    # cradle: lip plate + two end blocks (one print, lip down); horizontal holes are teardrops
    lip = bd.Pos(LIP_X[0], LIP_Y[0], Z0) * bd.Box(LIP_X[1] - LIP_X[0], LIP_Y[1] - LIP_Y[0], LIP_T,
                                                   align=(bd.Align.MIN,) * 3)
    blk = end_block_profile()
    far_blk, near_blk = yz_prism(blk, *FAR_B), yz_prism(blk, *NEAR_B)
    cradle = lip + far_blk + near_blk
    cradle = cradle + x_cyl(BOSS_R, NEAR_B[0] - INNER_RING_H, NEAR_B[0] + 0.01)    # inner thrust ring
    cradle = cradle - x_teardrop(HOLE_FAR / 2, FAR_B[0] - 1, FAR_B[1] + 1) - x_teardrop(HOLE_NEAR / 2, NEAR_B[0] - 1, NEAR_B[1] + 1)
    sy, sz = YA + STATOR_R * math.cos(math.radians(STATOR_PHI)), ZA + STATOR_R * math.sin(math.radians(STATOR_PHI))
    cradle = cradle - x_teardrop(MAG_POCKET_D / 2, NEAR_B[0] - 0.01, NEAR_B[1] - DET_FLOOR, sy, sz)  # opens inward
    for x in DOWEL_X:
        cradle = cradle - z_cyl(DOWEL_D / 2, Z0 - 0.01, Z0 + (3.0 if abs(x) > 90 else 1.4), x, DOWEL_Y)

    # front bar: beam + two U tabs (one print, front face down); mount pockets open to the front, floor to the box
    beam = bd.Pos(BEAM_X[0], BEAM_Y[0], BEAM_Z[0]) * bd.Box(BEAM_X[1] - BEAM_X[0], BEAM_Y[1] - BEAM_Y[0],
                                                             BEAM_Z[1] - BEAM_Z[0], align=(bd.Align.MIN,) * 3)
    front = beam
    for sx in (-1, 1):
        cx = sx * BASE_MAG_X
        u = hull([circle(cx, TAB_ZC, TAB_W / 2), np.array([(cx - TAB_W / 2, TAB_TOP), (cx + TAB_W / 2, TAB_TOP)])])
        tab = xz_prism(u, *TAB_Y)
        tab = bd.chamfer(tab.faces().sort_by(bd.Axis.Y)[-1].edges(), TAB_LEADIN)    # lead-in on the back face
        front = front + tab
    front, chamfered = front_face_chamfer(front)
    for sx in (-1, 1):
        front = front - y_cyl(MAG_POCKET_D / 2, TAB_Y[0] - 0.1, -MOUNT_FLOOR, sx * BASE_MAG_X, MOUNT_Z)
    for x in DOWEL_X:
        front = front - z_cyl(DOWEL_D / 2, Z0 - 3.0, Z0 + 0.01, x, DOWEL_Y)

    # knob: trefoil + tactile ribs + thrust boss + journal + keyed hex (one print, outer face down)
    knob = yz_prism(knob_profile(), *KNOB_X)
    for rib in knob_ribs():
        knob = knob + yz_prism(rib, *KNOB_X)
    knob = knob + x_cyl(BOSS_R, NEAR_B[1], KNOB_X[0] + 0.01)
    knob = knob + x_cyl(PIN_D / 2, NEAR_B[0], NEAR_B[1] + 0.01)
    knob = knob + keyed_hex(HEX_AF, KNOB_HEX_END, NEAR_B[0] + 0.01)
    lobes = [(YA + KNOB_MAG_R * math.cos(math.radians(p)), ZA + KNOB_MAG_R * math.sin(math.radians(p))) for p in KNOB_PHI]
    for my, mz in lobes:                                       # pockets open at the OUTER face, floor at the inner face
        knob = knob - x_cyl(MAG_POCKET_D / 2, KNOB_X[0] + DET_FLOOR, KNOB_X[1] + 0.01, my, mz)
    knob = knob - x_cyl(SCREW_BORE / 2, KNOB_HEX_END - 0.01, KNOB_X[1] + 0.01)
    knob = knob - x_cyl(SCREW_HEAD_D / 2, KNOB_X[1] - SCREW_HEAD_DEPTH, KNOB_X[1] + 0.01)

    far_pin = x_cyl(PIN_D / 2 - 0.01, *FAR_PIN_X) - x_cyl(1.25, FAR_PIN_X[0] - 0.1, FAR_PIN_X[0] + 6.0)

    mags = {}
    for sx in (-1, 1):
        mags[f"mount{'+' if sx > 0 else '-'}"] = y_cyl(4.0, -MOUNT_FLOOR - 3.0 * MOUNT_STACK, -MOUNT_FLOOR, sx * BASE_MAG_X, MOUNT_Z)
    for p, (my, mz) in zip(KNOB_PHI, lobes):
        mags[f"knob{int(p)}"] = x_cyl(4.0, KNOB_X[0] + DET_FLOOR, KNOB_X[0] + DET_FLOOR + 3.0 * KNOB_STACK, my, mz)
    mags["stator"] = x_cyl(4.0, NEAR_B[1] - DET_FLOOR - 3.0, NEAR_B[1] - DET_FLOOR, sy, sz)
    caps = [y_cyl(4.1, TAB_Y[0], TAB_Y[0] + CAP_T, sx * BASE_MAG_X, MOUNT_Z) for sx in (-1, 1)]
    caps += [x_cyl(4.1, KNOB_X[1] - KNOB_CAP_T, KNOB_X[1], my, mz) for my, mz in lobes]
    caps.append(x_cyl(SCREW_HEAD_D / 2 - 0.01, KNOB_X[1] - HUB_CAP_T, KNOB_X[1]))      # hub cap over the M3 head
    spacer = x_cyl(4.1, NEAR_B[0], NEAR_B[0] + STATOR_SPACER_T, sy, sz)
    pads = None
    for (xr, yr) in PADS:
        pd = bd.Pos(xr[0], yr[0], 0) * bd.Box(xr[1] - xr[0], yr[1] - yr[0], PAD_T, align=(bd.Align.MIN,) * 3)
        pads = pd if pads is None else pads + pd
    cap_all = caps[0]
    for c in caps[1:]:
        cap_all = cap_all + c
    parts = dict(box=box, lid=lid, base=base, tube=tube, plug_near=plug_n, plug_far=plug_f, rotor=rotor, lip=lip, beam=beam,
                 far_block=far_blk, near_block=near_blk, cradle=cradle, front_bar=front, knob=knob, far_pin=far_pin,
                 caps=cap_all, spacer=spacer, pads=pads)
    REPORT["cad_notes"] = dict(front_face_chamfer=chamfered)
    print(f"CAD built in {time.time() - t0:.1f} s (front-face chamfer {'ok' if chamfered else 'skipped'})")
    return parts, mags


def vol(a, b):
    try:
        return round(abs((a & b).volume), 4)
    except Exception:
        return float("nan")


def check_cad(parts, mags):
    section("3. CAD checks: interference, clearances, sweep, envelope, configuration paths")
    p = parts
    plate_parts = ["cradle", "front_bar", "rotor", "knob", "far_pin", "caps", "spacer", "pads"]
    # (a) static interference (contacts give ~0 volume)
    pairs = [("box", k) for k in plate_parts] + [("cradle", "rotor"), ("cradle", "knob"), ("cradle", "front_bar"),
                                                ("cradle", "far_pin"), ("rotor", "knob"), ("rotor", "far_pin"),
                                                ("front_bar", "rotor"), ("front_bar", "knob"), ("caps", "knob"),
                                                ("caps", "front_bar"), ("spacer", "cradle"), ("spacer", "rotor"),
                                                ("pads", "cradle"), ("pads", "front_bar")]
    inter = {f"{a}&{b}": vol(p[a], p[b]) for a, b in pairs}
    mag_inter = {k: round(sum(vol(m, p[q]) for q in plate_parts), 4) for k, m in mags.items()}
    print("interference volumes mm^3:", inter)
    print("magnet vs parts (should be 0: magnets sit in pockets):", mag_inter)
    # (b) clearances at rest
    dist = {
        "rotor-lip(radial)": p["tube"].distance_to(p["lip"]),
        "rotor-near_block(axial)": p["rotor"].distance_to(p["near_block"] - x_cyl(HOLE_NEAR / 2, 80, 100)),
        "rotor-far_block(axial)": p["rotor"].distance_to(p["far_block"]),
        "rotor-cradle(min, incl. inner thrust ring)": p["rotor"].distance_to(p["cradle"]),
        "rotor-front_bar": p["rotor"].distance_to(p["front_bar"]),
        "rotor-box": p["rotor"].distance_to(p["box"]),
        "knob body-near_block(axial)": yz_prism(knob_profile(), *KNOB_X).distance_to(p["near_block"]),
        "knob-box": p["knob"].distance_to(p["box"]),
        "knob-front_bar": p["knob"].distance_to(p["front_bar"]),
        "beam-lid(relief)": p["beam"].distance_to(p["lid"]),
        "tabs-box(contact)": p["front_bar"].distance_to(p["base"]),
    }
    dist = {k: round(v, 3) for k, v in dist.items()}
    print("clearances at rest mm:", dist)
    # (c) sweep: rotate rotor and knob through one 120 deg period
    sw_lip, sw_bar, sw_blk = [], [], []
    for th in range(0, 120, 6):
        r = rot_x(p["tube"], th)
        sw_lip.append(r.distance_to(p["lip"]))
        sw_bar.append(r.distance_to(p["front_bar"]))
        sw_blk.append(rot_x(p["rotor"], th).distance_to(p["far_block"]))
    kn_box, kn_bar, kn_lip = [], [], []
    for th in range(0, 120, 10):
        k = rot_x(yz_prism(knob_profile(), *KNOB_X), th)
        kr = rot_x(p["knob"], th)                                   # with tactile ribs
        kn_box.append(kr.distance_to(p["box"]))
        kn_bar.append(kr.distance_to(p["front_bar"]))
        kn_lip.append(k.distance_to(p["near_block"]))
    sweep = dict(rotor_to_lip_min=min(sw_lip), rotor_to_front_bar_min=min(sw_bar), rotor_to_far_block_min=min(sw_blk),
                 knob_to_box_min=min(kn_box), knob_to_front_bar_min=min(kn_bar), knob_body_to_near_block_min=min(kn_lip))
    sweep = {k: round(v, 3) for k, v in sweep.items()}
    print("sweep minima over 0-120 deg (mm):", sweep)
    # (d) envelope (bounding boxes + swept circles)
    bbs = {k: p[k].bounding_box() for k in plate_parts if k != "pads"}
    xmin = min(b.min.X for b in bbs.values())
    xmax = max(b.max.X for b in bbs.values())
    ymin_static = min(b.min.Y for b in bbs.values())
    knob_tip = KNOB_MAG_R + KNOB_LOBE_R
    ymin = min(ymin_static, YA - R_SW, YA - knob_tip)
    zmax_static = max(b.max.Z for b in bbs.values())
    zmax = max(zmax_static, ZA + R_SW, ZA + knob_tip)
    zmin = min(b.min.Z for b in bbs.values())
    env = dict(x=(round(xmin, 2), round(xmax, 2)), length=round(xmax - xmin, 2), y_min=round(ymin, 2),
               y_max=round(max(max(b.max.Y for b in bbs.values()), YA + knob_tip), 2), z_min=round(zmin, 2),
               z_max_static=round(zmax_static, 2), z_max_swept=round(zmax, 2), margin_to_rule=round(ymin - RULE_Y, 2),
               gap_to_tongue=round(ymin - TONGUE_Y, 2))
    print("envelope:", env)
    # (e) configuration paths (each motion is a pure translation)
    def vsum(moved, fixed):
        return round(sum(vol(m, f) for m in moved for f in fixed), 4)
    plate = [p[k] for k in plate_parts]
    path_install = {h: vsum([bd.Pos(0, 0, h) * q for q in plate], [p["box"]]) for h in (0.3, 1, 3, 6, 10, 20, 40, 60)}
    path_rotor = {h: vsum([bd.Pos(0, 0, h) * p["rotor"]], [p["cradle"]]) for h in (0.5, 2, 5, 10, 20, 40)}
    path_farpin = {d: vsum([bd.Pos(-d, 0, 0) * p["far_pin"]], [p["cradle"], p["rotor"]]) for d in (1, 3, 6, 9, 14)}
    path_knob = {d: vsum([bd.Pos(d, 0, 0) * p["knob"]], [p["cradle"], p["rotor"], p["spacer"]]) for d in (1, 3, 6, 10, 16, 23)}
    lid_lift = {h: vsum([bd.Pos(0, 0, h) * q for q in plate + [p["lid"]]], [p["base"]]) for h in (0.5, 2, 5, 10, 20, 40)}
    print("install path (plate down onto box) intersection mm^3:", path_install)
    print("rotor drop-in into cradle:", path_rotor)
    print("far pin axial insertion (-X offset):", path_farpin)
    print("knob axial insertion (+X offset):", path_knob)
    print("refill: lid + plate lifted together vs base:", lid_lift)
    rec("cad", dict(interference=inter, magnets=mag_inter, clearances=dist, sweep=sweep, envelope=env,
                    path_install=path_install, path_rotor=path_rotor, path_far_pin=path_farpin, path_knob=path_knob,
                    lid_lift=lid_lift))
    return env


def export_stl(parts, mags):
    for k in ("cradle", "front_bar", "rotor", "knob", "far_pin", "box", "lid", "base", "caps", "spacer", "pads",
              "plug_near", "plug_far"):
        bd.export_stl(parts[k], os.path.join(OUT, "stl", f"{k}.stl"))
    for k, m in mags.items():
        bd.export_stl(m, os.path.join(OUT, "stl", f"mag_{k}.stl"))


# =====================================================================================
# 4. Visibility from outside (ray casting against the knob, end blocks and tongue)
# =====================================================================================
def check_visibility(typo):
    section("4. Visibility of the display face from outside (ray casting)")
    from matplotlib.path import Path as MPath
    em = typo["em"]
    n = np.array([0.0, -math.cos(math.radians(30)), math.sin(math.radians(30))])   # display normal
    up = np.array([0.0, 0.5, S3 / 2])
    fb = np.array([0.0, YA - S_SIDE / 2, ZA - R_IN])
    s_mid = CHAMFER + (FACE_FLAT - typo["h_band"]) / 2       # distance along face from sharp vertex to ink bottom
    ink_v = np.linspace(s_mid, s_mid + typo["h_band"], 9)
    xs = []
    for (c0, c1) in typo["cells"]:
        xs += list(np.linspace(c0, c1, 6))
    P = np.array([fb + v * up + np.array([x, 0, 0]) for x in xs for v in ink_v])
    occl = {"knob": (MPath(np.array(knob_profile())), KNOB_X), "near_block": (MPath(np.array(end_block_profile())), NEAR_B),
            "far_block": (MPath(np.array(end_block_profile())), FAR_B)}

    def blocked(P, d):
        hit = np.zeros(len(P), bool)
        for name, (path, (x0, x1)) in occl.items():
            if abs(d[0]) < 1e-9:
                continue
            t0 = (x0 - P[:, 0]) / d[0]
            t1 = (x1 - P[:, 0]) / d[0]
            ta, tb = np.minimum(t0, t1), np.maximum(t0, t1)
            ta = np.maximum(ta, 0.0)
            ok = tb > ta
            for f in np.linspace(0, 1, 25):
                t = ta + f * (tb - ta)
                Q = P[:, 1:] + t[:, None] * d[1:]
                inside = path.contains_points(Q) & ok
                hit |= inside
        # tongue / dashboard: half space Y < TONGUE_Y, Z < 0 (rays from the face rise, checked anyway)
        t_t = (TONGUE_Y - P[:, 1]) / d[1] if d[1] < 0 else np.full(len(P), np.inf)
        z_at = P[:, 2] + t_t * d[2]
        hit |= np.isfinite(t_t) & (z_at < 0)
        return hit

    table = {}
    first_occl = {}
    for elev in (15, 25, 35, 45):
        row = {}
        for yaw in range(-60, 61, 5):
            e, a = math.radians(elev), math.radians(yaw)
            d = np.array([math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)])
            if d @ n <= 0:
                row[yaw] = 0.0
                continue
            vis = 1.0 - blocked(P, d).mean()
            row[yaw] = round(100 * vis, 1)
        table[elev] = row
        pos = [y for y in row if y > 0 and row[y] < 100]
        neg = [y for y in row if y < 0 and row[y] < 100]
        first_occl[elev] = dict(toward_knob=min(pos) if pos else None, toward_far=max(neg) if neg else None)
    for elev, row in table.items():
        print(f"elev {elev:2d} deg: " + " ".join(f"{y:+d}:{v:.0f}" for y, v in row.items() if y % 15 == 0))
    print("first yaw with any occlusion (deg):", first_occl)
    # sightline over the tongue from the lowest ink line
    z_low = fb[2] + s_mid * up[2]
    y_low = fb[1] + s_mid * up[1]
    over = {e: round(z_low + (y_low - TONGUE_Y) * math.tan(math.radians(e)), 1) for e in (15, 25, 35, 45)}
    print(f"lowest ink line at Y {y_low:.2f}, Z {z_low:.2f}; its sightline height above the tongue nose: {over}")
    # angular size
    hf = REPORT["typography"]["flat_height"]
    ang = {d: round(math.degrees(math.atan(hf / (d * 1000))) * 60, 1) for d in (1, 2, 4)}
    print(f"digit angular height (arcmin) at 1/2/4 m: {ang}")
    rec("visibility", dict(percent_visible=table, first_occlusion=first_occl, ink_low=(y_low, z_low),
                           sightline_height_over_tongue=over, digit_arcmin=ang))


# =====================================================================================
# 5. Magnet model (Gilbert surface charges), calibrated to the brief: 2x N52 8x3 @1.2 mm = 8.6 N
# =====================================================================================
MU0 = 4e-7 * np.pi
NR, NT = 10, 40


def disc_nodes(radius, n_r=NR, n_t=NT):
    x, wx = np.polynomial.legendre.leggauss(n_r)
    r = 0.5 * radius * (x + 1.0)
    wr = 0.5 * radius * wx * r
    t = (np.arange(n_t) + 0.5) * 2 * np.pi / n_t
    rr, tt = np.meshgrid(r, t, indexing="ij")
    ww = np.outer(wr, np.full(n_t, 2 * np.pi / n_t))
    return np.stack([(rr * np.cos(tt)).ravel(), (rr * np.sin(tt)).ravel()], axis=1), ww.ravel()


class Disc:
    """Axially magnetised disc: centre c, unit axis u (S->N), diameter d, thickness t, remanence br (T)."""

    def __init__(self, c, u, d=8.0, t=3.0, br=1.37):
        self.c = np.asarray(c, float)
        u = np.asarray(u, float)
        self.u = u / np.linalg.norm(u)
        p2, w = disc_nodes(d / 2)
        a = np.array([1.0, 0, 0]) if abs(self.u[0]) < 0.9 else np.array([0, 1.0, 0])
        e1 = np.cross(self.u, a)
        e1 /= np.linalg.norm(e1)
        e2 = np.cross(self.u, e1)
        loc = p2[:, :1] * e1 + p2[:, 1:2] * e2
        self.pts = np.vstack([self.c + 0.5 * t * self.u + loc, self.c - 0.5 * t * self.u + loc])
        self.q = np.concatenate([w, -w]) * br


def interact(src, dst):
    k = 1.0 / (4 * np.pi * MU0) * 1e-6
    d = dst.pts[:, None, :] - src.pts[None, :, :]
    r3 = np.linalg.norm(d, axis=2) ** 3
    fe = k * dst.q[:, None] * ((src.q[None, :] / r3)[:, :, None] * d).sum(axis=1)
    return fe.sum(axis=0), fe


def force_torque(srcs, dsts, ap=(0, 0, 0), ad=(1, 0, 0)):
    F, T = np.zeros(3), 0.0
    ap, ad = np.asarray(ap, float), np.asarray(ad, float)
    for s in srcs:
        for d in dsts:
            f, fe = interact(s, d)
            F += f
            T += float(np.dot(np.cross(d.pts - ap, fe).sum(axis=0), ad))
    return F, T


def calibrate_br():
    f = lambda br: -interact(Disc((0, 0, -1.5), (0, 0, 1), br=br), Disc((0, 0, 1.2 + 1.5), (0, 0, 1), br=br))[0][2]
    return 1.45 * math.sqrt(8.6 / f(1.45))


BASES = [("8x2 N35", 8, 2, 1.17), ("10x2 N35", 10, 2, 1.17), ("10x3 N38", 10, 3, 1.23),
         ("12x3 N38", 12, 3, 1.23), ("15x3 N38", 15, 3, 1.23)]


def mount_force(br52, base, wall, offset, floor=MOUNT_FLOOR, stack=MOUNT_STACK):
    """Our N52 8x3 (stack) behind 'floor' vs a base magnet behind 'wall'. offset = ours above base (+Z).
    Returns (normal pull toward the box N, vertical force on ours N; negative = down)."""
    name, d, t, br = base
    m1 = Disc((0, 0, -t / 2), (0, 0, 1), d, t, br)
    F = np.zeros(3)
    for k in range(stack):
        F += interact(m1, Disc((offset, 0, wall + floor + 1.5 + 3.0 * k), (0, 0, 1), 8, 3, br52))[0]
    return -F[2], F[0]


def mount_cases(br52, stack):
    """Per-point pull / downward shear for one tab stack: ranges and the named design corners."""
    i80, i90 = TAB_IRREV[stack]
    rows = []
    for bse in BASES:
        for w in (2.0, 2.5, 3.0):
            n, sh = mount_force(br52, bse, w, MOUNT_DELTA, stack=stack)
            rows.append((bse[0], w, n, -sh))
    N, S = np.array([r[2] for r in rows]), np.array([r[3] for r in rows])
    typ = mount_force(br52, BASES[1], 2.5, MOUNT_DELTA, stack=stack)
    weak = mount_force(br52, BASES[0], 3.0, MOUNT_DELTA, stack=stack)
    corner = lambda f, k: dict(pull=f[0] * k, down=-f[1] * k)
    res = dict(stack=stack, rows=rows, pull_20C=(N.min(), N.max()), down_20C=(S.min(), S.max()),
               pull_80C=(HOT * i80 * N.min(), HOT * i80 * N.max()), down_80C=(HOT * i80 * S.min(), HOT * i80 * S.max()),
               typical_20C=corner(typ, 1.0), weakest_20C=corner(weak, 1.0), weakest_80C=corner(weak, HOT * i80),
               weakest_90C=corner(weak, HOT90 * i90), strongest_20C=dict(pull=N.max(), down=S[np.argmax(N)]),
               irreversible=(i80, i90))
    # plate-0 slide-up force (vertical pull along the box face) per point at 20 C: shear + friction
    res["slide_up_20C"] = dict(weakest=-weak[1] + MU_PU[0] * weak[0], typical=-typ[1] + MU_PU[0] * typ[0])
    lift = []
    for h in (0, 1, 2, 3, 4, 5, 6, 8, 10, 14):
        n_w, s_w = mount_force(br52, BASES[0], 3.0, MOUNT_DELTA + h, stack=stack)
        n_s, s_s = mount_force(br52, BASES[4], 2.0, MOUNT_DELTA + h, stack=stack)
        lift.append((h, n_w, -s_w, n_s, -s_s))
    res["lift_table"] = lift
    return res


def check_mount(br52):
    section(f"5a. Mount magnets on the base points (base magnet UNKNOWN -> range); default stack {MOUNT_STACK}")
    out = {st: mount_cases(br52, st) for st in (1, 2)}
    for st, r in out.items():
        tag = "DEFAULT" if st == MOUNT_STACK else "option"
        print(f"--- stack {st} ({tag}), our N52 8x3 x{st} behind a {MOUNT_FLOOR} mm floor, +{MOUNT_DELTA} mm above the point; "
              f"irreversible x{r['irreversible'][0]} (80 C) / x{r['irreversible'][1]} (90 C)")
        if st == MOUNT_STACK:
            names = sorted(set(x[0] for x in r["rows"]), key=[b[0] for b in BASES].index)
            for nm in names:
                print(f"   base {nm:9s}: " + "  ".join(f"wall {x[1]}: pull {x[2]:.2f} N, down {x[3]:.2f} N" for x in r["rows"] if x[0] == nm))
        print(f"   20 C: pull {r['pull_20C'][0]:.2f}-{r['pull_20C'][1]:.2f} N, down {r['down_20C'][0]:.2f}-{r['down_20C'][1]:.2f} N; "
              f"80 C (rev + irr): pull {r['pull_80C'][0]:.2f}-{r['pull_80C'][1]:.2f} N")
        print(f"   corners: typical 20 C {r['typical_20C']['pull']:.2f}/{r['typical_20C']['down']:.2f}; weakest 20 C "
              f"{r['weakest_20C']['pull']:.2f}/{r['weakest_20C']['down']:.2f}; weakest 80 C {r['weakest_80C']['pull']:.2f}/"
              f"{r['weakest_80C']['down']:.2f}; weakest 90 C {r['weakest_90C']['pull']:.2f}/{r['weakest_90C']['down']:.2f} N (pull/down)")
        print(f"   plate-0 slide-up force per point at 20 C (down + {MU_PU[0]} x pull): weakest {r['slide_up_20C']['weakest']:.2f} N, "
              f"typical {r['slide_up_20C']['typical']:.2f} N")
    res = out[MOUNT_STACK]
    lift = res["lift_table"]
    print("lift h (mm) -> weakest pull/down, strongest pull/down (default stack):",
          ", ".join(f"{h}: {a:.2f}/{b:.2f}, {c:.2f}/{d:.2f}" for h, a, b, c, d in lift))
    res["peak_shear_on_lift"] = (max(x[2] for x in lift), max(x[4] for x in lift))
    rec("mount_magnets", res)
    rec("mount_magnets_alt", out[3 - MOUNT_STACK])
    return out


def detent_sweep(br, thetas):
    T, F = [], []
    kt = 3.0 * KNOB_STACK
    for th in thetas:
        a = math.radians(STATOR_PHI)
        st = [Disc((-1.5, STATOR_R * math.cos(a), STATOR_R * math.sin(a)), (1, 0, 0), br=br)]
        ro = []
        for p in KNOB_PHI:
            b = math.radians(p + th)
            ro.append(Disc((DETENT_GAP + kt / 2, KNOB_MAG_R * math.cos(b), KNOB_MAG_R * math.sin(b)), (1, 0, 0), t=kt, br=br))
        f, t = force_torque(st, ro)
        T.append(t)
        F.append(f)
    return np.array(T), np.array(F)


R_BOSS_MEAN = (PIN_D / 2 + 0.15 + BOSS_R) / 2          # boss / inner-ring annulus mean radius


def detent_friction(F_row, w_rot, mu_t=MU_ABS, mu_j=MU_ABS):
    """Friction torque: thrust (knob boss when attracted, near plug on the inner ring when repelled, same radius)
    + near journal (radial magnet force + half the rotor weight) + far journal (half the weight)."""
    w_half = 0.5 * w_rot
    rad = math.hypot(F_row[1], F_row[2] - w_half)
    return mu_t * abs(F_row[0]) * R_BOSS_MEAN + mu_j * rad * PIN_D / 2 + mu_j * w_half * PIN_D / 2


def check_detent(br52, masses):
    section(f"5b. Detent: 3 knob lobes x{KNOB_STACK} N52 + 1 stator, floor-backed pockets, face gap {DETENT_GAP:.1f}")
    th = np.arange(0.0, 71.0, 1.0)
    T, F = detent_sweep(br52, th)
    Trest = -T                         # restoring torque toward theta = 0 (positive)
    k = Trest[1] / th[1]
    pk = Trest[th <= 60].max()
    th_pk = th[np.argmax(Trest[th <= 60])]
    ax_rest, fz_rest, fy_rest = -F[0, 0], F[0, 2], F[0, 1]
    w_rot = masses["rotor_assembly_g"] * G
    t_thrust = MU_ABS * ax_rest * R_BOSS_MEAN
    t_near = MU_ABS * math.hypot(fy_rest, fz_rest - 0.5 * w_rot) * PIN_D / 2
    t_far = MU_ABS * 0.5 * w_rot * PIN_D / 2
    tf = t_thrust + t_near + t_far
    tf_ptfe = MU_PTFE / MU_ABS * t_thrust + t_near + t_far
    tf_tab = np.array([detent_friction(F[i], w_rot) for i in range(len(th))])
    tf_tab_ptfe = np.array([detent_friction(F[i], w_rot, MU_PTFE) for i in range(len(th))])
    tf_tab_045 = np.array([detent_friction(F[i], w_rot, 0.45, 0.45) for i in range(len(th))])

    def dead_edge(tf_arr):
        fine = np.linspace(20, 60, 801)
        diff = np.interp(fine, th, Trest) - np.interp(fine, th, tf_arr)
        idx = np.where(diff < 0)[0]
        return float(fine[idx[0]]) if len(idx) else 60.0
    de, de_p, de_45 = dead_edge(tf_tab), dead_edge(tf_tab_ptfe), dead_edge(tf_tab_045)
    show = [0, 1, 2, 4, 6, 8, 10, 13, 16, 20, 25, 30, 35, 40, 45, 50, 54, 57, 59, 60]
    print("theta deg : " + " ".join(f"{t:5.0f}" for t in show))
    print("T N*mm    : " + " ".join(f"{Trest[t]:5.1f}" for t in show))
    print("axial N   : " + " ".join(f"{-F[t, 0]:5.2f}" for t in show) + "   (+ = knob pulled onto the boss)")
    rev = th[(-F[:, 0] < 0) & (th <= 60)]
    print(f"peak restoring {pk:.1f} N*mm @ {th_pk:.0f} deg (80 C x{HOT}: {HOT * pk:.1f}; with 15 % irreversible loss "
          f"{HOT * N52_IRREV * pk:.1f}); stiffness {k:.2f} N*mm/deg")
    print(f"rest forces on knob: axial pull {ax_rest:.2f} N, radial Fz {fz_rest:+.2f} N (down = journal preload), Fy {fy_rest:+.2f}; "
          f"axial force reverses for theta {rev.min():.0f}..{120 - rev.min():.0f} deg (max {F[:, 0].max():.2f} N away from the boss)")
    print(f"friction at rest (dry mu {MU_ABS}): thrust {t_thrust:.1f} + near journal {t_near:.2f} + far journal {t_far:.2f} "
          f"= {tf:.1f} N*mm -> ratio peak/friction {pk / tf:.2f}; stop error +-{tf / k:.1f} deg "
          f"(PTFE on boss: {tf_ptfe:.1f} N*mm, +-{tf_ptfe / k:.1f} deg)")
    print(f"dead zone around the 60 deg midpoint (restoring < friction): dry {de:.1f}..{120 - de:.1f} deg "
          f"(+-{60 - de:.1f}); PTFE on both thrust faces {de_p:.1f}..{120 - de_p:.1f} (+-{60 - de_p:.1f}); "
          f"layer-line faces mu 0.45: ratio {pk / tf_tab_045[0]:.2f}, dead zone +-{60 - de_45:.1f}")
    t_switch = float(np.max(Trest[th <= 60] + tf_tab[th <= 60]))
    # pocket floors: magnet pull on a clamped 0.8 mm disc (screen for creep into the boss gap)
    p_floor = ax_rest / (math.pi * 4.0 ** 2)
    sig = 0.75 * p_floor * 4.15 ** 2 / DET_FLOOR ** 2
    bulge = {E: p_floor * 4.15 ** 4 / (64 * E * DET_FLOOR ** 3 / (12 * (1 - 0.35 ** 2))) for E in (2000, 300, 100)}
    print(f"switching torque (peak of restoring + friction) {t_switch:.1f} N*mm; floor stress {sig:.1f} MPa, bulge "
          + ", ".join(f"E{E}: {b:.3f}" for E, b in bulge.items()) + f" mm each (boss gap {BOSS_H})")
    res = dict(theta=list(th), torque=list(Trest), axial=list(-F[:, 0]), peak=pk, peak_theta=th_pk, peak_hot=HOT * pk,
               peak_hot_worst=HOT * N52_IRREV * pk, stiffness=k, axial_rest=ax_rest, radial_preload=fz_rest,
               friction=dict(thrust=t_thrust, near=t_near, far=t_far, total=tf, total_ptfe=tf_ptfe),
               ratio=pk / tf, stop_error=tf / k, stop_error_ptfe=tf_ptfe / k, ratio_mu045=pk / tf_tab_045[0],
               dead_zone_halfwidth=dict(dry=60 - de, ptfe=60 - de_p, mu045=60 - de_45), switch_torque=t_switch,
               reverse_axial=dict(from_deg=float(rev.min()), max_N=float(F[:, 0].max())),
               floor=dict(stress_MPa=sig, bulge_mm=bulge), radial=list(np.hypot(F[:, 1], F[:, 2])),
               F=F.tolist(), magnets=3 * KNOB_STACK + 1)
    rec("detent", res)
    return res, th, Trest, (tf_tab, tf_tab_ptfe)


def snap_dynamics(det, th_tab, T_tab, tf_tabs, inertia):
    section("5c. Snap dynamics after the finger releases past the dead zone")
    I = inertia * 1e3                  # kg m^2 -> N mm s^2

    def run(x0, w0, tf_arr, c_visc=0.0):
        th, w, dt, t = math.radians(x0), w0, 2e-6, 0.0
        rev, over = 0, 0.0
        while t < 1.5:
            xdeg = (math.degrees(th) + 60) % 120 - 60
            Tm = -math.copysign(1, xdeg) * np.interp(abs(xdeg), th_tab, T_tab)
            Tf = np.interp(abs(xdeg), th_tab, tf_arr)
            if abs(w) < 1e-3 and abs(Tm) <= Tf:
                break
            Tfr = -math.copysign(Tf, w) if abs(w) >= 1e-3 else -math.copysign(Tf, Tm)
            w_new = w + (Tm + Tfr - c_visc * w) / I * dt
            if w != 0 and w_new * w < 0:
                rev += 1
                w_new = 0.0
            w = w_new
            th += w * dt
            t += dt
            over = max(over, math.degrees(th) - 120)
        return dict(overshoot=round(over, 1), reversals=rev, settle_ms=round(1000 * t, 0),
                    final_err=round(math.degrees(th) - 120, 2))

    dry, ptfe = tf_tabs
    e_dry = 60 + det["dead_zone_halfwidth"]["dry"] + 0.5        # release just past the dead zone
    e_pt = 60 + det["dead_zone_halfwidth"]["ptfe"] + 0.5
    out = {}
    for label, x0, w0, tf_arr, c in [(f"dry, released at {e_dry:.1f} deg", e_dry, 0.0, dry, 0.0),
                                     (f"dry, finger 2 rad/s at {e_dry:.1f} deg", e_dry, 2.0, dry, 0.0),
                                     (f"PTFE, released at {e_pt:.1f} deg", e_pt, 0.0, ptfe, 0.0),
                                     (f"PTFE + damping grease c=1.0, {e_pt:.1f} deg", e_pt, 0.0, ptfe, 1.0)]:
        r = run(x0, w0, tf_arr, c)
        out[label] = r
        print(f"{label:42s}: overshoot {r['overshoot']:5.1f} deg, reversals {r['reversals']:2d}, settled after "
              f"{r['settle_ms']:4.0f} ms, final error {r['final_err']:+.2f} deg")
    print(f"(rotor + knob inertia about the axis {inertia * 1e6:.2f} e-6 kg m^2, from CAD)")
    rec("snap", out)


# =====================================================================================
# 6. Masses, centre of gravity, statics (LP), refill behaviour
# =====================================================================================
RHO_SILICONE = 1.2e-3       # g/mm^3, anti-slip strips
SCREW_G, SCREW_X = 1.4, 89.0  # M3x25 pan-head self-tapper (steel), mass centre on the axis


def check_masses(parts):
    section("6a. Masses and centre of gravity (CAD volume x 1.05 g/cm^3 x fill factor)")
    fill = dict(panels=1.0, plugs=1.0, cradle=0.85, front_bar=0.90, knob=0.95, far_pin=1.0, caps=1.0, spacer=1.0)
    keys = dict(panels="tube", cradle="cradle", front_bar="front_bar", knob="knob", far_pin="far_pin", caps="caps", spacer="spacer")
    vols = {k: parts[v].volume for k, v in keys.items()}
    vols["plugs"] = parts["plug_near"].volume + parts["plug_far"].volume
    cents = {k: parts[v].center(bd.CenterOf.MASS) for k, v in keys.items()}
    cents["plugs"] = (parts["plug_near"] + parts["plug_far"]).center(bd.CenterOf.MASS)
    m = {k: vols[k] * RHO_ABS * fill[k] for k in vols}
    mags = {"mount": (2 * MOUNT_STACK, (0.0, MOUNT_Y, MOUNT_Z)),
            "knob": (3 * KNOB_STACK, (KNOB_X[0] + DET_FLOOR + 1.5 * KNOB_STACK, YA, ZA)),
            "stator": (1, (NEAR_B[1] - DET_FLOOR - 1.5, YA, ZA - STATOR_R))}
    pc = parts["pads"].center(bd.CenterOf.MASS)
    other = {"pads (silicone)": (parts["pads"].volume * RHO_SILICONE, (pc.X, pc.Y, pc.Z)),
             "M3 screw": (SCREW_G, (SCREW_X, YA, ZA))}
    nmag = sum(v[0] for v in mags.values())
    total = sum(m.values()) + MAGNET_G * nmag + sum(v[0] for v in other.values())
    mom = np.zeros(3)
    for k in m:
        c = cents[k]
        mom += m[k] * np.array([c.X, c.Y, c.Z])
    for k, (n, c) in mags.items():
        mom += n * MAGNET_G * np.array(c)
    for k, (mm, c) in other.items():
        mom += mm * np.array(c)
    cog = mom / total
    for k in m:
        print(f"   {k:10s}: volume {vols[k] / 1000:6.2f} cm^3, fill {fill[k]:.2f} -> {m[k]:5.1f} g (solid {vols[k] * RHO_ABS:5.1f} g)")
    for k, (mm, c) in other.items():
        print(f"   {k:10s}: {mm:5.1f} g")
    print(f"   magnets   : {nmag} x {MAGNET_G} g = {nmag * MAGNET_G:.1f} g (tabs {2 * MOUNT_STACK}, knob {3 * KNOB_STACK}, stator 1)")
    solid = sum(vols.values()) * RHO_ABS + nmag * MAGNET_G + sum(v[0] for v in other.values())
    print(f"TOTAL {total:.1f} g (all-solid upper bound {solid:.1f} g); CoG X {cog[0]:+.1f}, Y {cog[1]:+.1f}, Z {cog[2]:+.1f}")
    # rotating assembly: tube + plugs + knob (+ its caps) + knob magnets + screw; the far pin is stationary now
    knob_caps_g = 0.95 * m["caps"]          # caps are tiny; nearly all cap volume sits in the knob
    rotor_asm = m["panels"] + m["plugs"] + m["knob"] + knob_caps_g + 3 * KNOB_STACK * MAGNET_G + SCREW_G
    rx = (m["panels"] * cents["panels"].X + m["plugs"] * cents["plugs"].X + m["knob"] * cents["knob"].X
          + 3 * KNOB_STACK * MAGNET_G * mags["knob"][1][0] + SCREW_G * SCREW_X) / (rotor_asm - knob_caps_g)
    import trimesh
    I = 0.0
    for key, f in (("rotor", 1.0), ("knob", fill["knob"])):
        path = os.path.join(OUT, "stl", f"{key}.stl")
        bd.export_stl(parts[key], path)
        tm = trimesh.load(path)
        tm.density = RHO_ABS * f * 1e-3        # g/mm^3 -> kg/mm^3
        It = tm.moment_inertia                 # kg mm^2 about the mesh CoM
        com = tm.center_mass
        dy, dz = com[1] - YA, com[2] - ZA
        I += It[0, 0] + tm.mass * (dy * dy + dz * dz)
    I += 3 * KNOB_STACK * MAGNET_G * 1e-3 * KNOB_MAG_R ** 2
    inertia = I * 1e-6                         # kg m^2
    res = dict(parts_g={k: round(v, 1) for k, v in m.items()}, magnets_n=nmag, magnets_g=nmag * MAGNET_G, total_g=total,
               solid_upper_g=solid, cog=tuple(cog), rotor_assembly_g=rotor_asm, rotor_cog_x=rx,
               inertia_kgm2=inertia, panel_each_g=m["panels"] / 3, other_g={k: v[0] for k, v in other.items()})
    print(f"rotating assembly {rotor_asm:.1f} g, CoG X {rx:+.1f}; inertia about the axis {inertia * 1e6:.2f} e-6 kg m^2")
    rec("mass", res)
    return res


# ---------- 3D rigid-body limit LP (replaces the v3 2D LPs that lumped both tabs; VU-1 / MLH-1 / MA-2) ----------
LP_STEP, LP_K = 2.0, 12        # contact sampling step (mm) and friction-pyramid facets


def rect_boundary(x0, x1, y0, y1, step):
    xs, ys = np.arange(x0, x1 + 1e-9, step), np.arange(y0, y1 + 1e-9, step)
    return ([(x, y0) for x in xs] + [(x1, y) for y in ys] + [(x, y1) for x in xs[::-1]] + [(x0, y) for y in ys[::-1]])


def lid_flat_boundary(y0, y1, step):
    """Boundary of (lid-top flat: plan rounded rectangle offset by the top fillet) within Y y0..y1."""
    xf, rc = BOX_L / 2 - LID_TOP_FILLET, BOX_CORNER_R - LID_TOP_FILLET
    cx, cy = BOX_L / 2 - BOX_CORNER_R, BOX_CORNER_R
    pts = [(x, y0) for x in np.arange(-cx, cx + 1e-9, step)]
    pts += [(sx * (cx + rc * math.cos(math.radians(a))), cy + rc * math.sin(math.radians(a)))
            for sx in (-1, 1) for a in np.linspace(-90, 0, 31)]
    pts += [(sx * xf, y) for sx in (-1, 1) for y in np.arange(cy, y1 + 1e-9, step)]
    pts += [(x, y1) for x in np.arange(-xf, xf + 1e-9, step)]
    return pts


def lp_contacts(pads=True, mu_lid=MU_PAD, mu_box=MU_PU[0], step=LP_STEP):
    """(point, normal, mu): lid support (silicone strips, or the bare lip footprint) + chamfered tab backs on the box."""
    C = []
    if pads:
        for (xr, yr) in PADS:
            C += [((x, y, 0.0), (0, 0, 1.0), mu_lid) for x, y in rect_boundary(xr[0], xr[1], yr[0], yr[1], step)]
    else:
        C += [((x, y, 0.0), (0, 0, 1.0), mu_lid) for x, y in lid_flat_boundary(LID_TOP_FILLET, LIP_Y[1], step)]
    hw, zt = TAB_W / 2 - TAB_LEADIN, TAB_TOP - TAB_LEADIN
    for sx in (-1, 1):
        cx = sx * BASE_MAG_X
        pts = [(x, zt) for x in np.arange(cx - hw, cx + hw + 1e-9, step)]
        pts += [(cx + s2 * hw, z) for s2 in (-1, 1) for z in np.arange(TAB_ZC, zt + 1e-9, step)]
        pts += [(cx + hw * math.cos(math.radians(a)), TAB_ZC + hw * math.sin(math.radians(a))) for a in np.linspace(180, 360, 19)]
        C += [((x, 0.0, z), (0, -1.0, 0), mu_box) for x, z in pts]
    return C


def lp_matrix(C, k=LP_K):
    cols = []
    for p, n, mu in C:
        p, n = np.array(p), np.array(n)
        a = np.array([1.0, 0, 0]) if abs(n[0]) < 0.9 else np.array([0, 1.0, 0])
        t1 = np.cross(n, a)
        t1 /= np.linalg.norm(t1)
        t2 = np.cross(n, t1)
        me = mu * math.cos(math.pi / k)                     # inscribed pyramid (conservative)
        for i in range(k):
            f = n + me * (math.cos(2 * math.pi * i / k) * t1 + math.sin(2 * math.pi * i / k) * t2)
            cols.append(np.r_[f, np.cross(p, f)])
    return np.array(cols).T


def lp_fixed(W, cog, fn, fs):
    b = np.r_[np.array([0, 0, -W]), np.cross(cog, [0, 0, -W])]
    for sx in (-1, 1):
        q, f = np.array([sx * BASE_MAG_X, MOUNT_Y, MOUNT_Z]), np.array([0.0, fn, -fs])
        b += np.r_[f, np.cross(q, f)]
    return b


def lp_cap(A, fixed, d=None, pt=None, couple=None):
    from scipy.optimize import linprog
    if couple is not None:
        lw = np.r_[np.zeros(3), np.asarray(couple, float)]
    else:
        d = np.asarray(d, float) / np.linalg.norm(d)
        lw = np.r_[d, np.cross(np.asarray(pt, float), d)]
    r = linprog(np.r_[np.zeros(A.shape[1]), -1.0], A_eq=np.c_[A, lw], b_eq=-fixed,
                bounds=[(0, None)] * A.shape[1] + [(0, 1e4)], method="highs")
    if r.status != 0:
        return float("nan")
    return float("inf") if r.x[-1] > 9e3 else float(r.x[-1])


KNOB_XC = 0.5 * (KNOB_X[0] + KNOB_X[1])


def gesture_rows(det, w_rot, phi0, sense, d3, kdet):
    """Finger force needed along the switching path (force line through the lobe centre, fixed direction d3).
    Needed torque = detent restoring torque + friction incl. the finger's own load on the boss and near journal."""
    th = np.array(det["theta"])
    T = np.array(det["torque"])
    F = np.array(det["F"])
    exit_deg = 60 + det["dead_zone_halfwidth"]["dry"]
    d3 = np.asarray(d3, float) / np.linalg.norm(d3)
    rows = []
    for i, t in enumerate(th):
        if t > exit_deg or (t > 30 and t % 5):
            continue
        phi = math.radians(phi0 + sense * t)
        c = np.array([YA + KNOB_MAG_R * math.cos(phi), ZA + KNOB_MAG_R * math.sin(phi)])
        r = c - np.array([YA, ZA])
        arm = sense * (r[0] * d3[2] - r[1] * d3[1])
        if arm <= 0.5:
            continue
        f = 0.0
        for _ in range(40):
            axial = kdet * (-F[i, 0]) - f * d3[0]            # onto the boss (+); an inward (-X) push adds to it
            rad = np.array([kdet * F[i, 1], kdet * F[i, 2] - 0.5 * w_rot]) + 1.035 * f * d3[1:]
            fr = MU_ABS * abs(axial) * R_BOSS_MEAN + MU_ABS * np.linalg.norm(rad) * PIN_D / 2 + MU_ABS * 0.5 * w_rot * PIN_D / 2
            f = (kdet * T[i] + fr) / arm
        if f > 0.05:
            rows.append((t, f, np.array([KNOB_XC, *(c - KNOB_LOBE_R * d3[1:])]), d3))
    return rows


def gesture_margin(A, fixed, rows):
    worst = (float("inf"), None, None, None)
    for t, need, pt, d3 in rows:
        cap = lp_cap(A, fixed, d3, pt)
        if cap / need < worst[0]:
            worst = (cap / need, t, need, cap)
    return worst


def lean_dir(alpha, toward, beta=0.0):
    """Unit push: alpha from vertical toward -Y (toward = -1, forward) or +Y (+1, toward the driver); beta inward (-X)."""
    a, b = math.radians(alpha), math.radians(beta)
    d = np.array([-math.sin(b), toward * math.sin(a) * math.cos(b), -math.cos(a) * math.cos(b)])
    return d / np.linalg.norm(d)


GESTURES = {"next = cabin corner": (30.0, -1), "prev = windshield corner": (150.0, +1)}


def check_statics(mass, mount, det):
    section("6b. Mount statics: 3D rigid-body LP (pads + chamfered tab backs, unilateral contacts, Coulomb pyramids)")
    W = mass["total_g"] * G
    cog = np.array(mass["cog"])
    w_rot = mass["rotor_assembly_g"] * G
    m = mount[MOUNT_STACK]
    i80, i90 = TAB_IRREV[MOUNT_STACK]
    conds = {   # name: (pull, down, pads?, mu_lid, mu_box, detent factor)
        "20C typical": (m["typical_20C"]["pull"], m["typical_20C"]["down"], True, MU_PAD, MU_PU[0], 1.0),
        "80C weakest": (m["weakest_80C"]["pull"], m["weakest_80C"]["down"], True, MU_PAD, MU_PU[0], HOT),
        "90C weakest+irr": (m["weakest_90C"]["pull"], m["weakest_90C"]["down"], True, MU_PAD, MU_PU[0], HOT90 * N52_IRREV),
        "80C weakest, mu_box 0.25": (m["weakest_80C"]["pull"], m["weakest_80C"]["down"], True, MU_PAD, 0.25, HOT),
        "80C weakest, NO pads": (m["weakest_80C"]["pull"], m["weakest_80C"]["down"], False, MU_PU[0], MU_PU[0], HOT),
    }
    mats = {}
    out = {}
    lobe_c = {"cabin": (KNOB_XC, YA + KNOB_MAG_R * math.cos(math.radians(30)), ZA + KNOB_MAG_R * math.sin(math.radians(30)))}
    for cname, (fn, fs, pads, mul, mub, kdet) in conds.items():
        key = (pads, mul, mub)
        if key not in mats:
            mats[key] = lp_matrix(lp_contacts(pads, mul, mub))
        A = mats[key]
        fx = lp_fixed(W, cog, fn, fs)
        th = np.array(det["theta"])
        Fd = np.array(det["F"])
        sw = max(kdet * det["torque"][i] + detent_friction(kdet * Fd[i], w_rot) for i in range(len(th)) if th[i] <= 60)
        r = dict(pull=fn, down=fs, switch_torque=sw)
        r["pinch_next"] = lp_cap(A, fx, couple=(-1, 0, 0))
        r["pinch_prev"] = lp_cap(A, fx, couple=(1, 0, 0))
        r["push_top_fwd_mid_N"] = lp_cap(A, fx, (0, -1, 0), (0, YA, ZA + R_SW))
        r["push_top_fwd_knob_N"] = lp_cap(A, fx, (0, -1, 0), lobe_c["cabin"])
        r["push_inward_knob_N"] = lp_cap(A, fx, (-1, 0, 0), lobe_c["cabin"])
        r["braking_g"] = lp_cap(A, fx, (0, -1, 0), cog) / W
        r["lift_off_g"] = lp_cap(A, fx, (0, 0, 1), cog) / W          # downward acceleration that unloads it (lam / W)
        r["lateral_g"] = min(lp_cap(A, fx, (1, 0, 0), cog), lp_cap(A, fx, (-1, 0, 0), cog)) / W
        full = cname in ("20C typical", "80C weakest", "90C weakest+irr")
        gest = {}
        for gname, (phi0, sense) in GESTURES.items():
            for toward, lab in ((-1, "lean fwd"), (+1, "lean to driver")):
                alphas = (0, 10, 20, 25, 30, 35, 40, 45, 50) if full else (0, 20, 30, 40)
                for al in alphas:
                    if al == 0 and toward > 0:
                        continue
                    rows = gesture_rows(det, w_rot, phi0, sense, lean_dir(al, toward), kdet)
                    gest[(gname, lab if al else "vertical", al)] = gesture_margin(A, fx, rows)
            if full:
                rows = gesture_rows(det, w_rot, phi0, sense, lean_dir(30, -1, 20), kdet)
                gest[(gname, "fwd 30 + inward 20", 30)] = gesture_margin(A, fx, rows)
        r["gestures"] = {f"{g} | {l} {a}": v for (g, l, a), v in gest.items()}
        # lean limits (forward): margin 1.5 and 1.0, by linear interpolation over alpha
        lim = {}
        for gname in GESTURES:
            pts = sorted([(a, v[0]) for (g, l, a), v in gest.items() if g == gname and l in ("vertical", "lean fwd")])
            for thr in (1.5, 1.0):
                lim_a = None
                for (a0, m0), (a1, m1) in zip(pts, pts[1:]):
                    if m0 >= thr > m1:
                        lim_a = a0 + (a1 - a0) * (m0 - thr) / (m0 - m1)
                        break
                lim[f"{gname} fwd lean @{thr}x"] = (round(float(lim_a), 1) if lim_a is not None
                                                     else (f">{pts[-1][0]}" if pts[-1][1] >= thr else "<0"))
        r["lean_limits_deg"] = lim
        out[cname] = r
        print(f"--- {cname}: pull {fn:.2f} N, down {fs:.2f} N per point; W {W:.2f} N; lid support "
              f"{'pads mu %.2f' % mul if pads else 'bare lip mu %.2f' % mul}, box mu {mub}")
        print(f"   pinch next/prev {r['pinch_next']:.0f}/{r['pinch_prev']:.0f} N*mm (need {sw:.0f}, {min(r['pinch_next'], r['pinch_prev']) / sw:.2f}x); "
              f"push fwd at prism top {r['push_top_fwd_mid_N']:.2f} N, at knob {r['push_top_fwd_knob_N']:.2f} N; "
              f"inward push at knob {r['push_inward_knob_N']:.2f} N")
        print(f"   braking {r['braking_g']:.2f} g, lift-off needs {r['lift_off_g']:.2f} g downward, lateral {r['lateral_g']:.2f} g")
        for kk, v in r["gestures"].items():
            print(f"   {kk:44s}: {v[0]:5.2f}x  (worst at theta {v[1]}, need {v[2]:.2f} N, capacity {v[3]:.2f} N)")
        print(f"   forward-lean limits (deg): {lim}")
    # criteria at the design corner (80 C weakest, reversible + irreversible tab loss)
    w = out["80C weakest"]
    doc_next = [v[0] for k, v in w["gestures"].items() if k.startswith("next") and ("vertical" in k or "driver" in k)]
    doc_prev = [v[0] for k, v in w["gestures"].items() if k.startswith("prev") and ("vertical" in k or k.endswith("lean fwd 10") or k.endswith("lean fwd 20"))]
    vert = min(v[0] for k, v in w["gestures"].items() if "vertical" in k)
    crit = dict(documented_gestures_ge_1p5=bool(min(doc_next + doc_prev) >= 1.5), vertical_press_ge_2=bool(vert >= 2.0),
                pinch_ge_1p5=bool(min(w["pinch_next"], w["pinch_prev"]) / w["switch_torque"] >= 1.5),
                braking_ge_1p5g=bool(w["braking_g"] >= 1.5), lift_off_ge_3g=bool(w["lift_off_g"] >= 3.0))
    vrows = gesture_rows(det, w_rot, 30.0, -1, (0, 0, -1), 1.0)
    press = max(f for _, f, _, _ in vrows)
    det["press_force"] = press
    print(f"check 8 (80C weakest): documented gestures min {min(doc_next + doc_prev):.2f}x (>=1.5), vertical press {vert:.2f}x (>=2), "
          f"pinch {min(w['pinch_next'], w['pinch_prev']) / w['switch_torque']:.2f}x, braking {w['braking_g']:.2f} g, "
          f"lift-off {w['lift_off_g']:.2f} g -> {'PASS' if all(crit.values()) else 'FAIL'} {crit}")
    print(f"vertical press on the cabin corner at 20 C needs up to {press:.1f} N (path max incl. finger-load friction)")
    out["criteria"] = crit
    out["press_force_20C_N"] = press
    rec("statics", out)
    return out


def check_refill(mass, mount):
    section("6c. Refill (lid lifted with the plate on it) and removal")
    m = mount[MOUNT_STACK]
    W = mass["total_g"] * G
    cog = mass["cog"]
    slide = {mu: round(math.degrees(math.atan(mu)), 1) for mu in (MU_PU[0], MU_PU[1], MU_PAD)}
    tip = math.degrees(math.atan2(cog[1], cog[2]))
    lift = m["lift_table"]
    i80 = TAB_IRREV[MOUNT_STACK][0]
    extra_w = max(2 * (b + 0.35 * a) for h, a, b, c, d in lift) * HOT * i80
    extra_s = max(2 * (d + 0.35 * c) for h, a, b, c, d in lift)
    hang = TAB_BOTTOM - PARTING_Z
    relief = [math.degrees(math.asin(0.4 / (z - PARTING_Z))) for z in (BEAM_Z[1], BEAM_Z[0])]
    print(f"plate rides on the lid: weight on the pads, beam catches the lid skirt (0.4 mm) against sliding rearward")
    print(f"lid tilt: slides at {slide} deg (mu ABS/PU 0.35, 0.5; silicone pads {MU_PAD}), tips over the front edge at {tip:.0f} deg")
    print(f"rear-edge peel: the lid pivots on its front skirt bottom; the 0.4 mm beam relief closes after "
          f"{min(relief):.1f}-{max(relief):.1f} deg, then the tabs are levered off the base face -> lift level, never peel")
    print(f"extra force to lift the lid / pull the plate off (magnets shear + friction): {extra_w:.1f} (weak, 80 C) .. "
          f"{extra_s:.1f} (strong, 20 C) N, plus weight {W:.2f} N")
    print(f"tabs hang {-hang:.1f} mm below the parting line -> the lid cannot be set down flat with the plate on")
    rec("refill", dict(slide_deg=slide, tip_deg=tip, extra_lift_N=(extra_w, extra_s), weight_N=W,
                       tabs_below_parting=-hang, peel_relief_closes_deg=relief))


def beam_section_I():
    """Lip + glued beam (full-length bond) and the two separately (spot glue), bending in the X-Z plane."""
    lip = (LIP_Y[1] - LIP_Y[0], LIP_T, Z0 + LIP_T / 2)
    beam = (BEAM_Y[1] - BEAM_Y[0], BEAM_H, Z0 - BEAM_H / 2)
    A = [b * h for b, h, _ in (lip, beam)]
    zc = sum(a * z for a, (_, _, z) in zip(A, (lip, beam))) / sum(A)
    I = sum(b * h ** 3 / 12 + a * (z - zc) ** 2 for a, (b, h, z) in zip(A, (lip, beam)))
    return I, sum(b * h ** 3 / 12 for b, h, _ in (lip, beam))


def check_heat(mass, det):
    section("6d. Constant loads on plastic: detent couple loop (rotor equilibrium + cradle beam on the lid)")
    W = mass["rotor_assembly_g"] * G
    xr = mass["rotor_cog_x"]
    x_near, x_far = 0.5 * (NEAR_B[0] + NEAR_B[1]), 0.5 * (ROT_X[0] + FAR_PIN_X[1])   # far: pin engagement in the plug bore
    x_km, z_km = KNOB_X[0] + DET_FLOOR + 1.5 * KNOB_STACK, ZA - KNOB_MAG_R
    x_st, z_st = NEAR_B[1] - DET_FLOOR - 1.5, ZA - STATOR_R
    F0 = np.array(det["F"][0])
    temps = {"20C": 1.0, "80C": HOT, "90C": HOT90, "90C+irr": HOT90 * N52_IRREV}

    def rotor(fax, frad, zb, g=1.0):
        m12 = (z_km - ZA) * (-fax) - (x_km - x_near) * (-frad) + (zb - ZA) * fax
        m3 = (xr - x_near) * W
        nf = (m12 + m3 * g) / (x_far - x_near)
        return frad + W * g - nf, nf, -m12 / m3 - 1.0          # last: vertical car acceleration (g, up +) where nf = 0
    jr = {}
    for tl, k in temps.items():
        fax, frad = k * det["axial_rest"], -k * F0[2]
        for zb in (ZA - BOSS_R, ZA):
            jr[(tl, zb)] = rotor(fax, frad, zb)
    print("rotor journal forces (on the rotor, up +): Nf < 0 = far bore pressed UP onto the stationary pin")
    for (tl, zb), (nn, nf, flip) in jr.items():
        print(f"   {tl:8s} boss pressure at Z {zb:4.1f}: near {nn:+.2f} N, far {nf:+.3f} N; far force changes sign at a vertical "
              f"car acceleration of {flip:+.2f} g")
    # cradle (lip + beam) on a compression-only foundation under the pads, Euler-Bernoulli FE
    n = 385
    x = np.linspace(LIP_X[0], LIP_X[1], n)
    h = x[1] - x[0]
    node = lambda xx: int(round((xx - x[0]) / h))
    sup = [i for i in range(n) if abs(x[i]) <= max(abs(PADS[1][0][0]), abs(PADS[1][0][1]))]

    def solve(EI, f, kf=300.0):
        K = np.zeros((2 * n, 2 * n))
        ke = EI / h ** 3 * np.array([[12, 6 * h, -12, 6 * h], [6 * h, 4 * h * h, -6 * h, 2 * h * h],
                                     [-12, -6 * h, 12, -6 * h], [6 * h, 2 * h * h, -6 * h, 4 * h * h]])
        for e in range(n - 1):
            idx = [2 * e, 2 * e + 1, 2 * e + 2, 2 * e + 3]
            K[np.ix_(idx, idx)] += ke
        active = set(sup)
        for _ in range(200):
            Kt = K.copy()
            for i in active:
                Kt[2 * i, 2 * i] += kf * h
            u = np.linalg.solve(Kt + np.eye(2 * n) * 1e-12, f)
            w = u[0::2]
            new = set(i for i in sup if w[i] < 0) or {sup[int(np.argmin([w[i] for i in sup]))]}
            if new == active:
                break
            active = new
        return w

    def loads(k, zb):
        fax, frad = k * det["axial_rest"], -k * F0[2]
        nn, nf, _ = rotor(fax, frad, zb)
        f = np.zeros(2 * n)
        cr, fb = REPORT["mass"]["parts_g"]["cradle"], REPORT["mass"]["parts_g"]["front_bar"]
        f[0::2] += -(0.5 * cr + fb) * G / (x[-1] - x[0]) * h          # lip + front bar, uniform
        for xx in (-93.5, 93.5):
            f[2 * node(xx)] += -0.25 * cr * G                         # end blocks
        fs = REPORT["mount_magnets"]["weakest_80C"]["down"]
        for xx in (-BASE_MAG_X, BASE_MAG_X):
            f[2 * node(xx)] += -fs - MOUNT_STACK * MAGNET_G * G
        f[2 * node(x_st)] += frad - MAGNET_G * G                     # stator pulled up toward the knob magnet
        f[2 * node(x_near)] += -nn
        f[2 * node(x_far)] += -nf
        f[2 * node(x_st) + 1] += -fax * (z_st - zb)                   # stator +X at z_st, boss -X at zb
        return f
    I_glued, I_spot = beam_section_I()
    lifts = {}
    for tl in ("20C", "90C", "90C+irr"):
        for zb in (ZA - BOSS_R, ZA):
            f = loads(temps[tl], zb)
            for lab, I in (("glued", I_glued), ("spot", I_spot)):
                for E in (2000.0, 300.0, 100.0):
                    w = solve(E * I, f)
                    lifts[(tl, zb, lab, E)] = (max(w[sup].max(), 0.0), w[-1])
    print(f"cradle lip + beam (Z {BEAM_Z[0]:.1f}..{BEAM_Z[1]:.1f}): I {I_glued:.0f} mm^4 glued full length, {I_spot:.0f} if only spot-glued")
    for tl in ("20C", "90C", "90C+irr"):
        print(f"   {tl:8s} near-end lip lift-off over the pads (boss low edge / centre), mm: " + "; ".join(
            f"{lab} E{E:.0f}: {lifts[(tl, ZA - BOSS_R, lab, E)][0]:.3f}/{lifts[(tl, ZA, lab, E)][0]:.3f}"
            for lab in ("glued", "spot") for E in (2000.0, 300.0, 100.0)))
    print(f"detent floors: {det['floor']['stress_MPa']:.1f} MPa; mount magnets: pressed onto a 0.8 mm floor backed by the box face")
    rec("heat", dict(journals={f"{k[0]} zb{k[1]:.1f}": v for k, v in jr.items()}, I_glued=I_glued, I_spot=I_spot,
                     lip_lift_mm={f"{k[0]} zb{k[1]:.1f} {k[2]} E{k[3]:.0f}": v[0] for k, v in lifts.items()}))


# =====================================================================================
# 7. Optional renders (pyvista off-screen); example number from the brief only
# =====================================================================================
LOGO_PLACEHOLDER = "YU7 PRO"   # logo face is a placeholder; final art = YU7 side-silhouette line + "YU7 PRO" (doc 4.6 rules)


def build_text_solids(typo, numbers=("13900139000", "13800138000")):
    """White digits for the render only (brief's example numbers), 0.4 mm proud of each face; proportional 3-4-4 layout."""
    em = typo["em"]
    solids = []
    faces = list(zip(numbers, (150.0, 270.0)))      # A at the front, B at the bottom (hidden)
    s_mid = CHAMFER + (FACE_FLAT - typo["h_band"]) / 2
    for text, nrm in faces:
        rot = nrm - 150.0
        n = np.array([0.0, math.cos(math.radians(nrm)), math.sin(math.radians(nrm))])
        upv = np.array([0.0, math.cos(math.radians(60 + rot)), math.sin(math.radians(60 + rot))])
        fbv = np.array([0.0, YA + R_C * math.cos(math.radians(210 + rot)), ZA + R_C * math.sin(math.radians(210 + rot))])
        base_pt = fbv + (s_mid - typo["ymin"] * em) * upv + n * 0.01      # baseline on the face
        centres = number_layout(text, typo)["centres"]
        for i, ch in enumerate(text):
            t = bd.Text(ch, font_size=em, font_path=FONT, align=(bd.Align.NONE, bd.Align.NONE))
            t = bd.scale(t, by=(DIGIT_COND, 1, 1))
            bb = t.bounding_box()
            base_local = bb.min.Y - typo["bounds"][ch][1] * em
            t = bd.Pos(-(bb.min.X + bb.max.X) / 2, -base_local) * t
            pl = bd.Plane(origin=tuple(base_pt + np.array([centres[i], 0, 0])), x_dir=(1, 0, 0), z_dir=tuple(n))
            solids.append(bd.extrude(pl * t, 0.4))
    # logo face (back = cabin side at rest): placeholder text, upright when it is the displayed face
    nrm = 30.0
    n = np.array([0.0, math.cos(math.radians(nrm)), math.sin(math.radians(nrm))])
    c = np.array([0.0, YA + R_IN * math.cos(math.radians(nrm)), ZA + R_IN * math.sin(math.radians(nrm))])
    t = bd.Text(LOGO_PLACEHOLDER, font_size=12.0 / 0.72, font_path=FONT, align=(bd.Align.CENTER, bd.Align.CENTER))
    pl = bd.Plane(origin=tuple(c + n * 0.01), x_dir=(1, 0, 0), z_dir=tuple(n))
    solids.append(bd.extrude(pl * t, 0.4))
    return solids


def section_drawing(typo):
    """Y-Z section at the middle of the plate with sightlines (matplotlib)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(9, 6))
    box = plt.Polygon([(0, 0), (60, 0), (60, -50), (0, -50)], closed=True, fc="#5a2f45", ec="k", lw=0.5, alpha=0.9)
    ax.add_patch(box)
    ax.plot([0, 60], [PARTING_Z, PARTING_Z], "k--", lw=0.5)
    ax.add_patch(plt.Polygon([(-60, 0), (TONGUE_Y, 0), (TONGUE_Y, -12), (-60, -12)], fc="#6b3a52", ec="k", lw=0.5))
    ax.add_patch(plt.Polygon(np.array(end_block_profile()), fc="#c8d3e6", ec="#0C2340", lw=0.8, ls=":"))
    for (_, yr) in PADS:
        ax.add_patch(plt.Polygon([(yr[0], 0), (yr[1], 0), (yr[1], PAD_T), (yr[0], PAD_T)], fc="#b0b0b0", ec="k", lw=0.3))
    ax.add_patch(plt.Polygon([(LIP_Y[0], Z0), (LIP_Y[1], Z0), (LIP_Y[1], Z0 + LIP_T), (LIP_Y[0], Z0 + LIP_T)], fc="#0C2340"))
    ax.add_patch(plt.Polygon([(BEAM_Y[0], BEAM_Z[0]), (BEAM_Y[1], BEAM_Z[0]), (BEAM_Y[1], BEAM_Z[1]), (BEAM_Y[0], BEAM_Z[1])],
                             fc="#0C2340"))
    ax.add_patch(plt.Polygon([(TAB_Y[0], TAB_TOP), (0, TAB_TOP), (0, TAB_BOTTOM + TAB_LEADIN), (-TAB_LEADIN, TAB_BOTTOM),
                              (TAB_Y[0], TAB_BOTTOM)], fc="#0C2340", alpha=0.6))
    ax.add_patch(plt.Polygon(np.array(tri_pts(R_IN, CHAMFER)), fc="#0C2340", ec="k", lw=0.5))
    ax.add_patch(plt.Polygon(np.array(tri_pts(R_IN - T_PANEL, 0)), fc="#d9d9d9", ec="k", lw=0.3))
    ax.add_patch(plt.Polygon(np.array(knob_profile()), fill=False, ec="#489FDF", lw=1.2, ls="--"))
    ax.add_patch(plt.Circle((YA, ZA), R_SW, fill=False, ec="gray", lw=0.6, ls=":"))
    ax.plot([MOUNT_Y], [MOUNT_Z], "o", color="#489FDF")
    ax.plot([0], [BASE_MAG_Z], "x", color="k")
    fb = np.array([YA - S_SIDE / 2, ZA - R_IN])
    up = np.array([0.5, S3 / 2])
    s_mid = CHAMFER + (FACE_FLAT - typo["h_band"]) / 2
    p0, p1 = fb + s_mid * up, fb + (s_mid + typo["h_band"]) * up
    ax.plot(*np.c_[p0, p1], color="white", lw=4)
    for e in (25, 45):
        d = np.array([-math.cos(math.radians(e)), math.sin(math.radians(e))])
        ax.plot(*np.c_[p0, p0 + 60 * d], color="#489FDF", lw=0.8)
        ax.text(*(p0 + 60 * d), f"{e} deg", fontsize=8)
    ax.axvline(RULE_Y, color="r", lw=0.8, ls="--")
    ax.text(RULE_Y + 0.5, -45, "Y = -35 rule", color="r", fontsize=8)
    ax.set_xlim(-55, 60)
    ax.set_ylim(-48, 62)
    ax.set_aspect("equal")
    ax.set_xlabel("Y (mm, windshield <- -> cabin)")
    ax.set_ylabel("Z (mm, lid top = 0)")
    ax.set_title("v3.1 section at mid-length (grey: silicone pads; dotted: end block; dashed: knob outline)")
    os.makedirs(os.path.join(OUT, "renders"), exist_ok=True)
    fig.savefig(os.path.join(OUT, "renders", "v3_section_yz.png"), dpi=130, bbox_inches="tight")
    plt.close(fig)


def render(parts, typo):
    import pyvista as pv
    pv.OFF_SCREEN = True
    txt = build_text_solids(typo)
    white = txt[0]
    for s in txt[1:]:
        white = white + s
    bd.export_stl(white, os.path.join(OUT, "stl", "_render_digits.stl"))
    keys = ("cradle", "front_bar", "rotor", "knob", "far_pin", "lid", "base", "caps", "pads")
    meshes = {k: pv.read(os.path.join(OUT, "stl", f"{k}.stl")) for k in keys}
    meshes["digits"] = pv.read(os.path.join(OUT, "stl", "_render_digits.stl"))
    col = {"cradle": "#0C2340", "front_bar": "#0C2340", "rotor": "#0C2340", "knob": "#16325c", "far_pin": "#0C2340",
           "lid": "#5a2f45", "base": "#4e2a3d", "caps": "#489FDF", "pads": "#2b2b2b", "digits": "#FFFFFF"}
    tongue = pv.Box(bounds=(-160, 160, -140, TONGUE_Y, -60, 0))
    views = {"outside_35deg": ((60, -900, 640), (0, 10, 10)), "outside_25deg": ((-250, -900, 450), (0, 10, 10)),
             "cabin_side": ((350, 520, 260), (0, 20, 5)), "knob_end": ((420, 60, 120), (90, 12, 15))}
    os.makedirs(os.path.join(OUT, "renders"), exist_ok=True)
    for name, (eye, focus) in views.items():
        pl = pv.Plotter(off_screen=True, window_size=(1600, 1000))
        pl.set_background("#d9d9d9")
        for k, mesh in meshes.items():
            pl.add_mesh(mesh, color=col[k], smooth_shading=False)
        if name.startswith("outside"):
            pl.add_mesh(tongue, color="#6b3a52")
        pl.camera.position, pl.camera.focal_point, pl.camera.up = eye, focus, (0, 0, 1)
        pl.camera.view_angle = 14
        pl.screenshot(os.path.join(OUT, "renders", f"v3_render_{name}.png"))
        pl.close()
    print("renders written to", os.path.join(OUT, "renders"))


# =====================================================================================
def summary():
    section("SUMMARY v3.1 (80C = reversible + irreversible tab loss; detent worst = 80C x 0.85)")
    R = REPORT
    t, c, d, m, mm = R["typography"], R["cad"], R["detent"], R["mass"], R["mount_magnets"]
    st = R["statics"]
    w, ty, h90 = st["80C weakest"], st["20C typical"], st["90C weakest+irr"]
    g = lambda r, key: r["gestures"][key][0]
    rows = [
        ("digits flat / round (mm)", f"{t['flat_height']:.2f} / {t['max_height']:.2f}  (MiSans Bold, em {t['em']}, condense {t['condense']})"),
        ("number layout", f"proportional: ink gap {R['layout']['examples'][0]['inner_gap']:.1f}, group gap {R['layout']['examples'][0]['group_gap']:.1f} mm (ratio {R['layout']['examples'][0]['ratio']:.1f}); fixed-cell fallback"),
        ("prism side / sweep R / axis", f"{S_SIDE} / {R_SW:.3f} / Y {YA} Z {ZA}"),
        ("length / max height / min Y", f"{c['envelope']['length']} / {c['envelope']['z_max_swept']} / {c['envelope']['y_min']} (rule margin {c['envelope']['margin_to_rule']})"),
        ("sweep clearance lip / end gaps", f"{c['sweep']['rotor_to_lip_min']} / near {c['clearances']['rotor-cradle(min, incl. inner thrust ring)']} far {c['sweep']['rotor_to_far_block_min']}; knob face {c['sweep']['knob_body_to_near_block_min']}"),
        ("visibility", f"100 % for elevation 15-45 deg, yaw +-45 deg; first knob-side occlusion at {R['visibility']['first_occlusion'][25]['toward_knob']} deg (25 deg elevation)"),
        ("mass", f"{m['total_g']:.1f} g CAD estimate (solid {m['solid_upper_g']:.1f}); {m['magnets_n']} magnets; CoG Y {m['cog'][1]:+.1f} Z {m['cog'][2]:+.1f}"),
        ("mount stack / pull / down per pt", f"stack {mm['stack']}: 20C {mm['pull_20C'][0]:.2f}-{mm['pull_20C'][1]:.2f} / {mm['down_20C'][0]:.2f}-{mm['down_20C'][1]:.2f} N; 80C weakest {mm['weakest_80C']['pull']:.2f}/{mm['weakest_80C']['down']:.2f}; 90C {mm['weakest_90C']['pull']:.2f}/{mm['weakest_90C']['down']:.2f}"),
        ("detent", f"peak {d['peak']:.1f} N*mm (80C {d['peak_hot']:.1f}, worst {d['peak_hot_worst']:.1f}), k {d['stiffness']:.2f}/deg, friction {d['friction']['total']:.1f} (ratio {d['ratio']:.2f}), stop +-{d['stop_error']:.1f} deg"),
        ("dead zone / snap (dry)", f"+-{d['dead_zone_halfwidth']['dry']:.1f} deg / " + str(list(R['snap'].values())[0])),
        ("switching effort", f"pinch {d['switch_torque']:.0f} N*mm or up to {st['press_force_20C_N']:.1f} N straight down on a corner"),
        ("pinch capacity (need)", f"80C weakest {min(w['pinch_next'], w['pinch_prev']):.0f} ({w['switch_torque']:.0f}), 20C typical {min(ty['pinch_next'], ty['pinch_prev']):.0f} ({ty['switch_torque']:.0f}) N*mm"),
        ("gestures 80C weakest", f"next vertical {g(w, 'next = cabin corner | vertical 0'):.2f}x, next toward driver 45 {g(w, 'next = cabin corner | lean to driver 45'):.2f}x, prev vertical {g(w, 'prev = windshield corner | vertical 0'):.2f}x, prev fwd 20 {g(w, 'prev = windshield corner | lean fwd 20'):.2f}x"),
        ("forward-lean limits 80C weakest", str(w['lean_limits_deg'])),
        ("push fwd at prism top", f"80C weakest {w['push_top_fwd_mid_N']:.2f} N, typical {ty['push_top_fwd_mid_N']:.2f} N; no pads {st['80C weakest, NO pads']['push_top_fwd_mid_N']:.2f} N"),
        ("braking / lift-off / lateral", f"{w['braking_g']:.2f} g / {w['lift_off_g']:.2f} g downward / {w['lateral_g']:.2f} g (80C weakest); 90C+irr {h90['braking_g']:.2f} / {h90['lift_off_g']:.2f} / {h90['lateral_g']:.2f}"),
        ("check 8 criteria", str(st['criteria'])),
        ("refill (plate rides on lid)", f"slides at {R['refill']['slide_deg']} deg tilt, tips at {R['refill']['tip_deg']:.0f} deg; extra lift {R['refill']['extra_lift_N'][0]:.1f}-{R['refill']['extra_lift_N'][1]:.1f} N"),
        ("detent loop (far journal)", ", ".join(f"{k}: {v[1]:+.2f} N flips at {v[2]:+.2f} g" for k, v in R['heat']['journals'].items() if k.startswith(('20C', '90C+irr')))),
        ("configuration paths", "install, rotor drop-in, far pin, knob, lid lift: all 0 mm^3 intersection" if all(
            v == 0 for k in ("path_install", "path_rotor", "path_far_pin", "path_knob", "lid_lift") for v in c[k].values()) else "CHECK FAILED"),
    ]
    for k, v in rows:
        print(f"  {k:32s} {v}")


def main():
    t0 = time.time()
    check_section()
    typo = check_typography(FACE_FLAT)
    check_layout(typo)
    parts, mags = build_parts()
    export_stl(parts, mags)
    check_cad(parts, mags)
    check_visibility(typo)
    br52 = calibrate_br()
    print(f"\n[magnet model] Br_eff calibrated to 8.6 N @1.2 mm: {br52:.4f} T")
    rec("br_eff", br52)
    mass = check_masses(parts)
    mount = check_mount(br52)
    det, th, T, tf_tabs = check_detent(br52, mass)
    snap_dynamics(det, th, T, tf_tabs, mass["inertia_kgm2"])
    check_statics(mass, mount, det)
    check_refill(mass, mount)
    check_heat(mass, det)
    if "--render" in sys.argv:
        render(parts, typo)
        section_drawing(typo)
    summary()
    with open(os.path.join(OUT, "report.json"), "w") as f:
        json.dump(REPORT, f, indent=1, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o))
    print(f"\nall checks done in {time.time() - t0:.0f} s; report: {OUT}/report.json")


if __name__ == "__main__":
    main()
