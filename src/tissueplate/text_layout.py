"""Digit typography and the 3-4-4 number layout (spec 4.6), plus per-glyph validity checks.

MiSans Bold, horizontal condense 0.86, em set by the face width (26.73 mm). Layout X values are world X;
face-local coordinates are x_f = X - rotor_x[0] (0 .. 181 along the rotor) and y_f across the face flat
(0 = lower flat edge when the face is displayed, 27.6 = upper edge).
"""
import math
from dataclasses import dataclass

import build123d as bd
import numpy as np
from fontTools.pens.basePen import BasePen
from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont

from .config import NUMBER_PATTERN
from .params import FONT_PATH

DIGITS = "0123456789"
GROUP_ENDS = (2, 6)          # 3-4-4 groups: a group gap follows digit index 2 and 6


class FlattenPen(BasePen):
    """Flatten glyph outlines into closed polylines (font units)."""

    def __init__(self, glyphset, steps=12):
        super().__init__(glyphset)
        self.contours, self.current, self.steps = [], [], steps

    def _moveTo(self, point):
        self.current = [point]

    def _lineTo(self, point):
        self.current.append(point)

    def _curveToOne(self, p1, p2, p3):
        p0 = np.array(self.current[-1])
        for t in np.linspace(0, 1, self.steps + 1)[1:]:
            u = 1 - t
            self.current.append(tuple(u ** 3 * p0 + 3 * u * u * t * np.array(p1) + 3 * u * t * t * np.array(p2)
                                      + t ** 3 * np.array(p3)))

    def _qCurveToOne(self, p1, p2):
        p0 = np.array(self.current[-1])
        for t in np.linspace(0, 1, self.steps + 1)[1:]:
            u = 1 - t
            self.current.append(tuple(u * u * p0 + 2 * u * t * np.array(p1) + t * t * np.array(p2)))

    def _closePath(self):
        if self.current:
            self.contours.append(np.array(self.current, float))
        self.current = []

    _endPath = _closePath


@dataclass(frozen=True)
class Typography:
    em: float                 # font size (mm)
    condense: float
    em_length_limit: float
    em_face_limit: float
    bounds: dict              # digit -> (xmin, ymin, xmax, ymax) in em units
    outlines: dict            # digit -> list of (n, 2) contours in em units
    widest: str
    ymin: float               # ink band bottom (em units, below the baseline)
    band: float               # ink band height (em units)
    flat_height: float        # '1' height (mm)
    band_height: float        # round-digit height (mm)
    glyph_w: float            # widest digit width after condensing (mm) = fixed cell width
    cells: tuple              # 11 fixed cells (x0, x1), world X
    baseline_y: float         # face-local y of the baseline

    @property
    def cell_box(self):
        return (self.cells[0][0], self.cells[-1][1])

    def ink_width(self, ch):
        b = self.bounds[ch]
        return (b[2] - b[0]) * self.em * self.condense


def font_metrics(font_path=FONT_PATH):
    font = TTFont(str(font_path))
    units = font["head"].unitsPerEm
    glyphset, cmap = font.getGlyphSet(), font.getBestCmap()
    bounds, outlines = {}, {}
    for ch in DIGITS:
        glyph = glyphset[cmap[ord(ch)]]
        bounds_pen = BoundsPen(glyphset)
        glyph.draw(bounds_pen)
        bounds[ch] = tuple(v / units for v in bounds_pen.bounds)
        flatten_pen = FlattenPen(glyphset)
        glyph.draw(flatten_pen)
        outlines[ch] = [c / units for c in flatten_pen.contours]
    return bounds, outlines


def make_typography(p):
    """em from the face width; error (never shrink) if the worst-case layout would not fit the rotor."""
    bounds, outlines = font_metrics()
    width_max = max(b[2] - b[0] for b in bounds.values())
    widest = max(bounds, key=lambda ch: bounds[ch][2] - bounds[ch][0])
    ymin = min(b[1] for b in bounds.values())
    band = max(b[3] for b in bounds.values()) - ymin
    # worst-case cell box: 11 widest cells + 10 gaps + 2 group gaps, centred at layout_shift,
    # right end at least end_margin_near inside the rotor end
    length_max = 2 * (p.rotor_x[1] - p.end_margin_near - p.layout_shift)
    em_length = (length_max - 10 * p.cell_gap - 2 * p.group_gap) / (11 * width_max * p.condense)
    em_face = (p.face_flat - 2 * p.face_margin) / band
    em = math.floor(em_face * 100) / 100
    if em_length < em:
        raise ValueError(f"condense {p.condense}: the worst-case number needs em <= {em_length:.2f} mm but the face "
                         f"sets em {em:.2f} mm; digits are never shrunk - lower condense instead")
    glyph_w = width_max * em * p.condense
    length = 11 * glyph_w + 10 * p.cell_gap + 2 * p.group_gap
    cells = []
    x = p.layout_shift - length / 2
    for index in range(11):
        cells.append((x, x + glyph_w))
        x += glyph_w + p.cell_gap + (p.group_gap if index in GROUP_ENDS else 0.0)
    band_height = band * em
    baseline_y = (p.face_flat - band_height) / 2 - ymin * em
    return Typography(em=em, condense=p.condense, em_length_limit=em_length, em_face_limit=em_face, bounds=bounds,
                      outlines=outlines, widest=widest, ymin=ymin, band=band,
                      flat_height=(bounds["1"][3] - bounds["1"][1]) * em, band_height=band_height,
                      glyph_w=glyph_w, cells=tuple(cells), baseline_y=baseline_y)


