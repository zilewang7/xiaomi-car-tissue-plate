"""The assembled model: every printed piece with its colour bodies, print transform and plate.

Data structure used by checks / export3mf / render / report:

    model.params      Params (all dimensions, derived values as properties)
    model.typography  text_layout.Typography (em, cells, glyph metrics)
    model.parts       {name: Part}, one Part per physical printed piece:
                      panel_A / panel_B / panel_L (PA / PB / PL), cradle (C), front_bar (F), knob (K),
                      plug_near (EN), plug_far (EF), far_pin + far_pin_spare (P), cap_tab- / cap_tab+ (lower
                      tab pockets) / cap_tabU- / cap_tabU+ (upper tab pockets, v3.3) / cap_knob30 / cap_knob150 /
                      cap_knob270 / cap_hub (D, one pry notch each), spacer (S), cooling_tube (Q, print-only
                      tube beside the knob, as tall as its print: the knob never prints alone)
        part.bodies       {colour: shape} in the ASSEMBLED pose at rest (theta = 0, face A displayed);
                          colour in COLOURS ("navy", "white", "azure"; COLOURS[c]["slot"] = AMS slot =
                          extruder); inlays are separate solids that exactly fill their pockets in the navy body
        part.to_print     bd.Location, assembled pose -> print pose (bed face at Z = 0, XY centred on 0)
        part.printed(c)   body of colour c in the print pose (part.printed() = all bodies, Compound)
        part.plate        production plate (2-plate design doc): 1 the multi-colour pieces (panels, front bar,
                          knob) and Q, 2 the navy pieces (cradle, plugs, far pins, caps, spacer)
        part.process      slicer profile class: "panel" | "struct" | "small" | "pin" | "cooling"
                          (bambu.PRODUCTION_SETTINGS)
        part.installed    False for the spare far pin and Q (print only, not in the assembly)
    model.hardware    {name: shape} bought items in the assembled pose: magnets mag_* (tabs: lower stacks
                      mag_tab-_k / mag_tab+_k on the base magnet points, upper stacks mag_tabU-_k / mag_tabU+_k on
                      the lid magnet points; mag_knob<phi>_k, mag_stator), pads pad_*
    model.reference   {name: shape} non-printed shapes for checks / renders: box, lid, base, tube (= 3
                      panels), rotor (tube + plugs), lip, beam, far_block, near_block, knob_body
    model.rotating    names (parts and hardware) that turn with the rotor about (axis_y, axis_z)
    model.reports     build-time facts (typography, per-face layout summary without digits, logo
                      clean-up, knob letters, tape hinges, face orientation, pocket walls, accent line seams,
                      M3 counterbore / pilot)
    model.results     filled by the hooks: "geometry", "checks", "plates", "renders", "report"

The phone numbers and texts stay in model.config (repr hidden); nothing in reports contains them (a text face
reports its font size, gaps and character positions only).
"""
from dataclasses import dataclass, field

import build123d as bd

from .box_model import build_box
from .config import ConfigError
from .cradle import build_cradle, build_pads
from .free_text import plan_text
from .front_bar import build_front_bar
from .knob import build_knob
from .logo_text import plan_logo
from .panels import build_panels, hinge_layout, print_rotation
from .params import COLOURS, make_params
from .rotor import build_plug_far, build_plug_near
from .small_parts import build_caps, build_cooling_tube, build_far_pin, build_magnets, build_spacer
from .text_layout import make_typography


@dataclass
class Part:
    name: str
    label: str                  # spec 4.2 label
    bodies: dict                # colour -> shape, assembled pose
    print_rotation: tuple       # (rx, ry, rz) deg applied before re-centring on the bed
    plate: int
    process: str
    installed: bool = True
    to_print: bd.Location = field(init=False, default=None)

    def __post_init__(self):
        unknown = set(self.bodies) - set(COLOURS)
        if unknown:
            raise ValueError(f"{self.name}: unknown colours {sorted(unknown)}")
        self.to_print = print_location(self.bodies, self.print_rotation)

    @property
    def colours(self):
        return list(self.bodies)

    def assembled(self):
        return bd.Compound(list(self.bodies.values()))

    def printed(self, colour=None):
        if colour is None:
            return self.to_print * self.assembled()
        return self.to_print * self.bodies[colour]

    @property
    def volume(self):
        return sum(body.volume for body in self.bodies.values())


@dataclass
class Model:
    params: object
    config: object
    typography: object
    parts: dict
    hardware: dict
    reference: dict
    rotating: tuple
    reports: dict
    results: dict = field(default_factory=dict)

    def plate(self, number):
        return [part for part in self.parts.values() if part.plate == number]

    def installed_parts(self):
        return [part for part in self.parts.values() if part.installed]


def print_location(bodies, rotation):
    turn = bd.Rot(*rotation)
    turned = turn * bd.Compound(list(bodies.values()))
    box = turned.bounding_box(optimal=True)
    return bd.Pos(-box.center().X, -box.center().Y, -box.min.Z) * turn


