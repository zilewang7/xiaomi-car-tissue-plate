"""Check 9: hole walls >= 1.2 (pressed 0.8 floors excepted) and horizontal holes are teardrops (spec 2.3 /
7-9). v3.1 had no automatic version of this check; it is measured on the CAD here.

Walls: the printed part (all colours fused) is cut perpendicular to each hole axis at a few depths; the wall
is the smallest distance from the hole outline to any other outline of that section. Floors / roofs are the
material run along the hole axis beyond the hole bottom. The 1.2 mm rule of spec 2.3 is a magnet-pocket
rule: magnet pockets are judged (hard), every other hole is reported (info). Upper tab pockets (v3.3 2.1): their 0.8
floor must rest on the box, so rays through it must end on the flat tab back face Y = 0 (hard).
Teardrops, in each part's print pose: (a) every round (cylindrical) hole with a horizontal axis is listed;
Ø > 2 mm fails, Ø <= 2 mm is a warning (its ceiling is a <= 1.4 mm curved bridge); (b) the teardrop holes
are cut perpendicular to their axis and their ceiling must be 45 deg slopes plus one flat bridge.
"""
import math

import build123d as bd
import numpy as np

from .common import item, section, solid_of

WALL_MIN = 1.2                # spec 2.3: magnet pocket walls
FLOOR_MIN = 0.8               # spec 2.3: pressed floors (exception to the wall rule)
SMALL_HOLE_D = 2.0            # round horizontal holes up to this diameter: warning only
ROOF_MAX_DEG = 45.0 + 1.0     # 45 deg roof + polygon tolerance
FLAT_DEG = 89.9
EDGE_SAMPLES = 32
BACKING_RAYS = 16             # rays per ring through an upper pocket floor (two rings + the centre)


# ---------------- hole tables (assembled pose; origin = open end on the axis, direction = into the hole) ----
def magnet_pockets(p):
    rows = []
    for stack, z in (("lower", p.mount_z), ("upper", p.upper_z)):
        for side in (-1, 1):
            rows.append(dict(part="front_bar", name=f"{stack} tab pocket {'+' if side > 0 else '-'}",
                             origin=(side * p.base_mag_x, p.tab_y[0], z), direction=(0, 1, 0),
                             depth=-p.mount_floor - p.tab_y[0]))
    for phi, (lobe_y, lobe_z) in zip(p.knob_phi, p.knob_lobes):
        rows.append(dict(part="knob", name=f"knob pocket {int(phi)}", origin=(p.knob_x[1], lobe_y, lobe_z),
                         direction=(-1, 0, 0), depth=p.knob_x[1] - p.knob_x[0] - p.det_floor))
    stator_y, stator_z = p.stator_yz
    rows.append(dict(part="cradle", name="stator pocket", origin=(p.near_block_x[0], stator_y, stator_z),
                     direction=(1, 0, 0), depth=p.near_block_x[1] - p.det_floor - p.near_block_x[0]))
    return rows


def other_holes(p):
    """Non-magnet holes: walls at given depths, optional roof run beyond the hole bottom."""
    y, z = p.axis
    near_mid, far_mid = 0.5 * sum(p.near_block_x), 0.5 * sum(p.far_block_x)
    return [
        dict(part="cradle", name="far bearing teardrop", origin=(p.far_block_x[0], y, z), direction=(1, 0, 0),
             depths=(far_mid - p.far_block_x[0],)),
        dict(part="cradle", name="near bearing teardrop", origin=(p.near_block_x[0], y, z), direction=(1, 0, 0),
             depths=(near_mid - p.near_block_x[0],)),
        dict(part="knob", name="screw bore through the keyed hex", origin=(p.knob_x[1], y, z), direction=(-1, 0, 0),
             depths=(p.knob_x[1] - 0.5 * (p.knob_hex_end + p.near_block_x[0]),)),
        dict(part="plug_near", name="keyed hex socket", origin=(p.rotor_x[1], y, z), direction=(-1, 0, 0),
             depths=(0.5 * (p.rotor_x[1] - p.knob_hex_end),)),
        dict(part="plug_far", name="far hex socket", origin=(p.rotor_x[0], y, z), direction=(1, 0, 0),
             depths=(0.5 * p.far_socket_depth,)),
    ]


TEARDROPS = ("far bearing teardrop", "near bearing teardrop", "stator pocket")


# ---------------- geometry tools ----------------
def section_faces(solid, point, normal):
    plane = bd.Plane(origin=tuple(point), z_dir=tuple(normal))
    cut = solid & (plane * bd.Rectangle(600, 600)).faces()[0]
    return [] if cut is None else list(cut.faces())


def hole_outline(solid, point, normal):
    """(face, index) of the inner wire of the section through point that surrounds point."""
    q = bd.Vector(*point)
    for face in section_faces(solid, point, normal):
        for index, wire in enumerate(face.inner_wires()):
            box = wire.bounding_box()
            if all(lo - 1e-6 <= v <= hi + 1e-6 for lo, v, hi in zip(box.min, q, box.max)):
                return face, index
    return None, None


