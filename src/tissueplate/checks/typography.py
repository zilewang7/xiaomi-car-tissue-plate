"""Check 1: typography and number layout (spec 4.6 / 7-1; port of concept/v3.1 sections 2 and 2b).

Length and face limits of the em, face margins, end margins of the worst-case cell box, raster stroke /
counter morphology (text_layout.stroke_report), number format, group gap >= 2 x ink gap for the number
faces and for the spec examples; for a [text] face (free_text.py, v3.4 6.7) its size x condense, usable area,
gaps between characters and counters (all enforced at build time, documented here) and three warnings: navy
narrower than the gap limit inside a character, broken strokes, ink lower than 20 mm (a text-only logo face [text] l
with logo "none" the same way); a custom wordmark beside the sketch (logo_text.py) its size, clearance to the
sketch, counters, broken strokes and gaps (hard) and the narrow-navy warning. With text on both faces
the number items describe the examples only and say so. The configured numbers and texts are never written
out: only their layout statistics (from the build reports) appear here; the examples are referred to by label.
"""
from ..config import NUMBER_PATTERN
from ..free_text import GAP_MIN, HOLE_MIN, INK_HEIGHT_WARN, LINE_MIN, SIZE_MIN
from ..logo import ART_BOX
from ..logo_text import CLEAR_MIN
from ..text_layout import number_layout, stroke_report
from .common import item, section

DIGIT_HEIGHT_MIN = 20.0       # spec 1: digit height >= 20 mm
STROKE_MIN = 2.8              # spec 4.6: strokes >= 2.8 mm
GROUP_RATIO_MIN = 2.0         # spec 4.6: group gap >= 2 x ink gap
EXAMPLES = {                  # spec / v3.1 example and worst-case layouts (labels only in the report)
    "example 1 (spec example)": "13900139000",
    "example 2 (spec example)": "13800138000",
    "example 3 (many narrow ones)": "11611112222",
    "example 4 (worst case, widest digits)": "14444444444",
}


def end_margins(typo, p):
    """Ink margins to the rotor ends: far end with the always-narrow first '1', knob end with the widest cell."""
    first_cell = typo.cells[0]
    one_width = typo.ink_width("1")
    far_ink = first_cell[0] + (typo.glyph_w - one_width) / 2
    return dict(far_cell=first_cell[0] - p.rotor_x[0], far_ink_with_1=far_ink - p.rotor_x[0],
                knob_cell=p.rotor_x[1] - typo.cells[-1][1])


def text_items(name, layout):
    """Items of a [text] face: the build already raised on every hard rule, the values document them."""
    printability = layout["printability"]
    fused, broken = printability["narrow_navy_positions"], printability["broken_stroke_positions"]
    size = round(layout["em"] * layout["condense"], 2)
    digits = "" if layout["digit_height"] is None else f", digits {layout['digit_height']:.1f}"
    return [
        item(f"face {name}: free text font size x condense (mm)", size, size >= SIZE_MIN - 1e-9,
             f">= {SIZE_MIN:g} (plate 0)", note=f"em {layout['em']:.2f}, condense {layout['condense']:.2f}"),
        item(f"face {name}: free text ink inside the usable area {ART_BOX}", [round(v, 2) for v in layout["ink"]],
             layout["glyphs_valid"], "build-time text_glyph_checks"),
        item(f"face {name}: gap between characters (mm)", layout["min_ink_gap"],
             layout["min_ink_gap"] is None or layout["min_ink_gap"] >= GAP_MIN - 0.02, f">= {GAP_MIN}"),
        item(f"face {name}: smallest counter (mm)", printability["counter_min"],
             printability["counter_min"] is None or printability["counter_min"] >= HOLE_MIN, f">= {HOLE_MIN}"),
        item(f"face {name}: characters with navy narrower than {GAP_MIN} mm inside (may print fused)",
             f"positions {fused}" if fused else "none", not fused, "none", level="warn"),
        item(f"face {name}: characters with a stroke narrower than {LINE_MIN} mm that breaks them",
             f"positions {broken}" if broken else "none", not broken, "none", level="warn"),
        item(f"face {name}: ink height (mm)", round(layout["ink_height"], 2),
             layout["ink_height"] >= INK_HEIGHT_WARN - 1e-9, f">= {INK_HEIGHT_WARN:g} (original design)",
             level="warn", note=f"line {layout['ink_height']:.1f}{digits}"),
    ]


def wordmark_items(logo):
    """Items of a custom wordmark beside the sketch: the build already raised on every hard rule."""
    printability = logo["printability"]
    fused, broken = printability["narrow_navy_positions"], printability["broken_stroke_positions"]
    gap = printability["min_neighbour_gap"]
    return [
        item("face L: wordmark font size (mm)", logo["em"], SIZE_MIN - 1e-9 <= logo["em"] <= logo["em_default"] + 1e-9,
             f"{SIZE_MIN:g} (plate 0) .. {logo['em_default']:.2f} (today's)"),
        item("face L: wordmark clearance to the sketch (mm)", logo["clearance"], logo["clearance"] >= CLEAR_MIN - 0.001,
             f">= {CLEAR_MIN:g} (v3.3 logo rule)"),
        item("face L: wordmark smallest counter (mm)", printability["counter_min"],
             printability["counter_min"] is None or printability["counter_min"] >= HOLE_MIN, f">= {HOLE_MIN}"),
        item(f"face L: wordmark characters with a stroke narrower than {LINE_MIN} mm that breaks them",
             f"positions {broken}" if broken else "none", not broken, "none (hard beside the sketch)"),
        item("face L: wordmark gap between characters (mm)", gap, gap is None or gap >= GAP_MIN - 0.02, f">= {GAP_MIN}"),
        item(f"face L: wordmark characters with navy narrower than {GAP_MIN} mm inside (may print fused)",
             f"positions {fused}" if fused else "none", not fused, "none", level="warn"),
    ]


