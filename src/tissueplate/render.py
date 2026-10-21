"""Off-screen pyvista renders of the v3.3 plate (out/renders/), then the Chinese assembly card.

    render_all(model) -> {image name: PNG path}  (stored by build_all in model.results["renders"])
    The assembly card (assembly_card.py) is written last; its path goes to model.results["assembly_card"].

The images are drawn in a child process (render_scene): without a usable OpenGL, VTK can end the process outright
(a forced OSMesa without the library: segmentation fault / access violation), which Python cannot catch. When the
child fails, the build goes on without images: model.results["render_problem"] says why, and the card and the
report say so (webui design 6.5).

Images. The A / B panels carry the real numbers or texts from config.toml, so every image stays local (spec 7):
    outside_35deg, outside_25deg          from outside the car (v3.1 cameras), face A displayed
    outside_35deg_B, outside_35deg_logo   same camera after one / two "next" presses (rotor turned NEXT_TURN)
    knob_end                              driver end: nabla knob, caps, outer-face letters
    cabin_side                            from the cabin at rest (logo face, upside down from there)
    exploded                              parts pulled apart along their assembly directions, spec labels
    plate_*                               top view of every plate of every 3MF under out/ (render_plates.py)
Meshes come from bd.export_stl (OCCT, fast) into a scratch folder under out/ that is deleted afterwards, with
scene.json for the child.
"""
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

import build123d as bd
import numpy as np
import pyvista as pv

from . import assembly_card, render_plates
from .params import COLOURS, FACE_NORMALS, NEXT_TURN, OUT_DIR, PROJECT_DIR
from .shapes import direction

RENDER_DIR = OUT_DIR / "renders"
RENDER_TIMEOUT = 900            # s; the images take about 5 s
# the child: python -I -c CHILD <src folder> <scene.json>
CHILD = "import sys; sys.path.insert(0, sys.argv[1]); from tissueplate.render import render_scene; render_scene(sys.argv[2])"
WINDOW = (1600, 1000)
BACKGROUND = "#d9d9d9"
MESH_TOLERANCE = 0.02           # mm chordal deviation
MESH_ANGULAR_TOLERANCE = 0.2    # rad
OTHER_HEX = {"mag": "#9a9a9a", "pad": "#2b2b2b", "lid": "#5a2f45", "base": "#4e2a3d", "tongue": "#6b3a52"}

# camera: eye, focal point, vertical view angle (deg); the first four are the v3.1 cameras
CAMERAS = {
    "outside_35deg": ((60, -900, 640), (0, 10, 10), 14),
    "outside_25deg": ((-250, -900, 450), (0, 10, 10), 14),
    "knob_end": ((420, 60, 120), (90, 12, 15), 14),
    "cabin_side": ((350, 520, 260), (0, 20, 5), 14),
    "exploded": ((620, -620, 480), (0, 0, 0), 20),          # direction only: the view is fitted to the parts
}
EXPLODED_ZOOM = 1.45            # after fitting the parts into the view
# exploded view labels (spec 4.2 labels): one item per part or per kind of magnet / cap (v3.3: lower and upper tab
# stack, lower and upper tab cap)
EXPLODED_LABELS = ("panel_A", "panel_B", "panel_L", "plug_near", "plug_far", "cradle", "front_bar", "knob", "far_pin",
                   "spacer", "mag_stator", "mag_tab+_1", "mag_tabU+_1", "cap_tab+", "cap_tabU+", "mag_knob30_1",
                   "cap_knob30", "pad_front")
# assembled images: name -> (camera, "next" presses from rest, show the leather tongue)
SHOTS = {
    "outside_35deg": ("outside_35deg", 0, True),
    "outside_25deg": ("outside_25deg", 0, True),
    "outside_35deg_B": ("outside_35deg", 1, True),
    "outside_35deg_logo": ("outside_35deg", 2, True),
    "knob_end": ("knob_end", 0, False),
    "cabin_side": ("cabin_side", 0, False),
}


@dataclass
class Item:
    name: str               # part / hardware / reference name in the model
    label: str              # spec 4.2 label shown in the exploded view
    colour_hex: str
    mesh: pv.PolyData


