"""Rotor tube panels PA / PB / PL (spec 4.2, 4.4, 4.6, 6-5).

The s = 30 chamfered triangular tube (2.4 mm wall, X -90.5 .. +90.5) is split along the three corner
bisector planes into three 30-deg mitred panels. Each panel's outer face carries flush inlays cut
0.8 mm deep (white_layers / azure_layers x 0.2) that are kept as SEPARATE solids per colour so the 3MF
can assign extruders: PA = number or text A (white), PB = number or text B (white), PL = logo (white + azure).

Faces at rest (outward normal angle about +X): A 150 (displayed), B 270 (bottom), L 30 (cabin side);
"next" turns the rotor -120 deg, so A -> B -> Logo. Face-local frame: origin at the -X end of the lower
face-flat edge (the edge that is lower when that face is displayed), x along +X, y up the face, z out.
Seen from outside with the face displayed, +x is to the viewer's right and +y up: never mirrored.
Tape hinges (6-5): A bottom edge = B top edge, B bottom = L top, L bottom = A top.
"""
import math

import build123d as bd
import numpy as np

from .config import ConfigError
from .free_text import text_faces, text_glyph_checks
from .logo import load_logo_faces
from .params import DISPLAY_NORMAL, FACE_NORMALS, FACE_ORDER
from .shapes import CUT_OVERSHOOT, direction, tri_pts, yz_prism
from .text_layout import glyph_checks, number_faces


def lower_vertex_angle(normal_deg):
    return (normal_deg + 60.0) % 360.0


def upper_vertex_angle(normal_deg):
    return (normal_deg - 60.0) % 360.0


def face_plane(p, face_name):
    """Face-local frame of one rotor face at rest."""
    normal_deg = FACE_NORMALS[face_name]
    normal = direction(normal_deg)
    up = direction(normal_deg - 90.0)
    lower_vertex = np.array(p.axis) + p.r_c * direction(lower_vertex_angle(normal_deg))
    origin = lower_vertex + p.chamfer * up
    plane = bd.Plane(origin=(p.rotor_x[0], origin[0], origin[1]), x_dir=(1, 0, 0), z_dir=(0, normal[0], normal[1]))
    if (plane.y_dir - bd.Vector(0, up[0], up[1])).length > 1e-9:
        raise AssertionError("face plane y axis is not the face 'up' direction")
    return plane


def _turn_about_x(vector, angle_deg):
    c, s = math.cos(math.radians(angle_deg)), math.sin(math.radians(angle_deg))
    x, y, z = vector
    return np.array([x, c * y - s * z, s * y + c * z])


def orientation_check(p, face_name):
    """Turn the face frame into the display pose and express it in the outside viewer's axes."""
    turn = DISPLAY_NORMAL - FACE_NORMALS[face_name]
    plane = face_plane(p, face_name)
    x_axis, y_axis, z_axis = (_turn_about_x(tuple(v), turn) for v in (plane.x_dir, plane.y_dir, plane.z_dir))
    view = -z_axis                                   # viewer outside, looking at the displayed face
    viewer_up = np.array([0.0, *direction(DISPLAY_NORMAL - 90.0)])
    viewer_right = np.cross(view, viewer_up)
    x_right, y_up = float(x_axis @ viewer_right), float(y_axis @ viewer_up)
    return dict(face=face_name, turn_to_display=turn, x_to_viewer_right=round(x_right, 6),
                y_to_viewer_up=round(y_up, 6), mirrored=bool(x_right * y_up < 0))


def hinge_layout():
    """Shared tube edges in face order: the lower edge of each face is the upper edge of the next face."""
    rows = []
    for index, name in enumerate(FACE_ORDER):
        following = FACE_ORDER[(index + 1) % 3]
        lower = lower_vertex_angle(FACE_NORMALS[name])
        upper_next = upper_vertex_angle(FACE_NORMALS[following])
        if abs(lower - upper_next) > 1e-9:
            raise AssertionError(f"{name} bottom edge does not meet {following} top edge")
        rows.append(dict(edge=f"{name} bottom = {following} top", vertex_deg_at_rest=lower))
    return rows


def build_tube(p):
    outer = tri_pts(p.r_in, p.chamfer, p.axis)
    inner = tri_pts(p.r_in - p.panel_t, 0, p.axis)
    return yz_prism(outer, *p.rotor_x) - yz_prism(inner, p.rotor_x[0] - 1, p.rotor_x[1] + 1)


