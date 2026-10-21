"""Cradle C (spec 4.2, 4.3, 4.4; v3.3 2.3, 2.5): lip plate + two triangular end blocks, one print, lip down.

Holes: far Ø5.95 running teardrop (far pin journal, v3.4), near Ø5.90 running teardrop (knob journal), both
roof up in the print; both are plate-0 strip picks smaller than the CAD shafts (verify_geometry.CALIBRATED_FITS);
stator pocket (teardrop, opens to the block's inner face, 0.8 wall toward the knob); inner thrust ring
r 4.6 x 0.3 on the near block inner face. No dowel holes (10-18: the front bar is glued to the lip directly). The
anti-slip tape (not printed) sticks under the lip in the two pad zones.
"""
import build123d as bd
import numpy as np

from .shapes import hull_pts, tri_pts, x_cyl, x_teardrop, yz_prism


def end_block_profile(p):
    """(Y, Z) outline of an end block: hull of the rotor section and the lip section."""
    lip_section = np.array([(p.lip_y[0], p.z0), (p.lip_y[1], p.z0), (p.lip_y[1], p.z0 + p.lip_t),
                            (p.lip_y[0], p.z0 + p.lip_t)])
    return hull_pts([np.array(tri_pts(p.r_in, p.chamfer, p.axis)), lip_section])


def build_cradle(p):
    """{'cradle': printed part, 'lip' / 'far_block' / 'near_block': plain features for clearance checks}."""
    y, z = p.axis
    lip = bd.Pos(p.lip_x[0], p.lip_y[0], p.z0) * bd.Box(p.lip_x[1] - p.lip_x[0], p.lip_y[1] - p.lip_y[0], p.lip_t,
                                                       align=(bd.Align.MIN,) * 3)
    profile = end_block_profile(p)
    far_block, near_block = yz_prism(profile, *p.far_block_x), yz_prism(profile, *p.near_block_x)
    cradle = lip + far_block + near_block
    cradle = cradle + x_cyl(p.boss_r, p.near_block_x[0] - p.inner_ring_h, p.near_block_x[0] + 0.01, y, z)
    cradle = cradle - x_teardrop(p.hole_far / 2, p.far_block_x[0] - 1, p.far_block_x[1] + 1, y, z, p.tear_top)
    cradle = cradle - x_teardrop(p.hole_near / 2, p.near_block_x[0] - 1, p.near_block_x[1] + 1, y, z, p.tear_top)
    stator_y, stator_z = p.stator_yz
    cradle = cradle - x_teardrop(p.mag_pocket_d / 2, p.near_block_x[0] - 0.01, p.near_block_x[1] - p.det_floor,
                                 stator_y, stator_z, p.tear_top)
    return {"cradle": cradle, "lip": lip, "far_block": far_block, "near_block": near_block}


def build_pads(p):
    """Anti-slip tape in the pad zones under the lip (bought; v3.4: 1.2 mm 3M double-sided); none when pad_t = 0."""
    if p.pad_t <= 0:
        return {}
    pads = {}
    for name, ((x0, x1), (y0, y1)) in zip(("pad_front", "pad_rear"), p.pad_zones):
        pads[name] = bd.Pos(x0, y0, 0) * bd.Box(x1 - x0, y1 - y0, p.pad_t, align=(bd.Align.MIN,) * 3)
    return pads
