"""Front bar F (spec 4.2, 4.3; v3.3 2.1, 2.2): 10 mm beam + two U tabs on the box magnet points, one print, front
face down.

Tabs: 20 wide, round bottom (true R10 arc) at tab_bottom (config, -40), 1.5 x 45 deg lead-in on the sides and the
round bottom of the back face; the top edge has none (v3.3), so the flat back face runs up to tab_top and backs the
whole upper pocket floor. Two mount pockets per tab, Ø8.3 open at the front face with a 0.8 floor toward the box
(the magnets are pulled onto it), depth = tab thickness - floor (7.2 for stack 2): the lower one mount_delta above
the base magnet point, the upper one upper_delta above the lid magnet point. No dowel holes (10-18: glued to the
lip directly). 0.4 x 45 deg chamfer on the front-face outline. Accent (v3.3 option E): one continuous azure
round-ended line on the front face, beam_line_top_seam below the top chamfer edge and above the upper pocket mouths,
rotor-length, inlaid azure_depth deep as a separate solid; the caps are navy, so the front shows the line only.
v3.1 drew the tab bottom as a 96-gon; chamfering that polygon left OCCT's volume integral 0.43 % high on
the bar (the mesh was right), so the tab is built from a true arc (shape change < 0.01 mm).
"""
import build123d as bd

from .shapes import CUT_OVERSHOOT, circle_pts, hull_pts, xz_prism, y_cyl


def tab_prism(p, centre_x):
    """One U tab: straight sides from tab_top down to the arc centre, R = tab_w / 2 arc bottom, along +Y."""
    half, y0 = p.tab_w / 2, p.tab_y[0]
    left_top, left_low = bd.Vector(centre_x - half, y0, p.tab_top), bd.Vector(centre_x - half, y0, p.tab_zc)
    right_top, right_low = bd.Vector(centre_x + half, y0, p.tab_top), bd.Vector(centre_x + half, y0, p.tab_zc)
    bottom = bd.Vector(centre_x, y0, p.tab_zc - half)
    outline = bd.Wire([bd.Edge.make_line(left_top, left_low), bd.Edge.make_three_point_arc(left_low, bottom, right_low),
                       bd.Edge.make_line(right_low, right_top), bd.Edge.make_line(right_top, left_top)])
    return bd.extrude(bd.Face(outline), p.tab_y[1] - p.tab_y[0], dir=(0, 1, 0))


def lead_in_edges(p, tab):
    """Back-face edges of a tab that get the lead-in: the sides and the round bottom, not the straight top edge."""
    back = tab.faces().sort_by(bd.Axis.Y)[-1]
    return [edge for edge in back.edges()
            if not (edge.geom_type == bd.GeomType.LINE and abs(edge.start_point().Z - p.tab_top) < 1e-6
                    and abs(edge.end_point().Z - p.tab_top) < 1e-6)]


def pocket_walls(p):
    """Printed walls around the two mount pockets in the tab plane, mm (the 0.8 floors are the allowed exception):
    lower = lower pocket to the tab sides / round bottom (the v3.2 value), upper_sides, between_pockets, to_beam_top;
    floor_backing = flat back face top - upper pocket top (>= 0: the box face backs the whole upper floor)."""
    pocket_r = p.mag_pocket_d / 2
    side = p.tab_w / 2 - pocket_r
    lower = side if p.mount_z >= p.tab_zc else min(side, p.tab_w / 2 - (p.tab_zc - p.mount_z) - pocket_r)
    upper_bottom, upper_top = p.upper_pocket_z
    walls = dict(lower=lower, upper_sides=side, between_pockets=upper_bottom - (p.mount_z + pocket_r),
                 to_beam_top=p.z0 - upper_top, floor_backing=p.flat_back_top - upper_top)
    return {name: round(value, 6) for name, value in walls.items()}


