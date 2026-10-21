"""Local web UI: stdlib ThreadingHTTPServer on 127.0.0.1, one static page, JSON API (webui design 4, 5).

Security (the page shows and builds the numbers and texts):
- binds 127.0.0.1 only, on a random port; Host must be 127.0.0.1:<port> or localhost:<port> (DNS rebinding);
- every /api/ request needs the per-launch token in the X-Plate-Token header (the page takes it from the URL fragment,
  which never reaches a server or a log); no CORS headers at all, so other origins cannot send that header;
- Origin and Sec-Fetch-Site, when the browser sends them, must be this page (a link elsewhere may open the page
  itself); POST bodies are JSON (<= 2 MB) only;
- CSP 'self' (images also blob:), no inline script; API replies are no-store; the access log (--verbose) shows the
  method, path and status only.
The page opens at once; build123d and the font load in the background (seconds; 1-2 min the first time after
a new .venv), the API waits for them.
"""
import argparse
import hmac
import json
import secrets
import signal
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from ..params import OUT_DIR
from . import platform

STATIC_DIR = Path(__file__).resolve().parent / "static"
PACKAGE_DIR = Path(__file__).resolve().parents[1]          # src/tissueplate: where a bug's place is looked for
STATIC_FILES = {"/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                "/style.css": ("style.css", "text/css; charset=utf-8")}
CONTENT_TYPES = {".3mf": "application/vnd.ms-package.3dmanufacturing-3dmodel+xml", ".stl": "model/stl",
                 ".step": "model/step", ".png": "image/png", ".md": "text/markdown; charset=utf-8",
                 ".json": "application/json", ".txt": "text/plain; charset=utf-8", ".log": "text/plain; charset=utf-8",
                 ".toml": "application/toml", ".gcode": "text/plain; charset=utf-8", ".zip": "application/zip"}
CSP = ("default-src 'self'; img-src 'self' blob:; object-src 'none'; base-uri 'none'; form-action 'none'; "
       "frame-ancestors 'none'")
TOKEN_HEADER = "X-Plate-Token"
MAX_BODY = 2 * 1024 * 1024
CHUNK = 1024 * 1024
READY_WAIT = 600                  # s the API waits for the background imports (a new .venv: 1-2 min, slower PCs more)
ROUTES = {("GET", "/api/status"): "status", ("GET", "/api/schema"): "schema", ("POST", "/api/validate"): "validate",
          ("POST", "/api/preview"): "preview", ("GET", "/api/config"): "config_read", ("POST", "/api/config"): "config_save",
          ("POST", "/api/config/export"): "config_export", ("POST", "/api/config/import"): "config_import",
          ("POST", "/api/build"): "build", ("GET", "/api/jobs"): "job_list", ("POST", "/api/open"): "open_output",
          ("POST", "/api/fonts/reveal"): "fonts_reveal"}
JOB_ROUTES = {("GET", ""): "job_status", ("GET", "/files"): "job_files", ("GET", "/file"): "job_file",
              ("GET", "/zip"): "job_zip", ("POST", "/cancel"): "job_cancel", ("POST", "/delete"): "job_delete"}


class Refused(Exception):
    def __init__(self, status, text):
        super().__init__(text)
        self.status, self.text = status, text


def report_bug(error):
    """A bug: its type and place in the terminal, never its message, which may hold a value (design 5.2). The place
    is the deepest frame in this package, not in the library it called."""
    frames = traceback.extract_tb(error.__traceback__)
    ours = [frame for frame in frames if Path(frame.filename).resolve().is_relative_to(PACKAGE_DIR)]
    place = (ours or frames)[-1]
    print(f"内部错误：{type(error).__name__}（{Path(place.filename).name}:{place.lineno}）", file=sys.stderr, flush=True)


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        """What escapes a handler (a page that left while its connection idled, a bug): never a traceback."""
        error = sys.exc_info()[1]
        if not isinstance(error, ConnectionError):
            report_bug(error)


class App:
    """Per-launch state shared by the request threads."""

    def __init__(self, port, token, verbose):
        self.port, self.token, self.verbose = port, token, verbose
        self.hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        self.origins = {f"http://{host}" for host in self.hosts}
        self.api, self.ready, self.failed = None, threading.Event(), None
        self.stop_server = None               # set by serve()

    def load(self, jobs_root, keep, example):
        """Background: import the pipeline (build123d, fonts), detect Bambu Studio, warm the previews."""
        started = time.time()
        try:
            from .api import Api
            self.api = Api(jobs_root, keep=keep, example=example)
        except Exception as error:          # shown to the page as 503, the server keeps running for the message
            self.failed = f"{type(error).__name__}: {error}"
            linux = sys.platform.startswith("linux") and isinstance(error, (ImportError, OSError))
            print(f"加载构建程序失败：{self.failed}" + ("（Linux 上先装 README「三个平台」里的系统包）" if linux else ""),
                  file=sys.stderr, flush=True)
        finally:
            self.ready.set()
        if self.api is not None:
            print(f"构建程序已加载（{time.time() - started:.0f} s），页面可以用了。", flush=True)
            from . import faces
            try:
                faces.preview("A", {}, "full")
                faces.preview("L", {}, "full")
            except Exception:
                pass                          # a missing font shows on the page


class Handler(BaseHTTPRequestHandler):
    server_version = "parking-plate"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    app = None                            # set by serve()

    def version_string(self):
        return self.server_version

    def log_request(self, code="-", size="-"):
        if self.app.verbose:
            sys.stderr.write(f"{self.command} {urlsplit(self.path).path} {code}\n")

    def log_error(self, format, *args):
        pass

    # ---------------- replies
    def security_headers(self, cache):
        for name, value in (("Content-Security-Policy", CSP), ("X-Content-Type-Options", "nosniff"),
                            ("Referrer-Policy", "no-referrer"), ("X-Frame-Options", "DENY"),
                            ("Cross-Origin-Opener-Policy", "same-origin"), ("Cross-Origin-Resource-Policy", "same-origin"),
                            ("Cache-Control", cache)):
            self.send_header(name, value)

    def reply(self, status, body, content_type="application/json; charset=utf-8", cache="no-store", headers=()):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.sent = True
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.security_headers(cache)
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def send_download(self, download):
        with download.handle as handle:
            self.sent = True
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPES.get(Path(download.name).suffix.lower(), "application/octet-stream"))
            self.send_header("Content-Length", str(download.size))
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(download.name)}")
            self.security_headers("no-store")
            self.end_headers()
            while chunk := handle.read(CHUNK):
                self.wfile.write(chunk)

    # ---------------- checks
    def check_request(self, path):
        """Refused(403) unless the request comes from this page; /api/ also needs the token."""
        app = self.app
        if self.headers.get("Host", "") not in app.hosts:
            raise Refused(403, "unexpected Host header")
        site = self.headers.get("Sec-Fetch-Site")
        # opening the page itself from a link in another page (a chat, a note) is fine: it holds no numbers, and the
        # API still needs the token and a same-origin caller (decided 10-20)
        opening_page = (path == "/" and self.headers.get("Sec-Fetch-Mode") == "navigate"
                        and self.headers.get("Sec-Fetch-Dest") == "document")
        if site is not None and site not in ("same-origin", "none") and not opening_page:
            raise Refused(403, "cross-site request")
        if path.startswith("/api/"):
            origin = self.headers.get("Origin")
            if origin is not None and origin not in app.origins:
                raise Refused(403, "foreign Origin")
            token = self.headers.get(TOKEN_HEADER, "").encode("utf-8", "replace")
            if not hmac.compare_digest(token, app.token.encode("utf-8")):
                raise Refused(403, "missing or wrong token")

    def read_json(self):
        if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
            raise Refused(415, "POST bodies must be application/json")
        if self.headers.get("Transfer-Encoding"):
            raise Refused(411, "send Content-Length")
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            raise Refused(411, "send Content-Length") from None
        if length < 0 or length > MAX_BODY:
            raise Refused(413, "body too large")
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, RecursionError):                # RecursionError: nested too deep
            raise Refused(400, "invalid JSON") from None
        if not isinstance(body, dict):
            raise Refused(400, "JSON object expected")
        return body

    # ---------------- methods
    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def refuse_method(self):
        self.close_connection = True
        self.reply(405, {"error": "method not allowed"}, headers=(("Allow", "GET, POST"),))

    do_OPTIONS = do_PUT = do_DELETE = do_PATCH = do_HEAD = refuse_method

    def target(self):
        try:
            return urlsplit(self.path)
        except ValueError:                    # e.g. an unclosed IPv6 host: "GET http://[::1/ HTTP/1.1"
            raise Refused(400, "bad request target") from None

    def dispatch(self, method):
        self.sent = False                     # a reply has started (one connection may carry several requests)
        try:
            url = self.target()
            self.check_request(url.path)
            if method == "GET" and url.path in STATIC_FILES:
                name, content_type = STATIC_FILES[url.path]
                self.reply(200, (STATIC_DIR / name).read_bytes(), content_type, cache="no-cache")
                return
            if not url.path.startswith("/api/"):
                raise Refused(404, "not found")
            body = self.read_json() if method == "POST" else None
            self.call_api(method, url.path, body, {key: values[-1] for key, values in parse_qs(url.query).items()})
        except Refused as refused:
            self.close_connection = True
            self.reply(refused.status, {"error": refused.text})     # the page may have left: Server.handle_error
        except ConnectionError:               # the page went away (on Windows also ConnectionAbortedError)
            self.close_connection = True
        except Exception as error:            # a bug outside the endpoints: as in call_api, never the traceback
            self.close_connection = True
            report_bug(error)
            if not self.sent:
                self.reply(500, {"error": f"内部错误（{type(error).__name__}）：终端里有出错的位置"})

    def call_api(self, method, path, body, query):
        app = self.app
        if (method, path) == ("POST", "/api/shutdown"):      # also while loading or after a failed load
            self.close_connection = True
            try:
                self.reply(200, {"stopping": True})           # first: the process ends right after the stop
            finally:
                app.stop_server()                             # also when the page left before the reply
            return
        if not app.ready.wait(READY_WAIT) or app.api is None:
            raise Refused(503, f"the server could not load the build pipeline ({app.failed or 'still loading'})")
        from .api import Download, HttpError
        name, arguments = ROUTES.get((method, path)), (body if method == "POST" else query,)
        if name is None and path.startswith("/api/jobs/"):
            job_id, _, action = path[len("/api/jobs/"):].partition("/")
            name = JOB_ROUTES.get((method, f"/{action}" if action else ""))
            arguments = (job_id,) + arguments
        if name is None:
            raise Refused(404 if method in ("GET", "POST") else 405, "not found")
        try:
            result = getattr(app.api, name)(*arguments)
            if not isinstance(result, Download):      # encoded here: a value JSON cannot hold (NaN) is a bug too
                status, payload = result
                result = status, json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except HttpError as error:
            raise Refused(error.status, error.text) from None
        except Exception as error:            # a bug: the page gets a reply, the terminal no value (design 5.2)
            report_bug(error)
            raise Refused(500, f"内部错误（{type(error).__name__}）：终端里有出错的位置") from None
        if isinstance(result, Download):
            self.send_download(result)
        else:
            self.reply(*result)


