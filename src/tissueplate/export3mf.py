"""Bambu Studio project 3MF writer.

Writes the same package layout that Bambu Studio 2.x saves (3MF core + production extension):
  3D/3dmodel.model            assembly objects + build items (bed position of each object)
  3D/Objects/object_<k>.model meshes of the parts of object k
  Metadata/model_settings.config   object names, per-object settings, part names + extruders, plates
  Metadata/project_settings.config full slicer config (optional, see bambu.export_project_settings)

A multi-colour part must be ONE object with several parts (one part per filament); separate objects get
their own elephant-foot compensation, which cuts grooves around inlays.

write_production_plates(model) packs the production plates (2-plate design doc: 1 colour, 2 navy) into ONE project
out/plates/parking_plate.3mf, slices it once with the CLI and writes out/plates/slice_report.json.
"""
from __future__ import annotations

import json
import math
import shutil
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree
from xml.sax.saxutils import escape, quoteattr

import numpy as np
from scipy.spatial import cKDTree

from . import bambu
from .params import COLOURS, OUT_DIR, PROJECT_DIR

APPLICATION = "BambuStudio-02.08.02.61"
BED_SIZE = (256.0, 256.0)          # P1S printable area
PLATE_GAP_FACTOR = 1.2             # Bambu lays plates out on a grid with a 20 % gap
IDENTITY_3MF = "1 0 0 0 1 0 0 0 1 0 0 0"
IDENTITY_4X4 = "1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"
WELD_STEP = 1e-5                   # mm; tessellation is per face, coincident vertices are merged
BRIM_EARS_FILE = "Metadata/brim_ear_points.txt"     # painted brim ears ("brim_ears" brim type)
BRIM_EARS_VERSION = 1      # as Bambu Studio 2.08 saves it: "x y z radius -1" per point, object coordinates

NS_CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
NS_PROD = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
NS_BAMBU = "http://schemas.bambulab.com/package/2021"
REL_3DMODEL = "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"


@dataclass
class Mesh:
    vertices: np.ndarray       # (n, 3) float, mm
    triangles: np.ndarray      # (m, 3) int, counter-clockwise seen from outside


@dataclass
class Part:
    name: str
    mesh: Mesh
    extruder: int              # 1-based filament index (= AMS slot)


@dataclass
class PlateObject:
    name: str
    parts: list[Part]
    position: tuple[float, float]                       # bed XY added to the part coordinates
    settings: dict[str, str] = field(default_factory=dict)   # per-object process overrides
    brim_ears: list[tuple[float, float, float]] = field(default_factory=list)   # (x, y, radius), part coords, Z = 0


@dataclass
class Plate:
    name: str
    objects: list[PlateObject]
    settings: dict[str, str] = field(default_factory=dict)   # plate metadata, e.g. first_layer_print_sequence


def welded_mesh(vertices, faces, keys) -> Mesh:
    """Vertices with equal keys merged, collapsed triangles dropped."""
    _, first_index, inverse = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    faces = inverse.reshape(-1)[faces]
    keep = (faces[:, 0] != faces[:, 1]) & (faces[:, 1] != faces[:, 2]) & (faces[:, 0] != faces[:, 2])
    return Mesh(vertices[first_index], faces[keep])


def mesh_from_shape(shape, tolerance: float = 0.01, angular_tolerance: float = 0.15) -> Mesh:
    """Tessellate a build123d shape into a welded, closed triangle mesh; raise if it is not closed."""
    points, triangles = shape.tessellate(tolerance, angular_tolerance)
    vertices = np.array([(p.X, p.Y, p.Z) for p in points], dtype=float)
    faces = np.array(triangles, dtype=np.int64).reshape(-1, 3)
    mesh = welded_mesh(vertices, faces, np.round(vertices / WELD_STEP).astype(np.int64))
    try:
        check_closed(mesh, shape.volume)
    except ValueError:
        # v3.4 6.8: a vertex within float noise of a WELD_STEP half step splits on the grid (free-text glyphs);
        # weld by distance instead (the number faces never get here)
        groups = cKDTree(vertices).query_ball_point(vertices, r=WELD_STEP)
        mesh = welded_mesh(vertices, faces, np.array([[min(group)] for group in groups], dtype=np.int64))
        check_closed(mesh, shape.volume)
    return mesh


def mesh_volume(mesh: Mesh) -> float:
    a, b, c = (mesh.vertices[mesh.triangles[:, k]] for k in range(3))
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


