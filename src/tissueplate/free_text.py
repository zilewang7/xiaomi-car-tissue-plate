"""Free text on a face ([text] a / b in config.toml; v3.4 design 6.6-6.8): one line of MiSans Bold.

Layout (6.6): characters at the font advance widths (no kerning; a space is its advance), neighbouring ink boxes at
least GAP_EM apart (the rest of the line is pushed where the font brings them closer), the line's ink box centred in
logo.ART_BOX (>= 3 mm from the face edges and the rotor ends: 175 x 21.6 mm). One font size and one condense (x scale)
per face: the size the line's ink band allows, never above EM_MAX; a line too long for it is condensed first (0.01
steps down to CONDENSE_MIN), then the size shrinks; size x condense below SIZE_MIN is an error (a text is never cut).
Printability (6.7, plate-0 limits) per character: closed counters >= HOLE_MIN (hard; a reading near the limit is
measured again at FINE_PIXEL, the worst of FINE_PHASES^2 raster phases), and three warnings: navy narrower than
GAP_MIN inside the character (may print fused), a stroke narrower than LINE_MIN that breaks the character
(stroke_breaks, shared with the logo face), the line's ink lower than INK_HEIGHT_WARN.
CAD (6.8): OCCT glyph faces, invalid ones repaired by ShapeFix, a white BRIDGE_R dot where an outline touches itself;
text_glyph_checks compares them with the font (area, ink box, gaps); panels.build_text_panel checks the cut.
The text never leaves config.toml: errors and reports name character positions (1-based), never the characters.
"""
import math
import unicodedata
from dataclasses import dataclass, field, replace
from functools import lru_cache

import build123d as bd
import numpy as np
from fontTools.pens.areaPen import AreaPen
from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont
from matplotlib.path import Path as MPath
from scipy import ndimage
from scipy.spatial import cKDTree

from .config import ConfigError
from .logo import ART_BOX, signed_area
from .params import FONT_PATH, FONT_URL
from .text_layout import FlattenPen

EM_MAX = 26.73          # 6.6: never above the number face's font size (a flat line would become a white slab)
CONDENSE_MIN = 0.86     # 6.6: condensed at most to the number faces' condense
SIZE_MIN = 8.0          # 6.7: font size x condense, plate 0 printed "YU7 PRO" at 8 mm; smaller is untested
GAP_EM = 0.075          # 6.6: ink boxes of neighbouring characters at least this far apart (em)
GAP_MIN = 0.5           # 6.7 hard limits (plate-0 ladder L): navy gap between two inlays,
HOLE_MIN = 0.8          # closed navy counter (inscribed circle),
LINE_MIN = 0.7          # white line (0.6 broke on plate 0)
INK_HEIGHT_WARN = 20.0  # 6.7: the original design asked for >= 20 mm high characters
PIXEL = 0.025           # mm per pixel, criteria as concept/v3.3/logo/drc33.py (calibrated there)
FINE_PIXEL = 0.005      # counters read within CRITICAL of HOLE_MIN are measured again at this pitch,
FINE_PHASES = 2         # at FINE_PHASES x FINE_PHASES sub-pixel phases, the worst reading counts
CRITICAL = 0.075        # mm
TOLERANCE_PX = 0.25     # pixel-centre alignment (drc33 CENTRE_TOL_PX)
SPECK = 0.05            # mm^2: smaller ink / navy islands are font artefacts, ignored
BRIDGE_R = 0.05         # white dot where a glyph outline touches itself (Ø0.1, below print resolution)
CORNER_TURN_DEG = 30.0  # sharp convex glyph vertex (run_logo_drc.py)
CORNER_NEAR = 0.6       # a thin-ink blob this close to a sharp convex vertex is that corner,
CORNER_EXTENT = 1.5     # unless it is longer than this (a real thin stroke)
REJECTED = {"Cc": "a control character (line break, tab)", "Cf": "an invisible format character",
            "Cs": "a surrogate", "Co": "a private-use character", "Cn": "an unassigned code point",
            "Zl": "a line separator", "Zp": "a paragraph separator", "Mn": "a combining mark",
            "Mc": "a combining mark", "Me": "a combining mark"}


