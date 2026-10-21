r"""Tests of the local web UI (webui design 8, 9 "自动测试" items 1, 2 and 4), stdlib unittest only:

    .venv/bin/python -I -X utf8 tests/test_webui.py
    .venv\Scripts\python.exe -I -X utf8 tests\test_webui.py          (Windows)

All files go to one temporary folder (TISSUEPLATE_OUT_DIR, config paths, job roots), removed at the end: the project's
config.toml and out/ are never read or written. Only example numbers and test sentinels; an assertion on config
contents passes a short message, which (longMessage off) a failure prints instead of the compared values. Tests that
need fonts/MiSans-Bold.ttf skip without it; TISSUEPLATE_TEST_BUILD=1 adds a full build (about 4 min).
"""
import atexit
import contextlib
import dataclasses
import functools
import gc
import hashlib
import http.client
import io
import itertools
import json
import os
import queue
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import unittest
import warnings
import zipfile
from datetime import datetime
from pathlib import Path
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
TEMP = Path(tempfile.mkdtemp(prefix="tissueplate-test-"))
atexit.register(shutil.rmtree, TEMP, ignore_errors=True)                 # also when an import or a check below fails
os.environ["TISSUEPLATE_OUT_DIR"] = str(TEMP)                            # params.OUT_DIR is computed at import
sys.path.insert(0, str(PROJECT / "src"))                                 # python -I ignores the script folder

from tissueplate import bambu, config, params  # noqa: E402
from tissueplate.webui import api, faces, jobs, platform, schema, server  # noqa: E402

if params.OUT_DIR != TEMP.resolve():
    raise RuntimeError("tissueplate was imported before TISSUEPLATE_OUT_DIR was set: run this file directly")

EXAMPLE = {"a": "13800138000", "b": "13900139000"}                       # config.example.toml
SENTINEL, SPACED, SENTINEL_B = "13812345678", "138 1234 5678", "13912345678"
SENTINEL_FORMS = (SENTINEL, SPACED, "138-1234-5678", "1234 5678", "12345678")
CJK = re.compile(r"[\u4e00-\u9fff]")
POSIX = os.name == "posix"
needs_font = unittest.skipUnless(params.FONT_PATH.exists(), "fonts/MiSans-Bold.ttf is missing (see README)")
V33_STATE = {"numbers": dict(EXAMPLE), "display": {"logo": "final"}, "fit": dict.fromkeys(config.RETIRED["fit"], 6.0),
             "mount": {"pad_t": 0.5, "delta_up": 1.75, "tab_bottom": -40.0}}                # webui design 9 item 3
TEXT_STATE = {"numbers": {"a": EXAMPLE["a"]}, "text": {"b": 'say "hi" \\ 小米\t', "l": "小米汽车"},
              "display": {"logo": "none"}}
# the sentinel as a value, a key name, a section name; spaced in [text] and [display]: rejected, never echoed
BAD_STATES = ({"numbers": dict(EXAMPLE), "box": {"skirt": SENTINEL}}, {"numbers": dict(EXAMPLE), "box": {SENTINEL: 1}},
              {"numbers": dict(EXAMPLE), SENTINEL: {"x": 1}},
              {"numbers": {"a": EXAMPLE["a"]}, "text": {"b": SPACED}, "display": {"logo": SPACED}})
TEXT_STATES = ({"numbers": {"b": EXAMPLE["b"]}, "text": {"a": SPACED}},
               {"numbers": {"b": EXAMPLE["b"]}, "text": {"a": SENTINEL}})
# a config.toml as a user keeps it (sentinels, a retired key): the page reads it and saves what it read
SAVED = f'[numbers]\na = "{SENTINEL}"\n\n[text]\nb = "{SPACED}"\nl = "SU7 Ultra"\n\n[fit]\nfar_bore = 6.0\n'
# outputs of a fake job (config.toml is the "config" group, design 4.5) and files no download may name
OUTPUTS = ("build_log.txt", "config.toml", "parts/print/rotor.navy.stl", "plates/parking_plate.3mf",
           "renders/front.png", "report.md")
UNLISTED = ("job.json", ".tmp/scratch.txt", "plates/presets/process.json", "parts/config.toml")
CSP = ("default-src 'self'; img-src 'self' blob:; object-src 'none'; base-uri 'none'; form-action 'none'; "
       "frame-ancestors 'none'")                                         # webui design 5.2
LINK = {"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"}       # a click on a link to the page


# ---------------------------------------------------------------- helpers
def strings(value):
    """Every string of a JSON-like value, dict keys included."""
    if isinstance(value, dict):
        return [text for key, item in value.items() for text in strings(key) + strings(item)]
    if isinstance(value, (list, tuple)):
        return [text for item in value for text in strings(item)]
    return [value] if isinstance(value, str) else []


def leaked(value, forms=SENTINEL_FORMS):
    """True when one of forms shows in a string of value, as written or with its spaces and dashes removed."""
    return any(form in text or form in re.sub(r"[\s-]", "", text) for text in strings(value) for form in forms)


def mode(path):
    return path.stat().st_mode & 0o777


def wait_for(condition, timeout, step=0.05):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            return False
        time.sleep(step)
    return True


def alive(pid):
    try:
        os.kill(pid, 0)                    # signal 0 only asks whether the process exists
    except ProcessLookupError:
        return False
    return True


def process_gone(pid, timeout):
    """True when process pid has ended within timeout seconds."""
    timeout = max(0.0, timeout)
    if sys.platform != "win32":
        return wait_for(lambda: not alive(pid), timeout)
    import ctypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel32.OpenProcess(0x00100000, False, pid)              # SYNCHRONIZE
    if not handle:
        return True                                                    # no such process any more
    try:
        return kernel32.WaitForSingleObject(handle, int(timeout * 1000)) == 0      # WAIT_OBJECT_0
    finally:
        kernel32.CloseHandle(handle)


def example_state():
    return schema.from_toml(schema.EXAMPLE_PATH.read_text(encoding="utf-8"))[0]


def filled(state):
    """state as to_toml writes it: retired keys left out, every missing key at its default."""
    result = {section: {key: value for key, value in table.items() if key not in config.RETIRED.get(section, {})}
              for section, table in state.items()}
    for name, value in schema.defaults().items():
        section, key = name.split(".")
        result.setdefault(section, {}).setdefault(key, value)
    return result


def fake_job(root, job_id, state="ok", files=None, **saved):
    """A job folder: job.json ({"id", "state"} and saved) plus files {relative path: text}."""
    directory = root / job_id
    for relative, text in {"job.json": json.dumps({"id": job_id, "state": state, **saved}), **(files or {})}.items():
        (directory / relative).parent.mkdir(parents=True, exist_ok=True)
        (directory / relative).write_text(text, encoding="utf-8", newline="\n")      # LF on Windows too
    return directory


def saved_state(job):
    """The state in job.json (None while it is being written)."""
    try:
        return json.loads((job.dir / "job.json").read_text(encoding="utf-8")).get("state")
    except (OSError, ValueError):
        return None


def config_api(folder, path):
    """api.Api outside example mode on the config.toml at path; no Bambu Studio probe."""
    with mock.patch.object(bambu, "locate", side_effect=bambu.SlicerUnavailable("test")):
        return api.Api(folder / "jobs", example=False, config_path=path)


def read_lines(stream):
    """A queue of the lines of stream, then None at its end; a daemon thread fills it: get(timeout=...) never hangs."""
    lines = queue.Queue()

    def read():
        for line in stream:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=read, daemon=True).start()
    return lines


def http_request(port, token, method, path, body=None, headers=None, raw=None):
    """(status, lower-case headers, body) of a request to 127.0.0.1:port; a header given as None is left out."""
    sent = {"Host": f"127.0.0.1:{port}", "X-Plate-Token": token, **(headers or {})}
    data = raw
    if data is None and body is not None:
        data = json.dumps(body).encode("utf-8")
    if data is not None:
        sent.setdefault("Content-Type", "application/json")
        sent.setdefault("Content-Length", str(len(data)))
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=120)
    try:
        connection.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        for name, value in sent.items():
            if value is not None:
                connection.putheader(name, value)
        connection.endheaders(data)
        response = connection.getresponse()
        return response.status, {name.lower(): value for name, value in response.getheaders()}, response.read()
    finally:
        connection.close()


class Case(unittest.TestCase):
    # a failure prints the msg of the assertion when it has one, else the compared values: so every assertion that
    # compares config contents (states, TOML text, file bytes) passes a msg
    longMessage = False

    def new_folder(self):
        return Path(tempfile.mkdtemp(dir=TEMP))