def panel_blank(tube, p, face_name):
    """Tube sector between the two corner bisector planes that bound this face."""
    normal_deg = FACE_NORMALS[face_name]
    reach = 4 * p.r_c
    centre = np.array(p.axis)
    points = [tuple(centre)] + [tuple(centre + reach * direction(normal_deg + offset)) for offset in (-60, 0, 60)]
    wedge = yz_prism(points, p.rotor_x[0] - 1, p.rotor_x[1] + 1)
    return tube & wedge


def inlay_cutters(faces, plane, depth):
    """Prisms from CUT_OVERSHOOT outside the face plane to 'depth' inside it."""
    outward = plane.z_dir
    shifted = bd.Plane(origin=plane.origin + outward * CUT_OVERSHOOT, x_dir=plane.x_dir, z_dir=plane.z_dir)
    cutters = [bd.extrude(shifted * face, amount=depth + CUT_OVERSHOOT, dir=-outward) for face in faces]
    return bd.Compound(cutters)


def split_inlays(blank, faces_by_colour, plane, depths):
    """{colour: shape}: navy = blank minus all cutters, each inlay = blank & its cutters (exact complements)."""
    bodies = {}
    navy = blank
    for colour, faces in faces_by_colour.items():
        if not faces:
            continue
        cutters = inlay_cutters(faces, plane, depths[colour])
        bodies[colour] = blank & cutters
        navy = navy - cutters
    bodies = {"navy": navy, **bodies}
    return bodies


def build_number_panel(tube, p, face_name, number, typo):
    plane = face_plane(p, face_name)
    placed, layout = number_faces(number, typo, p)
    layout_report = glyph_checks(placed, layout, typo, p)
    faces = [face for _, glyph in placed for face in glyph]
    bodies = split_inlays(panel_blank(tube, p, face_name), {"white": faces}, plane, {"white": p.white_depth})
    solids = len(bodies["white"].solids())
    if solids != len(number):
        raise ValueError(f"panel {face_name}: {solids} digit inlay solids, expected {len(number)}")
    return bodies, dict(layout=layout_report, inlay_solids={"white": solids})


def cut_problem(bodies, expected):
    """Why a text cut is not printable (v3.4 6.8: invalid solid, inlay solids != faces, open mesh), or None.
    expected: {colour: inlay faces}."""
    from .export3mf import mesh_from_shape     # the mesher of the 3MF export (export3mf imports nothing from here)
    for colour, body in bodies.items():
        if not body.is_valid:
            return f"the {colour} solid is not valid"
    for colour, count in expected.items():
        if len(bodies[colour].solids()) != count:
            return f"{len(bodies[colour].solids())} {colour} solids, expected {count}"
    for colour, body in bodies.items():
        try:
            mesh_from_shape(body)
        except ValueError:
            return f"the {colour} mesh is not closed"
    return None


def build_text_panel(tube, p, face_name, plan):
    """Free-text face (free_text.TextPlan): one white solid per glyph face. ConfigError when the cut is not printable,
    naming the first character that fails when cut alone (positions only)."""
    plane = face_plane(p, face_name)
    placed = text_faces(plan)
    try:
        layout_report = text_glyph_checks(placed, plan)
    except ConfigError as error:
        raise ConfigError(f"[text] {face_name.lower()}: {error}") from None
    faces = [face for _, glyph in placed for face in glyph]
    blank = panel_blank(tube, p, face_name)
    bodies = split_inlays(blank, {"white": faces}, plane, {"white": p.white_depth})
    problem = cut_problem(bodies, {"white": len(faces)})
    if problem is not None:
        culprit = next((position for position, glyph in placed
                        if cut_problem(split_inlays(blank, {"white": glyph}, plane, {"white": p.white_depth}),
                                       {"white": len(glyph)}) is not None), None)
        where = f"character {culprit}" if culprit is not None else "the line (each character alone is fine)"
        raise ConfigError(f"[text] {face_name.lower()}: {where} cannot be cut into a closed solid ({problem}); "
                          "use another character")
    return bodies, dict(layout=layout_report, inlay_solids={"white": len(faces)})


