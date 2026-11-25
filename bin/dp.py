#!/usr/bin/env python3
"""Desktop Pilot CLI.

Every subcommand prints one JSON object. Mutating commands check
`runtime/STOP` first, log the action, and return a nonzero exit code on
failure. The CLI is intentionally stateless: each invocation resolves windows
and UIA elements fresh, so there are no stale handles between DSH tool calls.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT))

import ocr_bridge  # noqa: E402
import runtime  # noqa: E402
import uia_bridge  # noqa: E402
import win32  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse_pair(text: str, name: str = "point") -> tuple[int, int]:
    parts = re.split(r"[,x\s]+", text.strip())
    if len(parts) != 2:
        raise ValueError(f"{name} must be 'x,y', got {text!r}")
    return int(parts[0]), int(parts[1])


def parse_region(text: str) -> tuple[int, int, int, int]:
    parts = re.split(r"[,x\s]+", text.strip())
    if len(parts) != 4:
        raise ValueError(f"region must be 'x,y,width,height', got {text!r}")
    return tuple(int(p) for p in parts)  # type: ignore[return-value]


def add_window_args(parser: argparse.ArgumentParser, foreground: bool = True) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--window", type=int, help="window handle")
    group.add_argument("--title", help="window title substring")
    group.add_argument("--pid", type=int, help="process id")
    if foreground:
        group.add_argument("--foreground", action="store_true", help="use the foreground window")


def resolve_window(args: argparse.Namespace, required: bool = True) -> dict[str, Any] | None:
    handle = getattr(args, "window", None)
    title = getattr(args, "title", None)
    pid = getattr(args, "pid", None)
    if not handle and not title and pid is None:
        if getattr(args, "foreground", False):
            handle = win32.get_foreground_window()
        elif required:
            raise ValueError("specify --window, --title, or --pid")
        else:
            return None
    return win32.resolve_window(handle=handle, title=title, pid=pid)


def focus_for(args: argparse.Namespace) -> dict[str, Any] | None:
    window = resolve_window(args, required=False)
    if window:
        win32.focus_window(window["handle"])
    return window


def capture_from_args(args: argparse.Namespace, label: str = "screen") -> tuple[Any, dict[str, Any], Path]:
    if getattr(args, "window", None) or getattr(args, "title", None) or getattr(args, "pid", None):
        window = resolve_window(args)
        img, meta = win32.capture_window(window["handle"], cursor=not getattr(args, "no_cursor", False))
        meta["window"] = window
        label = f"window-{window['handle']}"
    elif getattr(args, "monitor", None) is not None:
        monitors = win32.get_monitors()
        index = int(args.monitor)
        if index < 0 or index >= len(monitors):
            raise ValueError(f"monitor index {index} out of range (0..{len(monitors) - 1})")
        rect = monitors[index]["rect"]
        img, meta = win32.capture_region(rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1], cursor=not getattr(args, "no_cursor", False))
        meta["monitor"] = monitors[index]
        label = f"monitor-{index}"
    elif getattr(args, "region", None):
        x, y, width, height = parse_region(args.region)
        img, meta = win32.capture_region(x, y, width, height, cursor=not getattr(args, "no_cursor", False))
        label = "region"
    else:
        img, meta = win32.capture_screen(cursor=not getattr(args, "no_cursor", False))
    out = Path(args.out) if getattr(args, "out", None) else runtime.new_shot_path(label)
    win32.save_image(img, str(out), quality=getattr(args, "quality", 88))
    return img, meta, out.resolve()


def parse_shot_args(parser: argparse.ArgumentParser) -> None:
    add_window_args(parser, foreground=False)
    parser.add_argument("--monitor", type=int, help="monitor index")
    parser.add_argument("--region", help="x,y,width,height")
    parser.add_argument("--out", help="output image path")
    parser.add_argument("--quality", type=int, default=88)
    parser.add_argument("--no-cursor", action="store_true", help="do not draw the cursor marker")


def uia_root(args: argparse.Namespace):
    handle = getattr(args, "window", None)
    if not handle and (getattr(args, "title", None) or getattr(args, "pid", None)):
        handle = resolve_window(args)["handle"]
    return uia_bridge.root_control(window_handle=handle, foreground=bool(getattr(args, "foreground", False)))


def _uia_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "name": getattr(args, "find", None),
        "control_type": getattr(args, "type", None),
        "automation_id": getattr(args, "id", None),
        "class_name": getattr(args, "class_name", None),
        "exact": bool(getattr(args, "exact", False)),
        "max_depth": int(getattr(args, "depth", 12)),
    }


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_doctor(args: argparse.Namespace) -> dict[str, Any]:
    info = runtime.project_info()
    info.update(win32.describe())
    checks: dict[str, Any] = {}

    try:
        root = uia_bridge.root_control(foreground=True)
        top = uia_bridge.control_info(root)
        checks["uia"] = {"ok": True, "foreground_control": top}
    except Exception as exc:
        checks["uia"] = {"ok": False, "error": str(exc)}

    try:
        langs = ocr_bridge.languages()
        checks["ocr"] = {"ok": bool(langs), "languages": langs, "script": str(ocr_bridge.SCRIPT), "powershell": ocr_bridge.POWERSHELL}
    except Exception as exc:
        checks["ocr"] = {"ok": False, "error": str(exc)}

    checks["stop"] = {"active": runtime.is_stopped(), "path": str(runtime.STOP)}
    checks["skill_link"] = runtime.skill_link_state()
    checks["paths"] = {"root": str(runtime.ROOT), "shots": str(runtime.SHOTS), "log": str(runtime.LOG)}
    info["checks"] = checks
    info["ok"] = True
    return info


def cmd_windows(args: argparse.Namespace) -> dict[str, Any]:
    items = win32.list_windows(include_hidden=bool(args.all), include_untitled=bool(args.all))
    if args.title:
        items = [w for w in items if args.title.lower() in (w["title"] or "").lower()]
    if args.class_name:
        items = [w for w in items if args.class_name.lower() in (w["class"] or "").lower()]
    if args.pid is not None:
        items = [w for w in items if w["pid"] == args.pid]
    return {"ok": True, "count": len(items), "windows": items}


def cmd_screen(args: argparse.Namespace) -> dict[str, Any]:
    img, meta, path = capture_from_args(args, label="screen")
    result = {"ok": True, "path": str(path), "size": list(img.size), "bbox": meta.get("bbox"), "method": meta.get("method"), "window": meta.get("window"), "monitor": meta.get("monitor")}
    runtime.log_event("screen", {"path": str(path), "size": result["size"], "bbox": result["bbox"], "window": meta.get("window", {}).get("handle") if meta.get("window") else None})
    return result


def cmd_focus(args: argparse.Namespace) -> dict[str, Any]:
    runtime.require_running()
    window = resolve_window(args)
    focused = win32.focus_window(window["handle"])
    runtime.log_event("focus", {"window": window["handle"], "title": window["title"], "focused": focused})
    return {"ok": True, "focused": focused, "window": win32.get_window_info(window["handle"])}


def cmd_launch(args: argparse.Namespace) -> dict[str, Any]:
    runtime.require_running()
    target = args.target
    started = None
    method = ""
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", target):
        os.startfile(target)  # type: ignore[attr-defined]
        method = "startfile-url"
    elif target.lower().endswith((".exe", ".bat", ".cmd")) and Path(target).exists():
        command = [str(Path(target).resolve())]
        if args.args:
            command += shlex.split(args.args)
        started = subprocess.Popen(command, cwd=args.cwd or None)
        method = "process"
    else:
        os.startfile(target)  # type: ignore[attr-defined]
        method = "startfile"
    result: dict[str, Any] = {"ok": True, "target": target, "method": method, "pid": started.pid if started else None}
    if args.wait_title:
        deadline = time.time() + args.timeout
        while time.time() < deadline:
            matches = win32.find_windows(title=args.wait_title)
            if matches:
                result["window"] = matches[0]
                break
            time.sleep(0.25)
        else:
            result["ok"] = False
            result["error"] = f"no window matching {args.wait_title!r} within {args.timeout}s"
    runtime.log_event("launch", {"target": target, "method": method, "pid": result.get("pid"), "window": (result.get("window") or {}).get("handle")})
    return result


def cmd_uia(args: argparse.Namespace) -> dict[str, Any]:
    if args.click or args.invoke or args.set_value is not None or args.read or args.focus:
        runtime.require_running()
    root = uia_root(args)
    kwargs = _uia_kwargs(args)
    filter_values = {k: v for k, v in kwargs.items() if k != "max_depth"}
    has_filter = any(filter_values.values()) or bool(args.path)

    if not has_filter:
        tree = uia_bridge.dump_tree(root, max_depth=args.depth, max_nodes=args.max_nodes)
        return {"ok": True, "tree": tree}

    if args.path:
        ctrl = uia_bridge.select_path(root, args.path)
        info = uia_bridge.control_info(ctrl)
        info["path"] = args.path
        matches = [info]
    else:
        matches = uia_bridge.find_all(root, **kwargs, max_nodes=args.max_nodes)
        if not matches:
            return {"ok": False, "error": "no matching UIA control", "filter": kwargs}
        ctrl = uia_bridge.select_path(root, matches[0]["path"])
        info = matches[0]

    if args.focus:
        try:
            ctrl.SetFocus()
            info["focused"] = True
        except Exception as exc:
            info["focus_error"] = str(exc)

    if args.read:
        read = uia_bridge.read_text(ctrl)
        info["read"] = read

    action = None
    if args.invoke:
        action = uia_bridge.activate(ctrl, method="invoke")
    elif args.click:
        action = uia_bridge.activate(ctrl, method="auto")
    elif args.set_value is not None:
        action = uia_bridge.set_value(ctrl, args.set_value)

    result = {"ok": True, "matched": info, "matches": matches if args.all else None, "action": action}
    if args.all:
        result["count"] = len(matches)
    runtime.log_event("uia", {"window": (resolve_window(args, required=False) or {}).get("handle") if (args.window or args.title or args.pid) else None, "filter": kwargs, "path": info.get("path"), "action": action})
    return result


def cmd_click(args: argparse.Namespace) -> dict[str, Any]:
    runtime.require_running()
    if args.uia:
        root = uia_root(args)
        matches = uia_bridge.find_all(root, name=args.uia, control_type=args.uia_type, exact=args.exact, max_depth=args.depth)
        if not matches:
            return {"ok": False, "error": f"no UIA control matching {args.uia!r}"}
        ctrl = uia_bridge.select_path(root, matches[0]["path"])
        action = uia_bridge.activate(ctrl, method="auto")
        runtime.log_event("click", {"uia": args.uia, "action": action})
        return {"ok": True, "action": action, "matched": matches[0]}

    window = focus_for(args)
    if args.point:
        x, y = parse_pair(args.point)
    elif args.x is not None and args.y is not None:
        x, y = int(args.x), int(args.y)
    elif args.rel:
        if not window:
            return {"ok": False, "error": "--rel requires --window/--title/--pid"}
        base = window["client_rect"] if args.client and window.get("client_rect") else window["rect"]
        rx, ry = parse_pair(args.rel)
        x, y = base[0] + rx, base[1] + ry
    else:
        return {"ok": False, "error": "provide --x/--y, --point, --rel, or --uia"}
    win32.mouse_click(x, y, button=args.button, count=args.count, hold_ms=args.hold_ms)
    runtime.log_event("click", {"x": x, "y": y, "button": args.button, "count": args.count, "window": window["handle"] if window else None})
    return {"ok": True, "x": x, "y": y, "button": args.button, "count": args.count, "window": window}


def cmd_type(args: argparse.Namespace) -> dict[str, Any]:
    runtime.require_running()
    text = args.text
    if text is None and args.file:
        text = Path(args.file).read_text(encoding="utf-8")
    if text is None:
        return {"ok": False, "error": "provide --text or --file"}
    window = focus_for(args)
    target = None
    if args.uia:
        root = uia_root(args)
        matches = uia_bridge.find_all(root, name=args.uia, control_type=args.uia_type, exact=args.exact, max_depth=args.depth)
        if not matches:
            return {"ok": False, "error": f"no UIA control matching {args.uia!r}"}
        ctrl = uia_bridge.select_path(root, matches[0]["path"])
        try:
            ctrl.SetFocus()
            time.sleep(0.08)
        except Exception:
            pass
        target = matches[0]
        if args.replace:
            replaced = uia_bridge.set_value(ctrl, text)
            runtime.log_event("type", {"method": "uia-set-value", "chars": len(text), "secret": bool(args.secret), "target": target.get("name")})
            return {"ok": bool(replaced.get("ok")), "method": "uia-set-value", "chars": len(text), "secret": bool(args.secret), "result": replaced, "target": target}
        if args.clear:
            uia_bridge.set_value(ctrl, "")
    method = win32.type_text(text, method=args.method, interval=args.interval)
    if args.enter:
        time.sleep(0.1)
        win32.press_vk(win32.VK["enter"])
    runtime.log_event("type", {"method": method, "chars": len(text), "secret": bool(args.secret), "window": window["handle"] if window else None, "target": (target or {}).get("name")})
    out = {"ok": True, "method": method, "chars": len(text), "secret": bool(args.secret), "window": window, "target": target}
    if not args.secret:
        out["text"] = text
    return out


DANGEROUS = {
    "alt+f4",
    "win+r",
    "win+l",
    "win+x",
    "win+s",
    "win+a",
    "ctrl+shift+esc",
    "ctrl+alt+delete",
    "ctrl+alt+del",
    "alt+tab",
    "win+d",
    "win+e",
}


def cmd_key(args: argparse.Namespace) -> dict[str, Any]:
    runtime.require_running()
    normalized = re.sub(r"\s+", "", args.keys.lower())
    if normalized in DANGEROUS and not args.allow_dangerous:
        return {"ok": False, "error": f"refusing dangerous key combo {args.keys!r}; pass --allow-dangerous", "code": "dangerous-key"}
    window = focus_for(args)
    win32.key_combo(args.keys, repeat=args.repeat)
    runtime.log_event("key", {"keys": args.keys, "repeat": args.repeat, "window": window["handle"] if window else None, "dangerous": normalized in DANGEROUS})
    return {"ok": True, "keys": args.keys, "repeat": args.repeat, "window": window}


def cmd_scroll(args: argparse.Namespace) -> dict[str, Any]:
    runtime.require_running()
    window = focus_for(args)
    win32.mouse_scroll(args.amount, x=args.x, y=args.y)
    runtime.log_event("scroll", {"amount": args.amount, "x": args.x, "y": args.y, "window": window["handle"] if window else None})
    return {"ok": True, "amount": args.amount, "x": args.x, "y": args.y}


def cmd_drag(args: argparse.Namespace) -> dict[str, Any]:
    runtime.require_running()
    x1, y1 = parse_pair(args.from_point)
    x2, y2 = parse_pair(args.to_point)
    window = focus_for(args)
    win32.mouse_drag(x1, y1, x2, y2, button=args.button, duration=args.duration)
    runtime.log_event("drag", {"from": [x1, y1], "to": [x2, y2], "window": window["handle"] if window else None})
    return {"ok": True, "from": [x1, y1], "to": [x2, y2], "button": args.button}


def cmd_clipboard(args: argparse.Namespace) -> dict[str, Any]:
    if args.set is not None or args.clear:
        runtime.require_running()
    if args.clear:
        result = win32.clear_clipboard()
        runtime.log_event("clipboard", {"action": "clear", "ok": result})
        return {"ok": bool(result), "action": "clear"}
    if args.set is not None:
        result = win32.set_clipboard_text(args.set)
        runtime.log_event("clipboard", {"action": "set", "chars": len(args.set), "secret": bool(args.secret)})
        out = {"ok": bool(result), "action": "set", "chars": len(args.set), "secret": bool(args.secret)}
        if not args.secret:
            out["text"] = args.set
        return out
    text = win32.get_clipboard_text()
    return {"ok": text is not None, "text": text, "chars": len(text or "")}


def cmd_ocr(args: argparse.Namespace) -> dict[str, Any]:
    if args.click:
        runtime.require_running()
    img, meta, path = capture_from_args(args, label="ocr")
    origin = meta["bbox"][:2]
    result = ocr_bridge.ocr_file(path, language=args.language, origin=origin)
    result["path"] = str(path)
    result["capture"] = meta
    matches = ocr_bridge.find(result, args.find, exact=args.exact, first=not args.all) if args.find else []
    result["matches"] = matches
    result["matched"] = matches[0] if matches else None
    if args.find and not matches:
        result["ok"] = False
        result["error"] = f"OCR text {args.find!r} not found"
    if args.click and matches:
        center = matches[0]["center"]
        win32.mouse_click(center[0], center[1])
        result["clicked"] = center
        runtime.log_event("ocr-click", {"text": args.find, "center": center, "path": str(path)})
    if args.max_lines and len(result.get("lines") or []) > args.max_lines:
        result["lines_total"] = len(result["lines"])
        result["lines"] = result["lines"][: args.max_lines]
        result["truncated"] = True
    runtime.log_event("ocr", {"path": str(path), "find": args.find, "count": result.get("count"), "matched": bool(matches)})
    return result


def cmd_wait(args: argparse.Namespace) -> dict[str, Any]:
    deadline = time.time() + args.timeout
    last_error = None
    while time.time() < deadline:
        try:
            matches = win32.find_windows(title=args.window_title, pid=args.pid, include_hidden=False)
            if args.process:
                matches = [w for w in matches if (w.get("process") or "").lower() == args.process.lower()]
            if matches:
                return {"ok": True, "waited": round(args.timeout - max(0, deadline - time.time()), 2), "window": matches[0]}
        except Exception as exc:
            last_error = str(exc)
        time.sleep(args.interval)
    return {"ok": False, "error": "timeout waiting for window", "last_error": last_error}


def cmd_stop(args: argparse.Namespace) -> dict[str, Any]:
    return runtime.stop(args.reason or "")


def cmd_resume(args: argparse.Namespace) -> dict[str, Any]:
    return runtime.resume()


def cmd_tour(args: argparse.Namespace) -> dict[str, Any]:
    """Open a note in Notepad, type into it, read it back, and photograph it."""
    runtime.require_running()
    runtime.ensure_dirs()
    note = runtime.TMP / f"desktop-pilot-tour-{runtime.stamp()}.txt"
    info = win32.describe()
    screen = info["screen"]
    host = None
    try:
        fg = win32.get_foreground_window()
        host = win32.get_window_info(fg) if fg else None
    except Exception:
        host = None
    text = (
        "Desktop Pilot / 首次桌面握手\n"
        f"宿主: {os.environ.get('COMPUTERNAME', 'unknown')}\n"
        f"屏幕: {screen['screen_width']}x{screen['screen_height']} @ {info['dpi']} DPI\n"
        f"运行我的窗口: {(host or {}).get('title', 'unknown')}\n"
        f"时间: {runtime.now_iso()}\n"
        "---\n"
        "这条文字由 DSH 写入 Windows 11 记事本的 RichEdit 控件，\n"
        "再用 UI Automation 逐字读回。没有截图识别，没有视觉模型。\n"
    )
    note.write_text(text, encoding="utf-8")
    os.startfile(str(note))

    deadline = time.time() + 12
    window = None
    while time.time() < deadline:
        matches = win32.find_windows(title=note.name, include_hidden=False)
        if matches:
            window = matches[0]
            break
        time.sleep(0.25)
    if not window:
        return {"ok": False, "error": "Notepad window did not appear", "note": str(note)}

    win32.focus_window(window["handle"])
    time.sleep(0.4)
    root = uia_bridge.root_control(window_handle=window["handle"])
    matches = uia_bridge.find_all(root, name="文本编辑器", max_depth=10)
    if not matches:
        matches = uia_bridge.find_all(root, class_name="RichEditD2DPT", max_depth=10)
    if not matches:
        return {"ok": False, "error": "document control not found", "window": window, "note": str(note)}
    target = matches[0]
    ctrl = uia_bridge.select_path(root, target["path"])
    uia_bridge.activate(ctrl, method="click")
    time.sleep(0.3)
    before = uia_bridge.read_text(ctrl)

    suffix = f"\n[read-back ok] {runtime.now_iso()}\n"
    method = win32.type_text(suffix, method="clipboard")
    time.sleep(0.35)
    after = uia_bridge.read_text(ctrl)

    image, meta = win32.capture_window(window["handle"], cursor=False)
    shot = runtime.new_shot_path("tour")
    win32.save_image(image, str(shot))
    runtime.log_event("tour", {"note": str(note), "window": window["handle"], "read_chars": len(after.get("text", ""))})
    return {
        "ok": bool(after.get("ok")) and "read-back ok" in after.get("text", ""),
        "note": str(note),
        "window": window,
        "method": method,
        "before": before,
        "after": after,
        "screenshot": str(shot),
        "screenshot_size": list(image.size),
        "capture": meta,
    }


def cmd_status(args: argparse.Namespace) -> dict[str, Any]:
    info = runtime.project_info()
    info["uia"] = {"available": True}
    try:
        info["foreground"] = win32.get_window_info(win32.get_foreground_window()) if win32.get_foreground_window() else None
    except Exception as exc:
        info["foreground_error"] = str(exc)
    info["recent"] = runtime.tail_log(args.tail)
    info["ok"] = True
    return info


def cmd_log(args: argparse.Namespace) -> dict[str, Any]:
    return {"ok": True, "count": args.tail, "events": runtime.tail_log(args.tail)}


def cmd_console(args: argparse.Namespace) -> dict[str, Any]:
    from console.server import serve

    serve(port=args.port, open_browser=not args.no_open, token=args.token)
    return {"ok": True, "stopped": True}


def _run_ps(script: str, *extra: str) -> dict[str, Any]:
    powershell = ocr_bridge.POWERSHELL
    path = runtime.ROOT / "scripts" / script
    proc = subprocess.run(
        [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(path), *extra],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    out = (proc.stdout or "").strip()
    try:
        data = json.loads(out)
    except Exception:
        data = {"ok": proc.returncode == 0, "stdout": out, "stderr": (proc.stderr or "").strip(), "exit": proc.returncode}
    if proc.returncode not in (0, None):
        data.setdefault("ok", False)
        data.setdefault("error", (proc.stderr or out or f"exit {proc.returncode}").strip()[:2000])
    return data


def cmd_install(args: argparse.Namespace) -> dict[str, Any]:
    extra = ["-ProjectRoot", str(runtime.ROOT)]
    if args.force:
        extra.append("-Force")
    return _run_ps("install.ps1", *extra)


def cmd_uninstall(args: argparse.Namespace) -> dict[str, Any]:
    return _run_ps("uninstall.ps1", "-ProjectRoot", str(runtime.ROOT))


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dp", description="Desktop Pilot — Windows desktop control for DSH")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("doctor", help="environment and capability check")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("windows", help="list windows")
    p.add_argument("--all", action="store_true", help="include hidden and untitled windows")
    p.add_argument("--title", help="title substring")
    p.add_argument("--class", dest="class_name", help="class substring")
    p.add_argument("--pid", type=int)
    p.set_defaults(func=cmd_windows)

    p = sub.add_parser("screen", help="capture the screen, a window, a monitor, or a region")
    parse_shot_args(p)
    p.set_defaults(func=cmd_screen)

    p = sub.add_parser("focus", help="focus a window")
    add_window_args(p, foreground=False)
    p.set_defaults(func=cmd_focus)

    p = sub.add_parser("launch", help="launch an exe, file, or URL")
    p.add_argument("--target", required=True)
    p.add_argument("--args", help="arguments for an exe")
    p.add_argument("--cwd")
    p.add_argument("--wait-title", help="wait until a window title contains this")
    p.add_argument("--timeout", type=float, default=10)
    p.set_defaults(func=cmd_launch)

    p = sub.add_parser("uia", help="inspect or act on the UI Automation tree")
    add_window_args(p, foreground=True)
    p.add_argument("--depth", type=int, default=8)
    p.add_argument("--max-nodes", type=int, default=3000)
    p.add_argument("--find", help="name substring")
    p.add_argument("--type", help="control type, e.g. Button or Document")
    p.add_argument("--id", help="automation id substring")
    p.add_argument("--class", dest="class_name", help="class name substring")
    p.add_argument("--exact", action="store_true")
    p.add_argument("--path", help="child-index path, e.g. 0.1.2")
    p.add_argument("--all", action="store_true", help="return all matches")
    p.add_argument("--focus", action="store_true")
    p.add_argument("--read", action="store_true")
    p.add_argument("--invoke", action="store_true")
    p.add_argument("--click", action="store_true")
    p.add_argument("--set-value", dest="set_value", help="set a value-pattern control")
    p.set_defaults(func=cmd_uia)

    p = sub.add_parser("click", help="click coordinates or a UIA control")
    add_window_args(p, foreground=True)
    p.add_argument("--x", type=int)
    p.add_argument("--y", type=int)
    p.add_argument("--point", help="x,y")
    p.add_argument("--rel", help="x,y relative to the window")
    p.add_argument("--client", action="store_true", help="relative to the client area")
    p.add_argument("--uia", help="UIA name to click")
    p.add_argument("--uia-type", default=None, help="UIA control type filter")
    p.add_argument("--exact", action="store_true")
    p.add_argument("--depth", type=int, default=12)
    p.add_argument("--button", choices=["left", "right", "middle"], default="left")
    p.add_argument("--count", type=int, default=1)
    p.add_argument("--hold-ms", type=int, default=0)
    p.set_defaults(func=cmd_click)

    p = sub.add_parser("type", help="type text into the foreground window or a UIA control")
    add_window_args(p, foreground=True)
    p.add_argument("--text")
    p.add_argument("--file", help="read text from a UTF-8 file")
    p.add_argument("--method", choices=["auto", "clipboard", "sendinput"], default="auto")
    p.add_argument("--uia", help="UIA control name to focus/type into")
    p.add_argument("--uia-type")
    p.add_argument("--exact", action="store_true")
    p.add_argument("--depth", type=int, default=12)
    p.add_argument("--replace", action="store_true", help="replace the whole value via UIA")
    p.add_argument("--clear", action="store_true", help="clear the value before typing")
    p.add_argument("--enter", action="store_true")
    p.add_argument("--interval", type=float, default=0.004)
    p.add_argument("--secret", action="store_true")
    p.set_defaults(func=cmd_type)

    p = sub.add_parser("key", help="press a key or key combination")
    add_window_args(p, foreground=True)
    p.add_argument("--keys", required=True)
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--allow-dangerous", action="store_true")
    p.set_defaults(func=cmd_key)

    p = sub.add_parser("scroll", help="scroll the mouse wheel")
    add_window_args(p, foreground=True)
    p.add_argument("--amount", type=int, required=True, help="positive = up")
    p.add_argument("--x", type=int)
    p.add_argument("--y", type=int)
    p.set_defaults(func=cmd_scroll)

    p = sub.add_parser("drag", help="drag from one point to another")
    add_window_args(p, foreground=True)
    p.add_argument("--from", dest="from_point", required=True)
    p.add_argument("--to", dest="to_point", required=True)
    p.add_argument("--button", choices=["left", "right", "middle"], default="left")
    p.add_argument("--duration", type=float, default=0.4)
    p.set_defaults(func=cmd_drag)

    p = sub.add_parser("clipboard", help="read or write the clipboard")
    p.add_argument("--set")
    p.add_argument("--clear", action="store_true")
    p.add_argument("--secret", action="store_true")
    p.set_defaults(func=cmd_clipboard)

    p = sub.add_parser("ocr", help="capture and OCR the screen, window, monitor, or region")
    parse_shot_args(p)
    p.add_argument("--find", help="text to locate")
    p.add_argument("--exact", action="store_true")
    p.add_argument("--all", action="store_true", help="return all matches")
    p.add_argument("--click", action="store_true", help="click the first match")
    p.add_argument("--language", default="zh-Hans-CN")
    p.add_argument("--max-lines", type=int, default=300)
    p.set_defaults(func=cmd_ocr)

    p = sub.add_parser("wait", help="wait for a window")
    p.add_argument("--window-title", required=True)
    p.add_argument("--pid", type=int)
    p.add_argument("--process")
    p.add_argument("--timeout", type=float, default=10)
    p.add_argument("--interval", type=float, default=0.25)
    p.set_defaults(func=cmd_wait)

    p = sub.add_parser("stop", help="create runtime/STOP")
    p.add_argument("--reason", default="")
    p.set_defaults(func=cmd_stop)

    p = sub.add_parser("resume", help="remove runtime/STOP")
    p.set_defaults(func=cmd_resume)

    p = sub.add_parser("tour", help="open a Notepad note, type into it, read it back, and screenshot it")
    p.set_defaults(func=cmd_tour)

    p = sub.add_parser("status", help="project, skill, stop, and recent actions")
    p.add_argument("--tail", type=int, default=10)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("log", help="read the action log")
    p.add_argument("--tail", type=int, default=20)
    p.set_defaults(func=cmd_log)

    p = sub.add_parser("console", help="start the local observation console")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-open", action="store_true")
    p.add_argument("--token", default=None)
    p.set_defaults(func=cmd_console)

    p = sub.add_parser("install", help="install as a DSH skill via directory junction")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_install)

    p = sub.add_parser("uninstall", help="remove the DSH skill junction (keeps this project)")
    p.set_defaults(func=cmd_uninstall)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.func(args)
        if result is None:
            result = {"ok": True}
        runtime.emit(result, 0 if result.get("ok", True) else 1)
    except runtime.StoppedError as exc:
        runtime.emit(runtime.fail(str(exc), code="stopped"), 3)
    except KeyboardInterrupt:
        runtime.emit(runtime.fail("interrupted", code="interrupted"), 130)
    except Exception as exc:
        detail = traceback.format_exc(limit=8)
        runtime.log_event("error", {"command": args.command, "argv": sys.argv[1:]}, ok=False, error=str(exc))
        runtime.emit(runtime.fail(str(exc), code=exc.__class__.__name__, detail=detail), 1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())