# ---------------------------------------------------------------- 1 keys and the form schema
class KeysTest(Case):
    def test_keys_and_schema_rows(self):
        names = [f"{section}.{key}" for section, keys in config.SCHEMA.items() for key in keys]
        self.assertEqual(sorted(schema.KEYS), sorted(names))                       # none missing, none stale
        titles = [schema.KEYS[name][0] for name in names] + [schema.SECTION_TITLES[name][0] for name in config.SCHEMA]
        for title in titles:
            self.assertRegex(title, CJK)
        built = schema.build_schema()
        rows = [row for section in built["sections"] for row in section["keys"]]
        self.assertEqual([section["name"] for section in built["sections"]], list(config.SCHEMA))
        self.assertEqual([row["name"] for row in rows], names)                     # one row per key, in order
        defaults = {field.name: field.default for field in dataclasses.fields(params.Params)}
        for row in rows:
            field_name, kind, allowed = config.SCHEMA[row["name"].split(".")[0]][row["key"]]
            title, _, unit = schema.KEYS[row["name"]]
            with self.subTest(key=row["name"]):
                self.assertEqual((row["title"], row["unit"], row["kind"]), (title, unit, kind))
                self.assertEqual(row["default"], defaults[field_name])            # what an unwritten key takes
                if kind == "float":
                    self.assertEqual((row["min"], row["max"], row["step"] > 0), (*allowed, True))
                else:
                    self.assertTrue(row["choices"] and {choice["value"] for choice in row["choices"]} <= set(allowed))

    def test_tape_thickness(self):
        """The plates are taped (v3.4): pad_t 0.5 .. 1.5 mm, no magnets-only 0 (10-20); the v3.3 preset still works."""
        self.assertTrue(schema.validate(V33_STATE)["ok"], "the v3.3 preset (pad_t 0.5) is refused")
        for value in (0.0, 0.4, 1.6):
            state = {**V33_STATE, "mount": {**V33_STATE["mount"], "pad_t": value}}
            errors = [message["field"] for message in schema.validate(state)["messages"] if message["level"] == "error"]
            self.assertEqual(errors, ["mount.pad_t"], value)


# ---------------------------------------------------------------- 2 config.toml text
class TomlTest(Case):
    STATES = (("example", example_state()), ("v3.3", V33_STATE), ("text", TEXT_STATE))

    def test_round_trip(self):
        for name, state in self.STATES:
            with self.subTest(name):
                text = schema.to_toml(state)
                once = schema.from_toml(text)[0]
                self.assertEqual(once, filled(state), "the round trip changed the state")   # every key, none retired
                self.assertFalse(any(key in text for key in config.RETIRED["fit"]), "a retired key was written")
                again = schema.to_toml(once)
                self.assertEqual(schema.from_toml(again)[0], once, "the second round trip changed the state")
                self.assertEqual(again.splitlines()[1:], text.splitlines()[1:], "the second export differs")  # 1: time
        for text in ('say "hi"', "back\\slash \\n", "小米汽车 YU7", "tab\there", "\x01\x1f\x7f", "line\r\nbreak"):
            self.assertEqual(tomllib.loads("x = " + schema.toml_string(text))["x"], text, "toml_string changed a text")

    def test_unknown_names(self):
        for index, extra in enumerate(({"nope": {"x": 1}}, {"box": {"skirtt": 13.0}}, {SENTINEL: {"x": 1}},
                                       {"box": {SENTINEL: 1}})):
            with self.subTest(case=index):
                with self.assertRaises(config.ConfigError) as caught:
                    schema.to_toml({"numbers": dict(EXAMPLE), **extra})
                self.assertFalse(leaked(str(caught.exception)), "sentinel leaked")
        state, messages = schema.from_toml(f'[numbers]\na = "{EXAMPLE["a"]}"\nb = "{EXAMPLE["b"]}"\n'
                                           f'[box]\nskirtt = 13.62\n{SENTINEL_B} = 1\n[{SENTINEL_B}]\nx = 1\n')
        blocking = [message["text"] for message in messages if message.get("blocks_save")]
        self.assertEqual(len(blocking), 1)
        self.assertTrue("skirtt" in blocking[0] and schema.REDACTED in blocking[0], "the names are not shown masked")
        self.assertFalse(leaked(messages, (SENTINEL_B, "12345678")), "sentinel leaked")
        self.assertEqual(state, {"numbers": EXAMPLE, "box": {}}, "unknown names kept in the state")

    @needs_font
    def test_parse_config_unchanged(self):
        for name, state in self.STATES:
            with self.subTest(name):
                before = config.parse_config(state)
                after = config.parse_config(schema.from_toml(schema.to_toml(state))[0])
                self.assertEqual(params.make_params(before.overrides), params.make_params(after.overrides),
                                 "the parameters changed")
                self.assertEqual([before.number_a, before.number_b, before.text_a, before.text_b, before.text_l],
                                 [after.number_a, after.number_b, after.text_a, after.text_b, after.text_l],
                                 "the faces changed")


# ---------------------------------------------------------------- 3 save rules
class SaveTest(Case):
    def setUp(self):
        self.path = self.new_folder() / "config.toml"
        self.original, self.state = self.path.with_name("config.toml.orig.bak"), {"numbers": dict(EXAMPLE)}

    def names(self):
        return sorted(path.name for path in self.path.parent.iterdir())

    def stamped(self):
        return sorted(self.path.parent.glob("config.toml.[0-9]*.bak"))

    def test_first_save(self):
        sha = schema.save_config(self.state, None, path=self.path)
        self.assertEqual(sha, schema.sha256_of(self.path))
        self.assertEqual(self.names(), ["config.toml"])                          # nothing to back up
        self.assertEqual(schema.read_config(self.path)["state"], filled(self.state), "the saved state differs")
        if POSIX:
            self.assertEqual(mode(self.path), 0o600)

    def test_conflicts_and_backups(self):
        old = f'[numbers]\na = "{EXAMPLE["a"]}"\nb = "{EXAMPLE["b"]}"\n'.encode("utf-8")
        self.path.write_bytes(old)
        for expected, overwrite, status in ((None, False, 428), ("0" * 64, False, 409), ("0" * 64, True, 409)):
            with self.subTest(expected=expected, overwrite=overwrite):
                with self.assertRaises(schema.SaveConflict) as caught:
                    schema.save_config(self.state, expected, overwrite=overwrite, path=self.path)
                self.assertEqual(caught.exception.status, status)
                self.assertEqual(self.path.read_bytes(), old, "config.toml changed")
                self.assertEqual(self.names(), ["config.toml"])                  # no backup either
        sha = schema.save_config(self.state, None, overwrite=True, path=self.path)
        self.assertEqual([path.read_bytes() for path in [self.original, *self.stamped()]], [old, old],
                         "not one .orig.bak and one stamped backup of the old file")
        swapped = {"numbers": {"a": EXAMPLE["b"], "b": EXAMPLE["a"]}}
        schema.save_config(swapped, sha, path=self.path)
        self.assertEqual(schema.read_config(self.path)["state"]["numbers"], swapped["numbers"], "not saved")
        self.assertEqual(self.original.read_bytes(), old, ".orig.bak was written again")    # by the first save only
        if POSIX:
            self.assertEqual({mode(path) for path in [self.path, self.original, *self.stamped()]}, {0o600})

    def test_saves_in_one_second(self):
        """Stamped backups are named to the microsecond: two saves in one second keep both old versions."""
        self.path.write_text("# first\n", encoding="utf-8", newline="\n")
        ticks = itertools.count(1)                     # each clock read one microsecond later, all in one second
        clock = mock.Mock(now=lambda: datetime(2026, 1, 1, 12, 0, 0, next(ticks)))
        with mock.patch.object(schema, "datetime", clock):
            sha = schema.save_config(self.state, schema.sha256_of(self.path), path=self.path)
            first = self.path.read_bytes()
            schema.save_config({"numbers": {"a": EXAMPLE["b"], "b": EXAMPLE["a"]}}, sha, path=self.path)
        self.assertEqual([path.read_bytes() for path in self.stamped()], [b"# first\n", first],
                         "a stamped backup was overwritten")

    def test_backups_kept(self):
        self.path.write_text("# old\n", encoding="utf-8", newline="\n")
        old = [self.path.with_name(f"config.toml.2000-0101-00000{n}-000000.bak") for n in range(1, 7)]
        for path in old:
            path.write_text("# older\n", encoding="utf-8", newline="\n")
        schema.save_config(self.state, schema.sha256_of(self.path), path=self.path)
        kept = self.stamped()                          # 6 old + 1 new, 5 kept: the two oldest went, the new one last
        self.assertEqual(len(kept), schema.BACKUPS_KEPT)
        self.assertEqual(kept[:-1], old[2:])

    def test_failed_replace_keeps_the_file(self):
        self.path.write_text("# old\n", encoding="utf-8", newline="\n")
        with mock.patch.object(schema.os, "replace", side_effect=OSError("simulated")), self.assertRaises(OSError):
            schema.save_config(self.state, schema.sha256_of(self.path), path=self.path)
        self.assertEqual(self.path.read_bytes(), b"# old\n", "config.toml changed")
        self.assertEqual(len(list(self.path.parent.glob("config.toml.tmp-*"))), 1)
        schema.remove_stale_temp(self.path)
        self.assertEqual(list(self.path.parent.glob("config.toml.tmp-*")), [])


