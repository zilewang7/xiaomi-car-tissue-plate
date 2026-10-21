"""Nabla knob K (spec 4.2, 4.5): one print, outer face down.

Trefoil body (3 x R5.6 lobes at r 11, X 96.6 .. 104.0) + tactile ribs along X on the three flats
(A: one R1 rib 0.8 proud, B: two ribs 8 apart, Logo: one wide bar 0.6 proud) + thrust boss r 4.6 x 0.6 +
Ø6 journal + keyed hex (AF 5.0, key at +Z). Per lobe a pocket for knob_stack magnets opens at the outer
face with a 0.8 floor at the inner face; Ø3.3 screw bore + Ø6.4 counterbore on the axis, depth params.screw_head_depth
= M3 head k + 0.2 + 0.8 hub cap, >= 3.0 (v3.3 2.4: 3.4 for k 2.4).
Outer face letters (spec 4.5 "A / B / ◆", white): one glyph next to each flat, upright when that flat is
on top, i.e. when its face is outward; inlaid white_depth deep as a separate solid.
"""
import build123d as bd
import numpy as np

from .params import DISPLAY_NORMAL, FACE_NORMALS, FONT_PATH
from .shapes import CUT_OVERSHOOT, circle_pts, direction, hull_pts, keyed_hex, x_cyl, yz_prism

LETTERS = {"A": "A", "B": "B", "L": "◆"}    # face -> glyph on the outer face


def flat_angle(face_name):
    """Knob flat that is on top (90 deg) when this face is displayed."""
    return (90.0 + FACE_NORMALS[face_name] - DISPLAY_NORMAL) % 360.0


def knob_profile(p, rot=0.0):
    y, z = p.axis
    lobes = [circle_pts(y + p.knob_mag_r * np.cos(np.radians(phi + rot)), z + p.knob_mag_r * np.sin(np.radians(phi + rot)),
                        p.knob_lobe_r) for phi in p.knob_phi]
    return hull_pts(lobes)


def knob_ribs(p):
    """(Y, Z) rib outlines on the flats: A one rib, B two, Logo one wide bar."""
    outlines = []
    centre = np.array(p.axis)
    for face_name in ("A", "B", "L"):
        normal = direction(flat_angle(face_name))
        tangent = np.array([-normal[1], normal[0]])
        mid = centre + p.knob_flat_distance * normal
        if face_name == "L":
            inset = mid - (p.rib_r - p.bar_proud) * normal
            ends = [inset - p.bar_length / 2 * tangent, inset + p.bar_length / 2 * tangent]
            outlines.append(hull_pts([circle_pts(*end, p.rib_r, 24) for end in ends]))
            continue
        offsets = (0.0,) if face_name == "A" else (-p.rib_b_spacing / 2, p.rib_b_spacing / 2)
        for offset in offsets:
            rib_centre = mid - (p.rib_r - p.rib_proud) * normal + offset * tangent
            outlines.append([tuple(q) for q in circle_pts(*rib_centre, p.rib_r, 24)])
    return outlines


def outer_face_plane(p):
    """Plane on the outer face: local x = +Y (viewer's right seen from +X), local y = +Z, normal +X."""
    return bd.Plane(origin=(p.knob_x[1], *p.axis), x_dir=(0, 1, 0), z_dir=(1, 0, 0))


def letter_faces(p):
    """{face_name: [faces]} in outer-face local coordinates (origin on the axis), with the seam checks."""
    hub_r = p.screw_head_d / 2
    inner_r = hub_r + p.knob_letter_seam
    outer_r = p.knob_flat_distance - p.knob_letter_seam
    centre_r = 0.5 * (inner_r + outer_r)
    keep_out = [bd.Pos(p.knob_mag_r * np.cos(np.radians(phi)), p.knob_mag_r * np.sin(np.radians(phi)))
                * bd.Circle(p.mag_pocket_d / 2).faces()[0] for phi in p.knob_phi]
    keep_out.append(bd.Circle(hub_r).faces()[0])
    outline = bd.Polygon(*[(y - p.axis[0], z - p.axis[1]) for y, z in knob_profile(p)], align=None).faces()[0]
    result, report = {}, {}
    for face_name, glyph in LETTERS.items():
        text = bd.Text(glyph, font_size=p.knob_letter_size, font_path=str(FONT_PATH))
        box = text.bounding_box()
        if box.max.Y - box.min.Y > outer_r - inner_r + 1e-6:
            raise ValueError(f"knob letter {glyph!r} ({box.max.Y - box.min.Y:.2f} mm) does not fit between the hub cap "
                             f"and the flat ({outer_r - inner_r:.2f} mm)")
        angle = flat_angle(face_name)
        place = bd.Pos(*(centre_r * direction(angle))) * bd.Rot(0, 0, angle - 90.0)
        faces = [place * bd.Pos(-box.center().X, -box.center().Y) * face for face in text.faces()]
        seam = min(face.distance_to(other) for face in faces for other in keep_out)
        edge = min(face.distance_to(outline.outer_wire()) for face in faces)
        if min(seam, edge) < p.knob_letter_seam - 0.02:
            raise ValueError(f"knob letter {glyph!r}: navy seam {min(seam, edge):.2f} mm < {p.knob_letter_seam} mm")
        result[face_name] = faces
        report[face_name] = dict(glyph=glyph, flat_deg=angle, seam_to_caps=round(seam, 3), seam_to_edge=round(edge, 3),
                                 height=round(box.max.Y - box.min.Y, 3), width=round(box.max.X - box.min.X, 3))
    return result, report


def build_knob(p):
    """{'bodies': {'navy', 'white'}, 'knob_body': trefoil prism without ribs (clearance checks)}."""
    y, z = p.axis
    knob_body = yz_prism(knob_profile(p), *p.knob_x)
    knob = knob_body
    for rib in knob_ribs(p):
        knob = knob + yz_prism(rib, *p.knob_x)
    knob = knob + x_cyl(p.boss_r, p.near_block_x[1], p.knob_x[0] + 0.01, y, z)
    knob = knob + x_cyl(p.pin_d / 2, p.near_block_x[0], p.near_block_x[1] + 0.01, y, z)
    knob = knob + keyed_hex(p.hex_af, p.knob_hex_end, p.near_block_x[0] + 0.01, y, z, p.hex_key)
    for lobe_y, lobe_z in p.knob_lobes:      # pockets open at the OUTER face, floor at the inner face
        knob = knob - x_cyl(p.mag_pocket_d / 2, p.knob_x[0] + p.det_floor, p.knob_x[1] + 0.01, lobe_y, lobe_z)
    knob = knob - x_cyl(p.screw_bore / 2, p.knob_hex_end - 0.01, p.knob_x[1] + 0.01, y, z)
    knob = knob - x_cyl(p.screw_head_d / 2, p.knob_x[1] - p.screw_head_depth, p.knob_x[1] + 0.01, y, z)
    faces, letter_report = letter_faces(p)
    plane = outer_face_plane(p)
    shifted = bd.Plane(origin=plane.origin + bd.Vector(CUT_OVERSHOOT, 0, 0), x_dir=plane.x_dir, z_dir=plane.z_dir)
    letters = [face for face_list in faces.values() for face in face_list]
    cutters = bd.Compound([bd.extrude(shifted * face, amount=p.white_depth + CUT_OVERSHOOT, dir=(-1, 0, 0))
                           for face in letters])
    bodies = {"navy": knob - cutters, "white": knob & cutters}
    return {"bodies": bodies, "knob_body": knob_body, "letters": letter_report}