def check_number(text):
    if not isinstance(text, str) or NUMBER_PATTERN.fullmatch(text) is None:
        raise ValueError("number must be 11 digits starting with 1 (digits are never shrunk to fit)")


def number_layout(text, typo, p):
    """Glyph ink centres (world X). Proportional: equal ink gaps inside a group, wider group gaps; falls back
    to the fixed cells when the group gap cannot stay >= 2 x the ink gap."""
    check_number(text)
    widths = [typo.ink_width(ch) for ch in text]
    box_start, box_end = typo.cell_box
    box_length = box_end - box_start
    box_centre = 0.5 * (box_start + box_end)
    fixed = dict(mode="fixed", centres=[0.5 * (c0 + c1) for c0, c1 in typo.cells], inner_gap=None, group_gap=None,
                 ratio=None, length=box_length)
    if p.layout == "fixed":
        return fixed
    inner_gap = min(p.ink_gap, (box_length - sum(widths)) / 12.0)       # 8 inner gaps + 2 group gaps >= 2 g
    if inner_gap < p.ink_gap_min:
        return fixed
    group_gap = min(p.group_gap_max, (box_length - sum(widths) - 8 * inner_gap) / 2)
    total = sum(widths) + 8 * inner_gap + 2 * group_gap
    x = box_centre - total / 2
    centres = []
    for index, width in enumerate(widths):
        centres.append(x + width / 2)
        x += width + (group_gap if index in GROUP_ENDS else inner_gap)
    return dict(mode="proportional", centres=centres, inner_gap=inner_gap, group_gap=group_gap,
                ratio=group_gap / inner_gap, length=total, ink=(centres[0] - widths[0] / 2, centres[-1] + widths[-1] / 2))


def glyph_faces(ch, typo):
    """Condensed glyph faces with the ink centred on x = 0 and the baseline on y = 0."""
    text = bd.Text(ch, font_size=typo.em, font_path=str(FONT_PATH), align=(bd.Align.NONE, bd.Align.NONE))
    text = bd.scale(text, by=(typo.condense, 1, 1))
    box = text.bounding_box()
    baseline_local = box.min.Y - typo.bounds[ch][1] * typo.em
    text = bd.Pos(-(box.min.X + box.max.X) / 2, -baseline_local) * text
    return list(text.faces())


def number_faces(text, typo, p):
    """[(digit, [faces])] in face-local coordinates."""
    layout = number_layout(text, typo, p)
    placed = []
    for ch, centre in zip(text, layout["centres"]):
        x_face = centre - p.rotor_x[0]
        placed.append((ch, [bd.Pos(x_face, typo.baseline_y) * face for face in glyph_faces(ch, typo)]))
    return placed, layout


def _outline_area(contours):
    """Even-odd area of flattened contours (em^2)."""
    total = 0.0
    for c in contours:
        x, y = c[:, 0], c[:, 1]
        total += 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
    return abs(total)