def export_mesh(shape, path):
    if not bd.export_stl(shape, str(path), tolerance=MESH_TOLERANCE, angular_tolerance=MESH_ANGULAR_TOLERANCE):
        raise RuntimeError(f"render mesh export failed: {path.name}")
    return path.name


def write_scene(model, scratch):
    """Meshes of the installed parts (one per colour body), the bought hardware and the reference box, assembled
    pose at rest, and scene.json naming them for render_scene."""
    items = []
    for part in model.installed_parts():
        for colour, body in part.bodies.items():
            items.append(dict(name=part.name, label=part.label, colour=COLOURS[colour]["hex"],
                              mesh=export_mesh(body, scratch / f"{part.name}.{colour}.stl")))
    for name, shape in model.hardware.items():
        kind = name.split("_")[0]
        items.append(dict(name=name, label="N52" if kind == "mag" else "pad", colour=OTHER_HEX[kind],
                          mesh=export_mesh(shape, scratch / f"{name}.stl")))
    box = [dict(name=name, label="", colour=OTHER_HEX[name],
                mesh=export_mesh(model.reference[name], scratch / f"{name}.stl")) for name in ("lid", "base")]
    scene = dict(items=items, box=box, tongue_y=model.params.tongue_y, rotating=sorted(model.rotating),
                 axis=list(model.params.axis))
    path = scratch / "scene.json"
    path.write_text(json.dumps(scene, indent=1), encoding="utf-8")
    return path


def read_items(entries, scratch):
    return [Item(entry["name"], entry["label"], entry["colour"], pv.read(scratch / entry["mesh"])) for entry in entries]


def turned(items, scene, presses):
    """Rotor, knob and their magnets / caps after 'presses' x "next" (A -> B -> Logo)."""
    if presses == 0:
        return items
    axis_y, axis_z = scene["axis"]
    angle = presses * NEXT_TURN
    return [replace(item, mesh=item.mesh.rotate_x(angle, point=(0.0, axis_y, axis_z))) if item.name in scene["rotating"]
            else item for item in items]


def stack_index(magnet_name):
    """mag_tab+_2 -> 2: position in its stack, 1 = first in (on the printed floor)."""
    return int(magnet_name.rsplit("_", 1)[1])


def explode_offset(name):
    """Exploded-view shift (mm): rotor up with its panels apart and plugs out of the tube ends, knob and far pin
    out along the axis, stator and spacer out of the block's inner side, front bar down and forward, tab and knob
    magnets and caps out of their pockets in insertion order, pads below the lip."""
    rotor = np.array([0.0, 0.0, 60.0])
    front = np.array([0.0, -15.0, -35.0])
    knob = np.array([40.0, 0.0, 0.0])
    if name.startswith("panel_"):
        normal = direction(FACE_NORMALS[name[-1]])
        return rotor + 18.0 * np.array([0.0, normal[0], normal[1]])
    if name.startswith("mag_tab"):
        return front + np.array([0.0, -10.0 - 7.0 * stack_index(name), 0.0])
    if name.startswith("cap_tab"):
        return front + np.array([0.0, -42.0, 0.0])
    if name.startswith("mag_knob"):
        return knob + np.array([15.0 + 6.0 * stack_index(name), 0.0, 0.0])
    if name.startswith("cap_knob") or name == "cap_hub":
        return knob + np.array([40.0, 0.0, 0.0])
    if name.startswith("pad_"):
        return np.array([0.0, 0.0, -20.0])
    fixed = {"cradle": np.zeros(3), "front_bar": front, "knob": knob, "far_pin": np.array([-40.0, 0.0, 0.0]),
             "plug_near": rotor + np.array([35.0, 0.0, 0.0]), "plug_far": rotor + np.array([-35.0, 0.0, 0.0]),
             "mag_stator": np.array([-16.0, 0.0, 0.0]), "spacer": np.array([-28.0, 0.0, 0.0])}
    return fixed[name]


def exploded(items):
    return [replace(item, mesh=item.mesh.translate(explode_offset(item.name))) for item in items]


def label_points(items):
    """(points, texts) for EXPLODED_LABELS: above each item, 15 mm in from its -X end (centre if shorter);
    a part with several colour bodies is labelled once."""
    points, texts, labelled = [], [], set()
    for item in items:
        if item.name not in EXPLODED_LABELS or item.name in labelled:
            continue
        labelled.add(item.name)
        x0, x1, y0, y1, _, z1 = item.mesh.bounds
        points.append((x0 + min(15.0, (x1 - x0) / 2), (y0 + y1) / 2, z1 + 2.0))
        texts.append(item.label)
    return np.array(points), texts


