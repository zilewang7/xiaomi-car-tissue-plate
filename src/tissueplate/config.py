"""Load and validate config.toml (spec 7). Phone numbers and texts live only here and are never printed.

Every key is optional except the content of faces A and B: each comes from exactly one of [numbers] a / b (11 digits
starting with 1, the 3-4-4 number layout) or [text] a / b (one line of free text, free_text.py lays it out and checks
it when the model is built); [text] l replaces the logo face's wordmark, with [display] logo = "none" it is the
whole face (logo_text.py); missing keys take the spec value. Unknown keys, wrong types, out-of-range values and
malformed numbers raise ConfigError with a clear message (no silent fixing, no digit shrinking). Messages never
repeat a value from the file; digit runs in unknown section or key names are masked (someone may type a number
there). Keys retired in v3.4 are ignored with a note.
"""
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .front_bar import check_layout
from .params import FONT_PATH, FONT_URL, LOGO_FILES, PROJECT_DIR, make_params

CONFIG_PATH = PROJECT_DIR / "config.toml"
NUMBER_PATTERN = re.compile(r"1[0-9]{10}")
DIGIT_RUN = re.compile(r"[0-9](?:[ ()-]*[0-9]){6,}")     # 7+ digits, spaces / dashes / brackets between them


class ConfigError(ValueError):
    pass


# section -> key -> (Params field, kind, allowed). kind: "float" (range), "int" (set), "str" (set)
SCHEMA = {
    "display": {
        "logo": ("logo", "str", tuple(LOGO_FILES)),
        "condense": ("condense", "float", (0.70, 1.00)),
        "white_layers": ("white_layers", "int", (3, 4, 5)),          # plate-0 test 4 picks one of these
        "layout": ("layout", "str", ("proportional", "fixed")),
    },
    "mount": {
        "stack": ("mount_stack", "int", (2,)),                      # v3.3: no stack-1 fallback (fails check 10)
        "delta_up": ("mount_delta", "float", (0.0, 3.0)),           # both stacks: the upper one follows (v3.4)
        "tab_bottom": ("tab_bottom", "float", (-40.0, -30.0)),      # measured free to -40; -30 analysed fallback
        "pad_t": ("pad_t", "float", (0.5, 1.5)),                    # v3.4: 1.2 mm double-sided tape; >= 0.5 (10-20)
    },
    "detent": {
        "knob_stack": ("knob_stack", "int", (2,)),                  # v3.4: other values fail the build
        "boss_h": ("boss_h", "float", (0.6, 0.6)),
    },
    "box": {
        "skirt": ("skirt", "float", (10.0, 20.0)),
        "mag_from_end": ("mag_from_end", "float", (30.0, 60.0)),
        "mag_below_top": ("mag_below_top", "float", (15.0, 30.0)),
        "lid_mag_below_top": ("lid_mag_below_top", "float", (5.0, 13.0)),   # v3.3: lid magnet, upper stack
        "top_fillet": ("top_fillet", "float", (0.0, 5.0)),
    },
    "fit": {   # defaults: the author's plate-0 / 0b picks; a part that does not fit: change its key, reprint only
               # that part (README). Holes below the Ø6 journals are calibrated fits (verify_geometry)
        "near_hole": ("hole_near", "float", (5.85, 6.35)),           # cradle C: the knob journal turns freely in it
        "far_hole": ("hole_far", "float", (5.85, 6.35)),             # cradle C: the far pin journal turns in it
                                                                     # (v3.4), default 0.05 looser than near_hole
        "far_hex_af": ("far_hex_af", "float", (4.95, 5.05)),         # far pin P: hex in the AF 5.20 EF socket
        "hex_socket_af": ("hex_socket_af", "float", (5.15, 5.30)),   # near plug EN: hex socket of the knob peg
        "hex_af": ("hex_af", "float", (5.00, 5.10)),                 # hex pegs X: goes in, does not wobble (judged
                                                                     # in AF 5.15; the EN hex is 5.20 since 10-17)
        "tab_cap_d": ("tab_cap_d", "float", (8.15, 8.25)),           # plate 0b caps: in by finger, flat, no wobble
        "knob_cap_d": ("knob_cap_d", "float", (8.15, 8.25)),
        "hub_cap_d": ("hub_cap_d", "float", (6.25, 6.40)),           # plate 0b hub caps: tightest pressed in flat;
                                                                     # 6.45 would overlap the Ø6.40 counterbore
    },
    "hardware": {
        "screw_head_k": ("screw_head_k", "float", (1.6, 2.8)),       # M3 x 25 head height -> knob counterbore
    },
}
# keys of v3.3 files that v3.4 ignores (with a note) instead of rejecting as unknown
RETIRED = {"fit": {"far_bore": "the far plug has a hex socket",
                   "dowel_d_lip": "the cradle has no dowel holes",
                   "dowel_d_block": "the cradle has no dowel holes"}}


