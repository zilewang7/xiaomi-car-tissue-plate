"""Text on the logo face L ([text] l, [display] logo = "none"; v3.4 design 6.3-6.5, 6.7, 6.8).

Three cases (plan_logo):
- no [text] l (or l = BAKED_TEXT) with the sketch: None, the logo file verbatim (its baked wordmark, no new code);
- [text] l with the sketch: the baked wordmark (white rings BAKED_RINGS of the logo file) is replaced by this line,
  rendered the way concept/v3.3/logo/make_logo_v33.py rendered the baked one: matplotlib TextPath outlines of MiSans
  Bold (Bezier segments flattened to N_CURVE points), font advances + TRACKING mm, outer rings CCW, holes CW;
- [display] logo = "none": face L carries only the line, laid out like faces A / B (free_text.plan_text).

Layout beside the sketch (6.4): one line, ink bottom on the bottom edge of logo.ART_BOX (the nose tip height), never
condensed. The font size is the largest one from today's size (em_default, never larger) down to free_text.SIZE_MIN
in EM_STEP steps for which some position along x keeps CLEAR_MIN between the line and every sketch stroke (the line =
the glyph inks plus fillers over the gaps between them, so no stroke passes between two characters). At that size
the line takes the position nearest to today's wordmark centre whose clearance reaches min(CLEAR_GOOD, the best any
position reaches), as make_logo_v33 kept the first shift reaching CLEAR_GOOD, else the best one.
Printability beside the sketch (6.7, the free_text rules): counters >= HOLE_MIN, no stroke narrower than LINE_MIN that
breaks a character, glyph inks >= GAP_MIN apart (hard); navy narrower than GAP_MIN inside a character (warning).
Errors and reports name character positions (1-based), never the text.
"""
import json
import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
from matplotlib.font_manager import FontProperties
from matplotlib.path import Path as MPath
from matplotlib.textpath import TextPath
from scipy import ndimage
from scipy.spatial import cKDTree

from . import free_text
from .config import ConfigError
from .logo import ART_BOX, signed_area
from .params import FONT_PATH

BAKED_TEXT = "YU7 PRO"
BAKED_RINGS = slice(1, 10)      # white rings of the "final" logo file that are the baked wordmark (ring 0: window)
BAKED_INK = (74.472, 3.179, 118.27, 10.476)      # ink box of the baked wordmark rings (guards the ring split)
BAKED_CENTRE_X = 96.371         # ink-box centre of the baked wordmark (face mm), the tie-break anchor
CAP_TOP = 6.9                   # make_logo_v33 CAP_H: top of 'H' above the font origin at today's size (mm)
TRACKING = 0.45                 # mm added to every advance (make_logo_v33 TRACKING)
CLEAR_MIN = 1.5                 # make_logo_v33 TEXT_MIN_CLEAR: wordmark -> every sketch stroke (mm)
CLEAR_GOOD = 1.9                # make_logo_v33: the first shift reaching TEXT_MIN_CLEAR + 0.4 was kept
EM_STEP = 0.01
COARSE_STEP = 0.25              # slide steps (mm): size search, refined to FINE_STEP near the target
FINE_STEP = 0.01
SLIDE_STEP = 0.05               # final placement
TIE_MM = 0.01
N_CURVE = 12                    # points per Bezier segment (make_logo_v33 path_rings)
FIELD_PX = 0.025                # art distance raster (mm per pixel)
TOUCH_MM = 0.005                # two contours of one glyph closer than this touch (6.8: 不 当 很 清 ...): the navy cut
                                # would not be a closed solid, a free_text.BRIDGE_R white dot joins them


# ---------------------------------------------------------------- font (outlines as make_logo_v33 drew them)
def path_rings(path, n_curve=N_CURVE):
    """Closed polylines of a TextPath (make_logo_v33.path_rings)."""
    rings, current = [], []
    for segment, code in path.iter_bezier():
        points = segment.control_points
        if code == MPath.MOVETO:
            if len(current) > 2:
                rings.append(np.array(current))
            current = [points[0]]
        elif code == MPath.LINETO:
            current.append(points[-1])
        elif code in (MPath.CURVE3, MPath.CURVE4):
            current.extend(segment(np.linspace(0, 1, n_curve + 1)[1:]))
        elif code == MPath.CLOSEPOLY:
            if len(current) > 2:
                rings.append(np.array(current))
            current = []
    if len(current) > 2:
        rings.append(np.array(current))
    out = []
    for ring in rings:
        if np.allclose(ring[0], ring[-1]):
            ring = ring[:-1]
        keep = np.r_[True, np.hypot(*np.diff(ring, axis=0).T) > 1e-9]
        out.append(ring[keep])
    return out