# ---------------------------------------------------------------- 4 /api/config outside example mode
class ConfigApiTest(Case):
    """api.Api on a temporary config.toml (webui design 3.3, 9 item 1)."""

    def setUp(self):
        self.folder = self.new_folder()
        self.path, self.stale = self.folder / "config.toml", self.folder / "config.toml.tmp-0a1b2c3d"
        self.path.write_text(SAVED, encoding="utf-8", newline="\n")
        self.stale.write_text("# a save that stopped halfway\n", encoding="utf-8", newline="\n")
        self.api = config_api(self.folder, self.path)

    def call(self, name, argument):
        """(status, reply) of an endpoint; a refusal gives its status and {"error": text}."""
        try:
            return getattr(self.api, name)(argument)
        except api.HttpError as error:
            return error.status, {"error": error.text}

    def test_read(self):
        self.assertFalse(self.stale.exists(), "the temp file of an old save is still there")     # Api() removes it
        self.assertTrue(self.call("status", {})[1]["config_exists"])
        status, reply = self.call("config_read", {})
        self.assertEqual((status, reply["source"]), (200, "config.toml"))
        # the form gets the file as it is (it once got •••) and its sha256: only the messages are redacted
        self.assertEqual(reply["state"], tomllib.loads(SAVED), "the state is not the file's")
        self.assertEqual(reply["sha256"], hashlib.sha256(self.path.read_bytes()).hexdigest(), "not the file's sha256")
        self.assertIn("fit.far_bore", [message["field"] for message in reply["messages"]])      # retired: a warning
        self.assertFalse(leaked(reply["messages"], SENTINEL_FORMS + ("SU7 Ultra", "SU7Ultra")), "sentinel leaked")
        self.path.write_text(SAVED + '\n[box]\n"SU7 Ultra" = 1\n', encoding="utf-8", newline="\n")   # a text as a key
        messages = self.call("config_read", {})[1]["messages"]
        self.assertFalse(leaked(messages, ("SU7 Ultra", "SU7Ultra")), "the text is in the messages")
        self.path.unlink()
        self.assertEqual(self.call("config_read", {})[0], 404)
        self.assertFalse(self.call("status", {})[1]["config_exists"])

    def test_read_then_save(self):
        reply = self.call("config_read", {})[1]
        state, original = reply["state"], tomllib.loads(SAVED)
        status, saved = self.call("config_save", {"state": state, "sha256": reply["sha256"]})
        self.assertEqual(status, 200)
        self.assertEqual(saved["sha256"], schema.sha256_of(self.path))
        written = tomllib.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual((written["numbers"], written["text"]), (original["numbers"], original["text"]),
                         "the numbers or texts changed")
        current = saved["sha256"]
        for name, changes, sha, expected in (
                ("stale sha256", {}, reply["sha256"], 409), ("never read", {}, None, 428),
                ("unknown key", {"box": {"skirtt": 13.0}}, current, 422),
                ("redacted number", {"numbers": {"a": schema.REDACTED}}, current, 422),
                ("redacted text", {"text": {"b": f"138 {schema.REDACTED}"}}, current, 422),
                ("number not a string", {"numbers": {"a": int(SENTINEL)}}, current, 422),
                ("empty number box", {"box": {"skirt": None}}, current, 422),        # the page sends NaN as null
                ("number in a number box", {"box": {"skirt": SPACED}}, current, 422),
                ("text in a whole-number box", {"display": {"white_layers": SPACED}}, current, 422)):
            with self.subTest(name):
                before = sorted(self.folder.iterdir()), self.path.read_bytes()
                status, refused = self.call("config_save", {"state": {**state, **changes}, "sha256": sha})
                self.assertEqual(status, expected)
                self.assertEqual((sorted(self.folder.iterdir()), self.path.read_bytes()), before,
                                 "config.toml or a backup was written")
                self.assertFalse(leaked(refused), "sentinel leaked")
        before = self.path.read_bytes()
        self.assertEqual(self.call("config_save", {"state": state, "sha256": None, "overwrite": True})[0], 200)
        self.assertEqual(sorted(self.folder.glob("config.toml.[0-9]*.bak"))[-1].read_bytes(), before,
                         "no backup of the overwritten file")
        self.assertEqual(self.path.with_name("config.toml.orig.bak").read_text(encoding="utf-8"), SAVED,
                         ".orig.bak is not the file as the user had it")


# ---------------------------------------------------------------- 5 redaction
class RedactionTest(Case):
    def test_validate_and_from_toml(self):
        for index, state in enumerate(BAD_STATES):
            result = schema.validate(state)
            self.assertFalse(result["ok"], f"bad state {index} accepted")
            self.assertFalse(leaked(result), f"bad state {index}: sentinel leaked")
        for index, state in enumerate(TEXT_STATES):
            self.assertFalse(leaked(schema.validate(state)), f"text state {index}: sentinel leaked")
        texts = (f'[numbers]\na = "{EXAMPLE["a"]}"\nb = "{EXAMPLE["b"]}"\n[box]\nskirt = "{SENTINEL}"\n{SENTINEL} = 1\n'
                 f'[{SENTINEL}]\nx = 1\n', f'[numbers]\nb = "{EXAMPLE["b"]}"\n[text]\na = "{SPACED}"\n',
                 f'[numbers]\na = "{SENTINEL}\n')                                  # not TOML: line and column only
        for index, text in enumerate(texts):
            self.assertFalse(leaked(schema.from_toml(text)[1]), f"TOML text {index}: sentinel leaked")

    def test_redact(self):
        for text in (SENTINEL, SPACED, "138-1234-5678", "138 (1234) 5678", SENTINEL[:7]):
            self.assertEqual(schema.redact(f"x {text} y"), f"x {schema.REDACTED} y", "digit run not masked")
        self.assertEqual(schema.redact(f"x {SENTINEL[:6]} y"), f"x {SENTINEL[:6]} y", "six digits masked")
        self.assertEqual(schema.redact("my SU7 Ultra!", ["SU7 Ultra"]), f"my {schema.REDACTED}!", "text not masked")

    def test_job_log_lines(self):
        root, job_id = self.new_folder(), "2026-0101-000000-abcd"
        wrote = f"wrote out/web/{job_id}/report.md"
        fake_job(root, job_id, files={
            "config.toml": f'[numbers]\na = "{SENTINEL}"\n[text]\nb = "{SPACED}"\nl = "SU7 Ultra"\n',
            "build_log.txt": f"a {SENTINEL}\nb {SPACED}\nc 138-1234-5678\nl SU7 Ultra\n{wrote} for {SENTINEL}\n"})
        lines = [text for _, text in jobs.JobManager(root).get(job_id).log_lines(0)]
        self.assertEqual(len(lines), 5)
        self.assertFalse(leaked(lines, SENTINEL_FORMS + ("SU7 Ultra", "SU7Ultra")), "sentinel leaked")
        self.assertEqual(lines[4], f"{wrote} for {schema.REDACTED}", "the job id or the number")    # the id: kept


# ---------------------------------------------------------------- 6 jobs: recovery, retention, ids, outputs
class JobsTest(Case):
    def outputs(self):
        root = self.new_folder()
        directory = fake_job(root, "2026-0101-000000-abcd", files={name: name for name in OUTPUTS + UNLISTED[1:]})
        manager = jobs.JobManager(root)
        return manager, manager.get(directory.name)

    def test_restart(self):
        """After a server restart a running job is interrupted; created and elapsed come back from job.json."""
        root = self.new_folder()
        directory = fake_job(root, "2026-0101-000000-abcd", "running", created="2026-01-01T00:00:00", elapsed=12.5)
        summary = jobs.JobManager(root).get(directory.name).summary()
        saved = json.loads((directory / "job.json").read_text(encoding="utf-8"))
        for row in (summary, saved):
            self.assertEqual((row["state"], row["created"], row["elapsed"]),
                             ("interrupted", "2026-01-01T00:00:00", 12.5))

    def test_broken_job_json(self):
        """A job.json that is not a table or has a bad time: that job is left out, the server still starts."""
        root, good = self.new_folder(), "2026-0101-000000-abcd"
        fake_job(root, good)
        for job_id, saved in (("2026-0101-000001-abcd", {"created": "yesterday"}),
                              ("2026-0101-000002-abcd", {"stage_times": {"x": 1.0}}),
                              ("2026-0101-000003-abcd", {"stage_times": [1.0]}),
                              ("2026-0101-000005-abcd", {"created": 5}),
                              ("2026-0101-000006-abcd", {"created": "0001-01-01T00:00:00+14:00"}),    # year 0 here
                              ("2026-0101-000007-abcd", {"created": "9999-12-31T23:59:59-14:00"}),    # year 10000
                              ("2026-0101-000008-abcd", {"elapsed": float("nan")})):                  # NaN in JSON
            fake_job(root, job_id, "running", **saved)
        listed = fake_job(root, "2026-0101-000004-abcd") / "job.json"
        listed.write_text("[1, 2]", encoding="utf-8", newline="\n")
        (root / "2026-0101-000009-abcd").mkdir()                        # start() stopped before job.json
        for job_id, raw in (("2026-0101-000010-abcd", '{"state": "ok", "elapsed": 1e400}'),          # read as inf
                            ("2026-0101-000011-abcd", '{"state": ' + "[" * 100000 + "]" * 100000 + "}")):
            (fake_job(root, job_id) / "job.json").write_text(raw, encoding="utf-8", newline="\n")
        manager = jobs.JobManager(root)                       # a bad "created" once stopped the API from loading
        self.assertEqual([row["id"] for row in manager.list()], [good])

    def test_prune(self):
        root = self.new_folder()
        manager = jobs.JobManager(root, keep=2)
        ids = [f"2026-0101-00000{n}-abcd" for n in range(1, 6)]
        for job_id, state in zip(ids, ("running", "ok", "failed", "cancelled", "ok")):
            fake_job(root, job_id, state)
        manager.prune()
        self.assertEqual(manager.ids(), [ids[4], ids[3], ids[0]])         # the newest two finished, the running one
        self.assertFalse(manager.delete(ids[0]))

    def test_get_rejects_other_ids(self):
        root, valid = self.new_folder(), "2026-0101-000000-abcd"
        for name in (valid, valid + "0", "2026-0101-0000001-abcd", "x"):     # x: reached as <valid>/../x
            fake_job(root, name)
        manager = jobs.JobManager(root)
        self.assertEqual(manager.ids(), [valid])
        self.assertIsNotNone(manager.get(valid))
        for job_id in (valid + "0", f"{valid}/../x", "2026-0101-0000001-abcd", "../x", f"../{valid}", valid.upper(),
                       "", None):
            self.assertIsNone(manager.get(job_id), repr(job_id))

    def test_resolve(self):
        manager, job = self.outputs()
        for relative in OUTPUTS:
            self.assertEqual(manager.resolve(job, relative), (job.dir / relative).resolve(), relative)
        for relative in ("../report.md", "plates/../report.md", "./report.md", "/etc/passwd",
                         str(job.dir / "report.md"), "plates\\parking_plate.3mf", "report.md\x00",
                         "plates//parking_plate.3mf", "report.md/", "renders/", "", None) + UNLISTED:
            self.assertIsNone(manager.resolve(job, relative), repr(relative))

    def test_links(self):
        """A linked file, and a linked folder that leads out of the job folder: not listed, served or zipped."""
        manager, job = self.outputs()
        outside = self.new_folder()
        (outside / "secret.stl").write_text("outside", encoding="utf-8", newline="\n")
        try:
            (job.dir / "renders" / "zz_link.png").symlink_to(job.dir / "config.toml")
            (job.dir / "parts" / "assembled").symlink_to(outside, target_is_directory=True)     # group "assembly"
        except OSError:
            self.skipTest("symlinks are not available here")
        linked = ("renders/zz_link.png", "parts/assembled/secret.stl")
        self.assertFalse(set(linked) & {row["path"] for row in manager.files(job)}, "a link is listed")
        for relative in linked:
            self.assertIsNone(manager.resolve(job, relative), relative)
        handle, _ = manager.zip_file(job, {group for group, _, _ in jobs.GROUPS})
        with handle, zipfile.ZipFile(handle) as archive:
            self.assertFalse([name for name in archive.namelist() if name.endswith(linked)], "a link is zipped")
        listed = [{"path": linked[1], "size": 7, "group": "assembly"}]
        with mock.patch.object(manager, "files", return_value=listed):         # resolve()'s own last check
            self.assertIsNone(manager.resolve(job, linked[1]))

    def test_files_and_zip(self):
        manager, job = self.outputs()
        rows = manager.files(job)
        self.assertEqual(sorted(row["path"] for row in rows), sorted(OUTPUTS))
        self.assertLessEqual({row["group"] for row in rows}, {group for group, _, _ in jobs.GROUPS})
        handle, size = manager.zip_file(job, {"3mf", "report"})
        with handle, zipfile.ZipFile(handle) as archive:
            self.assertEqual(sorted(archive.namelist()), [f"{job.id}/plates/parking_plate.3mf", f"{job.id}/report.md"])
        self.assertGreater(size, 0)