def check_closed(mesh: Mesh, expected_volume: float) -> None:
    """Every edge must be shared by exactly two triangles and the signed volume must match the solid."""
    edges = np.sort(np.vstack([mesh.triangles[:, [0, 1]], mesh.triangles[:, [1, 2]], mesh.triangles[:, [2, 0]]]), axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    open_edges = int((counts != 2).sum())
    volume = mesh_volume(mesh)
    if open_edges or abs(volume - expected_volume) > 0.005 * abs(expected_volume) + 0.01:
        raise ValueError(f"mesh is not a closed solid: {open_edges} bad edges, volume {volume:.3f} vs {expected_volume:.3f}")


def plate_origin(plate_index: int, plate_count: int, bed_size=BED_SIZE) -> tuple[float, float]:
    """World XY of plate i (0-based) in a Bambu project (plates on a near-square grid)."""
    root = math.sqrt(plate_count)
    columns = int(round(root)) + (1 if root > round(root) else 0)
    row, column = divmod(plate_index, columns)
    return column * bed_size[0] * PLATE_GAP_FACTOR, -row * bed_size[1] * PLATE_GAP_FACTOR


def _uuid() -> str:
    return str(uuid.uuid4())


def _mesh_object_xml(object_id: int, mesh: Mesh) -> str:
    vertex_lines = "\n".join(f'     <vertex x="{x:.6f}" y="{y:.6f}" z="{z:.6f}"/>' for x, y, z in mesh.vertices)
    triangle_lines = "\n".join(f'     <triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in mesh.triangles)
    return (f'  <object id="{object_id}" p:UUID="{_uuid()}" type="model">\n   <mesh>\n    <vertices>\n{vertex_lines}\n'
            f'    </vertices>\n    <triangles>\n{triangle_lines}\n    </triangles>\n   </mesh>\n  </object>')


def _model_header(extra_metadata: str = "") -> str:
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<model unit="millimeter" xml:lang="en-US" xmlns="{NS_CORE}" xmlns:BambuStudio="{NS_BAMBU}" '
            f'xmlns:p="{NS_PROD}" requiredextensions="p">\n'
            ' <metadata name="BambuStudio:3mfVersion">1</metadata>\n' + extra_metadata)


def _metadata_lines(entries: dict[str, str], indent: str) -> list[str]:
    return [f'{indent}<metadata key={quoteattr(key)} value={quoteattr(str(value))}/>' for key, value in entries.items()]


def write_bambu_3mf(path: str | Path, plates: list[Plate], project_settings: dict | None = None,
                    title: str = "", bed_size=BED_SIZE) -> Path:
    """Write a Bambu Studio project with the given plates; returns the path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    next_id = 1
    object_files: dict[str, str] = {}
    assemblies, build_items, object_configs, plate_configs, ear_lines = [], [], [], [], []
    identify_id = 100
    for plate_index, plate in enumerate(plates):
        origin_x, origin_y = plate_origin(plate_index, len(plates), bed_size)
        instances = []
        for plate_object in plate.objects:
            file_index = len(object_files) + 1
            object_path = f"/3D/Objects/object_{file_index}.model"
            mesh_xml, components, part_configs = [], [], []
            for part in plate_object.parts:
                part_id = next_id
                next_id += 1
                mesh_xml.append(_mesh_object_xml(part_id, part.mesh))
                components.append(f'    <component p:path="{object_path}" objectid="{part_id}" p:UUID="{_uuid()}" '
                                  f'transform="{IDENTITY_3MF}"/>')
                part_configs.append("\n".join(
                    [f'    <part id="{part_id}" subtype="normal_part">']
                    + _metadata_lines({"name": part.name, "matrix": IDENTITY_4X4, "extruder": part.extruder}, "      ")
                    + ["    </part>"]))
            assembly_id = next_id
            next_id += 1
            object_files[object_path] = (_model_header() + " <resources>\n" + "\n".join(mesh_xml)
                                         + "\n </resources>\n <build/>\n</model>\n")
            assemblies.append(f'  <object id="{assembly_id}" p:UUID="{_uuid()}" type="model">\n   <components>\n'
                              + "\n".join(components) + "\n   </components>\n  </object>")
            x = origin_x + plate_object.position[0]
            y = origin_y + plate_object.position[1]
            build_items.append(f'  <item objectid="{assembly_id}" p:UUID="{_uuid()}" '
                               f'transform="1 0 0 0 1 0 0 0 1 {x:.4f} {y:.4f} 0" printable="1"/>')
            object_metadata = {"name": plate_object.name, "extruder": plate_object.parts[0].extruder}
            object_metadata.update(plate_object.settings)
            object_configs.append("\n".join([f'  <object id="{assembly_id}">'] + _metadata_lines(object_metadata, "    ")
                                            + part_configs + ["  </object>"]))
            if plate_object.brim_ears:      # keyed by the 1-based object order, like Bambu's own exporter
                ear_lines.append(f"object_id={file_index}|" + " ".join(
                    f"{x:.6f} {y:.6f} 0.000000 {radius:.6f} -1" for x, y, radius in plate_object.brim_ears))
            identify_id += 1
            instances.append("\n".join(["    <model_instance>"]
                                       + _metadata_lines({"object_id": assembly_id, "instance_id": 0,
                                                          "identify_id": identify_id}, "      ")
                                       + ["    </model_instance>"]))
        plate_configs.append("\n".join(["  <plate>"]
                                       + _metadata_lines({"plater_id": plate_index + 1, "plater_name": plate.name,
                                                          "locked": "false", **plate.settings}, "    ")
                                       + instances + ["  </plate>"]))

    root_metadata = (f' <metadata name="Application">{APPLICATION}</metadata>\n'
                     f' <metadata name="Title">{escape(title)}</metadata>\n')
    root_model = (_model_header(root_metadata) + " <resources>\n" + "\n".join(assemblies) + "\n </resources>\n"
                  f' <build p:UUID="{_uuid()}">\n' + "\n".join(build_items) + "\n </build>\n</model>\n")
    model_rels = ('<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
                  + "\n".join(f' <Relationship Target="{p}" Id="rel-{i + 1}" Type="{REL_3DMODEL}"/>'
                              for i, p in enumerate(object_files)) + "\n</Relationships>\n")
    root_rels = ('<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
                 f' <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="{REL_3DMODEL}"/>\n</Relationships>\n')
    content_types = ('<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
                     ' <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
                     ' <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>\n'
                     ' <Default Extension="png" ContentType="image/png"/>\n'
                     ' <Default Extension="gcode" ContentType="text/x.gcode"/>\n</Types>\n')
    model_settings = ('<?xml version="1.0" encoding="UTF-8"?>\n<config>\n' + "\n".join(object_configs) + "\n"
                      + "\n".join(plate_configs) + "\n  <assemble>\n  </assemble>\n</config>\n")

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("3D/3dmodel.model", root_model)
        archive.writestr("3D/_rels/3dmodel.model.rels", model_rels)
        for object_path, text in object_files.items():
            archive.writestr(object_path.lstrip("/"), text)
        archive.writestr("Metadata/model_settings.config", model_settings)
        if ear_lines:
            archive.writestr(BRIM_EARS_FILE, f"brim_points_format_version={BRIM_EARS_VERSION}\n" + "\n".join(ear_lines) + "\n")
        if project_settings is not None:
            archive.writestr("Metadata/project_settings.config", json.dumps(project_settings, indent=4, ensure_ascii=False))
    return path


# ================================================================== reading a 3MF back
def _keyed_metadata(element) -> dict[str, str]:
    return {item.get("key"): item.get("value") for item in element.findall("metadata") if item.get("key") is not None}


def read_model_settings(path: str | Path) -> dict[str, dict]:
    """Objects in Metadata/model_settings.config: {name: {"extruder", "settings", "parts": {part name: extruder}}}.

    A part without its own extruder (Bambu omits it when it equals the object's) uses the object's extruder."""
    with zipfile.ZipFile(path) as archive:
        root = ElementTree.fromstring(archive.read("Metadata/model_settings.config"))
    objects = {}
    for element in root.findall("object"):
        metadata = _keyed_metadata(element)
        name = metadata.pop("name")
        extruder = int(metadata.pop("extruder", "1"))
        parts = {}
        for part in element.findall("part"):
            part_metadata = _keyed_metadata(part)
            parts[part_metadata["name"]] = int(part_metadata.get("extruder", "0")) or extruder
        objects[name] = {"extruder": extruder, "settings": metadata, "parts": parts}
    return objects


def assignment_problems(found: dict[str, dict], expected: dict[str, dict]) -> list[str]:
    """Differences in objects, part extruders and per-object settings between a read-back 3MF and the plan."""
    problems = [f"unexpected object {name}" for name in sorted(set(found) - set(expected))]
    for name, plan in expected.items():
        if name not in found:
            problems.append(f"{name}: missing")
            continue
        if found[name]["parts"] != plan["parts"]:
            problems.append(f"{name}: part extruders {found[name]['parts']} != {plan['parts']}")
        for key, value in plan["settings"].items():
            if found[name]["settings"].get(key) != value:
                problems.append(f"{name}: {key} = {found[name]['settings'].get(key)!r}, expected {value!r}")
    return problems


# ================================================================== production plates (2-plate design doc)
PLATES_DIR = OUT_DIR / "plates"
PROJECT_FILE = "parking_plate.3mf"        # every production plate in one Bambu project
OLD_PROJECT_FILES = ("yu7_plates.3mf", "plate1.3mf", "plate2.3mf", "plate3.3mf")   # names of earlier versions
PLATE_NAMES = {1: "1 colour", 2: "2 navy"}
PLATE_CONTENTS = {1: "colour: panels PA PB PL, front bar F, knob K, cooling tube Q",
                  2: "navy: cradle C, plugs EN EF, far pins P, caps D, spacer S"}
TOWER_CORNER = (211.0, 211.0)    # wipe tower of a multi-colour plate, back-right; its box spans about -3 .. +42 mm
EAR_RADIUS = 5.0              # mm, mouse ears on the four panel corners (spec 4.2)
BRIM_ALLOWANCE = {"panel": 0.0, "struct": 5.0, "small": 3.0, "pin": 3.0, "cooling": 3.0}   # mm kept for its brim
SHRINK_ALLOWANCE = 1.0        # mm per side: shrink compensation scales XY by 1 / 0.994
LAYOUT_MARGIN, LAYOUT_GAP = 6.0, 6.0
TOWER_CLEARANCE = 10.0        # mm kept free in front of and left of the wipe tower corner
EAR_TOLERANCE = 1.0           # mm, first-layer brim of an ear lies within radius + this of its corner
STRUCT_BRIM_REACH = (4.0, 6.0)   # mm, a 5 mm outer brim seen beyond the CAD footprint (shrink growth included)
PIN_BRIM_REACH = (2.0, 4.0)      # mm, the 3 mm outer brim of the far pins
PLACE_TOLERANCE = 0.1         # mm, sliced object box vs the arranged box
ON_BED = 1e-6
# s per layer under every small / pin part (knob-cooling design doc): Bambu slows a layer to 12 s unless it hits the
# 20 mm/s floor (layers it slowed read 11.5-12.0 s); the knob printing alone got 2-3 s and jammed in EN (10-16)
MIN_SMALL_LAYER_S = 10.0


def _vertices(plate_object: PlateObject) -> np.ndarray:
    return np.vstack([part.mesh.vertices for part in plate_object.parts])


def bed_box(plate_object: PlateObject) -> tuple[float, float, float, float]:
    """XY box of the vertices lying on the bed (Z = 0), all parts of the object."""
    vertices = _vertices(plate_object)
    on_bed = vertices[np.abs(vertices[:, 2]) < ON_BED]
    (x0, y0), (x1, y1) = on_bed[:, :2].min(axis=0), on_bed[:, :2].max(axis=0)
    return float(x0), float(y0), float(x1), float(y1)


def production_object(piece, layer_height: float) -> PlateObject:
    """One slicer object per printed piece, one part per colour (navy body first), spec per-object settings."""
    colours = sorted(piece.colours, key=lambda colour: colour != "navy")
    parts = [Part(f"{piece.name}.{colour}", mesh_from_shape(piece.printed(colour)), COLOURS[colour]["slot"])
             for colour in colours]
    plate_object = PlateObject(f"{piece.label}_{piece.name}", parts, (0.0, 0.0),
                               bambu.production_settings(piece.process, layer_height))
    if piece.process == "panel":
        x0, y0, x1, y1 = bed_box(plate_object)
        plate_object.brim_ears = [(x, y, EAR_RADIUS) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
    return plate_object


def layout_box(plate_object: PlateObject, process: str) -> tuple[float, float, float, float]:
    """Bed area an object needs around its origin: footprint + brim (or ears) + shrink growth."""
    vertices = _vertices(plate_object)
    grow = BRIM_ALLOWANCE[process] + SHRINK_ALLOWANCE
    (x0, y0), (x1, y1) = vertices[:, :2].min(axis=0) - grow, vertices[:, :2].max(axis=0) + grow
    for x, y, radius in plate_object.brim_ears:
        reach = radius + SHRINK_ALLOWANCE
        x0, y0, x1, y1 = min(x0, x - reach), min(y0, y - reach), max(x1, x + reach), max(y1, y + reach)
    return float(x0), float(y0), float(x1), float(y1)


def keep_out_zones(project_settings: dict, with_tower: bool,
                   tower_xy: tuple[float, float] | None = None) -> list[tuple[float, float, float, float]]:
    """Bed rectangles no layout box may touch: the machine's excluded corner and, with a tower, its corner
    (tower_xy, default the project's first wipe_tower_x / y)."""
    zones = []
    corners = [tuple(float(value) for value in point.split("x")) for point in project_settings.get("bed_exclude_area", [])]
    if corners:
        xs, ys = [corner[0] for corner in corners], [corner[1] for corner in corners]
        zones.append((min(xs) - LAYOUT_GAP, min(ys) - LAYOUT_GAP, max(xs) + LAYOUT_GAP, max(ys) + LAYOUT_GAP))
    if with_tower:
        tower_x, tower_y = tower_xy or (float(project_settings["wipe_tower_x"][0]), float(project_settings["wipe_tower_y"][0]))
        zones.append((tower_x - TOWER_CLEARANCE, tower_y - TOWER_CLEARANCE, BED_SIZE[0], BED_SIZE[1]))
    return zones


def _overlap(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _shifted(box, position):
    return (box[0] + position[0], box[1] + position[1], box[2] + position[0], box[3] + position[1])


def arrange(boxes: dict[str, tuple], zones: list[tuple], bed=BED_SIZE) -> dict[str, tuple[float, float]]:
    """Rows of layout boxes, deepest first, each row centred in X. The block starts centred in Y and moves toward
    the front in 1 mm steps until no box touches a keep-out zone. Returns {name: bed XY of the object origin}."""
    width = {name: box[2] - box[0] for name, box in boxes.items()}
    depth = {name: box[3] - box[1] for name, box in boxes.items()}
    usable = bed[0] - 2 * LAYOUT_MARGIN
    rows: list[list[str]] = [[]]
    for name in sorted(boxes, key=lambda n: (-depth[n], -width[n], n)):
        if width[name] > usable:
            raise RuntimeError(f"{name} is wider than the bed")
        if rows[-1] and sum(width[n] + LAYOUT_GAP for n in rows[-1]) + width[name] > usable:
            rows.append([])
        rows[-1].append(name)
    row_depths = [max(depth[name] for name in row) for row in rows]
    y_front = (bed[1] - sum(row_depths) - LAYOUT_GAP * (len(rows) - 1)) / 2
    while y_front >= LAYOUT_MARGIN:
        corners, y = {}, y_front
        for row, row_depth in zip(rows, row_depths):
            x = (bed[0] - sum(width[n] for n in row) - LAYOUT_GAP * (len(row) - 1)) / 2
            for name in row:
                corners[name] = (x, y)
                x += width[name] + LAYOUT_GAP
            y += row_depth + LAYOUT_GAP
        rects = [(x, y, x + width[n], y + depth[n]) for n, (x, y) in corners.items()]
        inside = all(r[0] >= LAYOUT_MARGIN and r[2] <= bed[0] - LAYOUT_MARGIN and r[3] <= bed[1] - LAYOUT_MARGIN
                     for r in rects)
        if inside and not any(_overlap(rect, zone) for rect in rects for zone in zones):
            return {name: (x - boxes[name][0], y - boxes[name][1]) for name, (x, y) in corners.items()}
        y_front -= 1.0
    raise RuntimeError("production plate layout does not fit the bed")


def pack(boxes: dict[str, tuple], zones: list[tuple], bed=BED_SIZE) -> dict[str, tuple[float, float]]:
    """Production layout: first-fit shelves, deepest box first. Each box goes on the first shelf where it fits (not
    deeper than the shelf, room left in X), else on a new shelf behind the last one; X skips keep-out zones. The
    packed block then moves toward the bed centre as far as it stays inside the margins and clear of the zones.
    Returns {name: bed XY of the object origin}. (arrange() stays as it is for the plate-0b script.)"""
    width = {name: box[2] - box[0] for name, box in boxes.items()}
    depth = {name: box[3] - box[1] for name, box in boxes.items()}

    def free_x(x, y, name):
        while x + width[name] <= bed[0] - LAYOUT_MARGIN:
            hits = [zone for zone in zones if _overlap((x, y, x + width[name], y + depth[name]), zone)]
            if not hits:
                return x
            x = max(zone[2] for zone in hits)
        return None

    shelves, corners = [], {}
    for name in sorted(boxes, key=lambda n: (-depth[n], -width[n], n)):
        for shelf in shelves:
            x = free_x(shelf["x"], shelf["y"], name) if depth[name] <= shelf["depth"] else None
            if x is not None:
                break
        else:
            y = shelves[-1]["y"] + shelves[-1]["depth"] + LAYOUT_GAP if shelves else LAYOUT_MARGIN
            x = free_x(LAYOUT_MARGIN, y, name)
            if x is None or y + depth[name] > bed[1] - LAYOUT_MARGIN:
                raise RuntimeError(f"production plate layout: {name} does not fit the bed")
            shelf = {"y": y, "depth": depth[name]}
            shelves.append(shelf)
        corners[name] = (x, shelf["y"])
        shelf["x"] = x + width[name] + LAYOUT_GAP

    rects = {name: (x, y, x + width[name], y + depth[name]) for name, (x, y) in corners.items()}
    low = (min(r[0] for r in rects.values()), min(r[1] for r in rects.values()))
    high = (max(r[2] for r in rects.values()), max(r[3] for r in rects.values()))
    centre_shift = ((bed[0] - high[0] - low[0]) / 2, (bed[1] - high[1] - low[1]) / 2)
    for step in range(100, -1, -1):       # step 0 is the packed layout itself
        shift = (centre_shift[0] * step / 100, centre_shift[1] * step / 100)
        moved = [_shifted(rect, shift) for rect in rects.values()]
        inside = all(m[0] >= LAYOUT_MARGIN and m[1] >= LAYOUT_MARGIN and m[2] <= bed[0] - LAYOUT_MARGIN
                     and m[3] <= bed[1] - LAYOUT_MARGIN for m in moved)
        if inside and not any(_overlap(m, zone) for m in moved for zone in zones):
            break
    return {name: (x + shift[0] - boxes[name][0], y + shift[1] - boxes[name][1]) for name, (x, y) in corners.items()}


def _box_of(points) -> tuple[float, float, float, float] | None:
    if not points:
        return None
    xy = np.array([(x, y) for _, _, x, y in points])
    return tuple(round(float(v), 2) for v in (*xy.min(axis=0), *xy.max(axis=0)))


def _ear_check(plate_object: PlateObject, points: np.ndarray) -> dict:
    """Every ear corner has brim around it and no brim of this object lies elsewhere (ears, not a full brim)."""
    corners = np.array([(plate_object.position[0] + x, plate_object.position[1] + y) for x, y, _ in plate_object.brim_ears])
    radii = np.array([radius for _, _, radius in plate_object.brim_ears])
    if len(points) == 0:
        return {"ears_ok": False, "corners_with_ear": 0, "ear_reach_mm": None}
    distance = np.linalg.norm(points[:, None, :] - corners[None, :, :], axis=2)      # points x corners
    corner_has_ear = (distance <= radii[None, :] + EAR_TOLERANCE).any(axis=0)
    nearest = distance.argmin(axis=1)
    nearest_distance = distance[np.arange(len(points)), nearest]
    off_ear = nearest_distance > radii[nearest] + EAR_TOLERANCE
    return {"ears_ok": bool(corner_has_ear.all() and not off_ear.any()), "corners_with_ear": int(corner_has_ear.sum()),
            "ear_reach_mm": round(float(nearest_distance.max()), 2)}


def brim_report(objects: dict[str, PlateObject], boxes: dict[str, tuple], brim_points) -> dict:
    """First-layer brim (bed mm) grouped by the placed layout box that contains it: point count, reach beyond
    the footprint, AMS slots it is printed with, ear check for objects with ears, points outside every box."""
    first_layer = [(slot, x, y) for layer, slot, x, y in brim_points if layer == 1]
    slots = np.array([slot for slot, _, _ in first_layer], dtype=int)
    points = np.array([(x, y) for _, x, y in first_layer]).reshape(-1, 2)
    claimed = np.zeros(len(points), dtype=bool)
    per_object = {}
    for name, plate_object in objects.items():
        x0, y0, x1, y1 = _shifted(boxes[name], plate_object.position)
        inside = (points[:, 0] >= x0) & (points[:, 0] <= x1) & (points[:, 1] >= y0) & (points[:, 1] <= y1)
        claimed |= inside
        mine = points[inside]
        bx0, by0, bx1, by1 = bed_box(plate_object)        # the brim grows from the bed footprint
        low = np.array([bx0, by0]) + plate_object.position
        high = np.array([bx1, by1]) + plate_object.position
        reach = float(np.maximum(low - mine, mine - high).max()) if len(mine) else 0.0
        entry = {"points": int(len(mine)), "reach_mm": round(max(reach, 0.0), 2),
                 "slots": sorted(int(slot) for slot in set(slots[inside]))}
        if plate_object.brim_ears:
            entry.update(_ear_check(plate_object, mine))
        per_object[plate_object.name] = entry
    return {"objects": per_object, "points_outside_layout_boxes": int((~claimed).sum())}


def small_part_layer_times(objects: dict[str, PlateObject], process_of: dict[str, str],
                           scan: bambu.GcodeScan) -> dict[str, dict]:
    """Shortest whole-layer time over the layers each small / pin object prints on (layer bottom below its top):
    the time a layer has to cool before the next one lands on it. Shown rounded down, so a failing value never
    reads as the limit."""
    times = {}
    for plate_object in objects.values():
        if process_of[plate_object.name] not in ("small", "pin"):
            continue
        top = float(_vertices(plate_object)[:, 2].max())
        height = float(plate_object.settings["layer_height"])
        layers = [n for n, z in scan.layer_z.items() if z - height < top - 1e-6]
        if not layers:
            raise RuntimeError(f"{plate_object.name}: no G-code layer below its top {top:.2f} mm")
        worst = min(layers, key=lambda n: scan.layer_seconds[n])
        times[plate_object.name] = {"min_layer_s": math.floor(scan.layer_seconds[worst] * 10) / 10,
                                    "at_z": scan.layer_z[worst],
                                    "layers_below": sum(scan.layer_seconds[n] < MIN_SMALL_LAYER_S for n in layers)}
    return times


def first_layer_order(colours: list[str]) -> dict[str, str]:
    """Plate setting that prints navy first on layer 1. Bambu prints each object's brim in the first filament the
    object uses on layer 1; with the automatic order that is azure or white, right at the navy front faces."""
    if len(colours) < 2:
        return {}
    slots = sorted((COLOURS[colour]["slot"] for colour in colours), key=lambda slot: (slot != COLOURS["navy"]["slot"], slot))
    return {"first_layer_print_sequence": " ".join(str(slot) for slot in slots)}


def display_path(path: Path) -> str:
    """Project-relative when inside the project, with / on every platform."""
    path = Path(path).resolve()
    return (path.relative_to(PROJECT_DIR) if path.is_relative_to(PROJECT_DIR) else path).as_posix()


def _object_entry(piece, plate_object: PlateObject) -> dict:
    vertices = _vertices(plate_object)
    size = vertices.max(axis=0) - vertices.min(axis=0)
    return {"object": plate_object.name, "piece": piece.name, "label": piece.label, "process": piece.process,
            "installed": piece.installed,
            "parts": {part.name: part.extruder for part in plate_object.parts},
            "settings": plate_object.settings,
            "position": [round(v, 2) for v in plate_object.position],
            "size": [round(float(v), 2) for v in size],
            "brim_ears": len(plate_object.brim_ears)}


@dataclass
class PlannedPlate:
    number: int
    pieces: list                      # model parts on this plate
    objects: dict[str, PlateObject]   # piece name -> slicer object, bed position set
    boxes: dict[str, tuple]           # piece name -> layout box around the object origin
    colours: list[str]
    tower: tuple[float, float] | None     # wipe tower corner (plates with several colours)


def plan_plate(model, number: int, project_settings: dict) -> PlannedPlate:
    """Slicer objects of production plate n, packed on the bed; a plate with several colours gets the wipe tower."""
    pieces = model.plate(number)
    if not pieces:
        raise ValueError(f"the model has no printed pieces on plate {number}")
    objects = {piece.name: production_object(piece, model.params.layer_h) for piece in pieces}
    boxes = {piece.name: layout_box(objects[piece.name], piece.process) for piece in pieces}
    colours = sorted({colour for piece in pieces for colour in piece.colours})
    tower = TOWER_CORNER if len(colours) > 1 else None
    positions = pack(boxes, keep_out_zones(project_settings, with_tower=tower is not None, tower_xy=tower))
    for name, plate_object in objects.items():
        plate_object.position = positions[name]
    return PlannedPlate(number, pieces, objects, boxes, colours, tower)


def plate_result(planned: PlannedPlate, index: int, plate_count: int, summary: dict, slice_dir: Path,
                 inlay_layers: int, project_path: Path) -> dict:
    """Numbers and checks of one plate from the project slice (Bambu plate id = index + 1)."""
    plate_id = index + 1
    sliced = {plate["plate"]: plate for plate in summary["plates"]}[plate_id]
    details = bambu.sliced_plate_details(slice_dir, plate_id)
    gcode = slice_dir / f"plate_{plate_id}.gcode"
    scan = bambu.scan_gcode(gcode)
    origin = plate_origin(index, plate_count)
    objects, boxes = planned.objects, planned.boxes

    misplaced = []
    for plate_object in objects.values():
        vertices = _vertices(plate_object)
        low, high = vertices.min(axis=0), vertices.max(axis=0)
        want = (*(low[:2] + plate_object.position), *(high[:2] + plate_object.position), high[2])
        got = details["boxes"].get(plate_object.name)          # project XY: the plate origin is added
        if got is not None:
            got = (got[0] - origin[0], got[1] - origin[1], got[2] - origin[0], got[3] - origin[1], got[4])
        if got is None or max(abs(a - b) for a, b in zip(got, want)) > PLACE_TOLERANCE:
            misplaced.append(plate_object.name)
    tower = _box_of(scan.points["Prime tower"])
    rects = [_shifted(boxes[name], objects[name].position) for name in objects]
    brims = brim_report(objects, boxes, scan.points["Brim"])
    process_of = {objects[piece.name].name: piece.process for piece in planned.pieces}
    small_layers = small_part_layer_times(objects, process_of, scan)

    checks = {
        "on_bed": all(abs(_vertices(o)[:, 2].min()) < ON_BED for o in objects.values()),
        "one_slicer_object_per_piece": sorted(sliced["objects"]) == sorted(o.name for o in objects.values()),
        "placed_as_arranged": not misplaced,
        "no_warning": not sliced["warning"],
        "gcode_changes_match_result": sliced["tool_changes_in_gcode"] == sliced["filament_changes"],
        "changes_within_inlay_layers": all(1 <= layer <= inlay_layers for layer in scan.change_layers),
        "wipe_tower_only_with_several_colours": (tower is not None) == (len(planned.colours) > 1),
        "wipe_tower_inside_bed": tower is None or (tower[0] >= 0 and tower[1] >= 0 and tower[2] <= BED_SIZE[0]
                                                   and tower[3] <= BED_SIZE[1]),
        "wipe_tower_clear_of_objects": tower is None or not any(_overlap(tower, rect) for rect in rects),
        "brim_only_inside_layout_boxes": brims["points_outside_layout_boxes"] == 0,
        "brim_in_navy": all(entry["slots"] in ([], [COLOURS["navy"]["slot"]]) for entry in brims["objects"].values()),
    }
    if "struct" in process_of.values():
        checks["struct_brim_about_5mm"] = all(
            STRUCT_BRIM_REACH[0] <= brims["objects"][name]["reach_mm"] <= STRUCT_BRIM_REACH[1]
            for name, process in process_of.items() if process == "struct")
    if "pin" in process_of.values():
        checks["pin_brim_about_3mm"] = all(
            PIN_BRIM_REACH[0] <= brims["objects"][name]["reach_mm"] <= PIN_BRIM_REACH[1]
            for name, process in process_of.items() if process == "pin")
    if "panel" in process_of.values():
        checks["mouse_ears_on_panel_corners"] = all(
            brims["objects"][name]["ears_ok"] for name, process in process_of.items() if process == "panel")
    if small_layers:
        checks["small_part_layers_at_least_10s"] = all(entry["layers_below"] == 0 for entry in small_layers.values())
    minutes = sliced["minutes"]
    return {
        "file": display_path(project_path),
        "plate": planned.number,
        "name": PLATE_NAMES[planned.number],
        "contents": PLATE_CONTENTS[planned.number],
        "colours": planned.colours,
        "objects": [_object_entry(piece, objects[piece.name]) for piece in planned.pieces],
        "slice": {"minutes": minutes, "time_text": f"{int(minutes // 60)} h {minutes % 60:.0f} min",
                  "grams": sliced["grams"], "grams_total": sliced["grams_total"],
                  "model_grams": details["model_grams"], "filament_changes": sliced["filament_changes"],
                  "tool_changes_in_gcode": sliced["tool_changes_in_gcode"], "change_layers": scan.change_layers,
                  "layers": scan.layers, "warning": sliced["warning"], "gcode": display_path(gcode)},
        "wipe_tower_corner": list(planned.tower) if planned.tower else None,
        "wipe_tower_box": tower,
        "first_layer_brim": brims,
        "small_part_layer_time": small_layers,
        "misplaced": misplaced,
        "checks": checks,
        "ok": all(checks.values()),
    }


def remove_stale(out_dir: Path) -> None:
    """Outputs of earlier versions, by their known names only (v3.4 7 item 8): the projects (yu7_plates.3mf, one
    per plate before), their CLI round-trip copies and logs, the per-plate slice folders. Any other 3MF (a reprint
    project saved from Bambu Studio) is left alone and only mentioned."""
    roundtrip = out_dir / "slice" / "cli_roundtrip"
    old_files = [folder / name for name in OLD_PROJECT_FILES for folder in (out_dir, roundtrip)]
    old_files += [roundtrip / f"{Path(name).stem}_log.txt" for name in OLD_PROJECT_FILES]
    removed = [path for path in old_files if path.exists()]
    for path in removed:
        path.unlink()
    for folder in (out_dir / "slice").glob("plate*"):
        if folder.is_dir():
            shutil.rmtree(folder)
            removed.append(folder)
    if removed:
        print(f"  removed outputs of earlier versions: {', '.join(display_path(path) for path in removed)}")
    others = sorted(path.name for path in out_dir.glob("*.3mf") if path.name != PROJECT_FILE)
    if others:
        print(f"  other 3MF files in {display_path(out_dir)} left alone: {', '.join(others)}")


def manual_plates(model) -> dict:
    """Per plate the objects with the AMS slot of every colour STL and the settings the 3MF would carry: what the
    assembly card lists to set by hand when there is no 3MF (no-slicer mode, webui design 6.4)."""
    layer_height = model.params.layer_h
    plates = {}
    for number in sorted({part.plate for part in model.parts.values()}):
        pieces = model.plate(number)
        colours = sorted({colour for piece in pieces for colour in piece.colours})
        objects = [{"object": f"{piece.label}_{piece.name}", "piece": piece.name, "label": piece.label,
                    "process": piece.process, "installed": piece.installed,
                    "parts": {f"{piece.name}.{colour}": COLOURS[colour]["slot"]
                              for colour in sorted(piece.colours, key=lambda colour: colour != "navy")},
                    "settings": bambu.production_settings(piece.process, layer_height)} for piece in pieces]
        plates[str(number)] = {"plate": number, "name": PLATE_NAMES[number], "contents": PLATE_CONTENTS[number],
                               "colours": colours, "wipe_tower": len(colours) > 1,
                               "plate_settings": first_layer_order(colours), "objects": objects}
    return plates


def unsliced_report(model, out_dir: Path, reason: str) -> dict:
    """No-slicer mode: no 3MF, no slicing checks (check 11 "not sliced"). This tool's own project and slice outputs
    of an earlier build are removed: they would not match these parts."""
    stale = [out_dir / PROJECT_FILE, out_dir / "slice", out_dir / "presets"]
    removed = [path for path in stale if path.exists()]
    for path in removed:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    print(f"  no slicer ({reason}): no 3MF and no slicing checks")
    if removed:
        print(f"  removed the earlier project and slice outputs: {', '.join(display_path(path) for path in removed)}")
    report = {"generated": datetime.now().strftime("%Y-%m-%d %H:%M"), "sliced": False, "reason": reason, "file": None,
              "presets": {"machine": bambu.MACHINE_PRESET, "process": bambu.PROCESS_PRESET,
                          "filament": bambu.FILAMENT_PRESET, "bed": bambu.BED_TYPE, "shrink": bambu.FILAMENT_SHRINK,
                          "layer_height": model.params.layer_h},
              "ams_slots": {str(slot): name for slot, (name, _) in bambu.AMS_SLOTS.items()},
              "plates": manual_plates(model), "checks": {}, "ok": None}
    (out_dir / "slice_report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    return report


def write_production_plates(model, out_dir: Path | None = None) -> dict:
    """Production plates -> ONE project out/plates/parking_plate.3mf (plate 1 colour, plate 2 navy), sliced once by
    the CLI in out/plates/slice/, out/plates/slice_report.json.

    Returns the report: per plate the objects (parts -> AMS slot, settings, bed position), slice results
    (minutes, grams incl. flush, model grams, filament changes and their layers, warning), wipe tower and checks;
    project-wide checks and totals. Without a usable Bambu Studio (bambu.slicer()) the unsliced_report instead."""
    started = time.time()
    out_dir = Path(out_dir) if out_dir is not None else PLATES_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        bambu.slicer()
    except bambu.SlicerUnavailable as error:
        return unsliced_report(model, out_dir, str(error))
    preset_files = bambu.write_presets(bambu.plate_presets(), out_dir / "presets")
    project_settings = bambu.export_project_settings(preset_files, out_dir / "presets")
    layer_height = model.params.layer_h
    numbers = sorted({part.plate for part in model.parts.values()})
    if numbers != list(range(1, len(numbers) + 1)) or set(numbers) != set(PLATE_NAMES):
        raise ValueError(f"production plates must be {sorted(PLATE_NAMES)}, the model has {numbers}")
    planned = [plan_plate(model, number, project_settings) for number in numbers]

    settings = dict(project_settings)       # Bambu keeps one wipe tower position per plate
    for axis, key in ((0, "wipe_tower_x"), (1, "wipe_tower_y")):
        settings[key] = [f"{(plate.tower or bambu.WIPE_TOWER_XY)[axis]:g}" for plate in planned]
    path = out_dir / PROJECT_FILE
    write_bambu_3mf(path, [Plate(PLATE_NAMES[plate.number], list(plate.objects.values()), first_layer_order(plate.colours))
                           for plate in planned],
                    settings, title="Parking plate v3.4: " + "; ".join(PLATE_CONTENTS[n] for n in numbers))
    plan = {o.name: {"parts": {part.name: part.extruder for part in o.parts}, "settings": o.settings}
            for plate in planned for o in plate.objects.values()}
    slice_dir = out_dir / "slice"
    roundtrip = bambu.roundtrip_3mf(path, slice_dir / "cli_roundtrip" / PROJECT_FILE)
    problems = {"3mf": assignment_problems(read_model_settings(path), plan),
                "cli_roundtrip": assignment_problems(read_model_settings(roundtrip), plan)}
    if not problems["3mf"] and not problems["cli_roundtrip"]:
        remove_stale(out_dir)                             # only once the new project reads back correctly
    summary = bambu.slice_project(path, slice_dir)        # embedded project settings, as the GUI sees them

    inlay_layers = max(model.params.white_layers, model.params.azure_layers)
    plates = {}
    for index, plate in enumerate(planned):
        entry = plate_result(plate, index, len(planned), summary, slice_dir, inlay_layers, path)
        plates[str(plate.number)] = entry
        failed = [name for name, ok in entry["checks"].items() if not ok]
        print(f"  plate {plate.number} ({entry['name']}): {entry['slice']['time_text']}, {entry['slice']['grams_total']} g "
              f"{entry['slice']['grams']}, {entry['slice']['filament_changes']} filament changes; "
              f"checks {'ok' if not failed else 'FAILED ' + str(failed)}")
    global_checks = {
        "first_layer_is_one_layer": abs(float(project_settings["initial_layer_print_height"]) - layer_height) < 1e-9,
        "white_depth_whole_layers": abs(model.params.white_depth / layer_height
                                        - round(model.params.white_depth / layer_height)) < 1e-9,
        "extruders_and_settings_in_3mf": not problems["3mf"],
        "extruders_and_settings_after_cli_load": not problems["cli_roundtrip"],
        "every_piece_on_one_plate": sorted(name for plate in planned for name in plate.objects) == sorted(model.parts),
        "earlier_project_files_removed": not any((out_dir / name).exists() for name in OLD_PROJECT_FILES),
    }
    grams = {}
    for entry in plates.values():
        for colour, value in entry["slice"]["grams"].items():
            grams[colour] = round(grams.get(colour, 0.0) + value, 2)
    minutes = round(sum(entry["slice"]["minutes"] for entry in plates.values()), 1)
    report = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "sliced": True,
        "file": display_path(path),
        "presets": {"machine": bambu.MACHINE_PRESET, "process": bambu.PROCESS_PRESET,
                    "filament": bambu.FILAMENT_PRESET, "bed": bambu.BED_TYPE, "shrink": bambu.FILAMENT_SHRINK,
                    "wipe_tower_corner": {str(plate.number): list(plate.tower) if plate.tower else None
                                          for plate in planned},
                    "layer_height": layer_height},
        "ams_slots": {str(slot): name for slot, (name, _) in bambu.AMS_SLOTS.items()},
        "plates": plates,
        "assignment_problems": problems,
        "totals": {"minutes": minutes, "time_text": f"{int(minutes // 60)} h {minutes % 60:.0f} min",
                   "grams": grams, "grams_total": round(sum(grams.values()), 2),
                   "model_grams_total": round(sum(sum(e["slice"]["model_grams"].values()) for e in plates.values()), 2),
                   "filament_changes": sum(entry["slice"]["filament_changes"] for entry in plates.values())},
        "checks": global_checks,
        "ok": all(global_checks.values()) and all(entry["ok"] for entry in plates.values()),
        "cli_seconds": summary["cli_seconds"],
        "seconds": round(time.time() - started, 1),
    }
    (out_dir / "slice_report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    return report