class LogoFont(free_text.Font):
    """free_text.Font (cmap, advances) plus the TextPath outlines of make_logo_v33 in em units (em = 1000)."""

    def __init__(self):
        super().__init__()
        self.prop = FontProperties(fname=str(FONT_PATH))
        self._outlines = {}

    def outline(self, ch):
        """(rings, (xmin, ymin, xmax, ymax)) in font units, or ([], None) for a glyph without ink."""
        if ch not in self._outlines:
            if self.bounds(ch) is None:                 # space: TextPath of an empty outline fails
                self._outlines[ch] = ([], None)
            else:
                rings = free_text.orient_by_parity(path_rings(TextPath((0, 0), ch, size=1000.0, prop=self.prop)))
                points = np.vstack(rings)
                self._outlines[ch] = (rings, (*points.min(axis=0), *points.max(axis=0)))
        return self._outlines[ch]


@lru_cache(maxsize=1)
def logo_font():
    return LogoFont()


def em_default(font):
    """Today's font size: 'H' top at CAP_TOP (make_logo_v33: k = CAP_H / cap units, em = 1000 k)."""
    return CAP_TOP / (font.outline("H")[1][3] / 1000.0)


# ---------------------------------------------------------------- one line of glyphs
@dataclass(frozen=True)
class Glyph:
    position: int               # 1-based character position
    rings: tuple                # face mm, outer CCW / holes CW
    box: tuple                  # (x0, y0, x1, y1)


def line_glyphs(text, em, font):
    """Glyphs with the pen starting at x = 0 and the font origin on y = 0: advance x em + TRACKING per character;
    a glyph whose ink box comes closer than GAP_MIN to the previous one is pushed (with the rest of the line)."""
    scale = em / 1000.0
    pen, glyphs = 0.0, []
    for position, ch in enumerate(text, start=1):
        rings, bounds = font.outline(ch)
        if rings:
            start = pen + bounds[0] * scale
            if glyphs and start < glyphs[-1].box[2] + free_text.GAP_MIN:
                pen += glyphs[-1].box[2] + free_text.GAP_MIN - start
            placed = tuple(np.column_stack([ring[:, 0] * scale + pen, ring[:, 1] * scale]) for ring in rings)
            glyphs.append(Glyph(position, placed, (pen + bounds[0] * scale, bounds[1] * scale, pen + bounds[2] * scale,
                                                   bounds[3] * scale)))
        pen += font.advance(ch) * em + TRACKING
    return glyphs


def ink_box(glyphs):
    boxes = np.array([g.box for g in glyphs])
    return float(boxes[:, 0].min()), float(boxes[:, 1].min()), float(boxes[:, 2].max()), float(boxes[:, 3].max())


def moved(glyphs, dx, dy):
    return [Glyph(g.position, tuple(ring + (dx, dy) for ring in g.rings),
                  (g.box[0] + dx, g.box[1] + dy, g.box[2] + dx, g.box[3] + dy)) for g in glyphs]


def boundary_points(rings, step):
    """Points along closed rings, at most `step` apart (vertices included)."""
    pieces = []
    for ring in rings:
        closed = np.vstack([ring, ring[:1]])
        segments = np.diff(closed, axis=0)
        counts = np.maximum(np.ceil(np.hypot(*segments.T) / step).astype(int), 1)
        for start, segment, count in zip(closed[:-1], segments, counts):
            pieces.append(start + segment * (np.arange(count) / count)[:, None])
    return np.vstack(pieces)