@dataclass(frozen=True)
class Config:
    number_a: str = field(repr=False)     # face A (shown first); None when [text] a is set
    number_b: str = field(repr=False)     # face B; None when [text] b is set
    overrides: dict = field(default_factory=dict)   # Params field -> value
    source: str = ""
    notes: tuple = ()                                 # retired keys that were ignored, one line (the caller shows it)
    text_a: str = field(default=None, repr=False)     # [text] a: one line of free text on face A instead of a number
    text_b: str = field(default=None, repr=False)
    text_l: str = field(default=None, repr=False)     # [text] l: the logo face's line (None: the baked wordmark)

    def param_overrides(self):
        return dict(self.overrides)


def _check_number(key, value):
    if not isinstance(value, str):
        raise ConfigError(f"[numbers] {key} must be a quoted string of 11 digits starting with 1")
    if NUMBER_PATTERN.fullmatch(value) is None:
        digits = sum(ch.isdigit() for ch in value)
        raise ConfigError(f"[numbers] {key} must be exactly 11 digits starting with 1 (got {len(value)} characters, "
                          f"{digits} digits); digits are never shrunk or truncated to fit")
    return value


def masked(names):
    """Sorted names for a message, digit runs replaced by •••."""
    return [DIGIT_RUN.sub("•••", str(name)) for name in sorted(names, key=str)]


def _face_contents(data):
    """(number_a, number_b, text_a, text_b, text_l): each of faces A / B from exactly one of [numbers] / [text];
    l (face L) only in [text], optional."""
    contents = {}
    for section in ("numbers", "text"):
        values = data.get(section, {})
        if not isinstance(values, dict):
            raise ConfigError(f"[{section}] must be a table")
        unknown = set(values) - ({"a", "b"} if section == "numbers" else {"a", "b", "l"})
        if unknown:
            hint = " (the logo face text goes in [text] l)" if section == "numbers" and "l" in unknown else ""
            raise ConfigError(f"unknown key(s) {masked(unknown)} in [{section}]{hint}")
        contents[section] = values
    for key in ("a", "b"):
        given = [section for section in ("numbers", "text") if key in contents[section]]
        if len(given) == 2:
            raise ConfigError(f"face {key.upper()} is set twice, in [numbers] {key} and [text] {key}: keep one")
        if not given:
            raise ConfigError(f"face {key.upper()} needs [numbers] {key} (11 digits starting with 1) or [text] {key} "
                              "(one line of text)")
    numbers, texts = contents["numbers"], contents["text"]
    for key, value in texts.items():
        if not isinstance(value, str):
            raise ConfigError(f"[text] {key} must be a quoted string")
    return (_check_number("a", numbers["a"]) if "a" in numbers else None,
            _check_number("b", numbers["b"]) if "b" in numbers else None, texts.get("a"), texts.get("b"),
            texts.get("l"))


def _check_value(section, key, value, kind, allowed):
    name = f"[{section}] {key}"
    if kind == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigError(f"{name} must be a number")
        low, high = allowed
        if not low <= value <= high:                  # not float(value): a 310-digit integer overflows it
            if low == high:
                raise ConfigError(f"{name} must be {low:g}: the only value v3.4 supports")
            hint = " (see the [fit] notes in config.example.toml)" if section == "fit" else ""
            raise ConfigError(f"{name} is outside the allowed range {low} .. {high}{hint}")
        return float(value)
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(f"{name} must be an integer")
    elif kind == "str":
        if not isinstance(value, str):
            raise ConfigError(f"{name} must be a string")
    if value not in allowed:
        if len(allowed) == 1:
            raise ConfigError(f"{name} must be {allowed[0]!r}: the only value v3.4 supports")
        raise ConfigError(f"{name} must be one of {list(allowed)}")
    return value


