#!/usr/bin/env python3
"""Regression (v3.4 design 6.4): re-render the baked wordmark "YU7 PRO" the way concept/v3.3/logo/make_logo_v33.py
rendered it and compare it with the white rings 1..9 of the logo file, bit for bit after rounding to 4 decimals
(make_logo_v33 wrote np.round(ring, 4)). A custom [text] l is rendered with the same TextPath outlines, so a font or
matplotlib upgrade that changes them shows here first.

    python -I scripts/wordmark_check.py          exit 0 when every ring is identical
"""
import json
import sys
from pathlib import Path

import numpy as np
from matplotlib.path import Path as MPath
from matplotlib.textpath import TextPath

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))        # python -I ignores the script directory

from tissueplate.logo import signed_area  # noqa: E402
from tissueplate.logo_text import BAKED_RINGS, BAKED_TEXT, CAP_TOP, TRACKING, logo_font, path_rings  # noqa: E402
from tissueplate.params import FINAL_LOGO, font_is_authors  # noqa: E402

# make_logo_v33.layout() numbers of the baked wordmark (make_logo_v33_stdout.txt: "text shift +9.5 mm")
ART_Y = (3.0, 24.6)
W_PEAK, LAYOUT_TIP_W, MAIN_PX0_Y, X_NOSE, STRETCH, SHIFT = 1.58, 0.6, 356, 9.0, 1.2, 9.5


def v33_place():
    """(text centre x, baseline y) exactly as make_logo_v33.layout() computed them."""
    y_top = ART_Y[1] - 0.1 - W_PEAK / 2
    scale = (y_top - (ART_Y[0] + 0.1 + LAYOUT_TIP_W / 2)) / (MAIN_PX0_Y - 92.0)
    roof_peak_x = X_NOSE + (1160 - 284.0) * scale * STRETCH
    return roof_peak_x - 3.0 + SHIFT, ART_Y[0] + 0.45


def v33_rings(text):
    """make_logo_v33.text_rings: cap height CAP_TOP, advances + TRACKING, centred on the text centre, holes CW."""
    font = logo_font()
    x_centre, baseline = v33_place()
    k = CAP_TOP / TextPath((0, 0), "H", size=1000.0, prop=font.prop).get_extents().y1
    pen, glyphs = 0.0, []
    for ch in text:
        if ch != " ":
            glyphs.append([ring + np.array([pen, 0.0])
                           for ring in path_rings(TextPath((0, 0), ch, size=1000.0, prop=font.prop))])
        pen += font.advance(ch) * 1000.0 + TRACKING / k
    points = np.vstack([ring for glyph in glyphs for ring in glyph])
    cx = 0.5 * (points[:, 0].min() + points[:, 0].max())
    rings = []
    for glyph in glyphs:
        glyph = [np.column_stack([(ring[:, 0] - cx) * k + x_centre, ring[:, 1] * k + baseline]) for ring in glyph]
        for index, ring in enumerate(glyph):
            inside = sum(MPath(other).contains_point(ring[0]) for j, other in enumerate(glyph) if j != index)
            rings.append(ring if (signed_area(ring) > 0) == (inside % 2 == 0) else ring[::-1])
    return rings


def main():
    if not font_is_authors():
        print("skipped: fonts/MiSans-Bold.ttf is not the author's MiSans 4.009, so the outlines may differ from the baked "
              "rings without anything being wrong")
        return 0
    baked = [np.asarray(ring, float) for ring in json.loads(FINAL_LOGO.read_text(encoding="utf-8"))["white"][BAKED_RINGS]]
    fresh = [np.round(ring, 4) for ring in v33_rings(BAKED_TEXT)]
    same = len(baked) == len(fresh) and all(a.shape == b.shape and np.array_equal(a, b) for a, b in zip(baked, fresh))
    worst = max((float(np.abs(a - b).max()) for a, b in zip(baked, fresh) if a.shape == b.shape), default=None)
    print(f"{BAKED_TEXT!r}: {len(fresh)} rings re-rendered, {len(baked)} baked; "
          + ("identical after rounding to 4 decimals" if same else f"DIFFERENT (largest difference {worst} mm)"))
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main())
