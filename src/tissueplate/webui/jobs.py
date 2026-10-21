"""Build jobs: one scripts/build_all.py child at a time, each in its own private folder (webui design 4.4, 4.5).

Job folder out/web/<job id>/ (0700; files 0600 through umask 077 on macOS / Linux) = TISSUEPLATE_OUT_DIR of the build:
    config.toml        this job's config (numbers and texts inside: local only)
    build_log.txt      stdout of build_all.py (it never prints a number or a text)
    job.json           id, state, exit code, stage times (no numbers)
    .tmp/              temp folder of the build (TMPDIR, Windows TEMP / TMP)
    parts/ checks/ plates/ renders/ report.md <time>-装配卡.md     the build's outputs
"""
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import zipfile
from datetime import datetime
from pathlib import Path

from ..params import PROJECT_DIR
from . import platform
from .schema import redact, secrets_of

JOB_ID = re.compile(r"\d{4}-\d{4}-\d{6}-[0-9a-f]{4}")
STAGE_LINE = re.compile(r"\[stage (\d+)/(\d+)\] ")
STATES = {0: "ok", 1: "failed", 2: "config_error", 3: "unsliced", 4: "crashed"}
RUNNING = ("queued", "running")
# artifact groups: (group, label, glob patterns in the job folder)
GROUPS = (
    ("3mf", "3MF 工程（两盘）", ("plates/parking_plate.3mf",)),
    ("print_stl", "打印姿态 STL", ("parts/print/*.stl",)),
    ("print_step", "打印姿态 STEP", ("parts/print/*.step",)),
    ("assembly", "装配 STEP + STL", ("parts/assembly.step", "parts/assembled/*.stl")),
    ("card", "装配卡", ("*-装配卡.md",)),
    ("report", "报告和明细", ("report.md", "checks/checks_report.json", "parts/geometry_report.json",
                         "plates/slice_report.json", "parts/manifest.json")),
    ("renders", "渲染图", ("renders/*.png",)),
    ("config", "这次的 config.toml", ("config.toml",)),
    ("gcode", "命令行切出来的 G-code（只供参考）", ("plates/slice/plate_*.gcode",)),
    ("log", "构建日志", ("build_log.txt", "build_error.log")),
)
DEFAULT_ZIP_GROUPS = ("3mf", "print_stl", "print_step", "assembly", "card", "report", "renders")


class Busy(RuntimeError):
    pass


def _not_a_number(name):
    raise ValueError(f"{name} in job.json")             # NaN, Infinity: no JSON reply can hold them


def _finite(text):
    number = float(text)
    if not math.isfinite(number):                      # 1e400
        raise ValueError("an infinite number in job.json")
    return number


class Job:
    def __init__(self, job_id, directory):
        self.id, self.dir = job_id, Path(directory)
        self.state, self.exit_code, self.stage = "queued", None, 0
        self.created, self.started, self.finished = time.time(), None, None
        self.lines = []                       # (seconds since the start or None, text)
        self.stage_times = {}                 # stage number -> seconds since the start
        self.process = None
        self._hidden = None
        self.saved_elapsed = None             # of a job read back from job.json (started / finished are gone)

    def summary(self):
        elapsed = self.saved_elapsed if self.started is None else round((self.finished or time.time()) - self.started, 1)
        return {"id": self.id, "state": self.state, "exit_code": self.exit_code, "stage": self.stage,
                "stage_times": self.stage_times, "elapsed": elapsed, "lines": len(self.lines),
                "created": datetime.fromtimestamp(self.created).isoformat(timespec="seconds")}

    def save(self):
        with platform.open_private(self.dir / "job.json") as handle:
            handle.write(json.dumps(self.summary(), indent=1))

    def hidden(self):
        """The numbers and texts of this job's config.toml, for redact()."""
        if self._hidden is None:
            try:
                self._hidden = secrets_of(tomllib.loads((self.dir / "config.toml").read_text(encoding="utf-8")))
            except (OSError, tomllib.TOMLDecodeError):
                self._hidden = []
        return self._hidden

    def log_lines(self, since):
        # the job id is a digit run too: kept readable in the paths the build prints (the page shows it anyway)
        return [[seconds, redact(text.replace(self.id, "{job}"), self.hidden()).replace("{job}", self.id)]
                for seconds, text in self.lines[since:]]