def check_field(section, key, value):
    """One key on its own, checked as parse_config checks it (the web form, while typing): the value parse_config
    keeps, None for a retired key (ignored), or ConfigError."""
    if section in ("numbers", "text"):
        if key not in (("a", "b") if section == "numbers" else ("a", "b", "l")):
            raise ConfigError(f"unknown key(s) {masked([key])} in [{section}]")
        if section == "numbers":
            return _check_number(key, value)
        if not isinstance(value, str):
            raise ConfigError(f"[text] {key} must be a quoted string")
        return value
    if section not in SCHEMA:
        raise ConfigError(f"unknown section(s) {masked([section])}")
    if key in RETIRED.get(section, {}):
        return None
    if key not in SCHEMA[section]:
        raise ConfigError(f"unknown key(s) {masked([key])} in [{section}]")
    _, kind, allowed = SCHEMA[section][key]
    return _check_value(section, key, value, kind, allowed)


def parse_config(data, source=""):
    unknown_sections = set(data) - set(SCHEMA) - {"numbers", "text"}
    if unknown_sections:
        raise ConfigError(f"unknown section(s) {masked(unknown_sections)} in {source or 'config'}")
    number_a, number_b, text_a, text_b, text_l = _face_contents(data)
    if not FONT_PATH.exists():
        raise ConfigError(f"font fonts/{FONT_PATH.name} not found: download MiSans from {FONT_URL} and put "
                          f"{FONT_PATH.name} into fonts/ (the only file needed; the font is not in the repository)")
    overrides, notes = {}, []
    for section, keys in SCHEMA.items():
        values = data.get(section, {})
        if not isinstance(values, dict):
            raise ConfigError(f"[{section}] must be a table")
        retired = RETIRED.get(section, {})
        unknown = set(values) - set(keys) - set(retired)
        if unknown:
            raise ConfigError(f"unknown key(s) {masked(unknown)} in [{section}]")
        found = [key for key in values if key in retired]
        if found:     # one line for all of them (v3.4 4.4)
            reasons = "; ".join(dict.fromkeys(retired[key] for key in found))
            notes.append(f"[{section}] {', '.join(found)}: not used since v3.4 ({reasons}), ignored; "
                         "the lines can go")
        for key, value in values.items():
            if key in retired:
                continue
            param_name, kind, allowed = keys[key]
            try:
                overrides[param_name] = _check_value(section, key, value, kind, allowed)
            except ConfigError as error:
                if key != "logo":
                    raise
                raise ConfigError(f"{error}; the logo face text goes in [text] l") from None
    if "mount_delta" in overrides:
        overrides["upper_delta"] = overrides["mount_delta"]     # the upper stack follows delta_up (v3.4)
    p = make_params(overrides)
    try:
        check_layout(p)
    except ValueError as error:
        raise ConfigError(f"front bar layout does not fit this [mount]: {error}. pad_t, delta_up and tab_bottom "
                          "change together: take one of the sets in config.example.toml") from None
    from .text_layout import make_typography      # text_layout imports NUMBER_PATTERN from here
    try:
        make_typography(p)
    except ValueError:
        both_text = number_a is None and number_b is None
        raise ConfigError("[display] condense is too large for the 3-4-4 number layout (digits are never shrunk): "
                          "lower it, the default is 0.86"
                          + (" (with text on both faces the number layout is still built for check 6 and the v3.1 "
                             "comparison)" if both_text else "")) from None
    logo = overrides.get("logo", "final")
    if logo == "none" and text_l is None:
        raise ConfigError("[display] logo = \"none\" needs [text] l: face L would be blank")
    if LOGO_FILES[logo] is not None and not LOGO_FILES[logo].exists():
        raise ConfigError(f"logo geometry file for {logo!r} not found: {LOGO_FILES[logo]}")
    return Config(number_a=number_a, number_b=number_b, overrides=overrides, source=str(source), notes=tuple(notes),
                  text_a=text_a, text_b=text_b, text_l=text_l)


def load_config(path=None):
    config_path = Path(path) if path is not None else CONFIG_PATH
    if not config_path.exists():
        raise ConfigError(f"{config_path} not found: copy config.example.toml to config.toml and put the two "
                          "numbers in [numbers] or texts in [text] (the file stays local, it is gitignored)")
    with open(config_path, "rb") as handle:
        try:
            data = tomllib.load(handle)
        except tomllib.TOMLDecodeError as error:
            raise ConfigError(f"{config_path}: invalid TOML ({error})") from None
    return parse_config(data, source=config_path)
