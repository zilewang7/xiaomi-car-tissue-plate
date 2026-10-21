"""Top views of the print plates, read back from the 3MF projects under out/ (exactly what the slicer gets).

Every plate of the 3MF projects this repository writes (PROJECTS: out/plates/, out/plate0/, out/plate0b/) becomes
plate_<file stem>.png (plate_<file stem>_<plater id>.png when the project has several plates). Parts are drawn in
their extruder's filament colour (= AMS slot), seen from above like the slicer's prepare view, so inlays printed
face down are hidden; the legend lists each object's filaments.
Reads the Bambu layout written by export3mf.write_bambu_3mf: build items -> components -> meshes,
Metadata/model_settings.config for part extruders and plate membership, plate grid from export3mf.plate_origin.
"""
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import numpy as np
import pyvista as pv

from .export3mf import BED_SIZE, PROJECT_FILE, plate_origin
from .params import COLOURS

PREFIX = "plate_"
PROJECTS = (f"plates/{PROJECT_FILE}", "plate0/plate0_coupons.3mf", "plate0b/plate0b_coupons.3mf")
NS = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
PATH_KEY = "{http://schemas.microsoft.com/3dmanufacturing/production/2015/06}path"
SLOT_HEX = {colour["slot"]: colour["hex"] for colour in COLOURS.values()}
SLOT_NAME = {colour["slot"]: name for name, colour in COLOURS.items()}
UNKNOWN_HEX = "#ff00ff"        # extruder without a filament colour: shows up loudly
DEFAULT_EXTRUDER = 1           # what Bambu Studio uses when a part and its object name none
EDGE_HEX = "#c3d1e6"           # feature edges drawn over the parts
FEATURE_ANGLE = 30.0           # deg
BED_HEX = "#e3dcc8"            # textured PEI, drawn unlit
BACKGROUND = "#d9d9d9"
WINDOW = (1900, 1300)
LEGEND_XY = (1330, 40)         # pixels, lower-left corner of the legend text


@dataclass
class PlateObject:
    name: str
    parts: list             # [(pv.PolyData in bed coordinates, extruder = AMS slot)]


@dataclass
class PlateView:
    plater_id: int
    objects: list           # [PlateObject]


def transform_matrix(text):
    """3MF 'm00 m01 m02 m10 m11 m12 m20 m21 m22 m30 m31 m32' -> 4x4 for row vectors [x y z 1] @ M."""
    matrix = np.eye(4)
    if text:
        values = [float(value) for value in text.split()]
        matrix[:3, :3] = np.reshape(values[:9], (3, 3))
        matrix[3, :3] = values[9:12]
    return matrix


def mesh_objects(root):
    """{object id: (vertices, triangles)} of the mesh objects in one model file."""
    meshes = {}
    for obj in root.iterfind("m:resources/m:object", NS):
        mesh = obj.find("m:mesh", NS)
        if mesh is None:
            continue
        vertices = np.array([[float(v.get(axis)) for axis in "xyz"] for v in mesh.iterfind("m:vertices/m:vertex", NS)])
        triangles = np.array([[int(t.get(key)) for key in ("v1", "v2", "v3")]
                              for t in mesh.iterfind("m:triangles/m:triangle", NS)])
        meshes[obj.get("id")] = (vertices, triangles)
    return meshes


def polydata(vertices, triangles, matrix):
    moved = (np.c_[vertices, np.ones(len(vertices))] @ matrix)[:, :3]
    return pv.PolyData(moved, np.c_[np.full(len(triangles), 3), triangles].ravel())


def read_settings(archive):
    """Object names, part extruders (falling back to the object's) and [(plater id, object ids)]."""
    config = ET.fromstring(archive.read("Metadata/model_settings.config"))
    names, extruders = {}, {}
    for obj in config.iterfind("object"):
        meta = {m.get("key"): m.get("value") for m in obj.iterfind("metadata")}
        names[obj.get("id")] = meta.get("name", obj.get("id"))
        for part in obj.iterfind("part"):
            part_meta = {m.get("key"): m.get("value") for m in part.iterfind("metadata")}
            extruders[part.get("id")] = int(part_meta.get("extruder", meta.get("extruder", DEFAULT_EXTRUDER)))
    plates = []
    for plate in config.iterfind("plate"):
        meta = {m.get("key"): m.get("value") for m in plate.iterfind("metadata")}
        ids = [m.get("value") for m in plate.iterfind("model_instance/metadata") if m.get("key") == "object_id"]
        plates.append((int(meta.get("plater_id", len(plates) + 1)), ids))
    return names, extruders, plates


def built_objects(archive, extruders):
    """{object id: [(vertices, triangles, matrix, extruder)]} for every object placed by a build item; matrix =
    component transform followed by the build item transform."""
    root = ET.fromstring(archive.read("3D/3dmodel.model"))
    placements = {item.get("objectid"): transform_matrix(item.get("transform"))
                  for item in root.iterfind("m:build/m:item", NS)}
    model_files = {}
    objects = {}
    for obj in root.iterfind("m:resources/m:object", NS):
        object_id = obj.get("id")
        if object_id not in placements:
            continue
        parts = []
        for component in obj.iterfind("m:components/m:component", NS):
            file_name = component.get(PATH_KEY, "/3D/3dmodel.model").lstrip("/")
            if file_name not in model_files:
                model_files[file_name] = mesh_objects(ET.fromstring(archive.read(file_name)))
            part_id = component.get("objectid")
            vertices, triangles = model_files[file_name][part_id]
            matrix = transform_matrix(component.get("transform")) @ placements[object_id]
            parts.append((vertices, triangles, matrix, extruders.get(part_id, DEFAULT_EXTRUDER)))
        objects[object_id] = parts
    return objects