def serve(port=0, keep=5, open_browser=True, example=False, verbose=False):
    server = Server(("127.0.0.1", port), Handler)
    port = server.server_address[1]
    app = App(port, secrets.token_urlsafe(32), verbose)
    app.stop_server = server.shutdown
    Handler.app = app
    threading.Thread(target=app.load, args=(OUT_DIR / "web", keep, example), daemon=True).start()
    url = f"http://127.0.0.1:{port}/#token={app.token}"
    mode = "（示例模式：不读写 config.toml）" if example else ""
    print(f"挪车号码牌网页已启动{mode}，只有这台电脑能打开：\n  {url}", flush=True)
    if not (open_browser and platform.open_browser(url)):
        print("把上面这条链接复制到浏览器里打开。", flush=True)
    print("按 Ctrl+C 或关掉这个窗口停止服务器（正在跑的构建也会停）。", flush=True)
    print("正在后台加载构建程序（新建的环境第一次可能要 1–2 分钟，以后几秒）……", flush=True)

    def interrupt(signum, frame):
        raise KeyboardInterrupt

    for name in ("SIGTERM", "SIGHUP", "SIGBREAK"):        # SIGHUP: the terminal window closed; SIGBREAK: Windows
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), interrupt)
    started = time.time()
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        if app.api is not None:
            app.api.jobs.stop_all()
        server.server_close()
        print(f"服务器已停止（运行了 {(time.time() - started) / 60:.0f} 分钟）。", flush=True)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local web UI of the parking plate generator (127.0.0.1 only).")
    parser.add_argument("--port", type=int, default=0, help="port (default: a free one)")
    parser.add_argument("--keep", type=int, default=5, help="finished builds kept in out/web (default 5)")
    parser.add_argument("--no-browser", action="store_true", help="only print the link")
    parser.add_argument("--example", action="store_true", help="example config only: never reads or writes config.toml")
    parser.add_argument("--verbose", action="store_true", help="access log (method, path, status)")
    args = parser.parse_args(argv)
    return serve(args.port, max(1, args.keep), not args.no_browser, args.example, args.verbose)
