"""What differs between macOS, Windows and Linux for the web UI (webui design 6.5).

- build process: its own process group (macOS / Linux) or a Job Object that ends with the server (Windows), so a
  cancel or the server's exit stops the build and the Bambu Studio CLI it started;
- the build's environment: only what each platform needs, plus the job's output and temp folders;
- opening a 3MF in Bambu Studio, showing a file in the file manager, the browser;
- file permissions (0600 / 0700 do nothing on Windows: there the user folder's ACL keeps the files private).
"""
import os
import shutil
import signal
import subprocess
import sys
import webbrowser
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
# the cache folders too: matplotlib and ezdxf keep their font caches where the user has put them
PASS_THROUGH = ("TISSUEPLATE_BAMBU_STUDIO", "TISSUEPLATE_BAMBU_PROFILES", "XDG_CACHE_HOME", "XDG_CONFIG_HOME",
                "MPLCONFIGDIR")
WINDOWS_KEEP = ("PATH", "SystemRoot", "SystemDrive", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "ProgramFiles",
                "ProgramData", "COMPUTERNAME", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "PATHEXT", "WINDIR")
POSIX_KEEP = ("PATH", "HOME", "LANG", "USER", "LOGNAME")
LINUX_KEEP = ("DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR")
REVEAL_LABEL = "在资源管理器中显示" if IS_WINDOWS else "在访达中显示" if IS_MAC else "打开所在文件夹"
STOP_WAIT = 5.0                 # s between the polite stop and the kill


def build_environment(job_dir: Path) -> dict:
    """Environment of a build: nothing else of the server's (tokens, keys in the shell stay out)."""
    keep = WINDOWS_KEEP if IS_WINDOWS else POSIX_KEEP + (() if IS_MAC else LINUX_KEEP)
    environment = {name: os.environ[name] for name in keep + PASS_THROUGH if os.environ.get(name)}
    temp = str(job_dir / ".tmp")
    environment.update(TISSUEPLATE_OUT_DIR=str(job_dir), OPENBLAS_NUM_THREADS="1", TMPDIR=temp)
    if IS_WINDOWS:
        environment.update(TEMP=temp, TMP=temp)
    else:
        environment.setdefault("LANG", "en_US.UTF-8")
    return environment


