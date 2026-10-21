"""Previews of faces A / B / L as SVG, in memory only: they show the numbers and texts, so they are never written to
disk or logged (webui design 4.3).

They lay out with the build's own functions (text_layout.number_layout, free_text.line_layout, logo_text.plan_with_art)
and draw the same font outlines with fontTools, so positions and sizes are the build's; the CAD repairs and the
after-cut check run only in the build. A text face comes in two steps: "layout" (milliseconds) and "full" (adds the
counter and stroke checks, up to a few seconds per line; cached per text).
Face-local frame as panels.py: x 0 .. rotor length (knob end on the right, seen from outside), y 0 .. face flat.
"""
import json
import time
from functools import lru_cache

from .. import free_text, logo_text
from ..config import SCHEMA, ConfigError, check_field
from ..logo import ART_BOX
from ..params import COLOURS, make_params
from ..text_layout import make_typography, number_layout
from .schema import chinese, positions_in

NAVY, WHITE, AZURE = COLOURS["navy"]["hex"], COLOURS["white"]["hex"], COLOURS["azure"]["hex"]
GUIDE, MARK = "#f2c14e", "#ff4d4f"
EXAMPLE_NUMBERS = {"A": "13800138000", "B": "13900139000"}       # config.example.toml: faded placeholders


def _ring_path(rings, scale_x=1.0, scale_y=1.0, dx=0.0, dy=0.0):
    return " ".join("M" + " L".join(f"{x * scale_x + dx:.3f} {y * scale_y + dy:.3f}" for x, y in ring) + " Z"
                    for ring in rings)


def _frame(p, body, marks=(), example=False, box=ART_BOX):
    """Navy face, the dashed guide around box (the usable area: ART_BOX, on a number face the number cells), marks
    around (x0, y0, x1, y1) boxes; y up."""
    width, height = p.rotor_len, p.face_flat
    guide = (f'<rect x="{box[0]:.3f}" y="{box[1]:.3f}" width="{box[2] - box[0]:.3f}" height="{box[3] - box[1]:.3f}" '
             f'fill="none" stroke="{GUIDE}" stroke-width="0.15" stroke-dasharray="1 1"/>')
    boxes = "".join(f'<rect x="{x0 - 0.6:.3f}" y="{y0 - 0.6:.3f}" width="{x1 - x0 + 1.2:.3f}" height="{y1 - y0 + 1.2:.3f}" '
                    f'fill="none" stroke="{MARK}" stroke-width="0.5"/>' for x0, y0, x1, y1 in marks)
    opacity = ' opacity="0.45"' if example else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:g} {height:g}" width="{width * 4:g}" '
            f'height="{height * 4:g}"><rect width="{width:g}" height="{height:g}" fill="{NAVY}"/>'
            f'<g transform="translate(0 {height:g}) scale(1 -1)"><g{opacity}>{body}</g>{guide}{boxes}</g></svg>')


def _fill(path, colour):
    return f'<path fill="{colour}" fill-rule="nonzero" d="{path}"/>' if path else ""


# ---------------------------------------------------------------- number faces
@lru_cache(maxsize=8)
def _typography(overrides):
    p = make_params(dict(overrides))
    return p, make_typography(p)


def number_face(number, overrides, example=False):
    p, typo = _typography(overrides)
    layout = number_layout(number, typo, p)
    paths = []
    for ch, centre in zip(number, layout["centres"]):
        bounds = typo.bounds[ch]
        x_face = centre - p.rotor_x[0] - 0.5 * (bounds[0] + bounds[2]) * typo.em * typo.condense
        paths.append(_ring_path(typo.outlines[ch], typo.em * typo.condense, typo.em, x_face, typo.baseline_y))
    facts = {"kind": "number", "mode": layout["mode"], "digit_height": round(typo.band_height, 2),
             "inner_gap": None if layout["inner_gap"] is None else round(layout["inner_gap"], 2),
             "group_gap": None if layout["group_gap"] is None else round(layout["group_gap"], 2)}
    summary = (f"{'按字宽排' if layout['mode'] == 'proportional' else '固定格'} · 字高 {facts['digit_height']} mm"
               + (f" · 字距 {facts['inner_gap']} / 组距 {facts['group_gap']} mm" if facts["inner_gap"] else ""))
    cells = (typo.cell_box[0] - p.rotor_x[0], typo.baseline_y, typo.cell_box[1] - p.rotor_x[0],
             typo.baseline_y + typo.band_height)      # numbers use their own cells, wider than ART_BOX
    return {"svg": _frame(p, _fill(" ".join(paths), WHITE), example=example, box=cells), "facts": facts,
            "summary": summary}