def run(model):
    p, typo = model.params, model.typography
    number_faces = {name: number for name, number in (("A", model.config.number_a), ("B", model.config.number_b))
                    if number is not None}
    numbers_ok = all(NUMBER_PATTERN.fullmatch(number) is not None for number in number_faces.values())
    face_margin = (p.face_flat - typo.band_height) / 2
    margins = end_margins(typo, p)
    strokes = stroke_report(typo)
    layouts = {name: model.reports["faces"][name]["layout"] for name in ("A", "B")}
    faces = {name: layout for name, layout in layouts.items() if layout["mode"] != "text"}
    texts = {name: layout for name, layout in layouts.items() if layout["mode"] == "text"}
    logo = model.reports["logo"]
    if logo.get("mode") == "text":          # [display] logo = "none": face L laid out like A / B
        texts["L"] = model.reports["faces"]["L"]["layout"]
    examples = {}
    for label, text in EXAMPLES.items():
        layout = number_layout(text, typo, p)
        examples[label] = {key: value for key, value in layout.items() if key != "centres"}

    def ratio_ok(layout):
        return layout["mode"] == "fixed" or layout["ratio"] >= GROUP_RATIO_MIN - 1e-6

    items = []
    if number_faces:
        items.append(item(f"numbers {' / '.join(number_faces)}: 11 digits starting with 1", numbers_ok, numbers_ok,
                          "format (never shrunk)"))
    number_items = [
        item("digit height, flat '1' (mm)", typo.flat_height, typo.flat_height >= DIGIT_HEIGHT_MIN, f">= {DIGIT_HEIGHT_MIN}"),
        item("em set by the face fits the length limit (mm)", (typo.em, typo.em_length_limit),
             typo.em <= typo.em_length_limit, "em <= length limit"),
        item("face margin top / bottom (mm)", face_margin, face_margin >= p.face_margin - 1e-6, f">= {p.face_margin}"),
        item("ink margin far end (first digit '1', mm)", margins["far_ink_with_1"],
             margins["far_ink_with_1"] >= p.end_margin_near - 1e-6, f">= {p.end_margin_near}"),
        item("cell-box margin knob end (worst case, mm)", margins["knob_cell"],
             margins["knob_cell"] >= p.end_margin_near - 1e-6, f">= {p.end_margin_near}"),
        item("strokes survive 1.0 mm erosion, counters survive 0.8 mm dilation", strokes["ok"], strokes["ok"],
             "every digit"),
        item("thinnest stroke every digit survives (mm)", strokes["min_stroke"], strokes["min_stroke"] >= STROKE_MIN,
             f">= {STROKE_MIN}"),
        item("'1' stem width (mm)", strokes["stem_1"], level="info"),
    ]
    if not number_faces:          # v3.4 6.13 risk 10: the number layout is still built (check 6, v3.1 comparison)
        for entry in number_items:
            entry["name"] = f"number layout, examples only (no number face): {entry['name']}"
    items += number_items
    for name, layout in faces.items():
        items.append(item(f"face {name}: group gap / ink gap", layout["ratio"], ratio_ok(layout),
                          f">= {GROUP_RATIO_MIN} (or fixed cells)"))
        items.append(item(f"face {name}: glyph checks (valid, counters, area, margins, ink gap >= {p.ink_gap_min})",
                          layout["glyphs_valid"], layout["glyphs_valid"], "build-time glyph_checks"))
    for label, layout in examples.items():
        items.append(item(f"{label}: group gap / ink gap", layout["ratio"] if layout["mode"] == "proportional" else "fixed",
                          ratio_ok(layout), f">= {GROUP_RATIO_MIN} (or fixed cells)"))
    for name, layout in texts.items():
        items += text_items(name, layout)
    if logo.get("mode") == "wordmark":
        items += wordmark_items(logo)
    items.append(item("logo inside the usable area, white / azure do not overlap", logo["white_azure_overlap"],
                      level="info", note=f"art bbox {[round(v, 2) for v in logo['bbox']]} (build-time checks raise)"))
    numbers = dict(em=typo.em, em_length_limit=typo.em_length_limit, em_face_limit=typo.em_face_limit,
                   condense=typo.condense, flat_height=typo.flat_height, band_height=typo.band_height,
                   glyph_cell=typo.glyph_w, cell_box=typo.cell_box, face_margin=face_margin, end_margins=margins,
                   strokes={key: strokes[key] for key in ("ok", "stem_1", "min_stroke")},
                   faces=faces, examples=examples)
    if texts:                     # old configs: the output stays byte for byte as before
        numbers["texts"] = texts
    if logo.get("mode") == "wordmark":
        numbers["wordmark"] = {key: logo[key] for key in ("em", "em_default", "clearance", "ink", "printability")}
    return section("1 typography and layout", items, numbers)
