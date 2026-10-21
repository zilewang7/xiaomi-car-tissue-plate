"""Small printed parts (spec 4.2 P, D, S; v3.3 2.1, 2.4) and the bought magnets, all in the assembled pose.

Far pin P (v3.4): Ø6 journal in the far block hole, cone, regular hex AF far_hex_af pushed into the EF socket
(any of 6 angles), 14 long, no hole; it turns with the rotor; one spare is printed.
Caps D (navy since v3.3 option E, so the front shows no dots; plate-0b picks): tab
Ø8.25 x 0.8 (4: the lower and the upper pocket of each tab), knob Ø8.25 x 0.4 (3), hub Ø6.40 x 0.8 (1, over the M3
head); all flush with the outer surfaces, each with one Ø1.0 half-circle pry notch at the rim, placed so the needle
levers on solid navy (tab caps: at the bottom; knob caps: toward the knob axis, the 3.65 wall, not the 1.45 outer
lobe wall; hub cap: toward the 270 deg lobe). Tab and knob caps are glued all round (review m4: play in the vertical Ø8.3 holes; the
knob caps also take the outward magnet force while shifting, review M3), the hub cap with a glue dot. Stator spacer
S (navy) Ø8.4 x 1.2 behind the stator magnet: a press fit in the Ø8.3 pocket, because the stator is pushed
onto it by up to 1 N between 35 and 85 deg (review M3). Magnets: N52 Ø8 x 3, one solid each (tabs: a lower
mag_tab and an upper mag_tabU stack of mount_stack each, same Y; knob 3 x knob_stack, stator 1).
Cooling tube Q: print-only sacrificial tube as tall as the knob print, so the knob never prints alone (params).
"""
import build123d as bd

from .shapes import direction, x_cyl, x_hex, y_cyl, z_cyl

HUB_NOTCH_DEG = 270.0      # hub cap notch direction (rotates with the knob)


def x_cone(r0, r1, x0, x1, y, z):
    cone = bd.Cone(r0, r1, x1 - x0, rotation=(0, 90, 0), align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN))
    return bd.Pos(x0, y, z) * cone


def build_far_pin(p):
    """P: Ø6 journal in the far block hole, cone in the far gap (<= 45 deg in the hex-down print), regular hex AF
    far_hex_af (no key: the far end has no phase) to the EF socket floor with a 45 deg tip chamfer; no hole."""
    y, z = p.axis
    journal = x_cyl(p.pin_d / 2, p.far_block_x[0], p.far_block_x[1], y, z)
    cone = x_cone(p.pin_d / 2, p.far_hex_af / 2, p.far_block_x[1] - 0.001, p.rotor_x[0], y, z)
    hexagon = x_hex(p.far_hex_af, p.rotor_x[0] - 0.01, p.far_pin_end_x, y, z)
    tip_r = p.far_hex_af / 2 - p.far_tip_chamfer
    lead_in = x_cone(tip_r + 20.0, tip_r, p.far_pin_end_x - 20.0, p.far_pin_end_x, y, z)
    return journal + cone + (hexagon & lead_in)


def side_name(sign):
    return "+" if sign > 0 else "-"


def x_cap(p, radius, thickness, cap_y, cap_z, notch_deg):
    """Cap disc on the knob outer face with its pry notch at the rim, notch_deg seen from +X."""
    x0, x1 = p.knob_x[1] - thickness, p.knob_x[1]
    offset = radius * direction(notch_deg)
    notch = x_cyl(p.cap_notch_d / 2, x0 - 0.1, x1 + 0.1, cap_y + offset[0], cap_z + offset[1])
    return x_cyl(radius, x0, x1, cap_y, cap_z) - notch


def build_caps(p):
    """{name: solid} in the assembled pose: cap_tab- / cap_tab+ (lower pockets), cap_tabU- / cap_tabU+ (upper
    pockets), cap_knob<phi>, cap_hub."""
    caps = {}
    radius, y0, y1 = p.tab_cap_d / 2, p.tab_y[0], p.tab_y[0] + p.cap_t
    for prefix, z in (("cap_tab", p.mount_z), ("cap_tabU", p.upper_z)):
        for sign in (-1, 1):
            x = sign * p.base_mag_x
            notch = y_cyl(p.cap_notch_d / 2, y0 - 0.1, y1 + 0.1, x, z - radius)     # at the bottom of the cap
            caps[f"{prefix}{side_name(sign)}"] = y_cyl(radius, y0, y1, x, z) - notch
    for phi, (lobe_y, lobe_z) in zip(p.knob_phi, p.knob_lobes):
        caps[f"cap_knob{int(phi)}"] = x_cap(p, p.knob_cap_d / 2, p.knob_cap_t, lobe_y, lobe_z, phi + 180.0)   # inward
    caps["cap_hub"] = x_cap(p, p.hub_cap_d / 2, p.hub_cap_t, *p.axis, HUB_NOTCH_DEG)
    return caps


def build_spacer(p):
    stator_y, stator_z = p.stator_yz
    return x_cyl(p.spacer_d / 2, p.near_block_x[0], p.near_block_x[0] + p.stator_spacer_t, stator_y, stator_z)


def build_cooling_tube(p, height):
    """Q upright at the origin (not installed, so the pose only matters for printing)."""
    radius = p.cooling_tube_d / 2
    return z_cyl(radius, 0.0, height, 0.0, 0.0) - z_cyl(radius - p.cooling_tube_wall, -0.1, height + 0.1, 0.0, 0.0)


def build_magnets(p):
    """{name: solid}: tab stacks press on the 0.8 pocket floor, knob stacks on the inner floor, stator on its wall."""
    radius, thickness = p.magnet_d / 2, p.magnet_t
    magnets = {}
    for prefix, z in (("mag_tab", p.mount_z), ("mag_tabU", p.upper_z)):
        for sign in (-1, 1):
            for k in range(p.mount_stack):
                y1 = -p.mount_floor - k * thickness
                magnets[f"{prefix}{side_name(sign)}_{k + 1}"] = y_cyl(radius, y1 - thickness, y1, sign * p.base_mag_x, z)
    for phi, (lobe_y, lobe_z) in zip(p.knob_phi, p.knob_lobes):
        for k in range(p.knob_stack):
            x0 = p.knob_x[0] + p.det_floor + k * thickness
            magnets[f"mag_knob{int(phi)}_{k + 1}"] = x_cyl(radius, x0, x0 + thickness, lobe_y, lobe_z)
    stator_y, stator_z = p.stator_yz
    x1 = p.near_block_x[1] - p.det_floor
    magnets["mag_stator"] = x_cyl(radius, x1 - thickness, x1, stator_y, stator_z)
    return magnets