# ---------------------------------------------------------------- free text (faces A / B, face L without the sketch)
@lru_cache(maxsize=64)
def _printability(text):
    """(printability, error) of a line; cached (the counter and stroke checks take seconds)."""
    try:
        return free_text.printability_of(free_text.line_layout("A", text)), None
    except ConfigError as error:
        return None, str(error)


def _glyph_boxes(plan, positions):
    f = free_text.font()
    boxes = []
    for position, ch, x0, x1, y0 in plan.glyphs:
        if position in positions:
            bounds = f.bounds(ch)
            boxes.append((x0, y0, x1, y0 + (bounds[3] - bounds[1]) * plan.em))
    return boxes


def text_face(face, text, step, p):
    """Layout of one line; with step "full" also the counters (hard) and the warnings."""
    plan = free_text.line_layout(face, text)
    f = free_text.font()
    paths = []
    for _, ch, x0, _, y0 in plan.glyphs:
        bounds = f.bounds(ch)
        paths.append(_ring_path(f.contours(ch), plan.em * plan.condense, plan.em, x0 - bounds[0] * plan.em * plan.condense,
                                y0 - bounds[1] * plan.em))
    facts = {"kind": "text", "em": plan.em, "condense": plan.condense, "ink_height": round(plan.ink_height, 2),
             "limited_by": plan.limited_by}
    result = {"facts": facts, "errors": [], "warnings": [], "positions": [], "checked": step == "full",
              "summary": f"字号 {plan.em:.2f} mm · 压缩 {plan.condense:.2f} · 字高 {plan.ink_height:.1f} mm"}
    if plan.ink_height < free_text.INK_HEIGHT_WARN:
        result["warnings"].append(f"字高 {plan.ink_height:.1f} mm，低于原设计要求的 {free_text.INK_HEIGHT_WARN:g} mm（只提醒）")
    if step == "full":
        printability, error = _printability(text)
        if error:
            result["errors"].append(chinese(error))
            result["positions"] = positions_in(error)
        else:
            narrow, broken = printability["narrow_navy_positions"], printability["broken_stroke_positions"]
            if narrow:
                result["warnings"].append(f"第 {'、'.join(map(str, narrow))} 个字里面的藏青缝窄于 {free_text.GAP_MIN} mm，"
                                          "可能糊在一起（只提醒）")
            if broken:
                result["warnings"].append(f"第 {'、'.join(map(str, broken))} 个字有一笔细于 {free_text.LINE_MIN} mm，"
                                          "可能打断（只提醒）")
    result["svg"] = _frame(p, _fill(" ".join(paths), WHITE), _glyph_boxes(plan, set(result["positions"])))
    return result


# ---------------------------------------------------------------- face L
@lru_cache(maxsize=4)
def _logo_data(logo_file):
    with open(logo_file, encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=32)
def _wordmark(text, logo_file):
    """(plan, error) of a custom line beside the sketch; the layout itself takes about a second."""
    try:
        _, art = logo_text.art_field(logo_file)
        return logo_text.plan_with_art(text, art), None
    except ConfigError as error:
        return None, str(error)


@lru_cache(maxsize=32)
def _wordmark_check(text, logo_file):
    plan, _ = _wordmark(text, logo_file)
    return logo_text.check_logo_text(plan)