@dataclass(frozen=True)
class TextPlan:
    face: str                           # "A", "B" (or "L" for a text-only logo face)
    em: float                           # font size (mm)
    condense: float                     # x scale of every character
    limited_by: str                     # "height" (ink band, EM_MAX) or "length"
    em_height_limit: float
    em_length_limit: float              # at this condense
    glyphs: tuple = field(repr=False)   # ((position, ch, x0, x1, y0), ...) inked characters, face-local ink boxes
    ink: tuple = ()                     # (x0, y0, x1, y1) face-local
    ink_height: float = 0.0             # mm
    digit_height: float = None          # ink height of the digits, when the line has any
    min_gap: float = None               # smallest ink gap between neighbouring characters (mm)
    printability: dict = None           # positions only


class Font:
    """MiSans Bold metrics in em units, cached per character."""

    def __init__(self):
        if not FONT_PATH.exists():
            raise ConfigError(f"font fonts/{FONT_PATH.name} not found: download MiSans from {FONT_URL} and put "
                              f"{FONT_PATH.name} into fonts/ (the font is not in the repository)")
        font = TTFont(str(FONT_PATH))
        self.units = font["head"].unitsPerEm
        self.cmap = font.getBestCmap()
        self.glyphset = font.getGlyphSet()
        self.hmtx = font["hmtx"]
        self._cache = {}

    def _draw(self, ch, pen):
        self.glyphset[self.cmap[ord(ch)]].draw(pen)
        return pen

    def _get(self, kind, ch, make):
        key = (kind, ch)
        if key not in self._cache:
            self._cache[key] = make()
        return self._cache[key]

    def advance(self, ch):
        return self.hmtx[self.cmap[ord(ch)]][0] / self.units

    def bounds(self, ch):
        """(xmin, ymin, xmax, ymax) or None for a glyph without ink (space)."""
        def make():
            bounds = self._draw(ch, BoundsPen(self.glyphset)).bounds
            return None if bounds is None else tuple(v / self.units for v in bounds)
        return self._get("bounds", ch, make)

    def area(self, ch):
        return self._get("area", ch, lambda: abs(self._draw(ch, AreaPen(self.glyphset)).value) / self.units ** 2)

    def contours(self, ch):
        """Flattened outline, outer rings CCW and holes CW."""
        return self._get("contours", ch, lambda: orient_by_parity(
            [c / self.units for c in self._draw(ch, FlattenPen(self.glyphset)).contours]))


@lru_cache(maxsize=1)
def font():
    return Font()


def orient_by_parity(rings):
    """Outer rings CCW, holes CW, by how many other rings of the glyph contain the ring (even-odd)."""
    oriented = []
    for index, ring in enumerate(rings):
        inside = sum(MPath(other).contains_point(ring[0]) for k, other in enumerate(rings) if k != index)
        ccw = inside % 2 == 0
        oriented.append(ring if (signed_area(ring) > 0) == ccw else ring[::-1])
    return oriented


def check_characters(text, font):
    """ConfigError for the first character that cannot be placed on one line of this font (position only)."""
    for position, ch in enumerate(text, start=1):
        category = unicodedata.category(ch)
        if category in REJECTED:
            raise ConfigError(f"character {position} is {REJECTED[category]}: one line of visible characters per face")
        if ord(ch) not in font.cmap:
            raise ConfigError(f"character {position} is not in {FONT_PATH.name} (it would print as an empty box or in "
                              "another font): use another character")
        if (font.bounds(ch) is None) != (category == "Zs"):
            raise ConfigError(f"character {position} does not print on its own in {FONT_PATH.name}")


# ---------------------------------------------------------------- layout
def ink_spans(metrics, condense):
    """[(position, x0, x1)] of the inked characters in em from the pen origin: condensed advances, ink boxes of
    neighbours >= GAP_EM apart (this and every later character pushed)."""
    pen, spans = 0.0, []
    for position, advance, bounds in metrics:
        if bounds is not None:
            start = pen + bounds[0] * condense
            if spans and start < spans[-1][2] + GAP_EM:
                pen += spans[-1][2] + GAP_EM - start
                start = spans[-1][2] + GAP_EM
            spans.append((position, start, start + (bounds[2] - bounds[0]) * condense))
        pen += advance * condense
    return spans


def line_length(metrics, condense):
    spans = ink_spans(metrics, condense)
    return spans[-1][2] - spans[0][1]