# ---------------------------------------------------------------- the art: distance raster + exact boundary
def rasterise(rings, bounds, px):
    """Boolean mask (row 0 = y bottom) of the nonzero-winding fill of closed rings at pixel centres (scanline;
    concept/v3.3/logo/drc33.rasterise with the rows flipped)."""
    x0, y0, x1, y1 = bounds
    nx, ny = int(round((x1 - x0) / px)), int(round((y1 - y0) / px))
    mask = np.zeros((ny, nx), bool)
    a = np.vstack(rings)
    b = np.vstack([np.roll(ring, -1, axis=0) for ring in rings])
    low, high = np.minimum(a[:, 1], b[:, 1]), np.maximum(a[:, 1], b[:, 1])
    order = np.argsort(low)
    a, b, low, high = a[order], b[order], low[order], high[order]
    for row in range(ny):
        y = y0 + (row + 0.5) * px
        k = np.searchsorted(low, y, side="right")
        candidates = np.nonzero(high[:k] > y)[0]
        if candidates.size == 0:
            continue
        ax, ay, bx, by = a[candidates, 0], a[candidates, 1], b[candidates, 0], b[candidates, 1]
        up = (ay <= y) & (by > y)
        down = (by <= y) & (ay > y)
        crossing = up | down
        if not crossing.any():
            continue
        ax, ay, bx, by, up = ax[crossing], ay[crossing], bx[crossing], by[crossing], up[crossing]
        xc = ax + (y - ay) * (bx - ax) / (by - ay)
        winding = np.where(up, 1, -1)
        o = np.argsort(xc, kind="stable")
        xc, winding = xc[o], winding[o]
        inside = np.cumsum(winding)[:-1] != 0
        starts = np.ceil((xc[:-1][inside] - x0) / px - 0.5).astype(int)
        ends = np.ceil((xc[1:][inside] - x0) / px - 0.5).astype(int)
        diff = np.zeros(nx + 1, int)
        np.add.at(diff, np.clip(starts, 0, nx), 1)
        np.add.at(diff, np.clip(ends, 0, nx), -1)
        mask[row] = np.cumsum(diff[:-1]) > 0
    return mask