def wall_at(solid, point, normal):
    face, index = hole_outline(solid, point, normal)
    if face is None:
        return None
    inner = face.inner_wires()
    others = [face.outer_wire()] + [w for k, w in enumerate(inner) if k != index]
    return min(inner[index].distance_to(other) for other in others)


def material_run(solid, start, direction, length=20.0):
    """Length of the first material segment along the ray start + t * direction (t > 0); start in a void."""
    start, direction = np.asarray(start, float), np.asarray(direction, float)
    edge = bd.Edge.make_line(bd.Vector(*start), bd.Vector(*(start + length * direction)))
    inside = solid & edge
    if inside is None:
        return 0.0
    runs = []
    for segment in inside.edges():
        a = (np.array(tuple(segment.start_point())) - start) @ direction
        b = (np.array(tuple(segment.end_point())) - start) @ direction
        runs.append((min(a, b), max(a, b)))
    first = min(runs)
    return first[1] - first[0]


def at(origin, direction, distance):
    return np.asarray(origin, float) + distance * np.asarray(direction, float)


# ---------------- walls ----------------
def pocket_walls(model, solids):
    rows = {}
    for pocket in magnet_pockets(model.params):
        solid, depth = solids[pocket["part"]], pocket["depth"]
        walls = [wall_at(solid, at(pocket["origin"], pocket["direction"], d), pocket["direction"])
                 for d in (0.25, 0.5 * depth, depth - 0.25)]
        floor_start = at(pocket["origin"], pocket["direction"], depth - 0.05)     # just inside the pocket
        floor = material_run(solid, floor_start, pocket["direction"])
        rows[pocket["name"]] = dict(part=pocket["part"], wall_min=min(w for w in walls if w is not None),
                                    walls=walls, floor=floor, depth=depth)
    return rows


def floor_backing(p, solid):
    """Upper tab pockets: rays along +Y through the 0.8 floor (centre and two rings); where each ray's material ends."""
    radius = p.mag_pocket_d / 2 - 0.05
    offsets = [(0.0, 0.0)] + [(frac * radius * math.cos(a), frac * radius * math.sin(a)) for frac in (0.5, 1.0)
                              for a in np.linspace(0.0, 2 * math.pi, BACKING_RAYS, endpoint=False)]
    floors, ends = [], []
    for side in (-1, 1):
        for dx, dz in offsets:
            start = (side * p.base_mag_x + dx, -p.mount_floor - 0.05, p.upper_z + dz)      # 0.05 inside the pocket
            run = material_run(solid, start, (0.0, 1.0, 0.0))
            floors.append(run)
            ends.append(-p.mount_floor + run)
    return dict(rays=len(floors), floor_min=min(floors), floor_max=max(floors),
                end_off_box_face=round(max(abs(y) for y in ends), 6))


def hole_walls(model, solids):
    rows = {}
    for hole in other_holes(model.params):
        solid = solids[hole["part"]]
        walls = [wall_at(solid, at(hole["origin"], hole["direction"], d), hole["direction"]) for d in hole["depths"]]
        row = dict(part=hole["part"], wall_min=min(w for w in walls if w is not None))
        if "roof_at" in hole:
            start = at(hole["origin"], hole["direction"], hole["roof_at"] - 0.05)  # just inside the hole
            row["roof"] = material_run(solid, start, hole["direction"])
        rows[hole["name"]] = row
    return rows


# ---------------- teardrops ----------------
def round_horizontal_holes(model):
    """Concave cylinders whose axis is horizontal in the print pose: {part: [(diameter, count)]}."""
    found = {}
    for part in model.parts.values():
        holes = set()
        for face in part.printed().faces():
            if face.geom_type != bd.GeomType.CYLINDER:
                continue
            axis = face.axis_of_rotation
            point, normal = face.position_at(0.5, 0.5), face.normal_at(0.5, 0.5)
            radial = point - axis.position
            radial = radial - axis.direction * radial.dot(axis.direction)
            if normal.dot(radial) >= 0 or abs(axis.direction.Z) > 0.1:
                continue                                    # convex (boss) or vertical in the print
            foot = axis.position - axis.direction * axis.position.dot(axis.direction)    # axis line id
            holes.add((round(2 * face.radius, 3), tuple(round(v, 2) for v in foot)))
        if holes:
            diameters = sorted({d for d, _ in holes})
            found[part.name] = [(d, sum(1 for h in holes if h[0] == d)) for d in diameters]
    return found


