"""Local observation console for Desktop Pilot.

Binds 127.0.0.1 only. Read-only endpoints are open to the local machine;
STOP/RESUME require the per-process token printed at startup (also injected
into the page). The console never exposes arbitrary click/type endpoints —
it is an observation and kill-switch surface, not a second remote-control API.
"""

from __future__ import annotations

import json
import mimetypes
import secrets
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import ocr_bridge  # noqa: E402
import runtime  # noqa: E402
import win32  # noqa: E402

STATIC = ROOT / "console" / "static"


class Handler(BaseHTTPRequestHandler):
    server_version = "DesktopPilot/0.1"
    token = ""

    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    # -- helpers ---------------------------------------------------------

    def _send(self, code: int, body: bytes, content_type: str = "application/json; charset=utf-8", extra: dict[str, str] | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if extra:
            for key, value in extra.items():
                self.send_header(key, value)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"))

    def _error(self, code: int, message: str, **extra) -> None:
        self._json(code, {"ok": False, "error": message, **extra})

    def _authorized(self, query: dict[str, list[str]]) -> bool:
        supplied = self.headers.get("X-DP-Token") or (query.get("token") or [""])[0]
        return bool(supplied) and secrets.compare_digest(str(supplied), self.token)

    def _window_from_query(self, query: dict[str, list[str]]) -> dict | None:
        raw = (query.get("window") or [""])[0]
        if not raw or raw in {"screen", "desktop", "all"}:
            return None
        if raw == "foreground":
            handle = win32.get_foreground_window()
            return win32.get_window_info(handle) if handle else None
        return win32.get_window_info(int(raw))

    # -- routes ----------------------------------------------------------

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        try:
            if parsed.path in {"/", "/index.html"}:
                index = STATIC / "index.html"
                if not index.exists():
                    self._error(500, "console/static/index.html missing")
                    return
                html = index.read_text(encoding="utf-8").replace("__DP_TOKEN__", json.dumps(self.token))
                self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
                return
            if parsed.path == "/api/status":
                fg = win32.get_foreground_window()
                self._json(
                    200,
                    {
                        "ok": True,
                        "project": runtime.project_info(),
                        "foreground": win32.get_window_info(fg) if fg else None,
                        "windows": len(win32.list_windows()),
                        "recent": runtime.tail_log(12),
                        "server_time": runtime.now_iso(),
                    },
                )
                return
            if parsed.path == "/api/windows":
                self._json(200, {"ok": True, "windows": win32.list_windows()})
                return
            if parsed.path == "/api/log":
                tail = int((query.get("tail") or ["40"])[0])
                self._json(200, {"ok": True, "events": runtime.tail_log(max(1, min(500, tail)))})
                return
            if parsed.path == "/api/screen":
                window = self._window_from_query(query)
                if window:
                    img, meta = win32.capture_window(window["handle"], cursor=True)
                else:
                    img, meta = win32.capture_screen(cursor=True)
                import io

                buf = io.BytesIO()
                img.save(buf, format="PNG")
                self._send(200, buf.getvalue(), "image/png")
                return
            if parsed.path == "/api/ocr":
                window = self._window_from_query(query)
                language = (query.get("language") or ["zh-Hans-CN"])[0]
                if window:
                    result = ocr_bridge.ocr_window(window["handle"], language=language)
                else:
                    result = ocr_bridge.ocr_screen(language=language)
                find = (query.get("find") or [""])[0]
                if find:
                    result["matches"] = ocr_bridge.find(result, find)
                self._json(200, result)
                return
            if parsed.path == "/favicon.ico":
                self._send(204, b"", "image/x-icon")
                return
            self._error(404, "not found", path=parsed.path)
        except Exception as exc:
            self._error(500, str(exc), path=parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        try:
            if not self._authorized(query):
                self._error(403, "missing or invalid token")
                return
            if parsed.path == "/api/stop":
                self._json(200, runtime.stop("console button"))
                return
            if parsed.path == "/api/resume":
                self._json(200, runtime.resume())
                return
            self._error(404, "not found", path=parsed.path)
        except Exception as exc:
            self._error(500, str(exc), path=parsed.path)


def serve(port: int = 8765, open_browser: bool = True, token: str | None = None) -> None:
    runtime.ensure_dirs()
    token = token or secrets.token_urlsafe(24)
    Handler.token = token
    server = ThreadingHTTPServer(("127.0.0.1", int(port)), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(json.dumps({"ok": True, "url": url, "token": token, "bound": "127.0.0.1"}, ensure_ascii=False), flush=True)
    runtime.log_event("console", {"url": url, "port": port})
    if open_browser:
        threading.Thread(target=lambda: (time.sleep(0.4), webbrowser.open(url)), daemon=True).start()
    try:
        server.serve_forever(poll_interval=0.4)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()
    serve(args.port, open_browser=not args.no_open)