# ---------------------------------------------------------------- 7 build lifecycle with a stand-in build
GRANDCHILD = ("import os, signal, time\nif os.name == 'posix':\n    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
              "print('ready', flush=True)\ntime.sleep(60)\n")
SLEEPER = ("import os, subprocess, sys, time\n"
           f"grandchild = subprocess.Popen([sys.executable, '-I', '-c', {GRANDCHILD!r}], stdout=subprocess.PIPE)\n"
           "grandchild.stdout.readline()\nprint('pids', os.getpid(), grandchild.pid, flush=True)\ntime.sleep(60)\n")


def stages_then_exit(code):
    return f"import sys\nfor n in (1, 2, 3):\n    print('[stage %d/7] step' % n, flush=True)\nsys.exit({code})\n"


class ScriptJobs(jobs.JobManager):
    """JobManager whose build is a short Python script instead of build_all.py."""
    script = ""

    def command(self, job):
        return [sys.executable, "-I", "-c", self.script]


class BuildLifecycleTest(Case):
    def start(self, script):
        manager = ScriptJobs(self.new_folder())
        manager.script = script
        self.addCleanup(manager.stop_all)
        return manager, manager.start("# stand-in build\n")

    def test_exit_codes(self):
        for code, state in ((3, "unsliced"), (4, "crashed")):
            with self.subTest(code=code):
                manager, job = self.start(stages_then_exit(code))
                self.assertTrue(wait_for(lambda: saved_state(job) not in (None, *jobs.RUNNING), 30), "no end")
                saved = json.loads((job.dir / "job.json").read_text(encoding="utf-8"))
                self.assertEqual(saved["state"], state)
                self.assertEqual(saved["exit_code"], code)
                self.assertEqual(saved["stage"], 3)
                self.assertEqual(sorted(saved["stage_times"]), ["1", "2", "3"])
                self.assertEqual((job.state, sorted(job.stage_times)), (state, [1, 2, 3]))
                self.assertEqual((job.dir / "build_log.txt").read_text(encoding="utf-8").splitlines(),
                                 [f"[stage {n}/7] step" for n in (1, 2, 3)])
                reloaded = jobs.JobManager(job.dir.parent).get(job.id).summary()      # as after a server restart
                self.assertEqual(reloaded["created"], job.summary()["created"])
                self.assertEqual(reloaded["elapsed"], job.summary()["elapsed"])
                if POSIX:
                    self.assertEqual([mode(job.dir / name) for name in ("build_log.txt", "job.json", "config.toml")]
                                     + [mode(job.dir)], [0o600, 0o600, 0o600, 0o700])

    def test_no_resource_warning(self):
        """A finished build leaves no pipe or file open: an unclosed one warns when it is collected."""
        gc.collect()                                   # garbage of earlier tests is not this one's
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ResourceWarning)
            manager = ScriptJobs(self.new_folder())
            manager.script = stages_then_exit(0)
            job = manager.start("# stand-in build\n")
            ended = wait_for(lambda: saved_state(job) == "ok" and not [     # and its thread ("Thread-N (_run)") ended
                thread for thread in threading.enumerate() if thread.name.endswith("(_run)")], 30)
            del manager, job                           # the last references: the build's objects go here
            gc.collect()
        self.assertTrue(ended, "the stand-in build did not end")
        self.assertEqual([str(item.message) for item in caught if issubclass(item.category, ResourceWarning)], [])

    def test_cancel_stops_the_whole_build(self):
        manager, job = self.start(SLEEPER)
        started = wait_for(lambda: any(text.startswith("pids ") for _, text in job.lines), 30)
        self.assertTrue(started, "the stand-in build did not start")
        pids = {job.process.process.pid} | {int(value) for _, text in job.lines if text.startswith("pids ")
                                            for value in text.split()[1:]}
        with self.assertRaises(jobs.Busy):
            manager.start("# a second build\n")
        cancelled = time.monotonic()
        self.assertTrue(manager.cancel(job.id))
        for pid in sorted(pids):
            gone = process_gone(pid, cancelled + platform.STOP_WAIT + 5 - time.monotonic())
            self.assertTrue(gone, "a process of the cancelled build lives on")
        self.assertTrue(wait_for(lambda: saved_state(job) == "cancelled", 10), "not saved as cancelled")


# ---------------------------------------------------------------- 8 platform.py as on macOS, Windows and Linux
@contextlib.contextmanager
def system(name, environment=None):
    """platform.py as on "mac", "windows" or "linux": only environment in os.environ, _start recorded (nothing runs)."""
    with mock.patch.object(platform, "IS_WINDOWS", name == "windows"), \
            mock.patch.object(platform, "IS_MAC", name == "mac"), \
            mock.patch.dict(os.environ, environment or {}, clear=True), \
            mock.patch.object(platform, "_start") as start:
        yield start