def add_labels(plotter, points, texts, font_size):
    actor = plotter.add_point_labels(points, texts, font_size=font_size, text_color="black", shape_color="white",
                                     shape_opacity=0.8, show_points=False, always_visible=True)
    actor.GetMapper().PlaceAllLabelsOn()        # VTK drops overlapping labels otherwise


def shoot(items, camera, path, labels=None, fit=False):
    """Screenshot of the items; fit = keep the camera direction but frame all items."""
    eye, focus, view_angle = camera
    plotter = pv.Plotter(off_screen=True, window_size=WINDOW)
    plotter.set_background(BACKGROUND)
    for item in items:
        plotter.add_mesh(item.mesh, color=item.colour_hex, smooth_shading=True, split_sharp_edges=True)
    if labels is not None:
        add_labels(plotter, *labels, font_size=18)
    plotter.camera.position, plotter.camera.focal_point, plotter.camera.up = eye, focus, (0, 0, 1)
    plotter.camera.view_angle = view_angle
    if fit:
        plotter.reset_camera()
        plotter.camera.zoom(EXPLODED_ZOOM)
    plotter.enable_anti_aliasing("ssaa")
    plotter.screenshot(str(path))
    plotter.close()
    return path


def clear_old_images():
    RENDER_DIR.mkdir(parents=True, exist_ok=True)
    for name in list(SHOTS) + ["exploded"]:
        (RENDER_DIR / f"{name}.png").unlink(missing_ok=True)
    for old in RENDER_DIR.glob(f"{render_plates.PREFIX}*.png"):
        old.unlink()


def render_scene(scene_file):
    """The child process: every image of scene.json (and the plates), their names in rendered.json beside it."""
    scratch = Path(scene_file).parent
    scene = json.loads(Path(scene_file).read_text(encoding="utf-8"))
    items, box = read_items(scene["items"], scratch), read_items(scene["box"], scratch)
    tongue = Item("tongue", "", OTHER_HEX["tongue"], pv.Box(bounds=(-160, 160, -140, scene["tongue_y"], -60, 0)))
    images = {}
    for name, (camera, presses, with_tongue) in SHOTS.items():
        in_view = turned(items, scene, presses) + box + ([tongue] if with_tongue else [])
        images[name] = shoot(in_view, CAMERAS[camera], RENDER_DIR / f"{name}.png")
        print(f"    render {name}", flush=True)
    pulled_apart = exploded(items)
    images["exploded"] = shoot(pulled_apart, CAMERAS["exploded"], RENDER_DIR / "exploded.png",
                               labels=label_points(pulled_apart), fit=True)
    images.update(render_plates.render_plates(OUT_DIR, RENDER_DIR))
    (scratch / "rendered.json").write_text(json.dumps({name: str(path) for name, path in images.items()}),
                                           encoding="utf-8")


def render_all(model):
    """All images (module docstring) and the assembly card; returns {image name: PNG path}, empty when the render
    process failed (model.results["render_problem"])."""
    clear_old_images()
    with tempfile.TemporaryDirectory(dir=OUT_DIR, prefix=".render_meshes_") as scratch_name:
        scene_file = write_scene(model, Path(scratch_name))
        command = [sys.executable, "-I", "-X", "utf8", "-u", "-c", CHILD, str(PROJECT_DIR / "src"), str(scene_file)]
        try:
            code = subprocess.run(command, timeout=RENDER_TIMEOUT).returncode
        except subprocess.TimeoutExpired:
            code = "timeout"
        rendered = scene_file.parent / "rendered.json"
        images = ({name: Path(path) for name, path in json.loads(rendered.read_text(encoding="utf-8")).items()}
                  if code == 0 and rendered.exists() else None)
    if images is None:
        clear_old_images()                    # no partial set
        images = {}
        model.results["render_problem"] = "渲染进程" + ("超时" if code == "timeout" else f"异常结束，退出码 {code}")
        print(f"    renders FAILED: the render process ended ({code}); this computer made no images, the build goes on")
    model.results["assembly_card"] = assembly_card.write(model, images)
    return images