def line_layout(face, text):
    """TextPlan without the printability check (the web preview draws a line whose counters fail), or ConfigError
    (a character that cannot be placed, blank, too long)."""
    f = font()
    check_characters(text, f)
    metrics = [(position, f.advance(ch), f.bounds(ch)) for position, ch in enumerate(text, start=1)]
    inked = [(position, ch, bounds) for (position, ch), (_, _, bounds) in zip(enumerate(text, start=1), metrics)
             if bounds is not None]
    if not inked:
        raise ConfigError("has no visible character (a face cannot be left blank)")
    ymin = min(bounds[1] for _, _, bounds in inked)
    ymax = max(bounds[3] for _, _, bounds in inked)
    width, height = ART_BOX[2] - ART_BOX[0], ART_BOX[3] - ART_BOX[1]
    em_height = min(height / (ymax - ymin), EM_MAX)
    condense = 1.0
    while line_length(metrics, condense) * em_height > width and condense > CONDENSE_MIN + 1e-9:
        condense = round(condense - 0.01, 2)
    em_length = width / line_length(metrics, condense)
    em = math.floor(min(em_height, em_length) * 100) / 100
    if em * condense < SIZE_MIN - 1e-9:
        raise ConfigError(f"too long for one line: condensed to {condense:.2f} the font size would be {em:.2f} mm, "
                          f"size x condense below the {SIZE_MIN:g} mm plate-0 minimum ({len(inked)} visible "
                          "characters); shorten the text")
    spans = ink_spans(metrics, condense)
    shift = 0.5 * (ART_BOX[0] + ART_BOX[2]) - 0.5 * (spans[0][1] + spans[-1][2]) * em
    baseline = 0.5 * (ART_BOX[1] + ART_BOX[3]) - 0.5 * (ymin + ymax) * em
    glyphs = tuple((position, ch, shift + x0 * em, shift + x1 * em, baseline + bounds[1] * em)
                   for (position, ch, bounds), (_, x0, x1) in zip(inked, spans))
    gaps = [(b[1] - a[2]) * em for a, b in zip(spans, spans[1:])]
    digits = [bounds for _, ch, bounds in inked if unicodedata.category(ch) == "Nd"]
    digit_height = (max(b[3] for b in digits) - min(b[1] for b in digits)) * em if digits else None
    return TextPlan(face=face, em=em, condense=condense, limited_by="height" if em_height <= em_length else "length",
                    em_height_limit=em_height, em_length_limit=em_length, glyphs=glyphs,
                    ink=(shift + spans[0][1] * em, baseline + ymin * em, shift + spans[-1][2] * em, baseline + ymax * em),
                    ink_height=(ymax - ymin) * em, digit_height=digit_height, min_gap=min(gaps) if gaps else None)


def printability_of(plan):
    """check_printability of a line_layout plan."""
    f = font()
    inked = [(position, ch, f.bounds(ch)) for position, ch, _, _, _ in plan.glyphs]
    return check_printability(inked, f, plan.em, plan.condense, plan.em_height_limit)


def plan_text(face, text):
    """TextPlan of one face, or ConfigError (a character that cannot be placed, blank, too long, counters too small)."""
    plan = line_layout(face, text)
    return replace(plan, printability=printability_of(plan))


# ---------------------------------------------------------------- printability (raster, exact EDT disks)
def raster(rings, pixel=PIXEL, box=None, phase=(0.0, 0.0)):
    """(ink, x0, y0): even-odd fill of closed polylines (mm) at the pixel centres x0 + (i + 0.5) pixel, y0 + ...;
    box (x0, y0, x1, y1) limits the grid (default: the rings + 1 mm), phase shifts it by a fraction of a pixel."""
    if box is None:
        points = np.vstack(rings)
        box = (*(points.min(axis=0) - 1.0), *(points.max(axis=0) + 1.0))
    x0 = (np.floor(box[0] / pixel) + phase[0]) * pixel
    y0 = (np.floor(box[1] / pixel) + phase[1]) * pixel
    grid_x, grid_y = np.meshgrid(np.arange(x0 + pixel / 2, box[2], pixel), np.arange(y0 + pixel / 2, box[3], pixel))
    query = np.c_[grid_x.ravel(), grid_y.ravel()]
    ink = np.zeros(len(query), bool)
    for ring in rings:
        ink ^= MPath(ring).contains_points(query)
    return ink.reshape(grid_x.shape), x0, y0