class PlatformTest(Case):
    def test_build_environment(self):
        job, temp = TEMP / "job", str(TEMP / "job" / ".tmp")
        shell = {"PATH": "/usr/bin", "HOME": "/home/test", "SystemRoot": "C:\\Windows",
                 "USERPROFILE": "C:\\Users\\test", "DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0",
                 "XDG_RUNTIME_DIR": "/run/user/1000", "GITHUB_TOKEN": "fake-token",
                 "TISSUEPLATE_BAMBU_STUDIO": "/opt/bs", "TISSUEPLATE_BAMBU_PROFILES": "/opt/p",
                 "XDG_CACHE_HOME": "/home/test/c", "MPLCONFIGDIR": "/home/test/m"}
        ours = {"PATH": "/usr/bin", "TISSUEPLATE_BAMBU_STUDIO": "/opt/bs", "TISSUEPLATE_BAMBU_PROFILES": "/opt/p",
                "XDG_CACHE_HOME": "/home/test/c", "MPLCONFIGDIR": "/home/test/m",       # the user's cache folders
                "TISSUEPLATE_OUT_DIR": str(job), "OPENBLAS_NUM_THREADS": "1", "TMPDIR": temp}
        windows = {**ours, "SystemRoot": "C:\\Windows", "USERPROFILE": "C:\\Users\\test", "TEMP": temp, "TMP": temp}
        mac = {**ours, "HOME": "/home/test", "LANG": "en_US.UTF-8"}
        linux = {**mac, "DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0", "XDG_RUNTIME_DIR": "/run/user/1000"}
        for name, expected in (("windows", windows), ("mac", mac), ("linux", linux)):
            with self.subTest(system=name), system(name, shell):
                self.assertEqual(platform.build_environment(job), expected)       # GITHUB_TOKEN and the rest stay out
        with system("linux", {"LANG": "C.UTF-8"}):
            self.assertEqual(platform.build_environment(job)["LANG"], "C.UTF-8")

    def test_file_manager_and_bambu(self):
        path, app, cli = Path("/x/plates/parking_plate.3mf"), Path("/Applications/BambuStudio.app"), Path("/opt/bs/bs")
        for name, function, argument, command in (
                ("mac", platform.reveal, path, ["open", "-R", str(path)]),
                ("windows", platform.reveal, path, ["explorer", f"/select,{path}"]),
                ("mac", platform.open_folder, path.parent, ["open", str(path.parent)]),
                ("windows", platform.open_folder, path.parent, ["explorer", str(path.parent)])):
            with self.subTest(system=name, function=function.__name__), system(name) as start:
                self.assertTrue(function(argument))
                start.assert_called_once_with(command)
        for name, binary, command in (("mac", app / "Contents/MacOS/BambuStudio", ["open", "-a", str(app), str(path)]),
                                      ("mac", cli, [str(cli), str(path)]), ("windows", cli, [str(cli), str(path)]),
                                      ("linux", cli, [str(cli), str(path)])):
            with self.subTest(system=name, cli=str(binary)), system(name) as start:
                platform.open_in_bambu(binary, path)
                start.assert_called_once_with(command)

    def test_linux_file_manager(self):
        folder = Path("/x/plates")
        with system("linux"), mock.patch.object(platform, "open_folder", return_value=False) as open_folder:
            self.assertFalse(platform.reveal(folder / "parking_plate.3mf"))             # Linux: open the folder
            open_folder.assert_called_once_with(folder)
        converted = subprocess.CompletedProcess([], 0, stdout="C:\\x\\plates\n")
        with system("linux") as start, mock.patch.object(platform, "is_wsl", return_value=True), \
                mock.patch.object(platform.shutil, "which", return_value="/usr/bin/found"), \
                mock.patch.object(platform.subprocess, "run", return_value=converted) as run:
            self.assertTrue(platform.open_folder(folder))
            run.assert_called_once_with(["wslpath", "-w", str(folder)], capture_output=True, text=True)
            start.assert_called_once_with(["explorer.exe", "C:\\x\\plates"])
        for environment, found, command in (({"DISPLAY": ":0"}, "/usr/bin/xdg-open", ["xdg-open", str(folder)]),
                                            ({}, "/usr/bin/xdg-open", None),      # no desktop (SSH): it would fail
                                            ({"DISPLAY": ":0"}, None, None)):     # nothing to open it with
            with self.subTest(environment=environment, found=found), system("linux", environment) as start, \
                    mock.patch.object(platform, "is_wsl", return_value=False), \
                    mock.patch.object(platform.shutil, "which", return_value=found):
                self.assertEqual(platform.open_folder(folder), command is not None)
                self.assertEqual(start.call_args_list, [mock.call(command)] if command else [])

    def test_open_browser(self):
        url = "http://127.0.0.1:1/#token=test"
        for name, environment, opened in (("linux", {}, False), ("linux", {"DISPLAY": ":0"}, True),
                                          ("linux", {"WAYLAND_DISPLAY": "wayland-0"}, True), ("mac", {}, True)):
            with self.subTest(system=name, environment=environment), system(name, environment), \
                    mock.patch.object(platform.webbrowser, "open", return_value=True) as browser:
                self.assertEqual(platform.open_browser(url), opened)
                self.assertEqual(browser.call_args_list, [mock.call(url)] if opened else [])

    def test_private_folder_warning(self):
        home = TEMP / "home"
        with system("mac", {"USERPROFILE": str(home)}):
            self.assertIsNone(platform.private_folder_warning(TEMP / "elsewhere"))
        with system("windows", {"USERPROFILE": str(home)}):
            self.assertIsNone(platform.private_folder_warning(home / "project"))
            self.assertRegex(platform.private_folder_warning(TEMP / "elsewhere"), CJK)

    def test_peak_memory(self):
        with mock.patch.dict(sys.modules, {"resource": None}):
            self.assertIsNone(platform.peak_memory_mb())                       # Windows: not shown
        if POSIX:
            memory = platform.peak_memory_mb()
            self.assertEqual(sorted(memory), ["builds", "server"])
            self.assertTrue(10 < memory["server"] < 100_000, "the peak is not in MB")   # this process: build123d
            self.assertTrue(isinstance(memory["builds"], int) and 0 <= memory["builds"] < 100_000,
                            "the peak of the builds is not in MB")

    @unittest.skipUnless(POSIX, "0600 / 0700 do nothing on Windows")
    def test_private_modes(self):
        folder = platform.make_private_dir(self.new_folder() / "a" / "b")
        with platform.open_private(folder / "f.txt") as handle:
            handle.write("x")
        self.assertEqual([mode(folder), mode(folder / "f.txt")], [0o700, 0o600])
        with self.assertRaises(FileExistsError):
            platform.open_private(folder / "f.txt", exclusive=True)


