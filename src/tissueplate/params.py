"""All dimensions of the v3.4 plate (docs/2026-1021-1141-parking-plate-v3.4-design.md, on top of the v3.3 design
docs/2026-1017-0046-yu7-parking-plate-v3.3-design.md and the v3.2 spec
docs/2026-1013-2027-yu7-parking-plate-v3.2-design.md), one source.

Inputs are dataclass fields (spec values, some overridable from config.toml); everything derived is a
property so it can never go stale. Units: mm, N, g. Coordinates (spec 4.1): X along the box, +X = driver
side; Y from the windshield to the cabin, box front face Y = 0; Z up, lid top Z = 0. Rotation theta is
about +X (counter-clockwise seen from the driver side).
"""
import hashlib
import math
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]
FONT_PATH = PROJECT_DIR / "fonts" / "MiSans-Bold.ttf"        # not in the repository (README: download MiSans)
FONT_URL = "https://hyperos.mi.com/font/download"
FONT_SHA256 = "d0c1d327952ed935e86fb78a97a6c182b44f2c2b08777326786b1f8b26d1fe1e"     # the author's MiSans 4.009
# TISSUEPLATE_OUT_DIR: another output folder (the web UI builds into out/web/<job>); every output path below and in
# the other modules derives from OUT_DIR at import time
OUT_DIR = (Path(os.environ["TISSUEPLATE_OUT_DIR"]).resolve() if os.environ.get("TISSUEPLATE_OUT_DIR")
           else PROJECT_DIR / "out")
V31_SCRIPT = PROJECT_DIR / "concept" / "v3.1" / "verify_v3_1.py"
FINAL_LOGO = PROJECT_DIR / "concept" / "v3.3" / "logo" / "final" / "geometry.json"   # v3.3 2.6: 0.7 round tips
# "speed_dramatic" is the name the spec 7 config example still uses; it was finalised as "final" (4.6);
# "none": face L carries only [text] l (v3.4 6.5), no art file
LOGO_FILES = {"final": FINAL_LOGO, "speed_dramatic": FINAL_LOGO, "none": None}

# AMS slots (spec 5): extruder index and display colour per filament
COLOURS = {
    "white": {"slot": 1, "hex": "#FFFFFF", "filament": "Bambu ABS White 40100"},
    "azure": {"slot": 2, "hex": "#489FDF", "filament": "Bambu ABS Azure 40601"},
    "navy": {"slot": 3, "hex": "#0C2340", "filament": "Bambu ABS Navy Blue 40602"},
}

# rotor faces: A is displayed at rest (outward normal 150 deg: facing the windshield, 30 deg above
# horizontal); "next" (A -> B -> Logo) turns the rotor by -120 deg, so face k of FACE_ORDER rests at
# DISPLAY_NORMAL - k * NEXT_TURN: A 150 (front), B 270 (bottom), L 30 (cabin side).
DISPLAY_NORMAL = 150.0
NEXT_TURN = -120.0
FACE_ORDER = ("A", "B", "L")
FACE_NORMALS = {name: (DISPLAY_NORMAL - k * NEXT_TURN) % 360.0 for k, name in enumerate(FACE_ORDER)}


@lru_cache(maxsize=1)
def font_is_authors():
    """True when fonts/MiSans-Bold.ttf is the author's MiSans 4.009; another version is accepted, its layouts may
    differ slightly (v3.4 7 item 5)."""
    return hashlib.sha256(FONT_PATH.read_bytes()).hexdigest() == FONT_SHA256