class JobManager:
    def __init__(self, root, keep=5, python=sys.executable):
        self.root, self.keep, self.python = Path(root), keep, python
        self.jobs, self.lock, self.current = {}, threading.Lock(), None
        platform.make_private_dir(self.root)
        for job_id in self.ids():                 # a server that stopped while a build ran
            job = self.get(job_id)
            if job is not None and job.state in RUNNING:
                job.state = "interrupted"
                job.save()

    # ---------------- lifecycle
    def busy(self):
        return self.current is not None and self.current.state in RUNNING

    def start(self, config_text):
        with self.lock:
            if self.busy():
                raise Busy(self.current.id)
            job_id = datetime.now().strftime("%Y-%m%d-%H%M%S") + "-" + os.urandom(2).hex()
            job = Job(job_id, platform.make_private_dir(self.root / job_id))
            platform.make_private_dir(job.dir / ".tmp")
            with platform.open_private(job.dir / "config.toml", exclusive=True) as handle:
                handle.write(config_text)
            self.jobs[job_id], self.current = job, job
            job.save()
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def command(self, job):
        return [self.python, "-I", "-X", "utf8", "-u", str(PROJECT_DIR / "scripts" / "build_all.py"),
                "--config", str(job.dir / "config.toml"), "--no-v31"]

    def _run(self, job):
        job.state, job.started = "running", time.time()
        job.save()
        with platform.open_private(job.dir / "build_log.txt") as log:
            try:
                job.process = platform.BuildProcess(self.command(job), PROJECT_DIR, platform.build_environment(job.dir),
                                                    stdout=subprocess.PIPE)
            except OSError as error:
                job.lines.append((0.0, f"could not start the build: {type(error).__name__}"))
                job.state, job.finished = "crashed", time.time()
                job.save()
                return
            with job.process.process.stdout as stream:
                for raw in iter(stream.readline, b""):
                    text = raw.decode("utf-8", "replace").rstrip("\r\n")
                    seconds = round(time.time() - job.started, 1)
                    job.lines.append((seconds, text))
                    log.write(text + "\n")
                    log.flush()
                    stage = STAGE_LINE.match(text)
                    if stage:
                        job.stage = int(stage.group(1))
                        job.stage_times[job.stage] = seconds
            job.exit_code = job.process.process.wait()
            job.process.close()
        job.finished = time.time()
        if job.state == "cancelled":
            for leftover in job.dir.rglob("*.gcode.tmp"):      # the CLI stopped while writing (Windows)
                leftover.unlink(missing_ok=True)
        else:
            job.state = STATES.get(job.exit_code, "crashed")
        job.save()
        self.prune()

    def cancel(self, job_id):
        job = self.get(job_id)
        if job is None or job.process is None or job.state != "running":
            return False
        job.state = "cancelled"
        job.process.stop()
        return True

    def stop_all(self):
        if self.busy():
            self.cancel(self.current.id)

    # ---------------- lookup
    def ids(self):
        return sorted((path.name for path in self.root.iterdir() if path.is_dir() and JOB_ID.fullmatch(path.name)),
                      reverse=True)

    def get(self, job_id):
        if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
            return None
        if job_id in self.jobs:
            return self.jobs[job_id]
        directory = self.root / job_id
        try:                                # a broken job.json skips this job, never the whole server
            data = json.loads((directory / "job.json").read_text(encoding="utf-8"), parse_constant=_not_a_number,
                              parse_float=_finite)
            created = datetime.fromisoformat(data["created"]).timestamp() if data.get("created") else None
            if created is not None:
                datetime.fromtimestamp(created)     # summary() turns it back: years 1 and 9999 may not fit
            stage_times = {int(key): value for key, value in data.get("stage_times", {}).items()}
        except (OSError, ValueError, TypeError, AttributeError, OverflowError, RecursionError):
            return None
        job = Job(job_id, directory)
        job.state, job.exit_code, job.stage = data.get("state"), data.get("exit_code"), data.get("stage", 0)
        job.saved_elapsed = data.get("elapsed")
        if created is not None:
            job.created = created
        job.stage_times = stage_times
        log = directory / "build_log.txt"
        if log.is_file():
            job.lines = [(None, text) for text in log.read_text(encoding="utf-8", errors="replace").splitlines()]
        self.jobs[job_id] = job
        return job

    def list(self):
        return [job.summary() for job in (self.get(job_id) for job_id in self.ids()) if job is not None]

    # ---------------- outputs
    def files(self, job):
        """[{path, size, group}] of the outputs (the only files a download or "open" may name)."""
        rows, seen = [], set()
        for group, _, patterns in GROUPS:
            for pattern in patterns:
                for path in sorted(job.dir.glob(pattern)):
                    # no links, and nothing a linked folder leads out of the job folder to
                    if (path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(job.dir.resolve())
                            and path not in seen):
                        seen.add(path)
                        rows.append({"path": path.relative_to(job.dir).as_posix(), "size": path.stat().st_size,
                                     "group": group})
        return rows

    def resolve(self, job, relative):
        """Path of one listed output; None for anything else ('..', absolute, backslashes, NUL, links, unlisted)."""
        if not isinstance(relative, str) or not relative or "\\" in relative or "\x00" in relative:
            return None
        if relative.startswith("/") or any(part in ("", ".", "..") for part in relative.split("/")):
            return None
        if relative not in {row["path"] for row in self.files(job)}:
            return None
        path = (job.dir / relative).resolve()
        if not path.is_relative_to(job.dir.resolve()) or not path.is_file():
            return None
        return path

    def zip_file(self, job, groups):
        """Anonymous temporary file in the job folder holding a zip of the chosen groups."""
        handle = tempfile.TemporaryFile(dir=job.dir)
        with zipfile.ZipFile(handle, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for row in self.files(job):
                if row["group"] in groups:
                    archive.write(job.dir / row["path"], f"{job.id}/{row['path']}")
        size = handle.seek(0, 2)
        handle.seek(0)
        return handle, size

    # ---------------- retention
    def delete(self, job_id):
        job = self.get(job_id)
        if job is None or job.state in RUNNING:
            return False
        shutil.rmtree(job.dir)
        self.jobs.pop(job_id, None)
        return True

    def prune(self):
        """Keep the newest `keep` finished jobs: their outputs hold the numbers, they should not pile up."""
        finished = [row["id"] for row in self.list() if row["state"] not in RUNNING]
        for job_id in finished[self.keep:]:
            self.delete(job_id)
