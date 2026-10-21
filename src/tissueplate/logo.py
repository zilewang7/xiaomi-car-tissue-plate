"""Logo face inlays (spec 4.6; v3.3 2.6: 0.7 round tips): white / azure faces from
concept/v3.3/logo/final/geometry.json (params.FINAL_LOGO).

The JSON holds face-mm rings per colour ({"white": [...], "azure": [...]}); outer rings are CCW, holes CW;
x 0..181 along the rotor from the -X end, y 0..27.6 across the face flat, as seen from outside with the
logo face displayed. The same face-local frame is used for the digits, so panels.py maps both onto the
outward face without mirroring.

Ring clean-up before building faces: tiny self-intersection loops left by the stroke offsetting at the
trail joins (a few 0.01 mm^2) are spliced out, then each ring is simplified with Douglas-Peucker
(tolerance p.logo_simplify_tol, 0.002 mm: far below print resolution, keeps the booleans fast).
Any remaining self-intersection raises. Overlapping strokes of one colour are merged into one face.
"""
import json

import build123d as bd
import numpy as np
from matplotlib.path import Path as MPath

from .shapes import polygon_wire

COLOURS = ("white", "azure")
ART_BOX = (3.0, 3.0, 178.0, 24.6)    # x0, y0, x1, y1: >= 3 mm from the face edges and the rotor ends (4.6)