def read_project(path):
    """[PlateView] of one Bambu 3MF project, every mesh in its own plate's bed coordinates."""
    with zipfile.ZipFile(path) as archive:
        names, extruders, plates = read_settings(archive)
        objects = built_objects(archive, extruders)
    if not plates:
        plates = [(1, list(objects))]
    views = []
    for index, (plater_id, object_ids) in enumerate(plates):
        to_bed = np.eye(4)                       # plates sit on a grid in project space
        to_bed[3, :2] = [-value for value in plate_origin(index, len(plates))]
        plate_objects = []
        for object_id in object_ids:
            parts = [(polydata(vertices, triangles, matrix @ to_bed), extruder)
                     for vertices, triangles, matrix, extruder in objects[object_id]]
            plate_objects.append(PlateObject(names.get(object_id, object_id), parts))
        views.append(PlateView(plater_id, plate_objects))
    return views


def plate_image(view, title, path):
    """Bed, parts in their extruder colours, a number on each object and a legend (number, name, filaments)."""
    plotter = pv.Plotter(off_screen=True, window_size=WINDOW)
    plotter.set_background(BACKGROUND)
    width, depth = BED_SIZE
    plotter.add_mesh(pv.Plane(center=(width / 2, depth / 2, -0.05), direction=(0, 0, 1), i_size=width, j_size=depth),
                     color=BED_HEX, lighting=False)
    markers, legend = [], []
    for number, plate_object in enumerate(view.objects, start=1):
        for mesh, extruder in plate_object.parts:
            plotter.add_mesh(mesh, color=SLOT_HEX.get(extruder, UNKNOWN_HEX), smooth_shading=True,
                             split_sharp_edges=True)
            outline = mesh.extract_feature_edges(feature_angle=FEATURE_ANGLE, boundary_edges=False,
                                                 non_manifold_edges=False, manifold_edges=False)
            # shape cues for the straight-down view, lifted 0.05 mm so coplanar faces do not hide them
            plotter.add_mesh(outline.translate((0.0, 0.0, 0.05)), color=EDGE_HEX, line_width=1.5)
        bounds = np.array([mesh.bounds for mesh, _ in plate_object.parts])
        markers.append(((bounds[:, 0].min() + bounds[:, 1].max()) / 2, (bounds[:, 2].min() + bounds[:, 3].max()) / 2,
                        bounds[:, 5].max() + 1.0))
        filaments = " + ".join(SLOT_NAME.get(extruder, f"slot {extruder}") for _, extruder in plate_object.parts)
        legend.append(f"{number:2d}  {plate_object.name}  ({filaments})")
    if markers:
        actor = plotter.add_point_labels(np.array(markers), [str(n) for n in range(1, len(markers) + 1)], font_size=16,
                                         text_color="black", shape_color="white", shape_opacity=0.85,
                                         show_points=False, always_visible=True)
        actor.GetMapper().PlaceAllLabelsOn()        # VTK drops overlapping labels otherwise
    plotter.add_text(title, position="upper_left", font_size=12, color="black")
    plotter.add_text("\n".join(legend), position=LEGEND_XY, font_size=10, color="black")
    # parallel top view, bed on the left, legend on the right; front of the bed at the bottom
    view_height = depth * 1.08
    view_width = view_height * WINDOW[0] / WINDOW[1]
    centre = (view_width / 2 - depth * 0.04, depth / 2, 0.0)
    plotter.enable_parallel_projection()
    plotter.camera.position, plotter.camera.focal_point, plotter.camera.up = (centre[0], centre[1], 600.0), centre, (0, 1, 0)
    plotter.camera.parallel_scale = view_height / 2
    plotter.enable_anti_aliasing("ssaa")
    plotter.screenshot(str(path))
    plotter.close()
    return path


def find_projects(out_dir):
    """The projects of PROJECTS that exist. Other 3MF files (a reprint project saved from Bambu Studio, v3.4 7 item 8)
    are neither rendered nor read."""
    return [out_dir / name for name in PROJECTS if (out_dir / name).exists()]


def render_plates(out_dir, render_dir):
    """{image name: path} for every plate of every 3MF project found by find_projects."""
    images = {}
    for project in find_projects(out_dir):
        views = read_project(project)
        for view in views:
            name = f"{PREFIX}{project.stem}" + (f"_{view.plater_id}" if len(views) > 1 else "")
            if name in images:
                raise RuntimeError(f"two 3MF projects would both render as {name}.png: rename one of them")
            plate_text = f", plate {view.plater_id}" if len(views) > 1 else ""
            title = f"{project.relative_to(out_dir).as_posix()}{plate_text}: top view, front of the bed at the bottom"
            images[name] = plate_image(view, title, render_dir / f"{name}.png")
            print(f"    render {name}")
    return images