def build_display_panel(tube, p, face_name, number, plan, typo):
    """Face A / B: the free text when [text] sets it, else the number."""
    if plan is not None:
        return build_text_panel(tube, p, face_name, plan)
    return build_number_panel(tube, p, face_name, number, typo)


def build_logo_panel(tube, p, logo_faces):
    plane = face_plane(p, "L")
    depths = {"white": p.white_depth, "azure": p.azure_depth}
    bodies = split_inlays(panel_blank(tube, p, "L"), logo_faces, plane, depths)
    counts = {colour: len(bodies[colour].solids()) for colour in ("white", "azure")}
    for colour, count in counts.items():
        if count != len(logo_faces[colour]):
            raise ValueError(f"logo panel: {count} {colour} inlay solids, expected {len(logo_faces[colour])}")
    return bodies, dict(inlay_solids=counts)


def build_wordmark_panel(tube, p, logo, logo_faces):
    """Face L with a custom wordmark beside the sketch (logo_text, v3.4 6.4): the logo panel plus the post-cut check
    of 6.8 (three colours); the failing character is found by cutting the sketch with that character alone."""
    plane = face_plane(p, "L")
    depths = {"white": p.white_depth, "azure": p.azure_depth}
    blank = panel_blank(tube, p, "L")
    bodies = split_inlays(blank, logo_faces, plane, depths)
    expected = {colour: len(logo_faces[colour]) for colour in ("white", "azure")}
    problem = cut_problem(bodies, expected)
    if problem is not None:
        culprit = None
        for glyph in logo.plan.glyphs:
            faces, _ = load_logo_faces(p, rings=logo.rings([glyph]))
            alone = {colour: len(faces[colour]) for colour in ("white", "azure")}
            if cut_problem(split_inlays(blank, faces, plane, depths), alone) is not None:
                culprit = glyph.position
                break
        where = f"character {culprit}" if culprit is not None else "the line (each character alone is fine)"
        raise ConfigError(f"[text] l: {where} cannot be cut into a closed solid beside the sketch ({problem}); "
                          "use another character")
    return bodies, dict(inlay_solids=expected)


def load_face_l(p, logo):
    """(logo faces or None, logo report) of face L. logo None: today's logo file verbatim (report unchanged); else a
    logo_text.LogoChoice: the sketch with a custom wordmark ("wordmark") or a text-only face ("text")."""
    if logo is None:
        return load_logo_faces(p)
    if logo.mode == "text":
        return None, dict(file=None, bbox=logo.plan.ink, white_azure_overlap=0.0, **logo.report)
    try:
        faces, report = load_logo_faces(p, rings=logo.rings())
    except ValueError as error:
        raise ConfigError(f"[text] l: the wordmark outline cannot be built ({error}); use other characters") from None
    report.update(logo.report)
    return faces, report


def build_face_l(tube, p, logo, logo_faces):
    if logo is None:
        return build_logo_panel(tube, p, logo_faces)
    if logo.mode == "text":
        return build_text_panel(tube, p, "L", logo.plan)
    return build_wordmark_panel(tube, p, logo, logo_faces)


def print_rotation(face_name):
    """Rotation about X that turns the outer face down onto the bed (normal -> 270 deg)."""
    return (270.0 - FACE_NORMALS[face_name]) % 360.0


def build_panels(p, typo, numbers, text_plans, logo=None):
    """{face_name: (bodies, report)} for A, B, L plus the full tube (reference) and the logo report.
    numbers / text_plans: {face: number or None} / {face: free_text.TextPlan}, a face is in exactly one of them;
    logo: None (today's logo face) or a logo_text.LogoChoice ([text] l, [display] logo = "none")."""
    tube = build_tube(p)
    logo_faces, logo_report = load_face_l(p, logo)
    panels = {
        "A": build_display_panel(tube, p, "A", numbers["A"], text_plans.get("A"), typo),
        "B": build_display_panel(tube, p, "B", numbers["B"], text_plans.get("B"), typo),
        "L": build_face_l(tube, p, logo, logo_faces),
    }
    for name, (_, report) in panels.items():
        report["orientation"] = orientation_check(p, name)
        if report["orientation"]["mirrored"] or report["orientation"]["x_to_viewer_right"] < 0.999:
            raise AssertionError(f"face {name} would read mirrored from outside")
        report["next_presses_from_rest"] = FACE_ORDER.index(name)
    return panels, tube, logo_report