def logo_face(text, step, p):
    logo_file = str(p.logo_file)
    data = _logo_data(logo_file)
    if text is None or text == logo_text.BAKED_TEXT:
        body = _fill(_ring_path(data["white"]), WHITE) + _fill(_ring_path(data["azure"]), AZURE)
        return {"svg": _frame(p, body), "facts": {"kind": "logo"}, "summary": "YU7 侧影和「YU7 PRO」（和现在一样）",
                "errors": [], "warnings": [], "positions": [], "checked": True}
    plan, error = _wordmark(text, logo_file)
    if error:
        art = logo_text.custom_logo_rings(data, [])
        body = _fill(_ring_path(art["white"]), WHITE) + _fill(_ring_path(art["azure"]), AZURE)
        return {"svg": _frame(p, body), "facts": {"kind": "wordmark"}, "summary": "", "errors": [chinese(error)],
                "warnings": [], "positions": positions_in(error), "checked": True}
    rings = logo_text.custom_logo_rings(data, plan.glyphs)
    result = {"facts": {"kind": "wordmark", "em": round(plan.em, 2), "clearance": round(plan.clearance, 2)},
              "summary": f"字号 {plan.em:.2f} mm · 离侧影 {plan.clearance:.2f} mm", "errors": [], "warnings": [],
              "positions": [], "checked": step == "full"}
    if step == "full":
        drc = _wordmark_check(text, logo_file)
        if drc["errors"]:
            joined = "; ".join(drc["errors"])
            result["errors"].append(chinese(joined))
            result["positions"] = positions_in(joined)
        if drc["narrow_navy_positions"]:
            result["warnings"].append(f"第 {'、'.join(map(str, drc['narrow_navy_positions']))} 个字里面的藏青缝窄于 "
                                      f"{free_text.GAP_MIN} mm，可能糊在一起（只提醒）")
    marks = [glyph.box for glyph in plan.glyphs if glyph.position in set(result["positions"])]
    body = _fill(_ring_path(rings["white"]), WHITE) + _fill(_ring_path(rings["azure"]), AZURE)
    result["svg"] = _frame(p, body, marks)
    return result


# ---------------------------------------------------------------- one face of a state
def _display_overrides(state):
    """Params overrides of the [display] keys, or the Chinese message of the first bad one."""
    overrides = {}
    for key, value in (state.get("display") or {}).items():
        if key in SCHEMA["display"]:
            overrides[SCHEMA["display"][key][0]] = check_field("display", key, value)
    return overrides


def preview(face, state, step="full"):
    """{"svg", "summary", "facts", "errors", "warnings", "positions", "checked", "example", "ms"}; errors are hard
    (the build would stop), warnings are not. ConfigError for a bad [display] value or a malformed number."""
    started = time.perf_counter()
    overrides = _display_overrides(state)
    p = make_params(overrides)
    key = face.lower()
    numbers, texts = state.get("numbers") or {}, state.get("text") or {}
    for text_key, value in texts.items():          # strings only (ConfigError, as the build would say)
        check_field("text", text_key, value)
    if face == "L":
        if p.logo == "none":
            text = texts.get("l")
            if text is None:
                result = {"svg": _frame(p, ""), "summary": "", "facts": {"kind": "text"}, "checked": True, "warnings": [],
                          "errors": ["L 面选了「只放文字」，要填 L 面文字"], "positions": []}
            else:
                result = _text_or_error("L", text, step, p)
        else:
            result = logo_face(texts.get("l"), step, p)
    elif key in texts:
        result = _text_or_error(face, texts[key], step, p)
    elif key in numbers:
        check_field("numbers", key, numbers[key])
        result = number_face(numbers[key], tuple(sorted(overrides.items())))
        result.update(errors=[], warnings=[], positions=[], checked=True)
    else:
        result = number_face(EXAMPLE_NUMBERS[face], tuple(sorted(overrides.items())), example=True)
        result.update(errors=[], warnings=[], positions=[], checked=True, summary="示例号码（淡色）：这一面还没填")
    result["example"] = face != "L" and key not in texts and key not in numbers
    result["ms"] = round((time.perf_counter() - started) * 1000)
    return result


def _text_or_error(face, text, step, p):
    try:
        return text_face(face, text, step, p)
    except ConfigError as error:
        return {"svg": _frame(p, ""), "summary": "", "facts": {"kind": "text"}, "checked": True, "warnings": [],
                "errors": [chinese(str(error))], "positions": positions_in(str(error))}


def hard_errors(state):
    """{face: [Chinese errors]} of every face as the build would find them (the build button's last check)."""
    found = {}
    for face in ("A", "B", "L"):
        result = preview(face, state, "full")
        if result["errors"]:
            found[face] = result["errors"]
    return found