def navy_regions(ink, pixel=PIXEL):
    """Labels of the 4-connected navy regions and the ids of the closed ones (not touching the border) above SPECK."""
    labels, count = ndimage.label(~ink)
    sizes = np.bincount(labels.ravel())
    border = set(np.unique(np.r_[labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    closed = [k for k in range(1, count + 1) if k not in border and sizes[k] * pixel ** 2 >= SPECK]
    return labels, closed


def counter_readings(ink, pixel):
    """[(reading mm, region slices)] of the closed counters: inscribed diameter 2 x (EDT max - 0.5 px) x pixel."""
    labels, closed = navy_regions(ink, pixel)
    if not closed:
        return []
    deepest = np.atleast_1d(ndimage.maximum(ndimage.distance_transform_edt(~ink), labels, closed))
    boxes = ndimage.find_objects(labels)
    return [(2 * (float(d) - 0.5) * pixel, boxes[k - 1]) for k, d in zip(closed, deepest)]


def fine_counter(rings, region, x0, y0):
    """Worst reading of the counters inside one coarse counter's box (+ 0.3 mm) at FINE_PIXEL over the phases."""
    rows, cols = region
    box = (x0 + cols.start * PIXEL - 0.3, y0 + rows.start * PIXEL - 0.3,
           x0 + cols.stop * PIXEL + 0.3, y0 + rows.stop * PIXEL + 0.3)
    readings = []
    for i in range(FINE_PHASES):
        for j in range(FINE_PHASES):
            ink, _, _ = raster(rings, FINE_PIXEL, box, (i / FINE_PHASES, j / FINE_PHASES))
            readings += [reading for reading, _ in counter_readings(ink, FINE_PIXEL)]
    return min(readings) if readings else None


def counter_min(rings):
    """Smallest counter (mm) of one character, None without counters; readings near HOLE_MIN measured finely."""
    ink, x0, y0 = raster(rings)
    readings = []
    for reading, region in counter_readings(ink, PIXEL):
        if abs(reading - HOLE_MIN) <= CRITICAL:
            fine = fine_counter(rings, region, x0, y0)
            reading = reading if fine is None else fine
        readings.append(reading)
    return min(readings) if readings else None


def topology(ink):
    """(ink parts, closed navy regions), islands below SPECK ignored."""
    labels, _ = ndimage.label(ink, structure=np.ones((3, 3)))
    parts = int(np.sum(np.bincount(labels.ravel())[1:] * PIXEL ** 2 >= SPECK))
    return parts, len(navy_regions(ink)[1])


def narrow_navy(rings):
    """True if filling the navy narrower than GAP_MIN inside the character changes its topology (it may print fused)."""
    ink, _, _ = raster(rings)
    outside = ndimage.distance_transform_edt(~ink)          # px to the nearest ink pixel centre
    return topology(ink | (outside < GAP_MIN / (2 * PIXEL) - TOLERANCE_PX)) != topology(ink)


def sharp_vertices(rings):
    """Convex ink vertices turning >= CORNER_TURN_DEG (rings oriented: outer CCW, holes CW)."""
    points = []
    for ring in rings:
        previous = ring - np.roll(ring, 1, axis=0)
        following = np.roll(ring, -1, axis=0) - ring
        cross = previous[:, 0] * following[:, 1] - previous[:, 1] * following[:, 0]
        dot = np.einsum("ij,ij->i", previous, following)
        points.append(ring[np.degrees(np.arctan2(cross, dot)) >= CORNER_TURN_DEG])
    return np.vstack(points) if points else np.zeros((0, 2))


def thin_ink_blobs(rings, limit=LINE_MIN, px=PIXEL):
    """Ink not covered by any disk of diameter `limit` inside the ink (exact EDT disks, 2 px de-noise), as blobs
    classified 'corner' (at a sharp convex glyph vertex, short) or 'thin' (a stroke narrower than the limit)."""
    ink, x0, y0 = raster(rings, px)
    inside = ndimage.distance_transform_edt(ink)
    centres = inside >= limit / 2 / px - TOLERANCE_PX
    covered = (ndimage.distance_transform_edt(~centres) <= limit / 2 / px) & ink
    y, x = np.ogrid[-2:3, -2:3]
    thin = ndimage.binary_opening(ink & ~covered, structure=x * x + y * y <= 4)
    labels, _ = ndimage.label(thin, structure=np.ones((3, 3)))
    corners = sharp_vertices(rings)
    tree = cKDTree(corners) if len(corners) else None
    blobs = []
    for index, region in enumerate(ndimage.find_objects(labels), start=1):
        rows, cols = np.nonzero(labels[region] == index)
        bx = x0 + (cols + region[1].start + 0.5) * px
        by = y0 + (rows + region[0].start + 0.5) * px
        centre = np.array([bx.mean(), by.mean()])
        extent = float(np.hypot(bx.max() - bx.min(), by.max() - by.min()) + px)
        near = tree is not None and tree.query(centre)[0] <= CORNER_NEAR
        blobs.append(dict(kind="corner" if near and extent <= CORNER_EXTENT else "thin", extent=round(extent, 3)))
    return blobs


def stroke_breaks(rings, limit=LINE_MIN, px=PIXEL):
    """True if a stroke narrower than `limit` joins two parts of the character (or a whole part is that thin): the
    centres of the `limit` disks that fit inside the ink no longer form one piece per ink part (v3.1 erosion test).
    Tapered stroke tips thinner than the limit do not count: they print a little shorter, the character stays whole."""
    ink, _, _ = raster(rings, px)
    centres = ndimage.distance_transform_edt(ink) >= limit / 2 / px - TOLERANCE_PX
    parts, count = ndimage.label(ink, structure=np.ones((3, 3)))
    cores, _ = ndimage.label(centres, structure=np.ones((3, 3)))
    speck = max(int(SPECK / px ** 2), 1)
    for part in range(1, count + 1):
        if np.sum(parts == part) < speck:
            continue
        inside = cores[(parts == part) & (cores > 0)]
        sizes = np.bincount(inside)[1:] if inside.size else np.zeros(0, int)
        if int(np.sum(sizes >= 2)) != 1:                  # vanished (0) or split (>= 2)
            return True
    return False


def breaks(rings):
    """A stroke narrower than LINE_MIN (away from the sharp corners) breaks the character."""
    return any(blob["kind"] == "thin" for blob in thin_ink_blobs(rings)) and stroke_breaks(rings)


def glyph_rings(ch, f, em, condense):
    return [np.column_stack([c[:, 0] * em * condense, c[:, 1] * em]) for c in f.contours(ch)]


def check_printability(inked, f, em, condense, em_height):
    """ConfigError when a counter is below HOLE_MIN (positions and the font size it needs); else the summary with
    the warning positions (narrow navy inside a character, broken strokes)."""
    by_char = {}
    for _, ch, _ in inked:
        if ch not in by_char:
            rings = glyph_rings(ch, f, em, condense)
            by_char[ch] = dict(counter_min=counter_min(rings), narrow_navy=narrow_navy(rings), breaks=breaks(rings))
    filled, needed = [], 0.0
    for position, ch, _ in inked:
        reading = by_char[ch]["counter_min"]
        if reading is not None and reading < HOLE_MIN:
            filled.append(position)
            needed = max(needed, em * HOLE_MIN / max(reading, PIXEL))     # counters scale with the size
    if filled:
        reach = (f"more than this face allows ({em_height:.2f} mm): use other characters" if needed > em_height
                 else "fewer characters give a larger size")
        raise ConfigError(f"at font size {em:.2f} mm (condense {condense:.2f}), character(s) {filled} have counters "
                          f"below {HOLE_MIN} mm and would print filled; they need about {needed:.1f} mm, {reach}")
    counters = [r["counter_min"] for r in by_char.values() if r["counter_min"] is not None]
    return dict(characters=len(inked), distinct=len(by_char), counter_min=min(counters) if counters else None,
                narrow_navy_positions=[position for position, ch, _ in inked if by_char[ch]["narrow_navy"]],
                broken_stroke_positions=[position for position, ch, _ in inked if by_char[ch]["breaks"]])


# ---------------------------------------------------------------- OCCT faces and build-time checks
def touch_points(faces):
    """Points where two wires of one glyph meet."""
    wires = [wire for face in faces for wire in face.wires()]
    points = []
    for i in range(len(wires)):
        for j in range(i + 1, len(wires)):
            distance, point, _ = wires[i].distance_to_with_closest_points(wires[j])
            if distance < 1e-6:
                points.append(point)
    return points


def glyph_faces(ch, em, condense):
    """OCCT faces of one glyph, x scaled by condense. OCCT builds some MiSans outlines as invalid faces (about 3 % of
    the GB2312 level-1 characters, e.g. 好): ShapeFix repairs them. Where two wires touch at a point (不, 当 ...) the
    inlay and the navy would not be closed solids: a white BRIDGE_R dot at each touch point joins them."""
    text = bd.Text(ch, font_size=em, font_path=str(FONT_PATH), align=(bd.Align.NONE, bd.Align.NONE))
    if condense != 1.0:
        text = bd.scale(text, by=(condense, 1.0, 1.0))
    faces = [fixed for face in text.faces() for fixed in ([face] if face.is_valid else face.fix().faces())]
    points = touch_points(faces)
    if not points:
        return faces
    dots = [bd.Pos(point.X, point.Y) * bd.Circle(BRIDGE_R).faces()[0] for point in points]
    return list(faces[0].fuse(*faces[1:], *dots).clean().faces())


def text_faces(plan):
    """[(position, [faces])] face-local: each glyph's OCCT ink box placed on its planned ink box."""
    placed = []
    for position, ch, x0, x1, y0 in plan.glyphs:
        faces = glyph_faces(ch, plan.em, plan.condense)
        box = bd.Compound(faces).bounding_box()
        shift = bd.Pos(0.5 * (x0 + x1) - 0.5 * (box.min.X + box.max.X), y0 - box.min.Y)
        placed.append((position, [shift * face for face in faces]))
    return placed


def text_glyph_checks(placed, plan):
    """Valid faces, no wires that still touch, area = font outline area (catches a silent OCCT fallback font or a
    lost contour), ink inside ART_BOX, neighbours >= GAP_MIN. ConfigError on any failure (positions only); returns
    the layout report."""
    f = font()
    errors, ratios, spans = [], [], []
    for (position, faces), (_, ch, _, _, _) in zip(placed, plan.glyphs):
        ratio = sum(face.area for face in faces) / (f.area(ch) * plan.em ** 2 * plan.condense)
        ratios.append(ratio)
        box = bd.Compound(faces).bounding_box()
        spans.append((box.min.X, box.max.X))
        if not all(face.is_valid for face in faces):
            errors.append(f"character {position}: invalid face after the CAD repair")
        elif touch_points(faces):
            errors.append(f"character {position}: its outline touches itself in {FONT_PATH.name} and the CAD repair "
                          "failed, the cut would not be a closed solid")
        if abs(ratio - 1.0) > 0.01:
            errors.append(f"character {position}: area differs from the font outline by {100 * (ratio - 1):.1f} %")
        if (box.min.X < ART_BOX[0] - 0.05 or box.max.X > ART_BOX[2] + 0.05 or box.min.Y < ART_BOX[1] - 0.05
                or box.max.Y > ART_BOX[3] + 0.05):
            errors.append(f"character {position}: ink outside the usable area")
    gaps = [b[0] - a[1] for a, b in zip(spans, spans[1:])]
    if gaps and min(gaps) < GAP_MIN - 0.02:
        errors.append(f"ink gap {min(gaps):.2f} mm between characters, below {GAP_MIN} mm")
    if errors:
        raise ConfigError("the CAD glyphs fail their checks: " + "; ".join(errors) + "; use other characters")
    return dict(mode="text", em=plan.em, condense=plan.condense, limited_by=plan.limited_by,
                em_height_limit=plan.em_height_limit, em_length_limit=plan.em_length_limit, ink=plan.ink,
                ink_height=plan.ink_height, digit_height=plan.digit_height, ink_length=spans[-1][1] - spans[0][0],
                min_ink_gap=min(gaps) if gaps else None, characters=len(placed),
                faces=sum(len(faces) for _, faces in placed), glyphs_valid=True,
                area_ratio_range=(min(ratios), max(ratios)), printability=plan.printability)