# print orientations (spec 4.2 / concept/v3.1/run_slice.py)
LIP_DOWN = (0.0, 0.0, 0.0)
FRONT_FACE_DOWN = (90.0, 0.0, 0.0)        # Y min onto the bed
PLUS_X_DOWN = (0.0, 90.0, 0.0)            # X max onto the bed
MINUS_X_DOWN = (0.0, -90.0, 0.0)          # X min onto the bed
UPRIGHT = (0.0, 0.0, 0.0)                 # as built (cooling tube Q)


def plan_texts(config):
    """{face: free_text.TextPlan} of the [text] faces; ConfigError (before any geometry) when one cannot be printed."""
    plans = {}
    for face, text in (("A", config.text_a), ("B", config.text_b)):
        if text is not None:
            try:
                plans[face] = plan_text(face, text)
            except ConfigError as error:
                raise ConfigError(f"[text] {face.lower()}: {error}") from None
    return plans


def plan_face_l(config, p):
    """logo_text.LogoChoice of face L ([text] l, [display] logo = \"none\"), None for today's face; ConfigError
    before any geometry."""
    try:
        return plan_logo(config.text_l, p.logo, p.logo_file)
    except ConfigError as error:
        raise ConfigError(f"[text] l: {error}") from None


def build_model(config):
    p = make_params(config.param_overrides())
    typo = make_typography(p)
    text_plans = plan_texts(config)
    logo = plan_face_l(config, p)
    box = build_box(p)
    panels, tube, logo_report = build_panels(p, typo, {"A": config.number_a, "B": config.number_b}, text_plans,
                                             logo)
    plug_near, plug_far = build_plug_near(p), build_plug_far(p)
    cradle = build_cradle(p)
    front = build_front_bar(p)
    knob = build_knob(p)
    far_pin = build_far_pin(p)
    caps = build_caps(p)

    parts = {}

    def add(name, label, bodies, rotation, plate, process, installed=True):
        parts[name] = Part(name, label, bodies, rotation, plate, process, installed)

    for face_name, label in (("A", "PA"), ("B", "PB"), ("L", "PL")):
        add(f"panel_{face_name}", label, panels[face_name][0], (print_rotation(face_name), 0.0, 0.0), 1, "panel")
    add("cradle", "C", {"navy": cradle["cradle"]}, LIP_DOWN, 2, "struct")
    add("front_bar", "F", front["bodies"], FRONT_FACE_DOWN, 1, "struct")
    add("knob", "K", knob["bodies"], PLUS_X_DOWN, 1, "small")
    add("plug_near", "EN", {"navy": plug_near}, MINUS_X_DOWN, 2, "small")     # thrust face (+X) up
    add("plug_far", "EF", {"navy": plug_far}, PLUS_X_DOWN, 2, "small")        # socket end (-X) up
    add("far_pin", "P", {"navy": far_pin}, PLUS_X_DOWN, 2, "pin")             # hex tip down, journal on top
    add("far_pin_spare", "P", {"navy": far_pin}, PLUS_X_DOWN, 2, "pin", installed=False)
    for name, cap in caps.items():
        add(name, "D", {"navy": cap}, FRONT_FACE_DOWN if name.startswith("cap_tab") else PLUS_X_DOWN, 2, "small")
    add("spacer", "S", {"navy": build_spacer(p)}, PLUS_X_DOWN, 2, "small")
    knob_height = parts["knob"].printed().bounding_box(optimal=True).max.Z
    add("cooling_tube", "Q", {"navy": build_cooling_tube(p, knob_height)}, UPRIGHT, parts["knob"].plate, "cooling",
        installed=False)                                                     # on the knob's plate

    magnets = build_magnets(p)
    hardware = {**magnets, **build_pads(p)}
    reference = dict(box, tube=tube, rotor=tube + plug_near + plug_far, lip=cradle["lip"], beam=front["beam"],
                     far_block=cradle["far_block"], near_block=cradle["near_block"], knob_body=knob["knob_body"])
    rotating = tuple(["panel_A", "panel_B", "panel_L", "plug_near", "plug_far", "far_pin", "knob", "cap_hub"]
                     + [name for name in caps if name.startswith("cap_knob")]
                     + [name for name in magnets if name.startswith("mag_knob")])
    reports = dict(
        typography=dict(em=typo.em, condense=typo.condense, em_face_limit=typo.em_face_limit,
                        em_length_limit=typo.em_length_limit, flat_height=typo.flat_height,
                        band_height=typo.band_height, glyph_cell=typo.glyph_w, cell_box=typo.cell_box,
                        widest=typo.widest),
        faces={name: report for name, (_, report) in panels.items()},
        logo=logo_report,
        knob_letters=knob["letters"],
        hinges=hinge_layout(),
        pocket_walls=front["pocket_walls"],
        line_seams=front["line_seams"],
        screw=dict(counterbore=p.screw_head_depth, pilot_depth=p.pilot_depth, en_pilot_floor=p.en_pilot_floor,
                   tip_to_pilot_bottom=p.screw_tip_clearance),
    )
    return Model(params=p, config=config, typography=typo, parts=parts, hardware=hardware, reference=reference,
                 rotating=rotating, reports=reports)