@dataclass(frozen=True)
class Params:
    # ---------------- box (spec 2.2 measurements; config [box]) ----------------
    box_l: float = 172.5            # nameplate length
    box_d: float = 107.35           # lid outer width
    box_h: float = 77.5
    box_corner_r: float = 18.0      # plan-view corner radius (est. +-1.5)
    top_fillet: float = 2.5         # lid top-edge fillet (est. 2-3)
    skirt: float = 13.62            # lid top -> parting line
    mag_from_end: float = 47.04     # front base magnet centre -> nearest end face
    mag_below_top: float = 21.07    # front base magnet centre below the lid top
    lid_mag_below_top: float = 9.0  # lid magnet centre below the lid top (v3.3 2.1: single magnet + caliper);
                                    # X assumed = the base magnet's (+-base_mag_x)
    tongue_y: float = -38.36        # leather tongue nose at lid-top height (measured in the author's YU7)
    rule_y: float = -35.0           # hard rule: every part at Y >= -35 (from the author's YU7)

    # ---------------- anti-slip zones under the lip (4.3; v3.4: 1.2 mm 3M double-sided tape) ----------------
    # as built (10-18): the v3.3 parts, drawn on 0.5 pads, sit on the 1.2 tape, so mount_delta, upper_delta and
    # tab_bottom are the v3.3 values + 0.7 and C / F keep their v3.3 shape; change the four together or F changes
    pad_t: float = 1.2
    pad_zones: tuple = (((-72.0, 72.0), (3.5, 12.5)), ((-82.0, 82.0), (17.0, 27.0)))   # ((X), (Y)) front, rear

    # ---------------- rotor (4.4) ----------------
    side: float = 30.0              # sharp equilateral side
    chamfer: float = 1.2            # corner land: chamfer leg along each face
    panel_t: float = 2.4
    rotor_x: tuple = (-90.5, 90.5)  # tube length 181.0
    plug_len_near: float = 16.0
    plug_len_far: float = 10.0
    plug_clr: float = 0.2           # plug -> tube inner face
    plug_chamfer: float = 0.8
    lip_t: float = 2.0
    rad_clr: float = 1.2            # target radial clearance sweep circle -> lip top
    axis_y: float = 12.0

    # ---------------- end blocks, bearings, knob axle (4.4, 4.5) ----------------
    far_block_x: tuple = (-96.0, -91.0)
    near_block_x: tuple = (91.0, 96.0)
    boss_h: float = 0.6             # knob thrust boss (keep >= 0.6: two 0.8 floors may creep 0.12 each)
    boss_r: float = 4.6
    inner_ring_h: float = 0.3       # thrust ring on the near block inner face: near gap 0.2
    hole_near: float = 5.90         # running teardrop (knob journal); plate-0 strip H pick, overlaps the CAD journal
    hole_far: float = 5.95          # running teardrop (far pin journal, P turns with the rotor, v3.4); one strip H
                                    # grade looser than hole_near
    pin_d: float = 6.0              # knob journal and far pin journal
    far_hex_af: float = 5.05        # far pin hex in the EF socket (far_socket_af): 0.15 clearance as plate-0 peg AF
                                    # 5.00 in the AF 5.15 EN (goes in, does not wobble); no screw at the far end
    far_socket_af: float = 5.20     # EF hex socket; not a config key: P is tuned with far_hex_af
    far_socket_depth: float = 8.5   # EF hex socket depth (floor 1.5, as the old Ø6.1 bore)
    far_tip_chamfer: float = 0.3    # 45 deg at the P hex tip: the bed side in the hex-down print, lead-in into EF
    tear_top: float = 1.15          # teardrop roof cut flat at 1.15 r
    hex_af: float = 5.0
    hex_socket_af: float = 5.20     # EN only (config [fit] hex_socket_af, v3.4); was 5.15 (plate 0); 10-16 the
                                    # production knob jammed in it: +0.05 on the EN side (user), the hex stays 5.0
                                    # for strength (knob-cooling design doc)
    hex_key: float = 0.86           # key flat at 0.86 x corner radius (K / EN; the far hex has none, v3.4)
    knob_hex_end: float = 81.8      # hex tip = blind socket bottom (sets the near gap)
    screw_bore: float = 3.3         # M3x25 self-tapper on the axis
    screw_pilot: float = 2.5
    screw_len: float = 25.0         # M3 x 25: length under the head
    screw_head_k: float = 2.4       # M3 pan head height (not measured: v3.3 design value; config [hardware])
    screw_head_d: float = 6.4       # knob counterbore Ø
    counterbore_v32: float = 3.0    # v3.2 counterbore depth, kept when the head is low (k <= 2.0)
    pilot_depth_v32: float = 6.5    # v3.2 EN pilot depth (0.8 EN floor under it)
    pilot_floor_min: float = 0.4    # thinnest EN floor under the deepened pilot (v3.3 2.4)
    hub_cap_d: float = 6.40         # plate 0b pick (line-to-line in the Ø6.4 counterbore); glue dot, pried out later
    hub_cap_t: float = 0.8          # v3.3: twice as thick (user), flush with the knob face
    hub_cap_gap: float = 0.2        # hub cap underside -> M3 head

    # ---------------- detent and knob (4.5) ----------------
    magnet_d: float = 8.0           # N52 8 x 3
    magnet_t: float = 3.0
    mag_pocket_d: float = 8.3
    det_floor: float = 0.8          # printed floor between each detent magnet and the gap
    knob_stack: int = 2             # magnets per knob lobe
    knob_cap_t: float = 0.4         # review m4 (was 0.6): leaves knob_pocket_allowance behind the cap
    knob_pocket_allowance: float = 0.2   # magnet tolerance + floor-bridge sag; knob thickness stays 7.4
    knob_mag_r: float = 11.0
    knob_lobe_r: float = 5.6
    knob_phi: tuple = (30.0, 150.0, 270.0)   # lobes = the nabla corners at rest
    stator_r: float = 11.5          # 0.5 outward offset -> radial preload
    stator_phi: float = 270.0
    tab_cap_d: float = 8.25         # tab pocket caps, plate 0b pick (v3.2: 8.1, "a bit loose")
    knob_cap_d: float = 8.25        # knob pocket caps, plate 0b pick (all three lobes the same)
    cap_notch_d: float = 1.0        # one half-circle pry notch at the rim of every cap (plate 0b coupons)
    spacer_d: float = 8.4           # stator spacer S, press fit in the Ø8.3 pocket (review M3: carries the
                                    # reversed stator force while shifting; was 8.2 = the caps)
    rib_r: float = 1.0              # tactile ribs on the knob flats
    rib_proud: float = 0.8          # A (1 rib) and B (2 ribs)
    rib_b_spacing: float = 8.0
    bar_proud: float = 0.6          # Logo: one wide bar
    bar_length: float = 8.0         # between the bar's end-circle centres

    # ---------------- cradle lip, front bar, tabs (4.3; v3.3 2.1, 2.5) ----------------
    mount_stack: int = 2            # magnets per stack; each tab has a lower and an upper stack
    magnet_slot_t: float = 3.2      # pocket depth allowance per tab magnet
    mount_floor: float = 0.8        # pocket floor toward the box
    cap_t: float = 0.8              # tab cap
    lip_back_y: float = 28.0
    beam_h: float = 10.0
    beam_relief: float = 0.4        # beam -> lid skirt gap
    tab_w: float = 20.0
    tab_bottom: float = -39.3       # config; measured free to -40 in the author's YU7; as built -40 + 0.7 (tape)
    tab_top_below_lip: float = 3.0
    tab_leadin: float = 1.5         # 45 deg lead-in on the sides and the round bottom of the tab back face (v3.3:
                                    # not on the top edge)
    mount_delta: float = 2.45       # lower stack centre above the base magnet point (as built 1.75 + 0.7)
    upper_delta: float = 2.45       # upper stack centre above the lid magnet point (v3.3 2.1: 1.75; as built + 0.7)
    pocket_wall_min: float = 1.2    # magnet pocket wall rule (2.3)
    front_chamfer: float = 0.4      # bed-side front face outline

    # ---------------- typography and layout (4.6) ----------------
    condense: float = 0.86
    face_margin: float = 3.0        # ink band to the face-flat edges, top and bottom
    cell_gap: float = 1.8           # fixed-cell layout
    group_gap: float = 3.5
    end_margin_near: float = 2.0    # worst-case cell box -> rotor end at the knob end
    layout_shift: float = -1.0      # cell box shifted toward -X (first digit is always a narrow '1')
    ink_gap: float = 2.8            # proportional layout
    ink_gap_min: float = 1.8
    group_gap_max: float = 9.0
    layout: str = "proportional"
    layer_h: float = 0.2
    white_layers: int = 4           # white inlay depth = layers x layer_h
    azure_layers: int = 4           # azure inlay depth (spec 0.6-0.8)
    logo: str = "final"
    logo_simplify_tol: float = 0.002   # Douglas-Peucker tolerance on the logo rings

    # ---------------- accents named in spec 4.2 / 4.5 / 4.7 (sizes chosen here, v3.1 had none) -------------
    beam_line_w: float = 1.2        # azure line on the beam front face (>= 0.8 line rule, 4.6)
    beam_line_seam: float = 0.8     # v3.3 2.1: navy seam line -> beam front chamfer
    beam_line_top_seam: float = 1.0     # v3.3 option E: the line hangs this far below the beam top chamfer edge
    beam_line_pocket_gap: float = 0.8   # option E: navy gap line -> upper pocket mouth; the first layer widens the
                                        # hole 0.15 (elephant foot), so 0.5 / 0.6 lose the navy there (review E)
    knob_letter_size: float = 8.0   # MiSans Bold "A" / "B" font size (4.6 hard minimum 8 mm)
    knob_letter_seam: float = 0.8   # navy seam to caps / knob edge (4.6 seam rule)

    # ---------------- print aid (knob-cooling design doc) ----------------
    # sacrificial tube Q printed next to the knob, as tall as it: alone above the 8 mm front bar the knob got
    # 2-3 s layers at the 20 mm/s floor (jammed in EN, 10-16); Q with its own 20 mm/s walls fills ~11.5 s per
    # layer, so K prints at 200 mm/s with >= 11.5 s to cool, as on plate 0. Ø20 sits on the floor, Ø16 fails.
    cooling_tube_d: float = 25.0
    cooling_tube_wall: float = 1.3

    # ---------------- materials and magnet model inputs (used by the checks) ----------------
    rho_abs: float = 1.05e-3        # g/mm^3
    rho_silicone: float = 1.2e-3    # pad zones: silicone (v3.3), kept as an upper bound for the 3M tape
    magnet_g: float = 1.13
    screw_g: float = 1.4
    screw_x: float = 89.0
    g_newton_per_gram: float = 9.81e-3
    mu_abs: float = 0.35
    mu_ptfe: float = 0.15
    mu_pu: tuple = (0.35, 0.5)      # ABS on PU leather (est.)
    mu_pad: float = 0.8             # pad zones on PU leather (est., silicone; v3.4 tape: as if not stuck)
    hot80: float = 0.861            # reversible Br loss of both magnets at 80 C
    hot90: float = 0.839
    n52_irrev: float = 0.85
    tab_irrev: tuple = ((1, 0.90, 0.85), (2, 0.98, 0.98))   # (stack, 80 C, 90 C)

    # ================= derived values =================
    @property
    def z0(self):
        """Lip underside Z (the plate rides on the pads)."""
        return self.pad_t

    @property
    def r_in(self):
        return self.side / (2 * math.sqrt(3.0))

    @property
    def r_c(self):
        return self.side / math.sqrt(3.0)

    @property
    def r_sweep(self):
        """True sweep radius = chamfer corner."""
        return math.hypot(self.r_in, self.side / 2 - self.chamfer)

    @property
    def face_flat(self):
        return self.side - 2 * self.chamfer

    @property
    def axis_z(self):
        return round(self.z0 + self.lip_t + self.rad_clr + self.r_sweep, 1)

    @property
    def axis(self):
        return (self.axis_y, self.axis_z)

    @property
    def rotor_len(self):
        return self.rotor_x[1] - self.rotor_x[0]

    @property
    def parting_z(self):
        return -self.skirt

    @property
    def base_mag_x(self):
        return self.box_l / 2 - self.mag_from_end

    @property
    def base_mag_z(self):
        return -self.mag_below_top

    @property
    def lid_mag_z(self):
        return -self.lid_mag_below_top

    @property
    def far_pin_end_x(self):
        """P hex tip = EF socket floor at rest."""
        return self.rotor_x[0] + self.far_socket_depth

    @property
    def far_pin_slide_x(self):
        """Journal + cone of P: the length that slides through the far hole when P is pushed in."""
        return (self.far_block_x[0], self.rotor_x[0])

    @property
    def screw_head_depth(self):
        """Knob counterbore depth: M3 head + gap + hub cap, at least the v3.2 depth (v3.3 2.4: 3.4 for k 2.4)."""
        return round(max(self.counterbore_v32, self.screw_head_k + self.hub_cap_gap + self.hub_cap_t), 6)

    @property
    def pilot_depth(self):
        """EN pilot: deepened with the counterbore so the screw tip keeps its clearance, but only until the EN floor
        under it is pilot_floor_min (v3.3 2.4: 6.5 + min(depth - 3.0, 0.4))."""
        floor_v32 = self.knob_hex_end - self.pilot_depth_v32 - (self.rotor_x[1] - self.plug_len_near)
        deeper = min(self.screw_head_depth - self.counterbore_v32, floor_v32 - self.pilot_floor_min)
        return round(self.pilot_depth_v32 + deeper, 6)

    @property
    def en_pilot_floor(self):
        """EN material between the pilot bottom and the plug's inner end."""
        return round(self.knob_hex_end - self.pilot_depth - (self.rotor_x[1] - self.plug_len_near), 6)

    @property
    def screw_tip_clearance(self):
        """M3 tip -> pilot bottom (> 0: the screw never bottoms out)."""
        return round(self.knob_x[1] - self.screw_head_depth - self.screw_len - (self.knob_hex_end - self.pilot_depth), 6)

    @property
    def knob_t(self):
        return self.det_floor + self.magnet_t * self.knob_stack + self.knob_pocket_allowance + self.knob_cap_t

    @property
    def knob_x(self):
        start = self.near_block_x[1] + self.boss_h
        return (start, start + self.knob_t)

    @property
    def knob_flat_distance(self):
        """Axis -> knob flat."""
        return self.knob_mag_r * math.cos(math.radians(60)) + self.knob_lobe_r

    @property
    def knob_lobes(self):
        """(Y, Z) of the knob magnet lobes at rest, in knob_phi order."""
        return [(self.axis_y + self.knob_mag_r * math.cos(math.radians(phi)),
                 self.axis_z + self.knob_mag_r * math.sin(math.radians(phi))) for phi in self.knob_phi]

    @property
    def stator_yz(self):
        return (self.axis_y + self.stator_r * math.cos(math.radians(self.stator_phi)),
                self.axis_z + self.stator_r * math.sin(math.radians(self.stator_phi)))

    @property
    def stator_spacer_t(self):
        return (self.near_block_x[1] - self.near_block_x[0]) - self.det_floor - self.magnet_t

    @property
    def detent_gap(self):
        return self.det_floor + self.boss_h + self.det_floor

    @property
    def far_pin_x(self):
        return (self.far_block_x[0], self.far_pin_end_x)

    @property
    def tab_t(self):
        return self.mount_floor + self.magnet_slot_t * self.mount_stack + self.cap_t

    @property
    def tab_y(self):
        return (-self.tab_t, 0.0)

    @property
    def lip_x(self):
        return (self.far_block_x[0], self.near_block_x[1])

    @property
    def lip_y(self):
        return (-self.tab_t, self.lip_back_y)

    @property
    def beam_x(self):
        return self.lip_x

    @property
    def beam_y(self):
        return (-self.tab_t, -self.beam_relief)

    @property
    def beam_z(self):
        return (self.z0 - self.beam_h, self.z0)

    @property
    def tab_zc(self):
        return self.tab_bottom + self.tab_w / 2

    @property
    def tab_top(self):
        return self.z0 - self.tab_top_below_lip

    @property
    def mount_z(self):
        """World Z of the lower tab magnet centres (the pads lift the plate, the pockets stay at the base point)."""
        return self.base_mag_z + self.mount_delta

    @property
    def upper_z(self):
        """World Z of the upper tab magnet centres, upper_delta above the lid magnet point (v3.3 2.1)."""
        return self.lid_mag_z + self.upper_delta

    @property
    def upper_pocket_z(self):
        return (self.upper_z - self.mag_pocket_d / 2, self.upper_z + self.mag_pocket_d / 2)

    @property
    def flat_back_top(self):
        """Top of the flat tab back face that rests on the box (no lead-in on the top edge, v3.3 2.1). As built (tab top
        -1.8) its top 0.7 lies in the estimated R2.5 lid fillet; the upper pocket top (-2.40) is 0.10 into it, where the
        box face is <= 0.002 off the plane: accepted, not modelled (v3.4)."""
        return self.tab_top

    @property
    def mount_y(self):
        """Tab magnet stack centre (lower and upper stack)."""
        return -(self.mount_floor + 0.5 * self.magnet_t * self.mount_stack)

    @property
    def white_depth(self):
        return self.white_layers * self.layer_h

    @property
    def azure_depth(self):
        return self.azure_layers * self.layer_h

    @property
    def beam_line_z(self):
        """Accent option E (v3.3 2.2): one continuous azure line above the upper pockets, beam_line_top_seam below the
        beam top chamfer edge (Z -1.5 with the 0.5 pads); all caps are navy."""
        return self.z0 - self.front_chamfer - self.beam_line_top_seam - self.beam_line_w / 2

    @property
    def logo_file(self):
        return LOGO_FILES[self.logo]

    def tab_irreversible(self, stack):
        for row_stack, at_80, at_90 in self.tab_irrev:
            if row_stack == stack:
                return at_80, at_90
        raise KeyError(f"no irreversible-loss factors for stack {stack}")


def make_params(overrides=None):
    """Spec defaults with config overrides (a dict of Params field names)."""
    return Params(**(overrides or {}))
