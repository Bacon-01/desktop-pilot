"""Windows.Media.Ocr bridge.

Windows ships a usable OCR engine; calling it through PowerShell 5.1 + WinRT
avoids adding Tesseract or a vision-model dependency. The PowerShell script
does the WinRT dance and returns compact JSON; this module handles capture,
temporary files, coordinate translation, and text matching.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import runtime
import win32

POWERSHELL = shutil.which("powershell.exe") or r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
SCRIPT = runtime.ROOT / "scripts" / "ocr.ps1"
CREATE_NO_WINDOW = 0x08000000


def available() -> bool:
    return Path(POWERSHELL).exists() and SCRIPT.exists()


def _run(args: list[str], timeout: float = 90) -> dict[str, Any]:
    if not available():
        return {"ok": False, "error": "OCR bridge unavailable (PowerShell or scripts/ocr.ps1 missing)"}
    try:
        proc = subprocess.run(
            [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"OCR timed out after {timeout}s"}
    except Exception as exc:
        return {"ok": False, "error": f"OCR failed to start: {exc}"}
    out = (proc.stdout or "").strip()
    if not out:
        return {"ok": False, "error": "OCR produced no output", "stderr": (proc.stderr or "").strip()[:2000], "exit": proc.returncode}
    try:
        data = json.loads(out)
    except Exception:
        return {"ok": False, "error": "OCR output was not JSON", "stdout": out[:4000], "stderr": (proc.stderr or "").strip()[:2000]}
    if proc.returncode not in (0, None) and data.get("ok"):
        data["exit"] = proc.returncode
    return data


def languages() -> list[str]:
    if not Path(POWERSHELL).exists():
        return []
    command = (
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
        "[Windows.Media.Ocr.OcrEngine,Windows.Media.Ocr,ContentType=WindowsRuntime] | Out-Null; "
        "[Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages | ForEach-Object { $_.LanguageTag }"
    )
    try:
        proc = subprocess.run(
            [POWERSHELL, "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            creationflags=CREATE_NO_WINDOW,
        )
        return [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
    except Exception:
        return []


def _line_rect(line: dict[str, Any]) -> list[int] | None:
    words = line.get("words") or []
    if not words:
        return None
    xs = [int(w["x"]) for w in words]
    ys = [int(w["y"]) for w in words]
    x2 = [int(w["x"]) + int(w["w"]) for w in words]
    y2 = [int(w["y"]) + int(w["h"]) for w in words]
    return [min(xs), min(ys), max(x2), max(y2)]


def _normalize(text: str) -> str:
    return "".join(str(text).split()).lower()


def annotate(result: dict[str, Any], origin: tuple[int, int] = (0, 0)) -> dict[str, Any]:
    ox, oy = origin
    lines = []
    for line in result.get("lines") or []:
        rect = _line_rect(line)
        item = {
            "text": line.get("text", ""),
            "rect": [rect[0] + ox, rect[1] + oy, rect[2] + ox, rect[3] + oy] if rect else None,
            "words": [
                {
                    "text": w.get("text", ""),
                    "rect": [int(w["x"]) + ox, int(w["y"]) + oy, int(w["x"]) + int(w["w"]) + ox, int(w["y"]) + int(w["h"]) + oy],
                }
                for w in (line.get("words") or [])
            ],
        }
        item["center"] = [(item["rect"][0] + item["rect"][2]) // 2, (item["rect"][1] + item["rect"][3]) // 2] if item["rect"] else None
        lines.append(item)
    return {
        "ok": bool(result.get("ok")),
        "language": result.get("language"),
        "origin": [ox, oy],
        "lines": lines,
        "count": len(lines),
        "error": result.get("error"),
    }


def ocr_file(path: str | Path, language: str = "zh-Hans-CN", origin: tuple[int, int] = (0, 0)) -> dict[str, Any]:
    data = _run(["-Path", str(Path(path).resolve()), "-Language", language])
    return annotate(data, origin=origin)


def ocr_image(img, label: str = "ocr", language: str = "zh-Hans-CN", origin: tuple[int, int] = (0, 0)) -> dict[str, Any]:
    path = runtime.temp_path(label, ".png")
    try:
        win32.save_image(img, str(path))
        data = _run(["-Path", str(path), "-Language", language])
        return annotate(data, origin=origin)
    finally:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass


def ocr_screen(language: str = "zh-Hans-CN", cursor: bool = False) -> dict[str, Any]:
    img, meta = win32.capture_screen(cursor=cursor)
    bbox = meta["bbox"]
    result = ocr_image(img, label="screen", language=language, origin=(bbox[0], bbox[1]))
    result["capture"] = meta
    return result


def ocr_region(x: int, y: int, width: int, height: int, language: str = "zh-Hans-CN", cursor: bool = False) -> dict[str, Any]:
    img, meta = win32.capture_region(x, y, width, height, cursor=cursor)
    bbox = meta["bbox"]
    result = ocr_image(img, label="region", language=language, origin=(bbox[0], bbox[1]))
    result["capture"] = meta
    return result


def ocr_window(window_handle: int, language: str = "zh-Hans-CN", cursor: bool = False) -> dict[str, Any]:
    img, meta = win32.capture_window(window_handle, cursor=cursor)
    bbox = meta["bbox"]
    result = ocr_image(img, label="window", language=language, origin=(bbox[0], bbox[1]))
    result["capture"] = meta
    return result


def find(result: dict[str, Any], needle: str, exact: bool = False, first: bool = True) -> list[dict[str, Any]]:
    """Find OCR text by substring (whitespace-insensitive) or exact line match.

    Returns matches with screen-space rects and centers. Chinese OCR inserts
    spaces between glyphs, so matching always compares whitespace-stripped text.
    """
    target = _normalize(needle)
    if not target:
        return []
    matches = []
    for line in result.get("lines") or []:
        text = line.get("text") or ""
        norm = _normalize(text)
        matched = (norm == target) if exact else (target in norm)
        if matched and line.get("rect"):
            matches.append(
                {
                    "text": text,
                    "rect": line["rect"],
                    "center": line["center"],
                    "words": line.get("words") or [],
                    "kind": "line",
                }
            )
            if first:
                return matches
    if not matches:
        # Fall back to individual words for cases where OCR splits a label.
        for line in result.get("lines") or []:
            for word in line.get("words") or []:
                norm = _normalize(word.get("text") or "")
                matched = (norm == target) if exact else (target in norm)
                if matched and word.get("rect"):
                    rect = word["rect"]
                    matches.append(
                        {
                            "text": word.get("text"),
                            "rect": rect,
                            "center": [(rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2],
                            "words": [word],
                            "kind": "word",
                        }
                    )
                    if first:
                        return matches
    return matches