def glyph_checks(placed, layout, typo, p):
    """Per-glyph validity: valid faces, holes = font counters, area = font outline area, ink inside the face
    flat margins and the cell box, no glyph closer than the minimum ink gap. Raises on any failure."""
    errors = []
    rows = []
    box_start = typo.cell_box[0] - p.rotor_x[0]
    box_end = typo.cell_box[1] - p.rotor_x[0]
    ink_spans = []
    for index, (ch, faces) in enumerate(placed):
        valid = all(face.is_valid for face in faces)
        holes = sum(len(face.inner_wires()) for face in faces)
        area = sum(face.area for face in faces)
        font_area = _outline_area(typo.outlines[ch]) * typo.em ** 2 * typo.condense
        bbox = bd.Compound(faces).bounding_box()
        ink_spans.append((bbox.min.X, bbox.max.X))
        row = dict(index=index, valid=valid, faces=len(faces), holes=holes, expected_holes=len(typo.outlines[ch]) - 1,
                   area_ratio=area / font_area, x=(bbox.min.X, bbox.max.X), y=(bbox.min.Y, bbox.max.Y))
        rows.append(row)
        if not valid:
            errors.append(f"glyph {index}: invalid face")
        if len(faces) != 1 or holes != row["expected_holes"]:
            errors.append(f"glyph {index}: {len(faces)} faces / {holes} holes, expected 1 / {row['expected_holes']}")
        if abs(row["area_ratio"] - 1.0) > 0.01:
            errors.append(f"glyph {index}: area differs from the font outline by {100 * (row['area_ratio'] - 1):.1f} %")
        if bbox.min.Y < p.face_margin - 0.05 or bbox.max.Y > p.face_flat - p.face_margin + 0.05:
            errors.append(f"glyph {index}: ink outside the {p.face_margin} mm face margins")
        if bbox.min.X < box_start - 0.05 or bbox.max.X > box_end + 0.05:
            errors.append(f"glyph {index}: ink outside the cell box")
    min_gap = p.ink_gap_min if layout["mode"] == "proportional" else 0.0
    gaps = [ink_spans[i + 1][0] - ink_spans[i][1] for i in range(len(ink_spans) - 1)]
    if min(gaps) < min_gap - 0.02:
        errors.append(f"ink gap {min(gaps):.2f} mm below {min_gap} mm")
    if layout["mode"] == "proportional" and layout["ratio"] < 2.0 - 1e-6:
        errors.append(f"group gap only {layout['ratio']:.2f} x the ink gap (spec >= 2)")
    if errors:
        raise ValueError("digit glyph checks failed: " + "; ".join(errors))
    return dict(mode=layout["mode"], inner_gap=layout["inner_gap"], group_gap=layout["group_gap"],
                ratio=layout["ratio"], ink_length=ink_spans[-1][1] - ink_spans[0][0], min_ink_gap=min(gaps),
                glyphs_valid=True, area_ratio_range=(min(r["area_ratio"] for r in rows), max(r["area_ratio"] for r in rows)))


def stroke_report(typo, pixel=0.04):
    """Raster morphology per digit (v3.1 check): 1.0 mm erosion keeps every stroke, 0.8 mm dilation keeps every
    counter open (v3.3: plate-0 ladder L, closed navy holes >= 0.8); also the '1' stem width and the stroke width
    every digit survives."""
    from matplotlib.path import Path as MPath
    from scipy import ndimage

    def disk(radius):
        n = int(radius / pixel)
        return np.hypot(*np.mgrid[-n:n + 1, -n:n + 1]) * pixel <= radius

    min_pixels = int(0.1 / pixel ** 2)          # ignore specks < 0.1 mm^2 (corner artefacts)

    def count(mask):
        labels, n = ndimage.label(mask)
        return int(sum(1 for k in range(1, n + 1) if (labels == k).sum() >= min_pixels))

    em, cond = typo.em, typo.condense
    result, stem = {}, None
    for ch in DIGITS:
        b = typo.bounds[ch]
        contours = [np.c_[(c[:, 0] - b[0]) * em * cond, (c[:, 1] - typo.ymin) * em] for c in typo.outlines[ch]]
        xs = np.arange(-0.5, (b[2] - b[0]) * em * cond + 1.0, pixel)
        ys = np.arange(-0.5, typo.band * em + 1.0, pixel)
        grid_x, grid_y = np.meshgrid(xs, ys)
        query = np.c_[grid_x.ravel(), grid_y.ravel()]
        ink = np.zeros(len(query), bool)
        for c in contours:                       # even-odd fill: counters become holes
            ink ^= MPath(c).contains_points(query)
        ink = ink.reshape(grid_x.shape)
        components, background = count(ink), count(~ink)
        eroded = count(ndimage.binary_erosion(ink, structure=disk(0.5)))
        dilated_background = count(~ndimage.binary_dilation(ink, structure=disk(0.4)))
        stroke_ok = 1.0
        for radius in (0.8, 1.1, 1.4, 1.7):
            if count(ndimage.binary_erosion(ink, structure=disk(radius))) == components:
                stroke_ok = 2 * radius
            else:
                break
        result[ch] = dict(components=components, after_erosion_1mm=eroded, background_regions=background,
                          after_dilation_0p8mm=dilated_background, min_stroke_ge=stroke_ok)
        if ch == "1":
            row = ink[int((0.35 * typo.band * em) / pixel)]
            runs = np.diff(np.r_[0, row.astype(int), 0])
            starts, ends = np.where(runs == 1)[0], np.where(runs == -1)[0]
            stem = max(e - s for s, e in zip(starts, ends)) * pixel
    ok = all(v["components"] == v["after_erosion_1mm"] and v["background_regions"] == v["after_dilation_0p8mm"]
             for v in result.values())
    return dict(ok=ok, stem_1=stem, min_stroke=min(v["min_stroke_ge"] for v in result.values()), digits=result)
