"""The endpoints of the web UI (webui design 4.2) behind server.py's checks: each takes the parsed JSON body (POST) or
the query (GET) and returns (status, JSON object) or a Download; HttpError for the refusals.
"""
import io
import sys
from dataclasses import dataclass
from pathlib import Path

from .. import bambu
from ..config import ConfigError
from ..params import FONT_PATH, FONT_URL, PROJECT_DIR, font_is_authors
from . import faces, platform, schema
from .jobs import DEFAULT_ZIP_GROUPS, GROUPS, Busy, JobManager


class HttpError(Exception):
    def __init__(self, status, text):
        super().__init__(text)
        self.status, self.text = status, text


@dataclass
class Download:
    handle: object          # open binary file
    size: int
    name: str


def _state(body):
    state = body.get("state")
    if not isinstance(state, dict):
        raise HttpError(400, "state must be a JSON object")
    return state


def _clean(value, hidden):
    """Every string of a reply redacted (the SVG has outlines, no characters)."""
    if isinstance(value, str):
        return schema.redact(value, hidden)
    if isinstance(value, list):
        return [_clean(item, hidden) for item in value]
    if isinstance(value, dict):
        return {key: value if key == "svg" else _clean(value, hidden) for key, value in value.items()}
    return value


class Api:
    def __init__(self, jobs_root, keep=5, example=False, config_path=schema.CONFIG_PATH):
        self.example, self.config_path = example, Path(config_path)     # config_path: tests pass a temporary one
        self.jobs = JobManager(jobs_root, keep=keep)
        self.probe_dir = Path(jobs_root) / ".bambu_probe"
        self.slicer_status = None
        self.detect()
        if not example:
            schema.remove_stale_temp(self.config_path)

    # ---------------- status
    def detect(self):
        """Bambu Studio as the build will find it (located and tried once); the font."""
        font_is_authors.cache_clear()
        try:
            found = bambu.trial_run(bambu.locate(), self.probe_dir)
            self.slicer_status = {"found": True, "version": found.version, "cli": str(found.cli),
                                  "version_ok": found.version in (None, bambu.APP_VERSION), "expected": bambu.APP_VERSION}
        except bambu.SlicerUnavailable as error:
            self.slicer_status = {"found": False, "reason": str(error)}

    def status(self, query):
        if query.get("refresh"):
            self.detect()
        font = {"present": FONT_PATH.exists(), "authors": FONT_PATH.exists() and font_is_authors(), "url": FONT_URL}
        current = self.jobs.current
        return 200, {"bambu": {key: value for key, value in self.slicer_status.items() if key != "cli"}, "font": font,
                     "busy": current.id if self.jobs.busy() else None, "example": self.example,
                     "config_exists": None if self.example else self.config_path.exists(),
                     "platform": {"system": sys.platform, "reveal_label": platform.REVEAL_LABEL,
                                  "warning": platform.private_folder_warning(PROJECT_DIR)},
                     "keep": self.jobs.keep, "memory_mb": platform.peak_memory_mb()}

    def schema(self, query):
        return 200, schema.build_schema()

    # ---------------- config
    def validate(self, body):
        state = _state(body)
        return 200, schema.validate(state)

    def preview(self, body):
        state = _state(body)
        face, step = body.get("face"), body.get("step", "full")
        if face not in ("A", "B", "L") or step not in ("layout", "full"):
            raise HttpError(400, "face must be A, B or L and step layout or full")
        if not all(isinstance(table, dict) for table in state.values()):
            raise HttpError(400, "every section of state must be a JSON object")
        hidden = schema.secrets_of(state)
        try:
            result = faces.preview(face, state, step)
        except ConfigError as error:
            return 422, {"errors": [schema.redact(schema.chinese(str(error)), hidden)]}
        return 200, _clean(result, hidden)

    def config_read(self, query):
        if self.example:
            result = schema.read_config(schema.EXAMPLE_PATH)
            result["sha256"] = None                       # never saved back
            return 200, {**result, "source": "config.example.toml"}
        result = schema.read_config(self.config_path)
        if result is None:
            raise HttpError(404, "没有 config.toml")
        # only the messages: the state fills the form and the sha256 comes back with the save
        hidden = schema.secrets_of(result["state"] or {})
        return 200, {**result, "messages": _clean(result["messages"], hidden), "source": "config.toml"}

    def config_save(self, body):
        if self.example:
            raise HttpError(403, "示例模式（--example）不读写 config.toml")
        state = _state(body)
        sha256, overwrite = body.get("sha256"), bool(body.get("overwrite"))
        try:
            return 200, {"sha256": schema.save_config(state, sha256 if isinstance(sha256, str) else None, overwrite,
                                                      path=self.config_path)}
        except schema.SaveConflict as conflict:
            raise HttpError(conflict.status, conflict.text) from None
        except ConfigError:
            raise HttpError(422, "有不认识的段或键，或者数值框里不是数字：不能保存") from None

    def config_export(self, body):
        try:
            text = schema.to_toml(_state(body))
        except ConfigError:
            raise HttpError(422, "有不认识的段或键，或者数值框里不是数字：不能导出") from None
        data = text.encode("utf-8")
        return Download(io.BytesIO(data), len(data), "config.toml")

    def config_import(self, body):
        text = body.get("toml")
        if not isinstance(text, str):
            raise HttpError(400, "toml must be a string")
        state, messages = schema.from_toml(text)
        hidden = schema.secrets_of(state or {})
        return 200, {"state": state, "messages": _clean(messages, hidden)}

    # ---------------- build and jobs
    def build(self, body):
        state = _state(body)
        result = schema.validate(state)
        if not result["ok"]:
            return 422, result
        problems = faces.hard_errors(state)
        if problems:
            hidden = schema.secrets_of(state)
            return 422, {"ok": False, "messages": [{"field": f"face.{face}", "level": "error",
                                                    "text": schema.redact(f"{face} 面：{'；'.join(errors)}", hidden)}
                                                   for face, errors in problems.items()]}
        try:
            job = self.jobs.start(schema.to_toml(state))
        except Busy:
            raise HttpError(409, "已经有一个构建在跑") from None
        return 202, {"job": job.summary()}

    def job_list(self, query):
        return 200, {"jobs": self.jobs.list()}

    def _job(self, job_id):
        job = self.jobs.get(job_id)
        if job is None:
            raise HttpError(404, "没有这个任务")
        return job

    def job_status(self, job_id, query):
        job = self._job(job_id)
        try:
            since = max(0, int(query.get("since", "0")))
        except ValueError:
            raise HttpError(400, "since must be an integer") from None
        lines = job.log_lines(since)
        return 200, {"job": job.summary(), "lines": lines, "next": since + len(lines)}

    def job_files(self, job_id, query):
        job = self._job(job_id)
        return 200, {"files": self.jobs.files(job), "groups": [{"group": g, "label": label} for g, label, _ in GROUPS],
                     "default_zip": list(DEFAULT_ZIP_GROUPS)}

    def job_file(self, job_id, query):
        path = self.jobs.resolve(self._job(job_id), query.get("path", ""))
        if path is None:
            raise HttpError(404, "不是这个任务列出的产物")
        return Download(open(path, "rb"), path.stat().st_size, path.name)

    def job_zip(self, job_id, query):
        job = self._job(job_id)
        known = {group for group, _, _ in GROUPS}
        wanted = [name for name in query.get("groups", ",".join(DEFAULT_ZIP_GROUPS)).split(",") if name]
        if not wanted or any(name not in known for name in wanted):
            raise HttpError(400, "unknown artifact group")
        if job.state in ("queued", "running"):
            raise HttpError(409, "构建还没结束")
        handle, size = self.jobs.zip_file(job, set(wanted))
        group = f"-{wanted[0]}" if len(wanted) == 1 else ""       # one group: its name, so downloads don't clash
        return Download(handle, size, f"parking-plate-{job.id}{group}.zip")

    def job_cancel(self, job_id, body):
        return 200, {"cancelled": self.jobs.cancel(self._job(job_id).id)}

    def job_delete(self, job_id, body):
        job = self._job(job_id)
        if not self.jobs.delete(job.id):
            raise HttpError(409, "构建还在跑，先取消")
        return 200, {"deleted": True}

    def open_output(self, body):
        """{"job", "path", "action": "bambu" | "reveal"}: only listed outputs; Bambu Studio only for the 3MF."""
        job = self._job(body.get("job"))
        path = self.jobs.resolve(job, body.get("path"))
        if path is None:
            raise HttpError(404, "不是这个任务列出的产物")
        if body.get("action") == "bambu":
            if path.suffix != ".3mf" or not self.slicer_status.get("found"):
                raise HttpError(400, "只能用 Bambu Studio 打开这次的 3MF")
            platform.open_in_bambu(Path(self.slicer_status["cli"]), path)
            return 200, {"opened": True}
        if body.get("action") == "reveal":
            return 200, {"opened": platform.reveal(path), "path": str(path)}
        raise HttpError(400, "action must be bambu or reveal")

    def fonts_reveal(self, body):
        folder = FONT_PATH.parent
        folder.mkdir(exist_ok=True)
        return 200, {"opened": platform.open_folder(folder), "path": str(folder)}