class ArtField:
    """Distance from any face point to the sketch strokes: a raster for the search, exact boundary points to confirm."""

    def __init__(self, art_rings, px=FIELD_PX, face=(0.0, 0.0, 181.0, 27.6)):
        self.px, self.face = px, face
        ink = rasterise(art_rings, face, px)
        # pixel centre -> nearest art pixel centre minus 0.75 px: the nearest art pixel centre lies within 0.71 px of
        # the art boundary, so the raster never exceeds the true distance (the search stays conservative)
        self.distance = np.maximum(ndimage.distance_transform_edt(~ink) - 0.75, 0.0) * px
        self.tree = cKDTree(boundary_points(art_rings, 0.01))

    def sample(self, points):
        """Bilinear raster distance at points (n, 2)."""
        cols = (points[:, 0] - self.face[0]) / self.px - 0.5
        rows = (points[:, 1] - self.face[1]) / self.px - 0.5
        return ndimage.map_coordinates(self.distance, [rows, cols], order=1, mode="nearest")

    def profile(self, points, shifts, chunk=2_000_000):
        """Min raster distance of `points` slid by each x shift."""
        shifts = np.asarray(shifts, float)
        out = np.empty(len(shifts))
        per = max(chunk // max(len(points), 1), 1)
        for start in range(0, len(shifts), per):
            block = shifts[start:start + per]
            moved_points = points[None, :, :] + np.stack([block, np.zeros_like(block)], axis=1)[:, None, :]
            values = self.sample(moved_points.reshape(-1, 2)).reshape(len(block), len(points))
            out[start:start + per] = values.min(axis=1)
        return out

    def exact(self, rings):
        """Min distance from the rings' boundary (0.01 mm samples) to the art boundary (0.01 mm samples)."""
        distance, _ = self.tree.query(boundary_points(rings, 0.01))
        return float(distance.min())


# ---------------------------------------------------------------- layout with the art
@dataclass(frozen=True)
class LogoTextPlan:
    em: float
    em_default: float
    cap_top: float              # 'H' top above the font origin (mm): CAP_TOP at today's size
    baseline: float             # face y of the font origin
    clearance: float            # exact min distance from the line (ink and gap fillers) to the sketch strokes (mm)
    best_clearance: float       # best raster clearance any slide position reaches at this size
    ink: tuple                  # (x0, y0, x1, y1) face mm
    glyphs: tuple = field(repr=False)
    sizes_tried: int = 0

    def rings(self):
        return [ring for glyph in self.glyphs for ring in glyph.rings]


def slide_range(glyphs):
    """(dy, low, high): dy puts the ink bottom on the ART_BOX bottom, x shifts low..high keep the ink inside ART_BOX;
    None if the line does not fit."""
    x0, y0, x1, y1 = ink_box(glyphs)
    dy = ART_BOX[1] - y0
    low, high = ART_BOX[0] - x0, ART_BOX[2] - x1
    if y1 + dy > ART_BOX[3] + 1e-9 or high < low:
        return None
    return dy, low, high


def gap_fillers(glyphs):
    """Rectangles over the gaps between neighbouring glyph boxes, from the lower bottom to the lower top: the sketch may
    not pass through the line between two characters (a word space is wide enough for the 1 mm drop stroke)."""
    rings = []
    for a, b in zip(glyphs[:-1], glyphs[1:]):
        x0, x1 = a.box[2], b.box[0]
        y0, y1 = min(a.box[1], b.box[1]), min(a.box[3], b.box[3])
        if x1 > x0 + 1e-9:
            rings.append(np.array([(x0, y0), (x1, y0), (x1, y1), (x0, y1)]))
    return rings


def clearance_rings(glyphs):
    """What must keep the clearance to the sketch: the outer glyph rings (holes lie inside them) and the gap fillers."""
    return [ring for glyph in glyphs for ring in glyph.rings if signed_area(ring) > 0] + gap_fillers(glyphs)


def outer_points(glyphs, dy, step=0.1):
    """Boundary samples of clearance_rings, moved up by dy."""
    return boundary_points(clearance_rings(glyphs), step) + (0.0, dy)


def shifts_between(low, high, step):
    return np.unique(np.r_[np.arange(low, high, step), high])


def reaches(glyphs, art, target):
    """(True / False, coarse best): some slide position keeps >= target (raster). The clearance changes by at most
    the shift (1-Lipschitz), so only coarse samples within COARSE_STEP / 2 of the target are refined."""
    found = slide_range(glyphs)
    if found is None:
        return False, None
    dy, low, high = found
    points = outer_points(glyphs, dy)
    shifts = shifts_between(low, high, COARSE_STEP)
    values = art.profile(points, shifts)
    best = float(values.max())
    if best >= target:
        return True, best
    near = shifts[values >= target - COARSE_STEP / 2]
    if len(near) == 0:
        return False, best
    fine = np.unique(np.clip(np.concatenate([s + np.arange(-COARSE_STEP / 2, COARSE_STEP / 2 + 1e-9, FINE_STEP)
                                             for s in near]), low, high))
    best = max(best, float(art.profile(points, fine).max()))
    return best >= target, best


def slide(glyphs, art):
    """(dx, dy, best): the position nearest to today's wordmark centre whose clearance reaches min(CLEAR_GOOD, the best
    any position reaches) (make_logo_v33 kept the first shift reaching CLEAR_GOOD, else the best one)."""
    dy, low, high = slide_range(glyphs)
    points = outer_points(glyphs, dy)
    shifts = shifts_between(low, high, SLIDE_STEP)
    values = art.profile(points, shifts)
    best = float(values.max())
    target = min(CLEAR_GOOD, best)
    good = shifts[values >= target - TIE_MM]
    x0, _, x1, _ = ink_box(glyphs)
    dx = float(good[np.argmin(np.abs(good + 0.5 * (x0 + x1) - BAKED_CENTRE_X))])
    return dx, dy, best


def plan_with_art(text, art, font=None, clear_min=CLEAR_MIN):
    """LogoTextPlan of a custom wordmark beside the sketch (art: ArtField), or ConfigError (positions only)."""
    font = font or logo_font()
    free_text.check_characters(text, font)
    visible = [position for position, ch in enumerate(text, start=1) if font.outline(ch)[0]]
    if not visible:
        raise ConfigError("has no visible character (a face cannot be left blank)")
    em_top = em_default(font)
    steps = int(math.floor((em_top - free_text.SIZE_MIN) / EM_STEP + 1e-9))
    sizes = [em_top] + [free_text.SIZE_MIN + k * EM_STEP for k in range(steps, -1, -1)
                        if free_text.SIZE_MIN + k * EM_STEP < em_top - 1e-9]       # descending, em_top first
    tried = 0

    def ok(index):
        nonlocal tried
        tried += 1
        return reaches(line_glyphs(text, sizes[index], font), art, clear_min)

    if not ok(0)[0]:
        fits, best = ok(len(sizes) - 1)
        if not fits:
            reason = ("the line does not fit the usable area" if best is None
                      else "the line runs into the sketch wherever it is placed" if best <= 0.0
                      else f"the best position keeps only {best:.2f} mm to the sketch")
            raise ConfigError(f"too long for the logo face: at the {free_text.SIZE_MIN:g} mm minimum font size {reason} "
                              f"(needs >= {clear_min:g} mm; {len(visible)} visible characters, "
                              f"{prefix_that_fits(text, art, font, clear_min)} fit): shorten it, or set [display] "
                              "logo = \"none\" for a text-only face")
        bad, good = 0, len(sizes) - 1                 # sizes[good] reaches the clearance, sizes[bad] does not
        while good - bad > 1:
            middle = (bad + good) // 2
            if ok(middle)[0]:
                good = middle
            else:
                bad = middle
        index = good
    else:
        index = 0
    while True:                                        # confirm with exact distances (raster is conservative)
        glyphs = line_glyphs(text, sizes[index], font)
        dx, dy, best = slide(glyphs, art)
        placed = moved(glyphs, dx, dy)
        clearance = art.exact(clearance_rings(placed))
        if clearance >= clear_min - 0.001 or index == len(sizes) - 1:
            break
        index += 1                                     # exact check failed: one size step smaller
    em = sizes[index]
    return LogoTextPlan(em=em, em_default=em_top, cap_top=font.outline("H")[1][3] * em / 1000, baseline=dy,
                        clearance=clearance, best_clearance=best, ink=ink_box(placed), glyphs=tuple(placed),
                        sizes_tried=tried)


def prefix_that_fits(text, art, font, clear_min):
    """'the first N visible characters' that fit at the minimum size (positions only)."""
    visible = [k for k, ch in enumerate(text) if font.outline(ch)[0]]
    low, high = 0, len(visible)                       # a prefix of `low` visible characters fits, `high` does not
    while high - low > 1:
        middle = (low + high) // 2
        prefix = text[:visible[middle - 1] + 1]
        if reaches(line_glyphs(prefix, free_text.SIZE_MIN, font), art, clear_min)[0]:
            low = middle
        else:
            high = middle
    return f"the first {low} visible characters"


# ---------------------------------------------------------------- printability, touch points
def check_logo_text(plan):
    """Report with 'errors' (hard: counters >= HOLE_MIN, no stroke narrower than LINE_MIN that breaks a character,
    glyph inks >= GAP_MIN apart) and the warning narrow_navy_positions (navy narrower than GAP_MIN inside a character).
    Positions only."""
    by_shape, counters, filled, broken, fused = {}, [], [], [], []
    for glyph in plan.glyphs:
        key = tuple(np.round(np.vstack(glyph.rings) - glyph.box[:2], 6).ravel()[:64])   # same glyph, same size
        if key not in by_shape:
            rings = list(glyph.rings)
            by_shape[key] = dict(counter_min=free_text.counter_min(rings), narrow_navy=free_text.narrow_navy(rings),
                                 breaks=free_text.breaks(rings))
        result = by_shape[key]
        if result["counter_min"] is not None:
            counters.append(result["counter_min"])
            if result["counter_min"] < free_text.HOLE_MIN:
                filled.append(glyph.position)
        if result["breaks"]:
            broken.append(glyph.position)
        if result["narrow_navy"]:
            fused.append(glyph.position)
    neighbour_gaps = [glyph_distance(a, b) for a, b in zip(plan.glyphs[:-1], plan.glyphs[1:])]
    errors = []
    if filled:
        errors.append(f"character(s) {filled} have counters below {free_text.HOLE_MIN} mm at font size {plan.em:.2f} "
                      "mm and would print filled")
    if broken:
        errors.append(f"character(s) {broken} have strokes below {free_text.LINE_MIN} mm at font size {plan.em:.2f} mm "
                      "that would break")
    if neighbour_gaps and min(neighbour_gaps) < free_text.GAP_MIN - 0.02:
        errors.append(f"ink gap {min(neighbour_gaps):.2f} mm between characters, below {free_text.GAP_MIN} mm")
    return dict(counter_min=min(counters) if counters else None, narrow_navy_positions=fused,
                broken_stroke_positions=broken, min_neighbour_gap=min(neighbour_gaps) if neighbour_gaps else None,
                errors=errors)


def glyph_distance(a, b):
    return float(cKDTree(boundary_points(a.rings, 0.01)).query(boundary_points(b.rings, 0.01))[0].min())


def touch_points(glyph):
    """Points where two contours of one glyph touch (closer than TOUCH_MM)."""
    clouds = [boundary_points([ring], 0.002) for ring in glyph.rings]
    points = []
    for i in range(len(clouds)):
        tree = cKDTree(clouds[i])
        for j in range(i + 1, len(clouds)):
            distance, nearest = tree.query(clouds[j])
            k = int(np.argmin(distance))
            if distance[k] < TOUCH_MM:
                points.append(0.5 * (clouds[j][k] + clouds[i][nearest[k]]))
    return points


def bridge_rings(glyphs, sides=16):
    """White dots (radius free_text.BRIDGE_R, CCW) over every touch point; logo.merge_overlapping fuses them into
    the glyph, as free_text.glyph_faces does for faces A / B."""
    angles = np.linspace(0.0, 2 * np.pi, sides, endpoint=False)
    circle = free_text.BRIDGE_R * np.column_stack([np.cos(angles), np.sin(angles)])
    return [point + circle for glyph in glyphs for point in touch_points(glyph)]


# ---------------------------------------------------------------- rings for the logo panel
def split_baked(data):
    """(art rings, baked wordmark rings) of the logo file: white BAKED_RINGS are the wordmark, the window and every
    azure ring are the art. Raises if the file does not hold the wordmark there."""
    white = [np.asarray(ring, float) for ring in data["white"]]
    words = white[BAKED_RINGS]
    points = np.vstack(words)
    box = (*points.min(axis=0), *points.max(axis=0))
    if len(words) != 9 or max(abs(a - b) for a, b in zip(box, BAKED_INK)) > 0.01:
        raise ValueError("logo file: white rings 1..9 are not the baked wordmark, cannot replace the text")
    art = white[:BAKED_RINGS.start] + white[BAKED_RINGS.stop:] + [np.asarray(ring, float) for ring in data["azure"]]
    return art, words


def custom_logo_rings(data, glyphs):
    """{colour: rings} for logo.load_logo_faces: the file's art with the baked wordmark replaced by these glyphs."""
    split_baked(data)
    white = data["white"][:BAKED_RINGS.start] + data["white"][BAKED_RINGS.stop:]
    rings = [ring for glyph in glyphs for ring in glyph.rings]
    return {"white": white + rings + bridge_rings(glyphs), "azure": data["azure"]}


@dataclass(frozen=True)
class LogoChoice:
    mode: str                                   # "wordmark" (beside the sketch) | "text" (text-only face)
    plan: object = field(repr=False)            # LogoTextPlan ("wordmark") or free_text.TextPlan ("text")
    data: dict = field(default=None, repr=False)    # the logo file ("wordmark")
    report: dict = None                         # sizes, clearance, positions only

    def rings(self, glyphs=None):
        """{colour: rings} of the wordmark face with all its glyphs, or only `glyphs` (to find one that fails)."""
        return custom_logo_rings(self.data, self.plan.glyphs if glyphs is None else glyphs)


@lru_cache(maxsize=4)
def art_field(logo_file):
    """(logo file data, ArtField of its sketch): computed once per file (about 0.4 s)."""
    data = json.loads(Path(logo_file).read_text(encoding="utf-8"))
    art, _ = split_baked(data)
    return data, ArtField(art)


def plan_logo(text, logo, logo_file):
    """None for today's face (no [text] l, or l = BAKED_TEXT, with the sketch: the logo file verbatim), else a
    LogoChoice. ConfigError (character positions only) when the text cannot be laid out or printed."""
    if logo == "none":
        plan = free_text.plan_text("L", text)
        return LogoChoice("text", plan, None, dict(mode="text", em=plan.em, condense=plan.condense, ink=plan.ink))
    if text is None or text == BAKED_TEXT:
        return None
    data, art = art_field(str(logo_file))
    plan = plan_with_art(text, art)
    drc = check_logo_text(plan)
    if drc["errors"]:
        raise ConfigError("; ".join(drc["errors"]) + f" (beside the sketch the font size is at most {plan.em_default:.2f} "
                          f"mm; [display] logo = \"none\" allows up to {free_text.EM_MAX} mm)")
    report = dict(mode="wordmark", em=plan.em, em_default=plan.em_default, cap_top=plan.cap_top,
                  clearance=plan.clearance, ink=plan.ink, sizes_tried=plan.sizes_tried,
                  printability={key: drc[key] for key in ("counter_min", "narrow_navy_positions",
                                                          "broken_stroke_positions", "min_neighbour_gap")})
    return LogoChoice("wordmark", plan, data, report)
