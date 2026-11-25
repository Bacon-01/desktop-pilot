"""Shared runtime state: paths, JSON output, redaction, action log, STOP.

A file named `runtime/STOP` is the single kill switch. Every mutating command
checks it before doing anything; `stop` and `resume` only create or remove
that file. This works across processes and across DSH sessions.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "runtime"
SHOTS = RUNTIME / "shots"
TMP = RUNTIME / "tmp"
LOG = RUNTIME / "actions.jsonl"
STOP = RUNTIME / "STOP"
VERSION = "0.1.0"
SKILL_LINK = Path(os.environ.get("USERPROFILE", str(Path.home()))) / ".dsh" / "skills" / "desktop-pilot"


class StoppedError(RuntimeError):
    pass


def ensure_dirs() -> None:
    for path in (RUNTIME, SHOTS, TMP):
        path.mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def is_stopped() -> bool:
    return STOP.exists()


def require_running() -> None:
    if is_stopped():
        raise StoppedError(f"STOP is active at {STOP}; run `dp.py resume` first")


def stop(reason: str = "") -> dict[str, Any]:
    ensure_dirs()
    message = f"{now_iso()} {reason}".strip()
    STOP.write_text(message + "\n", encoding="utf-8")
    log_event("stop", {"reason": reason})
    return {"ok": True, "stopped": True, "path": str(STOP), "message": message}


def resume() -> dict[str, Any]:
    existed = STOP.exists()
    if existed:
        STOP.unlink()
    log_event("resume", {"was_stopped": existed})
    return {"ok": True, "stopped": False, "was_stopped": existed}


def new_shot_path(label: str = "screen", ext: str = ".png") -> Path:
    ensure_dirs()
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", label).strip("-") or "screen"
    return SHOTS / f"{safe}-{stamp()}-{os.getpid()}{ext}"


def temp_path(label: str = "tmp", ext: str = ".png") -> Path:
    ensure_dirs()
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", label).strip("-") or "tmp"
    return TMP / f"{safe}-{os.getpid()}-{int(time.time() * 1000)}{ext}"


_SENSITIVE = re.compile(r"(password|passwd|pwd|token|secret|authorization|cookie|api[_-]?key|session)", re.IGNORECASE)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if _SENSITIVE.search(str(key)) and not isinstance(item, bool):
                out[key] = "***"
            else:
                out[key] = redact(item)
        return out
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        # Don't attempt to scrub arbitrary prose; only structured keys are
        # considered sensitive. This keeps normal screen text readable.
        return value
    return value


def log_event(action: str, payload: dict[str, Any] | None = None, ok: bool = True, error: str | None = None) -> None:
    ensure_dirs()
    record = {
        "ts": now_iso(),
        "action": action,
        "ok": ok,
        "pid": os.getpid(),
        "payload": redact(payload or {}),
    }
    if error:
        record["error"] = error
    try:
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def tail_log(count: int = 20) -> list[dict[str, Any]]:
    if not LOG.exists():
        return []
    try:
        lines = LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    out = []
    for line in lines[-max(1, count) :]:
        try:
            out.append(json.loads(line))
        except Exception:
            out.append({"raw": line})
    return out


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def emit(obj: dict[str, Any], exit_code: int | None = None) -> None:
    _configure_stdout()
    print(json.dumps(obj, ensure_ascii=False, default=str))
    if exit_code is not None:
        raise SystemExit(exit_code)


def ok(**fields: Any) -> dict[str, Any]:
    return {"ok": True, **fields}


def fail(message: str, code: str = "error", **fields: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "code": code, **fields}


def main_guard(fn):
    """Decorator for CLI entry points: always emit JSON, always exit nonzero on error."""
    def wrapper(*args, **kwargs):
        try:
            result = fn(*args, **kwargs)
            if isinstance(result, dict):
                emit(result, 0 if result.get("ok", True) else 1)
            elif result is not None:
                emit(ok(result=result), 0)
            return result
        except StoppedError as exc:
            emit(fail(str(exc), code="stopped"), 3)
        except KeyboardInterrupt:
            emit(fail("interrupted", code="interrupted"), 130)
        except Exception as exc:
            detail = traceback.format_exc(limit=6)
            log_event("error", {"args": list(args)}, ok=False, error=str(exc))
            emit(fail(str(exc), code=exc.__class__.__name__, detail=detail), 1)

    return wrapper


def skill_link_state() -> dict[str, Any]:
    state = {"path": str(SKILL_LINK), "exists": SKILL_LINK.exists(), "is_symlink": SKILL_LINK.is_symlink()}
    try:
        state["target"] = str(SKILL_LINK.resolve()) if SKILL_LINK.exists() else None
    except Exception:
        state["target"] = None
    state["points_to_project"] = bool(state["target"] and Path(state["target"]).resolve() == ROOT)
    return state


def project_info() -> dict[str, Any]:
    return {
        "root": str(ROOT),
        "runtime": str(RUNTIME),
        "version": VERSION,
        "python": sys.version.split()[0],
        "stopped": is_stopped(),
        "stop_file": str(STOP),
        "skill": skill_link_state(),
    }