def beam_line_seams(p):
    """Navy seams (mm) from the accent line to the flat front face edges (beam top / bottom minus the front chamfer)
    and down to the upper pocket mouths."""
    half = p.beam_line_w / 2
    return dict(to_top=round(p.z0 - p.front_chamfer - (p.beam_line_z + half), 6),
                to_bottom=round(p.beam_line_z - half - (p.beam_z[0] + p.front_chamfer), 6),
                to_upper_pocket=round(p.beam_line_z - half - p.upper_pocket_z[1], 6))


def beam_line_outline(p):
    """(X, Z) outline of the azure accent line: round ends, spanning the rotor length."""
    radius = p.beam_line_w / 2
    left, right = p.rotor_x[0] + radius, p.rotor_x[1] - radius
    return hull_pts([circle_pts(left, p.beam_line_z, radius, 48), circle_pts(right, p.beam_line_z, radius, 48)])


def chamfer_front_face(front, size):
    front_face = front.faces().sort_by(bd.Axis.Y)[0]
    return bd.chamfer(front_face.outer_wire().edges(), size)


def check_layout(p):
    """Raise when the pockets or the accent line do not fit (never moves them)."""
    walls = pocket_walls(p)
    thin = {name: round(walls[name], 3) for name in ("lower", "upper_sides", "between_pockets", "to_beam_top")
            if walls[name] < p.pocket_wall_min}
    if thin:
        raise ValueError(f"mount pocket walls {thin} mm < {p.pocket_wall_min} mm (tab_bottom {p.tab_bottom}, base magnet "
                         f"Z {p.base_mag_z}, lid magnet Z {p.lid_mag_z})")
    if walls["floor_backing"] < 0:
        raise ValueError(f"upper pocket top Z {p.upper_pocket_z[1]:.2f} is above the flat back face top Z "
                         f"{p.flat_back_top}: its 0.8 floor would not rest on the box (lid magnet Z {p.lid_mag_z})")
    seams = beam_line_seams(p)
    edges = {name: seams[name] for name in ("to_top", "to_bottom")}
    if min(edges.values()) < p.beam_line_seam:
        raise ValueError(f"accent line at Z {p.beam_line_z:.2f}: navy seams {edges} to the front chamfer < "
                         f"{p.beam_line_seam} mm (pads {p.pad_t})")
    if seams["to_upper_pocket"] < p.beam_line_pocket_gap:
        raise ValueError(f"accent line at Z {p.beam_line_z:.2f}: navy gap {seams['to_upper_pocket']} mm to the upper "
                         f"pocket mouths < {p.beam_line_pocket_gap} mm (lid magnet Z {p.lid_mag_z}, pads {p.pad_t})")
    return walls, seams


def build_front_bar(p):
    """{'bodies': {'navy', 'azure'}, 'beam': plain beam for clearance checks, 'pocket_walls', 'line_seams'}."""
    walls, seams = check_layout(p)
    beam = bd.Pos(p.beam_x[0], p.beam_y[0], p.beam_z[0]) * bd.Box(p.beam_x[1] - p.beam_x[0], p.beam_y[1] - p.beam_y[0],
                                                                   p.beam_h, align=(bd.Align.MIN,) * 3)
    front = beam
    for side in (-1, 1):
        tab = tab_prism(p, side * p.base_mag_x)
        tab = bd.chamfer(lead_in_edges(p, tab), p.tab_leadin)    # lead-in on the back face
        front = front + tab
    front = chamfer_front_face(front, p.front_chamfer)
    for side in (-1, 1):
        for z in (p.mount_z, p.upper_z):
            front = front - y_cyl(p.mag_pocket_d / 2, p.tab_y[0] - 0.1, -p.mount_floor, side * p.base_mag_x, z)
    line_cutter = xz_prism(beam_line_outline(p), p.tab_y[0] - CUT_OVERSHOOT, p.tab_y[0] + p.azure_depth)
    bodies = {"navy": front - line_cutter, "azure": front & line_cutter}     # one solid: it clears the pockets
    return {"bodies": bodies, "beam": beam, "pocket_walls": walls, "line_seams": seams}
