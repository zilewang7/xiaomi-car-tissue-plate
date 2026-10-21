"""STL + STEP export of the built model to out/parts/ (3MF writing lives in export3mf.py).

    out/parts/print/<part>.<colour>.stl      print pose, one file per colour body (bed face at Z = 0)
    out/parts/print/<part>.step              print pose, all colour bodies, named and coloured
    out/parts/assembled/<part>.<colour>.stl  assembled pose at rest (installed parts only)
    out/parts/assembled/<hardware>.stl       magnets, pads; lid.stl / base.stl reference box
    out/parts/assembly.step                  installed parts + hardware, named and coloured
    out/parts/manifest.json                  index of the files above
"""
import json

import build123d as bd

from .params import COLOURS

STL_TOLERANCE = 0.01          # mm chordal deviation
STL_ANGULAR_TOLERANCE = 0.15  # rad
HARDWARE_COLOURS = {"mag": "#9a9a9a", "pad": "#2b2b2b"}


def _stl(shape, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not bd.export_stl(shape, str(path), tolerance=STL_TOLERANCE, angular_tolerance=STL_ANGULAR_TOLERANCE):
        raise RuntimeError(f"STL export failed: {path}")


def _labelled(shape, label, colour_hex):
    copy = shape.moved(bd.Location())
    copy.label = label
    copy.color = bd.Color(colour_hex)
    return copy


def part_compound(part, location):
    children = [_labelled(location * body, f"{part.name}.{colour}", COLOURS[colour]["hex"])
                for colour, body in part.bodies.items()]
    return bd.Compound(children=children, label=part.name)


def export_parts(model, out_dir):
    print_dir, assembled_dir = out_dir / "print", out_dir / "assembled"
    for folder in (print_dir, assembled_dir):
        for pattern in ("*.stl", "*.step"):
            for old in folder.glob(pattern):      # files of renamed parts / colours from earlier builds
                old.unlink()
    manifest = []
    for part in model.parts.values():
        for colour in part.colours:
            entry = dict(part=part.name, label=part.label, colour=colour, slot=COLOURS[colour]["slot"],
                         plate=part.plate, process=part.process, installed=part.installed,
                         print_rotation=part.print_rotation, print_stl=f"print/{part.name}.{colour}.stl")
            _stl(part.printed(colour), print_dir / f"{part.name}.{colour}.stl")
            if part.installed:
                _stl(part.bodies[colour], assembled_dir / f"{part.name}.{colour}.stl")
                entry["assembled_stl"] = f"assembled/{part.name}.{colour}.stl"
            manifest.append(entry)
        if not bd.export_step(part_compound(part, part.to_print), str(print_dir / f"{part.name}.step")):
            raise RuntimeError(f"STEP export failed: {part.name}")
    for name, shape in model.hardware.items():
        _stl(shape, assembled_dir / f"{name}.stl")
    for name in ("lid", "base"):
        _stl(model.reference[name], assembled_dir / f"{name}.stl")
    children = [part_compound(part, bd.Location()) for part in model.installed_parts()]
    children += [_labelled(shape, name, HARDWARE_COLOURS[name.split("_")[0]]) for name, shape in model.hardware.items()]
    if not bd.export_step(bd.Compound(children=children, label="parking_plate_v3_4"), str(out_dir / "assembly.step")):
        raise RuntimeError("STEP export failed: assembly")
    with open(out_dir / "manifest.json", "w", encoding="utf-8") as handle:
        json.dump(dict(files=manifest, hardware=sorted(model.hardware), reference=["assembled/lid.stl", "assembled/base.stl"],
                       assembly="assembly.step"), handle, indent=1)
    return manifest