# ---------------------------------------------------------------- 9 the server, in this process
class ServerTest(Case):
    """server.serve() without its printing and signal handlers: example mode, no Bambu Studio, jobs in TEMP."""

    @classmethod
    def setUpClass(cls):
        cls.httpd = server.Server(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.app = server.App(cls.port, secrets.token_urlsafe(32), False)
        server.Handler.app = cls.app
        cls.jobs_root, cls.job_id = TEMP / "server-jobs", "2026-0101-000000-abcd"
        fake_job(cls.jobs_root, cls.job_id, files={
            "report.md": "# report\n", "plates/parking_plate.3mf": "3mf", "parts/print/rotor.navy.stl": "stl",
            "config.toml": f'[numbers]\na = "{SENTINEL}"\n', "build_log.txt": f"[stage 1/7] x\nnumber {SENTINEL}\n"})
        with mock.patch.object(bambu, "locate", side_effect=bambu.SlicerUnavailable("test")), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            # config_path in TEMP: a regression of example mode must not write the project's config.toml
            with mock.patch.object(api, "Api", functools.partial(api.Api, config_path=TEMP / "server-config.toml")):
                cls.app.load(cls.jobs_root, 5, True)                           # its terminal lines: ServeTest
        if cls.app.api is None:
            cls.httpd.server_close()
            raise RuntimeError(f"the API did not load: {cls.app.failed}")
        cls.no_gui = mock.patch.object(platform, "_start")          # no request may open a file manager or Bambu
        cls.gui = cls.no_gui.start()
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(5)
        cls.no_gui.stop()

    def request(self, method, path, body=None, headers=None, raw=None):
        return http_request(self.port, self.app.token, method, path, body, headers, raw)

    def status(self, *args, **kwargs):
        return self.request(*args, **kwargs)[0]

    def reply_of(self, *args, **kwargs):
        status, _, payload = self.request(*args, **kwargs)
        return status, json.loads(payload)

    def test_host_token_origin(self):
        port, page = self.port, f"http://127.0.0.1:{self.port}"
        for name, path, headers, expected in (
                ("no token", "/api/status", {"X-Plate-Token": None}, 403),
                ("wrong token", "/api/status", {"X-Plate-Token": "x" * 43}, 403),
                ("token in the query only", f"/api/status?token={self.app.token}", {"X-Plate-Token": None}, 403),
                ("right token", "/api/status", {}, 200), ("no Host", "/api/status", {"Host": None}, 403),
                ("foreign Host", "/api/status", {"Host": f"evil.example:{port}"}, 403),
                ("foreign Host, page", "/", {"Host": f"evil.example:{port}"}, 403),
                ("other port", "/api/status", {"Host": "127.0.0.1:1"}, 403),
                ("localhost", "/api/status", {"Host": f"localhost:{port}"}, 200),
                ("foreign Origin", "/api/status", {"Origin": "http://evil.example"}, 403),
                ("own Origin", "/api/status", {"Origin": page}, 200),
                ("cross-site", "/api/status", {"Sec-Fetch-Site": "cross-site"}, 403),
                ("cross-site page", "/", {"Sec-Fetch-Site": "cross-site"}, 403),
                ("same-site", "/api/status", {"Sec-Fetch-Site": "same-site"}, 403),     # a page on another port
                ("same-site page", "/", {"Sec-Fetch-Site": "same-site"}, 403),
                ("same-origin", "/api/status", {"Sec-Fetch-Site": "same-origin"}, 200),
                ("typed or pasted link", "/", {"Sec-Fetch-Site": "none"}, 200),
                ("link in another page", "/", {**LINK, "Sec-Fetch-Site": "cross-site"}, 200),     # decided 10-20
                ("link in another page, same-site", "/", {**LINK, "Sec-Fetch-Site": "same-site"}, 200),
                ("link to the API", "/api/status", {**LINK, "Sec-Fetch-Site": "cross-site"}, 403),
                ("link to the script", "/app.js", {**LINK, "Sec-Fetch-Site": "cross-site"}, 403),
                ("page in a frame", "/", {**LINK, "Sec-Fetch-Site": "cross-site", "Sec-Fetch-Dest": "iframe"}, 403),
                ("page fetched", "/", {**LINK, "Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "no-cors"}, 403)):
            with self.subTest(name):
                self.assertEqual(self.status("GET", path, headers=headers), expected)
        self.assertEqual(self.status("POST", "/api/validate", raw=b"", headers={"Origin": "http://evil.example"}), 403)

    def test_bodies(self):
        # refused before the body is read: none is sent (an unread body may turn the close into a reset)
        json_type = {"Content-Type": "application/json"}
        for name, headers, raw, expected in (
                ("form", {"Content-Type": "application/x-www-form-urlencoded"}, b"", 415),
                ("text/plain", {"Content-Type": "text/plain"}, b"", 415), ("no length", json_type, None, 411),
                ("chunked", {**json_type, "Transfer-Encoding": "chunked"}, None, 411),
                ("3 MB", {"Content-Length": str(3 * 1024 * 1024)}, b"", 413), ("not JSON", {}, b"{nope", 400),
                ("a list", {}, b"[]", 400), ("state not an object", {}, b'{"state": []}', 400),
                ("nested too deep", {}, b"[" * 50000 + b"]" * 50000, 400)):
            with self.subTest(name), contextlib.redirect_stderr(io.StringIO()) as terminal:
                self.assertEqual(self.status("POST", "/api/validate", headers=headers, raw=raw), expected)
                self.assertEqual(terminal.getvalue(), "", "a traceback in the terminal")
        for face, state, expected in (("A", {"display": "x"}, 400), ("A", {"text": {"a": 5}}, 422),
                                      ("L", {"text": {"l": 5}}, 422)):        # not a table; not a string
            with self.subTest(face=face, state=state):
                self.assertEqual(self.status("POST", "/api/preview", {"face": face, "state": state}), expected)

    def test_methods_paths_headers(self):
        for method in ("OPTIONS", "PUT", "DELETE", "PATCH"):
            status, headers, _ = self.request(method, "/api/build", headers={"Origin": "http://evil.example",
                                                                             "Access-Control-Request-Method": "POST"})
            self.assertEqual((status, [name for name in headers if name.startswith("access-control")]), (405, []))
        for path in ("/api/nope", "/../../config.example.toml", "/../schema.py", "/%2e%2e/%2e%2e/config.example.toml",
                     "/static/app.js", "/app.js/../../schema.py", "/index.html", "/config.toml",
                     "/api/jobs/..%2F..%2Fsrc", "/api/jobs/2026-1019-121045-zzzz/files"):
            self.assertEqual(self.status("GET", path), 404, path)
        status, headers, _ = self.request("GET", "/")
        self.assertEqual((status, headers["content-security-policy"], headers["cache-control"]), (200, CSP, "no-cache"))
        self.assertEqual([headers[name] for name in ("x-content-type-options", "referrer-policy", "x-frame-options")],
                         ["nosniff", "no-referrer", "DENY"])
        for path, content_type in (("/app.js", "text/javascript"), ("/style.css", "text/css")):
            status, headers, _ = self.request("GET", path)
            self.assertEqual((status, headers["content-type"]), (200, f"{content_type}; charset=utf-8"), path)
        status, headers, payload = self.request("GET", "/api/schema")
        self.assertEqual((status, headers["cache-control"]), (200, "no-store"))
        self.assertEqual(json.loads(payload), json.loads(json.dumps(schema.build_schema(), ensure_ascii=False)))

    def test_config_endpoints(self):
        state = {"numbers": dict(EXAMPLE), "text": {"l": "SU7 Ultra"}}
        self.assertEqual(self.status("POST", "/api/config", {"state": state, "sha256": None}), 403)      # example mode
        status, reply = self.reply_of("GET", "/api/config")
        self.assertEqual((status, reply["source"], reply["sha256"]), (200, "config.example.toml", None))
        self.assertEqual(reply["state"]["numbers"], EXAMPLE, "not the example numbers")
        reply = self.reply_of("GET", "/api/status")[1]
        self.assertEqual((reply["example"], reply["config_exists"]), (True, None))         # config.toml not even probed
        self.assertEqual(reply["bambu"], {"found": False, "reason": "test"})
        status, headers, exported = self.request("POST", "/api/config/export", {"state": state})
        self.assertEqual((status, headers["content-disposition"].split(";")[0]), (200, "attachment"))
        reply = self.reply_of("POST", "/api/config/import", {"toml": exported.decode("utf-8")})[1]
        self.assertEqual(reply["state"], filled(state), "export -> import changed the state")
        self.assertEqual(self.status("POST", "/api/config/export", {"state": {**state, "box": {"skirtt": 1}}}), 422)
        bad = f'[numbers]\na = "{SENTINEL}"\n[text]\nl = "SU7 Ultra\n'                 # the string never ends
        reply = self.reply_of("POST", "/api/config/import", {"toml": bad})[1]
        self.assertFalse(leaked(reply, SENTINEL_FORMS + ("SU7 Ultra",)), "the TOML text is in the reply")
        self.assertIsNone(reply["state"], "the bad TOML gave a state")
        self.assertIn("行", reply["messages"][0]["text"], "no line and column in the message")
        # an empty number box (NaN, sent as null), a number in it, a text float() reads as infinite; a number too big
        # for a float (JSON 1e400, a whole-number box)
        bodies = {name: json.dumps({"state": {**state, "box": {"skirt": skirt}}})
                  for name, skirt in (("null", None), ("spaced number", SPACED), ("inf", "inf"))}
        bodies["1e400"] = json.dumps({"state": {**state, "display": {"white_layers": "W"}}}).replace('"W"', "1e400")
        for name, raw in bodies.items():
            with self.subTest(name), contextlib.redirect_stderr(io.StringIO()) as terminal:
                status, reply = self.reply_of("POST", "/api/config/export", raw=raw.encode("utf-8"))
                self.assertEqual(status, 422)
                self.assertFalse(leaked([reply, terminal.getvalue()]), "the value is in the reply or the terminal")
                self.assertEqual(terminal.getvalue(), "", "a traceback in the terminal")
        for value, shown in (("2026-10-20", "2026-10-20"), ("nan", "nan"), ("-inf", "-inf")):   # JSON has none of these
            with self.subTest(value=value):
                status, reply = self.reply_of("POST", "/api/config/import", {"toml": f"[box]\nskirt = {value}\n"})
                self.assertEqual((status, reply["state"]["box"]["skirt"]), (200, shown))
                self.assertIn("box.skirt", [message["field"] for message in reply["messages"]])
        for name, toml in (("arrays too deep", "x = " + "[" * 3000 + "]" * 3000 + "\n"),
                           ("a 5000-digit integer", "[box]\nskirt = " + "1" * 5000 + "\n")):
            with self.subTest(name), contextlib.redirect_stderr(io.StringIO()) as terminal:
                status, reply = self.reply_of("POST", "/api/config/import", {"toml": toml})
                self.assertEqual((status, reply["state"], terminal.getvalue()), (200, None, ""))
                self.assertIn("TOML", reply["messages"][0]["text"])
        status, reply = self.reply_of("POST", "/api/validate", {"state": {"box": {"skirt": 10 ** 309}}})
        self.assertEqual((status, reply["ok"]), (200, False))                  # float() of it overflows: no 500
        text = f'[numbers]\na = "{EXAMPLE["a"]}"\nb = "{EXAMPLE["b"]}"\n[box]\nskirtt = 13.62\n[{SENTINEL_B}]\nx = 1\n'
        reply = self.reply_of("POST", "/api/config/import", {"toml": text})[1]
        self.assertTrue(any(message.get("blocks_save") for message in reply["messages"]))
        self.assertFalse(leaked(reply, (SENTINEL_B, "12345678")), "sentinel leaked")

    def test_config_outside_example_mode(self):
        """The page's read -> save over HTTP, on a temporary config.toml: the numbers come back as they are."""
        folder = self.new_folder()
        path = folder / "config.toml"
        path.write_text(SAVED, encoding="utf-8", newline="\n")
        with mock.patch.object(self.app, "api", config_api(folder, path)):
            status, reply = self.reply_of("GET", "/api/config")
            self.assertEqual(status, 200)
            self.assertEqual(reply["state"]["numbers"], {"a": SENTINEL}, "the numbers came back redacted")
            body = {"state": reply["state"], "sha256": reply["sha256"]}
            self.assertEqual(self.status("POST", "/api/config", body), 200)
            self.assertEqual(self.status("POST", "/api/config", body), 409)           # its sha256 is the old one now
        self.assertEqual(tomllib.loads(path.read_text(encoding="utf-8"))["numbers"], {"a": SENTINEL},
                         "the numbers changed")

    def test_job_endpoints(self):
        base, job_id = f"/api/jobs/{self.job_id}", self.job_id
        status, reply = self.reply_of("GET", f"{base}?since=0")
        self.assertEqual((status, reply["job"]["state"], reply["next"]), (200, "ok", 2))
        self.assertFalse(leaked(reply), "sentinel leaked")                                 # the log is redacted
        status, headers, payload = self.request("GET", f"{base}/file?path=report.md")
        self.assertEqual(status, 200)
        self.assertEqual(payload, b"# report\n")
        self.assertEqual(headers["content-disposition"], "attachment; filename*=UTF-8''report.md")
        for path in ("..%2F..%2Fconfig.example.toml", "plates/../../report.md", "/etc/passwd", "..%5Cconfig.toml",
                     "report.md%00", "job.json", "config.toml/"):
            self.assertEqual(self.status("GET", f"{base}/file?path={path}"), 404, path)
        payload = self.request("GET", f"{base}/zip")[2]                                # default: no config, no log
        self.assertEqual(sorted(zipfile.ZipFile(io.BytesIO(payload)).namelist()), [
            f"{job_id}/{name}" for name in ("parts/print/rotor.navy.stl", "plates/parking_plate.3mf", "report.md")])
        for query, name in (("", job_id), ("?groups=report", f"{job_id}-report"), ("?groups=3mf,report", job_id)):
            disposition = self.request("GET", f"{base}/zip{query}")[1]["content-disposition"]   # one group: named
            self.assertEqual(disposition, f"attachment; filename*=UTF-8''parking-plate-{name}.zip", query)
        self.assertEqual(self.status("GET", f"{base}/zip?groups=nope"), 400)

    def test_open_and_reveal(self):
        """/api/open: listed outputs, Bambu Studio for the 3MF only; reveal and /api/fonts/reveal as on macOS."""
        job_id = self.job_id
        for job, path, action, expected in ((job_id, "job.json", "reveal", 404), ("x", "report.md", "reveal", 404),
                                            (job_id, "report.md", "print", 400),
                                            (job_id, "parts/print/rotor.navy.stl", "bambu", 400),
                                            (job_id, "plates/parking_plate.3mf", "bambu", 400)):    # no Bambu Studio
            body = {"job": job, "path": path, "action": action}
            self.assertEqual(self.status("POST", "/api/open", body), expected, path)
        report, fonts = (self.jobs_root / job_id / "report.md").resolve(), TEMP / "fonts"
        with mock.patch.object(platform, "IS_MAC", True), mock.patch.object(platform, "IS_WINDOWS", False), \
                mock.patch.object(api, "FONT_PATH", fonts / "MiSans-Bold.ttf"):
            self.gui.reset_mock()
            status, reply = self.reply_of("POST", "/api/open", {"job": job_id, "path": "report.md", "action": "reveal"})
            self.assertEqual((status, reply["opened"], reply["path"]), (200, True, str(report)))
            self.gui.assert_called_once_with(["open", "-R", str(report)])
            self.gui.reset_mock()
            status, reply = self.reply_of("POST", "/api/fonts/reveal", {})
            self.assertEqual((status, reply["opened"], reply["path"]), (200, True, str(fonts)))
            self.gui.assert_called_once_with(["open", str(fonts)])

    def test_shutdown_any_time(self):
        """/api/shutdown replies, then stops the server: also while the pipeline loads or after it failed to load."""
        for name, state in (("loaded", {}), ("loading", {"ready": threading.Event()}),
                            ("failed", {"api": None, "failed": "ImportError: test"})):
            stop = mock.Mock()
            with self.subTest(name), mock.patch.multiple(self.app, stop_server=stop, **state):
                self.assertEqual(self.reply_of("POST", "/api/shutdown", {}), (200, {"stopping": True}))
                self.assertTrue(wait_for(lambda: stop.called, 5), "the server was not stopped")
                stop.assert_called_once_with()
        with mock.patch.object(self.app, "stop_server") as stop:
            self.assertEqual(self.status("POST", "/api/shutdown", {}, headers={"X-Plate-Token": None}), 403)
        stop.assert_not_called()

    def test_shutdown_replies_then_stops(self):
        """One reply, then the stop in the same request; a page that leaves before the reply still stops it."""
        replied, events, writers = threading.Event(), [], []
        original = server.Handler.reply

        def stop():
            events.append("stop" if replied.wait(5) else "stopped before the reply")
            events.append(threading.current_thread() in writers)

        def writing(handler, *args, **kwargs):
            writers.append(threading.current_thread())
            return original(handler, *args, **kwargs)

        with mock.patch.object(self.app, "stop_server", side_effect=stop), \
                mock.patch.object(server.Handler, "reply", autospec=True, side_effect=writing) as reply:
            self.assertEqual(self.reply_of("POST", "/api/shutdown", {}), (200, {"stopping": True}))
            replied.set()
            self.assertTrue(wait_for(lambda: len(events) == 2, 10), "the server was not stopped")
            time.sleep(0.2)                                     # a second reply would come now
        self.assertEqual(events, ["stop", True])
        self.assertEqual(reply.call_count, 1, "a second reply after the stop")
        with mock.patch.object(self.app, "stop_server") as stop, \
                mock.patch.object(server.Handler, "reply", side_effect=BrokenPipeError):
            with contextlib.suppress(http.client.HTTPException, OSError):          # no reply: the page left
                self.request("POST", "/api/shutdown", {})
            self.assertTrue(wait_for(lambda: stop.called, 5), "the server kept running")

    def test_bad_target_and_escaped_errors(self):
        """A request line urlsplit refuses: 400. Errors that escape a handler: silent for a page that left, else one
        line (never a traceback)."""
        with contextlib.redirect_stderr(io.StringIO()) as terminal:
            self.assertEqual(self.status("GET", "http://[::1/"), 400)
        self.assertEqual(terminal.getvalue(), "", "a traceback in the terminal")
        for error, expected in ((ConnectionResetError(54, "Connection reset by peer"), ""),
                                (ValueError(f"no {SENTINEL}"), "内部错误：ValueError（test_webui.py:")):
            with self.subTest(type(error).__name__), contextlib.redirect_stderr(io.StringIO()) as terminal:
                try:
                    raise error
                except Exception:
                    self.httpd.handle_error(None, ("127.0.0.1", 1))
            line = terminal.getvalue()
            if expected:
                self.assertTrue(line.startswith(expected) and line.count("\n") == 1, "not one line with the place")
            else:
                self.assertEqual(line, "", "a page that left is not an error")
            self.assertFalse(leaked(terminal.getvalue()), "the message is in the terminal")

    def test_internal_error(self):
        """A bug: 500 for the page, its type and place (in this package) in the terminal, never the message's value."""
        for name, method, path, failing, place in (
                ("in a function an endpoint calls", "POST", "/api/validate",
                 mock.patch.object(schema, "validate", side_effect=ValueError(f"could not convert {SPACED!r}")),
                 "api.py:"),
                ("a reply JSON cannot hold", "GET", "/api/status",
                 mock.patch.object(self.app.api, "status", return_value=(200, {"memory_mb": float("nan")})),
                 "server.py:"),
                ("outside the endpoints", "GET", "/", mock.patch.object(server, "STATIC_DIR", TEMP / "no-static"),
                 "server.py:")):
            with self.subTest(name), failing, contextlib.redirect_stderr(io.StringIO()) as terminal:
                status, reply = self.reply_of(method, path, {"state": {}} if method == "POST" else None)
                self.assertEqual(status, 500)
                line = terminal.getvalue()
                self.assertTrue(line.startswith("内部错误：") and f"（{place}" in line and line.count("\n") == 1,
                                f"not one line with the place in {place}")
                self.assertFalse(leaked([reply, line]), "the value is in the reply or the terminal")

    def test_pipeline_not_loaded(self):
        with mock.patch.object(self.app, "api", None), mock.patch.object(self.app, "failed", "ImportError: test"):
            status, reply = self.reply_of("GET", "/api/status")
        self.assertEqual(status, 503)
        self.assertIn("ImportError: test", reply["error"])            # the page shows it: 服务器没准备好：…

    @needs_font
    def test_validate_and_preview(self):
        retired = {"numbers": dict(EXAMPLE), "fit": {"far_bore": 6.1}}
        for state, warned in (({"numbers": dict(EXAMPLE)}, False), (retired, True)):
            reply = self.reply_of("POST", "/api/validate", {"state": state})[1]
            warnings_given = [message for message in reply["messages"] if message["level"] == "warning"]
            self.assertEqual((reply["ok"], bool(warnings_given)), (True, warned))
        body = {"face": "A", "state": {"text": {"a": "+00 0000 0000"}}, "step": "layout"}
        status, reply = self.reply_of("POST", "/api/preview", body)
        self.assertEqual((status, reply["facts"]["kind"], reply["errors"]), (200, "text", []))
        self.assertAlmostEqual(reply["facts"]["em"], 25.77, delta=0.01)
        status, reply = self.reply_of("POST", "/api/preview", {"face": "A", "state": {"numbers": {"a": SENTINEL}}})
        self.assertEqual((status, reply["facts"]["kind"], reply["example"], reply["svg"][:4]),
                         (200, "number", False, "<svg"))
        self.assertFalse(leaked({key: value for key, value in reply.items() if key != "svg"}), "sentinel leaked")
        status, reply = self.reply_of("POST", "/api/preview", {"face": "B", "state": {}})
        self.assertEqual((status, reply["example"]), (200, True))                 # an empty face: the faded example
        body = {"face": "A", "state": {"display": {"condense": SENTINEL}}}
        status, reply = self.reply_of("POST", "/api/preview", body)
        self.assertEqual(status, 422)
        self.assertFalse(leaked(reply), "sentinel leaked")
        self.assertEqual(self.status("POST", "/api/preview", {"face": "Q", "state": {}}), 400)

    @needs_font
    def test_build_refuses_bad_faces(self):
        """v3.4 design 6.12 error cases: 422, no text, no character of a text and no number in the reply."""
        face_b = {"b": EXAMPLE["b"]}
        cases = (("澎程 beside the sketch", {"numbers": dict(EXAMPLE), "text": {"l": "澎程"}}),
                 ("text only without l", {"numbers": dict(EXAMPLE), "display": {"logo": "none"}}),
                 ("赢", {"numbers": face_b, "text": {"a": "赢"}}), ("☎", {"numbers": face_b, "text": {"a": "☎"}}),
                 ("line break", {"numbers": face_b, "text": {"a": "MOVE\nCAR"}}),
                 ("empty", {"numbers": face_b, "text": {"a": ""}}))
        with mock.patch.object(self.app.api.jobs, "start", side_effect=jobs.Busy("guard")):     # never a real build
            for name, state in cases:
                with self.subTest(name):
                    status, reply = self.reply_of("POST", "/api/build", {"state": state})
                    self.assertEqual((status, reply.get("ok")), (422, False))
                    texts = [text for text in state.get("text", {}).values() if text]
                    forms = (texts + [part for text in texts for part in text.split("\n")]
                             + CJK.findall("".join(texts)) + list(state["numbers"].values()))
                    self.assertFalse(leaked(reply, tuple(forms)), "a text or a number is in the reply")


# ---------------------------------------------------------------- 10 starting the server, the download zip
class ServeTest(Case):
    def test_start_load_stop(self):
        """scripts/webui.py as the start-webui scripts run it (a child process; example mode, no browser, no Bambu
        Studio): the terminal lines, the background load, /api/shutdown, exit code 0."""
        out_dir = self.new_folder()
        (out_dir / ".tmp").mkdir()
        environment = {**platform.build_environment(out_dir), "TISSUEPLATE_BAMBU_STUDIO": str(out_dir / "missing")}
        with subprocess.Popen([sys.executable, "-I", "-X", "utf8", "-u", str(PROJECT / "scripts" / "webui.py"),
                               "--example", "--no-browser"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              encoding="utf-8", env=environment) as child:
            try:
                printed = read_lines(child.stdout)                   # a missing line fails the test, never hangs it
                lines = [printed.get(timeout=60) for _ in range(5)]  # printed at once, before the pipeline loads
                port, token = re.search(r"127\.0\.0\.1:(\d+)/#token=(\S+)", lines[1]).groups()
                status, _, payload = http_request(int(port), token, "GET", "/api/status")     # waits for the load
                self.assertEqual(status, 200)
                lines.append(printed.get(timeout=60))
                self.assertEqual(http_request(int(port), token, "POST", "/api/shutdown", {})[0], 200)
                child.wait(timeout=60)
                rest, end, errors = printed.get(timeout=10), printed.get(timeout=10), child.stderr.read()
            finally:
                child.kill()                                         # no-op once it has exited
        self.assertTrue(json.loads(payload)["example"])
        for line, start in zip(lines, ("挪车号码牌网页已启动（示例模式", "  http://127.0.0.1:", "把上面这条链接复制到浏览器里打开",
                                       "按 Ctrl+C", "正在后台加载构建程序")):
            self.assertTrue(line.startswith(start), start)
        self.assertRegex(lines[5], r"^构建程序已加载（\d+ s），页面可以用了。$")
        self.assertTrue(rest.startswith("服务器已停止"), "no stop line")
        self.assertEqual((end, child.returncode, errors), (None, 0, ""))

    def test_load_failure(self):
        """The page sends the user to the terminal when the pipeline did not load: the reason is printed there."""
        app, out, err = server.App(1, "token", False), io.StringIO(), io.StringIO()
        missing = ImportError("libGL.so.1: cannot open shared object file")
        with mock.patch.object(api, "Api", side_effect=missing), mock.patch.object(server.sys, "platform", "linux"), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            app.load(TEMP / "never", 5, True)
        self.assertTrue(app.ready.is_set(), "requests would wait for READY_WAIT")
        self.assertIsNone(app.api)
        self.assertEqual(out.getvalue(), "")
        self.assertTrue(err.getvalue().startswith("加载构建程序失败：ImportError: libGL.so.1"), "no failure line")
        self.assertIn("三个平台", err.getvalue())                                  # the Linux system packages
        self.assertGreaterEqual(server.READY_WAIT, 600)          # the first import in a new .venv takes 1-2 min

    def test_tracked_paths_are_ascii(self):
        """macOS unzip stops at a non-ASCII name in a git archive zip (GitHub's Download ZIP), leaving out the rest."""
        try:
            listed = subprocess.run(["git", "ls-files", "-z"], cwd=PROJECT, capture_output=True, check=True,
                                    timeout=60).stdout.split(b"\0")
        except (OSError, subprocess.SubprocessError):
            self.skipTest("no git, or not a git checkout")
        self.assertGreater(len(listed), 1)
        self.assertEqual([name.decode("utf-8", "replace") for name in listed if not name.isascii()], [])


# ---------------------------------------------------------------- 11 preview numbers
@needs_font
class PreviewNumbersTest(Case):
    # (face, [display] logo, text, font size, second fact, its value), measured today: v3.4 design 6.9 (faces A / B),
    # 6.4 (face L beside the sketch: clearance to it; XIAOMI 2.05, the design has 2.06), 6.5 (face L text only)
    SAMPLES = (("A", "final", "+00 0000 0000", 25.77, "condense", 0.86),
               ("A", "final", "000-0000-0000", 24.40, "condense", 0.86),
               ("A", "final", "MOVE MY CAR? CALL", 17.71, "condense", 0.86),
               ("A", "final", "临时停车请联系我", 22.76, "condense", 0.97),
               ("A", "final", "挪车请扫码", 23.27, "condense", 1.00),
               ("A", "final", "不好意思 稍等", 23.02, "condense", 1.00),
               ("A", "final", "请致电 138 0013 8000", 18.82, "condense", 0.86),       # the full step stops these two
               ("A", "final", "赢", 23.00, "condense", 1.00),
               ("L", "final", "YU7", 9.03, "clearance", 2.27), ("L", "final", "YU7 MAX", 9.03, "clearance", 1.90),
               ("L", "final", "SU7 Ultra", 9.03, "clearance", 1.90), ("L", "final", "XIAOMI", 9.03, "clearance", 2.05),
               ("L", "final", "Xiaomi SU7 Ultra", 9.03, "clearance", 1.74),
               ("L", "final", "小米汽车", 8.70, "clearance", 1.51), ("L", "final", "小米 YU7", 8.58, "clearance", 1.50),
               ("L", "none", "SU7 Ultra", 26.73, "condense", 1.00), ("L", "none", "N90 Max", 26.73, "condense", 1.00),
               ("L", "none", "XIAOMI SU7", 26.73, "condense", 1.00), ("L", "none", "小米汽车", 23.00, "condense", 1.00))

    def test_layout_numbers(self):
        for face, logo, text, em, fact, value in self.SAMPLES:
            with self.subTest(face=face, logo=logo, text=text):
                result = faces.preview(face, {"text": {face.lower(): text}, "display": {"logo": logo}}, "layout")
                self.assertEqual(result["errors"], [])
                self.assertAlmostEqual(result["facts"]["em"], em, delta=0.01)
                self.assertAlmostEqual(result["facts"][fact], value, delta=0.01)

    def test_full_checks(self):
        result = faces.preview("L", {"text": {"l": "SU7 Ultra"}}, "full")
        self.assertEqual((result["checked"], result["errors"], result["warnings"]), (True, [], []))
        result = faces.preview("B", {"text": {"b": "MOVE MY CAR? CALL"}}, "full")
        self.assertEqual((result["checked"], result["errors"], len(result["warnings"])), (True, [], 1))     # ink < 20
        for face, text in (("L", "澎程"), ("A", "请致电 138 0013 8000")):
            with self.subTest(face=face, text=text):
                result = faces.preview(face, {"text": {face.lower(): text}}, "full")
                self.assertEqual((len(result["errors"]), result["positions"]), (1, [1]))   # counter of character 1

    def test_guides(self):
        """The dashed guide: a number face shows its cells (wider than ART_BOX), a text face ART_BOX (3 .. 178)."""
        guide = re.compile(r'<rect x="([-\d.]+)" y="([-\d.]+)" width="([\d.]+)" height="([\d.]+)" fill="none" '
                           f'stroke="{faces.GUIDE}"')
        number = guide.search(faces.preview("A", {}, "layout")["svg"]).groups()
        text = guide.search(faces.preview("B", {"text": {"b": "MOVE"}}, "layout")["svg"]).groups()
        for measured, expected in zip(number, (0.13, 3.80, 178.74, 21.60)):    # x 0.13 .. 178.87, baseline + 21.6
            self.assertAlmostEqual(float(measured), expected, delta=0.01)
        self.assertEqual(text, ("3.000", "3.000", "175.000", "21.600"))


# ---------------------------------------------------------------- 12 a full build (manual)
GEOMETRY = (".3mf", ".step", ".stl", ".gcode")


@unittest.skipUnless(os.environ.get("TISSUEPLATE_TEST_BUILD") == "1", "manual: TISSUEPLATE_TEST_BUILD=1 (about 4 min)")
class FullBuildTest(Case):
    @needs_font
    def test_outputs_never_hold_the_number(self):
        """v3.4 design 6.12: no file name and no output text of the job (3MF members, STEP, G-code included) holds
        the number; config.toml aside."""
        state = {"numbers": {"a": SENTINEL}, "text": {"b": SPACED}}
        self.assertTrue(schema.validate(state)["ok"], "the test config is not valid")
        self.assertEqual(faces.hard_errors(state), {}, "the test config has hard errors")
        manager = jobs.JobManager(self.new_folder())
        self.addCleanup(manager.stop_all)
        started = time.monotonic()
        job = manager.start(schema.to_toml(state))
        finished = wait_for(lambda: saved_state(job) not in (None, *jobs.RUNNING), 15 * 60, step=2)
        sys.stderr.write(f"\nfull build: {job.state}, exit code {job.exit_code}, {time.monotonic() - started:.0f} s\n")
        self.assertTrue(finished, "the build did not finish in 15 min")
        self.assertIn(job.state, ("ok", "unsliced"), f"exit code {job.exit_code}")
        self.assertTrue((job.dir / "report.md").is_file(), "no report.md in the job folder: the search would be empty")
        for path in sorted(job.dir.rglob("*")):
            relative = path.relative_to(job.dir).as_posix()
            self.assertFalse(leaked([relative]), "a file name holds the number")
            if not path.is_file() or relative == "config.toml" or path.suffix == ".png":
                continue
            if path.suffix == ".3mf":                                          # a zip of XML and thumbnails
                with zipfile.ZipFile(path) as archive:
                    texts = [archive.read(name).decode("utf-8", "replace") for name in archive.namelist()
                             if not name.endswith(".png")]
            else:
                texts = [path.read_text(encoding="utf-8", errors="replace")]
            # coordinates are long digit runs (one build's STEP files hold about 2.5 M eight-digit windows): there an
            # 8-digit part of the number turns up by chance, so geometry is searched for the whole number only
            forms = SENTINEL_FORMS[:3] if path.suffix in GEOMETRY else SENTINEL_FORMS
            self.assertFalse(leaked(texts, forms), f"{relative} holds the number")


if __name__ == "__main__":
    unittest.main()
