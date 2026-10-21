"""Small geometry helpers shared by the part modules (ported from concept/v3.1/verify_v3_1.py).

Section polygons are lists of (Y, Z) points; prisms are extruded along +X between two X values.
"""
import math

import build123d as bd
import numpy as np
from scipy.spatial import ConvexHull

SQRT3 = math.sqrt(3.0)
CUT_OVERSHOOT = 0.1          # inlay cutters start this far outside the face so the booleans are clean


def direction(angle_deg):
    """Unit vector (Y, Z) at angle_deg, measured counter-clockwise from +Y (seen from +X)."""
    angle = math.radians(angle_deg)
    return np.array([math.cos(angle), math.sin(angle)])


def tri_vertices(r_in, centre, rot=0.0):
    """Sharp equilateral triangle (Y, Z) with inradius r_in; vertices at 90, 210, 330 deg + rot."""
    circumradius = 2.0 * r_in
    return [np.asarray(centre, float) + circumradius * direction(angle + rot) for angle in (90.0, 210.0, 330.0)]


def tri_pts(r_in, chamfer, centre, rot=0.0):
    """Equilateral triangle with each corner cut 'chamfer' along both edges; bottom face horizontal at rot 0."""
    vertices = tri_vertices(r_in, centre, rot)
    if chamfer <= 0:
        return [tuple(v) for v in vertices]
    points = []
    for index in range(3):
        vertex, previous, following = vertices[index], vertices[index - 1], vertices[(index + 1) % 3]
        points.append(tuple(vertex + (previous - vertex) / np.linalg.norm(previous - vertex) * chamfer))
        points.append(tuple(vertex + (following - vertex) / np.linalg.norm(following - vertex) * chamfer))
    return points


def circle_pts(cy, cz, r, n=96):
    angles = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return np.c_[cy + r * np.cos(angles), cz + r * np.sin(angles)]


def hull_pts(point_sets):
    """Convex hull (counter-clockwise) of several 2D point arrays."""
    points = np.vstack([np.asarray(s, float) for s in point_sets])
    hull = ConvexHull(points)
    return [tuple(points[i]) for i in hull.vertices]


def yz_prism(pts, x0, x1):
    """Extrude a (Y, Z) polygon along +X from x0 to x1."""
    face = bd.Plane.YZ * bd.Polygon(*pts, align=None)
    return bd.Pos(x0, 0, 0) * bd.extrude(face, x1 - x0, dir=(1, 0, 0))


def xz_prism(pts, y0, y1):
    """Extrude an (X, Z) polygon along +Y from y0 to y1."""
    plane = bd.Plane(origin=(0, y0, 0), x_dir=(1, 0, 0), z_dir=(0, 1, 0))   # local y = world -Z
    face = plane * bd.Polygon(*[(p[0], -p[1]) for p in pts], align=None)
    return bd.extrude(face, y1 - y0, dir=(0, 1, 0))


def x_cyl(r, x0, x1, y, z):
    cylinder = bd.Cylinder(r, x1 - x0, rotation=(0, 90, 0), align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN))
    return bd.Pos(x0, y, z) * cylinder


def y_cyl(r, y0, y1, x, z):
    cylinder = bd.Cylinder(r, y1 - y0, rotation=(-90, 0, 0), align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN))
    return bd.Pos(x, y0, z) * cylinder


def z_cyl(r, z0, z1, x, y):
    cylinder = bd.Cylinder(r, z1 - z0, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN))
    return bd.Pos(x, y, z0) * cylinder


def teardrop_pts(r, y, z, top, n=72):
    """Circle + 45 deg roof pointing +Z (up in the lip-down print); roof cut flat at top * r."""
    half_flat = r * (math.sqrt(2) - top)
    points = [(y + half_flat, z + top * r), (y - half_flat, z + top * r)]
    for angle in np.linspace(135.0, 405.0, n, endpoint=False):
        points.append((y + r * math.cos(math.radians(angle)), z + r * math.sin(math.radians(angle))))
    return points


def x_teardrop(r, x0, x1, y, z, top):
    return yz_prism(teardrop_pts(r, y, z, top), x0, x1)


def x_hex(af, x0, x1, axis_y, axis_z):
    """Regular hexagon prism along X (across flats af), corners at 30 + 60 k deg (one at +Z): six insertion phases."""
    corner_r = af / SQRT3
    points = [(axis_y + corner_r * math.cos(math.radians(30 + 60 * k)), axis_z + corner_r * math.sin(math.radians(30 + 60 * k)))
              for k in range(6)]
    return yz_prism(points, x0, x1)


def keyed_hex(af, x0, x1, axis_y, axis_z, key):
    """x_hex with its +Z corner flattened at key x corner radius: one insertion phase only."""
    corner_r = af / SQRT3
    cut = bd.Pos((x0 + x1) / 2, axis_y, axis_z + key * corner_r + 5.0) * bd.Box(abs(x1 - x0) + 2, 20, 10)
    return x_hex(af, x0, x1, axis_y, axis_z) - cut


def rotate_about_x_axis(shape, angle_deg, axis_y, axis_z):
    """Rotate a shape by angle_deg about the line parallel to X through (axis_y, axis_z)."""
    return bd.Pos(0, axis_y, axis_z) * bd.Rot(angle_deg, 0, 0) * bd.Pos(0, -axis_y, -axis_z) * shape


def polygon_wire(ring):
    return bd.Wire.make_polygon([(float(x), float(y), 0.0) for x, y in ring], close=True)


def fuse_all(shapes):
    """Boolean union of a list of shapes (left fold, explicit for readability)."""
    result = shapes[0]
    for shape in shapes[1:]:
        result = result + shape
    return result
