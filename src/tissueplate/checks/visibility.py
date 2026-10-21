"""Check 6: visibility of the displayed face from outside (port of concept/v3.1 section 4).

Sample points cover the worst-case cell box x the ink band on the displayed face (the same pose for A, B
and the logo face, whose art also lies inside the cell box). Rays go to an outside viewer at elevation
15-45 deg and yaw -60..60 deg; occluders are the knob (trefoil + tactile ribs), the two end blocks
(prisms of their YZ outlines) and the leather tongue / dashboard half space Y < tongue, Z < 0 (the cabin model:
measured in the author's YU7).
"""
import math

import numpy as np
from matplotlib.path import Path as MPath

from ..cradle import end_block_profile
from ..knob import knob_profile, knob_ribs
from .common import item, section

ELEVATIONS = (15, 25, 35, 45)
YAWS = tuple(range(-60, 61, 5))
SPEC_YAW = 45                 # spec 7-6: 100 % visible for elevation 15-45 deg x yaw +-45 deg
RAY_STEPS = 25


def face_frame(p):
    """Displayed face: outward normal (150 deg), 'up' along the face, front-bottom sharp vertex."""
    normal = np.array([0.0, -math.cos(math.radians(30)), math.sin(math.radians(30))])
    up = np.array([0.0, 0.5, math.sqrt(3.0) / 2])
    corner = np.array([0.0, p.axis_y - p.side / 2, p.axis_z - p.r_in])
    return normal, up, corner


def sample_points(p, typo):
    normal, up, corner = face_frame(p)
    ink_start = p.chamfer + (p.face_flat - typo.band_height) / 2       # along the face from the sharp vertex
    heights = np.linspace(ink_start, ink_start + typo.band_height, 9)
    xs = [x for c0, c1 in typo.cells for x in np.linspace(c0, c1, 6)]
    points = np.array([corner + v * up + np.array([x, 0, 0]) for x in xs for v in heights])
    return points, ink_start


def occluders(p):
    """[(YZ path, (x0, x1))]: knob outline and ribs over the knob X range, both end blocks."""
    block = MPath(np.array(end_block_profile(p)))
    rows = [(MPath(np.array(knob_profile(p))), p.knob_x)]
    rows += [(MPath(np.array(rib)), p.knob_x) for rib in knob_ribs(p)]
    rows += [(block, p.near_block_x), (block, p.far_block_x)]
    return rows


def blocked(points, direction, blockers, tongue_y):
    hit = np.zeros(len(points), bool)
    if abs(direction[0]) > 1e-9:
        for path, (x0, x1) in blockers:
            t0 = (x0 - points[:, 0]) / direction[0]
            t1 = (x1 - points[:, 0]) / direction[0]
            ta = np.maximum(np.minimum(t0, t1), 0.0)
            tb = np.maximum(t0, t1)
            crosses = tb > ta
            for f in np.linspace(0, 1, RAY_STEPS):
                t = ta + f * (tb - ta)
                q = points[:, 1:] + t[:, None] * direction[1:]
                hit |= path.contains_points(q) & crosses
    if direction[1] < 0:
        t_tongue = (tongue_y - points[:, 1]) / direction[1]
        hit |= points[:, 2] + t_tongue * direction[2] < 0
    return hit


def run(model):
    p, typo = model.params, model.typography
    normal, up, corner = face_frame(p)
    points, ink_start = sample_points(p, typo)
    blockers = occluders(p)
    table, first = {}, {}
    for elevation in ELEVATIONS:
        row = {}
        for yaw in YAWS:
            e, a = math.radians(elevation), math.radians(yaw)
            direction = np.array([math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)])
            if direction @ normal <= 0:
                row[yaw] = 0.0
                continue
            row[yaw] = 100.0 * (1.0 - blocked(points, direction, blockers, p.tongue_y).mean())
        table[elevation] = row
        toward_knob = [y for y in row if y > 0 and row[y] < 100]
        toward_far = [y for y in row if y < 0 and row[y] < 100]
        first[elevation] = dict(toward_knob=min(toward_knob) if toward_knob else None,
                                toward_far=max(toward_far) if toward_far else None)
    spec_min = min(v for row in table.values() for yaw, v in row.items() if abs(yaw) <= SPEC_YAW)
    low_z = corner[2] + ink_start * up[2]
    low_y = corner[1] + ink_start * up[1]
    over_tongue = {e: low_z + (low_y - p.tongue_y) * math.tan(math.radians(e)) for e in ELEVATIONS}
    arcmin = {d: math.degrees(math.atan(typo.flat_height / (d * 1000))) * 60 for d in (1, 2, 4)}
    items = [
        item(f"visible share, elevation 15-45 x yaw +-{SPEC_YAW} deg (%)", spec_min, spec_min >= 100.0 - 1e-9, "= 100"),
        item("first yaw with any occlusion per elevation (deg)", first, level="info"),
        item("lowest ink line sightline height above the tongue nose (mm)", over_tongue, level="info"),
    ]
    numbers = dict(percent_visible=table, first_occlusion=first, ink_low=(low_y, low_z),
                   sightline_height_over_tongue=over_tongue, digit_arcmin=arcmin, sample_points=len(points))
    return section("6 visibility from outside (ray casting)", items, numbers)