def ceiling(face_wire, centre, up, plane_normal):
    """Overhang of the hole outline in the print pose: max roof angle of sloped / curved ceiling, flat bridge
    length. Angle from vertical: 0 = wall, 45 = teardrop roof, 90 = flat ceiling."""
    worst_slope, flat, curved = 0.0, 0.0, 0.0
    for edge in face_wire.edges():
        if edge.geom_type == bd.GeomType.LINE:
            samples = [(0.5, edge.end_point() - edge.start_point())]
        else:
            samples = [(t, edge.tangent_at(t)) for t in np.linspace(0.02, 0.98, EDGE_SAMPLES)]
        for t, tangent in samples:
            normal = plane_normal.cross(tangent).normalized()
            if normal.dot(edge.position_at(t) - centre) < 0:
                normal = -normal                             # pointing into the material
            lift = normal.dot(up)
            if lift <= 0:
                continue                                     # floor side of the hole
            angle = math.degrees(math.asin(min(1.0, lift)))
            if edge.geom_type == bd.GeomType.LINE and angle >= FLAT_DEG:
                flat += edge.length
            elif edge.geom_type == bd.GeomType.LINE:
                worst_slope = max(worst_slope, angle)
            else:
                curved = max(curved, angle)
    return dict(max_roof_deg=worst_slope, flat_bridge=flat, curved_ceiling_deg=curved)


def printed_point(part, point):
    """Assembled-pose point -> print pose."""
    return (part.to_print * bd.Pos(*point)).position


def teardrop_roofs(model):
    p = model.params
    rows = {}
    holes = {h["name"]: h for h in other_holes(p)}
    stator = next(h for h in magnet_pockets(p) if h["name"] == "stator pocket")
    holes["stator pocket"] = dict(stator, depths=(0.5 * stator["depth"],))
    for name in TEARDROPS:
        hole = holes[name]
        part = model.parts[hole["part"]]
        solid = part.to_print * solid_of(part)
        point = printed_point(part, at(hole["origin"], hole["direction"], hole["depths"][0]))
        normal = (printed_point(part, at(hole["origin"], hole["direction"], 1.0))
                  - printed_point(part, hole["origin"])).normalized()
        face, index = hole_outline(solid, tuple(point), tuple(normal))
        wire = face.inner_wires()[index]
        profile = ceiling(wire, wire.bounding_box().center(), bd.Vector(0, 0, 1), normal)
        horizontal = abs(normal.Z) < 1e-6
        profile.update(axis_horizontal_in_print=horizontal,
                       ok=(not horizontal) or (profile["max_roof_deg"] <= ROOF_MAX_DEG and profile["curved_ceiling_deg"] <= ROOF_MAX_DEG))
        rows[name] = profile
    return rows


def run(model):
    solids = {name: solid_of(model.parts[name]) for name in
              ("front_bar", "knob", "cradle", "plug_near", "plug_far", "far_pin")}
    pockets = pocket_walls(model, solids)
    backing = floor_backing(model.params, solids["front_bar"])
    holes = hole_walls(model, solids)
    rounds = round_horizontal_holes(model)
    roofs = teardrop_roofs(model)
    items = []
    for name, row in pockets.items():
        items.append(item(f"{name}: wall (mm)", row["wall_min"], row["wall_min"] >= WALL_MIN - 1e-6, f">= {WALL_MIN}"))
        items.append(item(f"{name}: pressed floor (mm)", row["floor"], row["floor"] >= FLOOR_MIN - 0.01,
                          f">= {FLOOR_MIN} (exception to the wall rule)"))
    backed = backing["end_off_box_face"] <= 1e-3 and backing["floor_min"] >= FLOOR_MIN - 0.01
    items.append(item(f"upper tab pocket floors on the flat back face: {backing['rays']} rays, floor min / max, largest "
                      "|Y| where the material ends (mm)",
                      (backing["floor_min"], backing["floor_max"], backing["end_off_box_face"]), backed,
                      f"every ray ends on the box face Y = 0 (<= 0.001), floor >= {FLOOR_MIN}",
                      note="the box face carries the whole upper floor (no lead-in on the tab top edge, v3.3 2.1)"))
    for name, row in holes.items():
        value = (row["wall_min"], row["roof"]) if "roof" in row else row["wall_min"]
        label = f"{name}: wall / roof (mm)" if "roof" in row else f"{name}: wall (mm)"
        items.append(item(label, value, level="info", note="not a magnet pocket"))
    for part_name, rows in rounds.items():
        for diameter, count in rows:
            level = "warn" if diameter <= SMALL_HOLE_D else "hard"
            items.append(item(f"{part_name}: {count} round horizontal hole(s) Ø{diameter:g} in the print pose", diameter,
                              False, f"teardrop (round tolerated up to Ø{SMALL_HOLE_D:g} as a warning)", level=level,
                              note="ceiling is a curved bridge of 0.71 x Ø" if level == "warn" else ""))
    for name, row in roofs.items():
        items.append(item(f"{name}: teardrop roof in the print pose (deg from vertical)", row["max_roof_deg"], row["ok"],
                          f"<= 45 roof + one flat bridge (flat {row['flat_bridge']:.2f} mm)"))
    numbers = dict(magnet_pockets=pockets, upper_floor_backing=backing, other_holes=holes,
                   round_horizontal_holes=rounds, teardrops=roofs)
    return section("9 hole walls >= 1.2 (pressed 0.8 floors excepted), horizontal holes are teardrops", items, numbers)