def signed_area(ring):
    x, y = ring[:, 0], ring[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def _cross(u, v):
    return u[..., 0] * v[..., 1] - u[..., 1] * v[..., 0]


def _segment_hit(a, b, c, d):
    """Proper intersection point of segments ab and cd, or None."""
    r, s = b - a, d - c
    denominator = _cross(r, s)
    if abs(denominator) < 1e-15:
        return None
    t = _cross(c - a, s) / denominator
    u = _cross(c - a, r) / denominator
    if 0 < t < 1 and 0 < u < 1:
        return a + t * r
    return None


def remove_micro_loops(ring, window=6):
    """Splice out small loops where segment i crosses segment i + k (k <= window)."""
    points = [np.asarray(q, float) for q in ring]
    removed = 0
    index = 0
    while index < len(points) - 1:
        a, b = points[index], points[index + 1]
        hit = None
        for step in range(2, window + 1):
            if index + step + 1 >= len(points):
                break
            crossing = _segment_hit(a, b, points[index + step], points[index + step + 1])
            if crossing is not None:
                hit = (step, crossing)
                break
        if hit is None:
            index += 1
            continue
        step, crossing = hit
        points = points[:index + 1] + [crossing] + points[index + step + 1:]   # drop the loop points
        removed += 1
        index = max(index - window, 0)
    return np.array(points), removed


def _douglas_peucker(points, tol):
    keep = np.zeros(len(points), bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        chord = points[j] - points[i]
        length = np.hypot(*chord)
        inner = points[i + 1:j]
        if length < 1e-12:
            distance = np.hypot(*(inner - points[i]).T)
        else:
            distance = np.abs(_cross(chord, inner - points[i])) / length
        k = int(np.argmax(distance))
        if distance[k] > tol:
            keep[i + 1 + k] = True
            stack += [(i, i + 1 + k), (i + 1 + k, j)]
    return points[keep]


def simplify_ring(ring, tol):
    """Douglas-Peucker on a closed ring, split at point 0 and the farthest point from it."""
    far = int(np.argmax(np.hypot(*(ring - ring[0]).T)))
    first = _douglas_peucker(ring[:far + 1], tol)
    second = _douglas_peucker(np.vstack([ring[far:], ring[:1]]), tol)
    return np.vstack([first[:-1], second[:-1]])


def self_intersections(ring):
    """Number of proper crossings between non-adjacent segments of a closed ring."""
    start = np.asarray(ring, float)
    end = np.roll(start, -1, axis=0)
    n = len(start)
    crossings = 0
    for i in range(n):
        j = np.arange(i + 2, n)
        if i == 0:
            j = j[j != n - 1]
        if len(j) == 0:
            continue
        a, b, c, d = start[i], end[i], start[j], end[j]
        o1 = _cross(b - a, c - a)
        o2 = _cross(b - a, d - a)
        o3 = _cross(d - c, a - c)
        o4 = _cross(d - c, b - c)
        crossings += int(np.sum((o1 * o2 < 0) & (o3 * o4 < 0)))
    return crossings


def clean_rings(rings, tol):
    cleaned, report = [], dict(rings=len(rings), points_in=0, points_out=0, loops_removed=0, area_change=0.0)
    for raw in rings:
        raw = np.asarray(raw, float)
        ring, removed = remove_micro_loops(raw)
        if tol > 0:
            ring = simplify_ring(ring, tol)
        if self_intersections(ring):
            raise ValueError("logo ring still self-intersects after clean-up")
        if np.sign(signed_area(ring)) != np.sign(signed_area(raw)):
            raise ValueError("logo ring orientation changed during clean-up")
        report["points_in"] += len(raw)
        report["points_out"] += len(ring)
        report["loops_removed"] += removed
        report["area_change"] += abs(signed_area(ring)) - abs(signed_area(raw))
        cleaned.append(ring)
    return cleaned, report


def faces_from_rings(rings):
    """Planar faces (z = 0): every CCW ring is an outer boundary, every CW ring a hole of the outer containing it."""
    outers = [r for r in rings if signed_area(r) > 0]
    holes = [r for r in rings if signed_area(r) < 0]
    owner = []
    for hole in holes:
        containing = [k for k, outer in enumerate(outers) if MPath(outer).contains_point(hole[0])]
        if len(containing) != 1:
            raise ValueError(f"logo hole is inside {len(containing)} outer rings (expected 1)")
        owner.append(containing[0])
    faces = []
    for k, outer in enumerate(outers):
        inner = [polygon_wire(hole) for hole, o in zip(holes, owner) if o == k]
        face = bd.Face(polygon_wire(outer), inner)
        if not face.is_valid:
            raise ValueError("invalid logo face")
        faces.append(face)
    return faces


def merge_overlapping(faces):
    """Union of same-colour faces: overlapping strokes (the tail stroke hangs on the shoulder trail) become one
    face, so every inlay is one clean solid."""
    if len(faces) < 2:
        return faces
    merged = [face for face in faces[0].fuse(*faces[1:]).clean().faces()]
    if not all(face.is_valid for face in merged):
        raise ValueError("invalid logo face after merging overlapping strokes")
    return merged


def load_logo_faces(p, rings=None):
    """{colour: [faces]} in face-local coordinates, plus a report of the clean-up and the layout checks.
    rings: {colour: rings} to build instead of the logo file (a custom wordmark, logo_text.LogoChoice.rings)."""
    if rings is None:
        with open(p.logo_file, encoding="utf-8") as handle:
            data = json.load(handle)
    else:
        data = rings
    unknown = set(data) - set(COLOURS)
    if unknown:
        raise ValueError(f"logo file has unknown colours {sorted(unknown)}")
    faces, report = {}, {"file": str(p.logo_file)}
    for colour in COLOURS:
        rings, ring_report = clean_rings(data.get(colour, []), p.logo_simplify_tol)
        separate = faces_from_rings(rings)
        faces[colour] = merge_overlapping(separate)
        ring_report["strokes"] = len(separate)
        ring_report["overlap_merged"] = sum(f.area for f in separate) - sum(f.area for f in faces[colour])
        ring_report["faces"] = len(faces[colour])
        ring_report["holes"] = sum(len(f.inner_wires()) for f in faces[colour])
        ring_report["area"] = sum(f.area for f in faces[colour])
        report[colour] = ring_report
    all_faces = faces["white"] + faces["azure"]
    box = bd.Compound(all_faces).bounding_box()
    report["bbox"] = (box.min.X, box.min.Y, box.max.X, box.max.Y)
    inside = (box.min.X >= ART_BOX[0] and box.min.Y >= ART_BOX[1] and box.max.X <= ART_BOX[2]
              and box.max.Y <= ART_BOX[3])
    if not inside:
        raise ValueError(f"logo art {report['bbox']} leaves the usable area {ART_BOX}")
    overlap = 0.0
    for white_face in faces["white"]:
        for azure_face in faces["azure"]:
            common = white_face & azure_face
            overlap += sum(f.area for f in common.faces()) if common is not None else 0.0
    if overlap > 1e-6:
        raise ValueError(f"white and azure logo areas overlap by {overlap:.4f} mm^2")
    report["white_azure_overlap"] = overlap
    return faces, report