# ---------------------------------------------------------------- the build process and its children
if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    class _BasicLimits(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class _ExtendedLimits(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", _BasicLimits), ("IoInfo", ctypes.c_ulonglong * 6),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    _kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _ntdll = ctypes.WinDLL("ntdll")
    _ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
    _JOB_KILL_ON_CLOSE = 0x2000
    _EXTENDED_LIMITS = 9
    _CREATE_SUSPENDED = 0x4


def _new_job():
    """A Job Object whose processes all end when its last handle closes (the server exits, even by a crash)."""
    job = _kernel32.CreateJobObjectW(None, None)
    limits = _ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = _JOB_KILL_ON_CLOSE
    if not job or not _kernel32.SetInformationJobObject(job, _EXTENDED_LIMITS, ctypes.byref(limits),
                                                        ctypes.sizeof(limits)):
        raise OSError(ctypes.get_last_error(), "could not create the Job Object for the build")
    return job


class BuildProcess:
    """A started build; stop() ends it with everything it started."""

    def __init__(self, command, cwd, environment, stdout):
        self.job = None
        if IS_WINDOWS:
            # started suspended and put into the job before it runs, so the venv launcher's interpreter and the
            # Bambu Studio CLI are in it too; CREATE_NEW_PROCESS_GROUP keeps the console's Ctrl+C for the server
            self.job = _new_job()
            flags = _CREATE_SUSPENDED | subprocess.CREATE_NEW_PROCESS_GROUP
            self.process = subprocess.Popen(command, cwd=cwd, env=environment, stdout=stdout, stderr=subprocess.STDOUT,
                                            creationflags=flags)
            handle = int(self.process._handle)
            if not _kernel32.AssignProcessToJobObject(self.job, handle):
                self.process.kill()
                raise OSError(ctypes.get_last_error(), "could not put the build into its Job Object")
            _ntdll.NtResumeProcess(handle)
        else:
            self.process = subprocess.Popen(command, cwd=cwd, env=environment, stdout=stdout, stderr=subprocess.STDOUT,
                                            start_new_session=True, umask=0o077)

    def stop(self):
        """The build, its render child and the Bambu Studio CLI: the whole job (Windows), or SIGTERM to the process
        group and SIGKILL to what is left of it after STOP_WAIT (the CLI may ignore SIGTERM)."""
        if IS_WINDOWS:
            if self.job:
                _kernel32.TerminateJobObject(self.job, 1)
            return
        try:
            os.killpg(self.process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            self.process.wait(STOP_WAIT)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(self.process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def close(self):
        if IS_WINDOWS and self.job:
            _kernel32.CloseHandle(self.job)
            self.job = None


# ---------------------------------------------------------------- files, folders, browser
def make_private_dir(path: Path) -> Path:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not IS_WINDOWS:
        os.chmod(path, 0o700)
    return path


def open_private(path: Path, exclusive=False):
    """Text file for writing, 0600 on macOS / Linux (the server's umask does not apply)."""
    flags = os.O_WRONLY | os.O_CREAT | (os.O_EXCL if exclusive else os.O_TRUNC)
    return os.fdopen(os.open(path, flags, 0o600), "w", encoding="utf-8", newline="\n")


def private_folder_warning(project_dir: Path):
    """Windows ignores 0600 / 0700: a project outside the user folder may be readable by other users."""
    if not IS_WINDOWS:
        return None
    home = Path(os.environ.get("USERPROFILE", str(Path.home()))).resolve()
    if Path(project_dir).resolve().is_relative_to(home):
        return None
    return "仓库不在你的用户目录下：同一台电脑的其他用户可能读到 config.toml 和 out/。建议把仓库移到用户目录里。"


def is_wsl():
    try:
        return "microsoft" in Path("/proc/version").read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        return False


def _start(command):
    subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=not IS_WINDOWS)


def open_in_bambu(cli: Path, path: Path):
    """Open a 3MF in the Bambu Studio GUI (Windows / Linux: the .3mf may not be associated with it)."""
    if IS_MAC:
        app = next((parent for parent in cli.parents if parent.suffix == ".app"), None)
        _start(["open", "-a", str(app), str(path)] if app else [str(cli), str(path)])
    else:
        _start([str(cli), str(path)])


def reveal(path: Path):
    """Show a file in the file manager; False when there is none (the page shows the path instead)."""
    if IS_MAC:
        _start(["open", "-R", str(path)])
    elif IS_WINDOWS:
        _start(["explorer", f"/select,{path}"])      # returns 1 even when it worked: not checked
    else:
        return open_folder(path.parent)
    return True


def open_folder(folder: Path):
    """Open a folder in the file manager; False when there is none."""
    if IS_MAC:
        _start(["open", str(folder)])
    elif IS_WINDOWS:
        _start(["explorer", str(folder)])
    elif is_wsl() and shutil.which("explorer.exe") and shutil.which("wslpath"):
        _start(["explorer.exe", subprocess.run(["wslpath", "-w", str(folder)], capture_output=True, text=True).stdout.strip()])
    elif shutil.which("xdg-open") and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        _start(["xdg-open", str(folder)])
    else:
        return False
    return True


def open_browser(url):
    """False when no browser could be started (WSL, a server without a desktop): copy the link from the terminal."""
    if not (IS_MAC or IS_WINDOWS) and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return False
    try:
        return webbrowser.open(url)
    except webbrowser.Error:
        return False


def peak_memory_mb():
    """{"server", "builds"} peak resident memory (MB) on macOS / Linux; None on Windows (not shown there)."""
    try:
        import resource
    except ImportError:
        return None
    scale = 1024 * 1024 if IS_MAC else 1024
    return {"server": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / scale),
            "builds": round(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / scale)}
