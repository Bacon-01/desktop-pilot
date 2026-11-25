#!/usr/bin/env python3
"""Smoke tests for Desktop Pilot.

Default mode is side-effect free: it checks capability, window enumeration,
screen capture, OCR, STOP semantics, and the skill junction.

`--gui` adds a real Notepad round trip. It opens a temporary file, reads it,
appends a marker, reads it back through UIA, and saves a screenshot. The tab is
left open on purpose so you can inspect it; close it manually when done.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DP = ROOT / "bin" / "dp.py"
TMP = ROOT / "runtime" / "tmp"

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def call(*args: str, expect_ok: bool = True, timeout: int = 120) -> tuple[dict, int]:
    proc = subprocess.run(
        [sys.executable, str(DP), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    raw = (proc.stdout or "").strip().splitlines()
    data = None
    for line in reversed(raw):
        line = line.strip()
        if line.startswith("{"):
            try:
                data = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
    if data is None:
        raise AssertionError(
            f"no JSON from `dp.py {' '.join(args)}`\n"
            f"exit={proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    if expect_ok and not data.get("ok"):
        raise AssertionError(f"command failed: {' '.join(args)}\n{json.dumps(data, ensure_ascii=False, indent=2)}")
    if expect_ok and proc.returncode != 0:
        raise AssertionError(f"exit {proc.returncode} for {' '.join(args)}\n{json.dumps(data, ensure_ascii=False, indent=2)}")
    return data, proc.returncode


def section(name: str) -> None:
    print(f"\n== {name} ==")


def test_doctor() -> None:
    section("doctor")
    data, _ = call("doctor")
    assert data["ok"], data
    assert data["screen"]["screen_width"] > 0 and data["screen"]["screen_height"] > 0, data["screen"]
    assert data["checks"]["uia"]["ok"] is True, data["checks"]["uia"]
    assert data["checks"]["ocr"]["ok"] is True, data["checks"]["ocr"]
    assert data["checks"]["ocr"]["languages"], data["checks"]["ocr"]
    assert data["skill"]["points_to_project"] is True, data["skill"]
    print(f"screen={data['screen']['screen_width']}x{data['screen']['screen_height']} dpi={data['dpi']}")
    print(f"ocr={data['checks']['ocr']['languages']} skill={data['skill']['points_to_project']}")


def test_windows() -> None:
    section("windows")
    data, _ = call("windows")
    assert data["count"] >= 1, data
    fg = [w for w in data["windows"] if w.get("foreground")]
    print(f"windows={data['count']} foreground={fg[0]['title'] if fg else None}")


def test_screen() -> None:
    section("screen")
    TMP.mkdir(parents=True, exist_ok=True)
    out = TMP / f"smoke-screen-{os.getpid()}.png"
    data, _ = call("screen", "--out", str(out), "--no-cursor")
    assert out.exists() and out.stat().st_size > 1000, data
    assert data["size"][0] > 0 and data["size"][1] > 0, data
    print(f"path={out} size={data['size']} bytes={out.stat().st_size}")


def test_ocr() -> None:
    section("ocr")
    data, _ = call("ocr", "--max-lines", "40", timeout=180)
    assert data["ok"], data
    assert data.get("count", 0) >= 1, data
    print(f"language={data['language']} lines={data['count']} path={data['path']}")


def test_stop() -> None:
    section("stop/resume")
    data, _ = call("stop", "--reason", "smoke test")
    assert data["stopped"] is True, data
    blocked, code = call("click", "--x", "10", "--y", "10", expect_ok=False)
    assert blocked.get("code") == "stopped", blocked
    assert code == 3, code
    resumed, _ = call("resume")
    assert resumed["stopped"] is False and resumed["was_stopped"] is True, resumed
    print(f"blocked_code={blocked['code']} resumed={resumed['was_stopped']}")


def test_gui() -> None:
    section("gui / notepad")
    TMP.mkdir(parents=True, exist_ok=True)
    name = f"desktop-pilot-smoke-{os.getpid()}.txt"
    path = TMP / name
    base = "Desktop Pilot smoke base: 你好，世界。\n"
    marker = f"SMOKE-{os.getpid()}-OK"
    path.write_text(base, encoding="utf-8")

    launched, _ = call("launch", "--target", str(path), "--wait-title", name, "--timeout", "12")
    assert launched.get("ok"), launched
    window = launched.get("window") or {}
    handle = window.get("handle")
    assert handle, launched
    print(f"window={handle} title={window.get('title')!r}")

    call("focus", "--window", str(handle))
    time.sleep(0.5)
    call("uia", "--window", str(handle), "--find", "文本编辑器", "--click", "--depth", "10")
    time.sleep(0.3)
    read, _ = call("uia", "--window", str(handle), "--find", "文本编辑器", "--read", "--depth", "10")
    text = ((read.get("matched") or {}).get("read") or {}).get("text", "")
    deadline = time.time() + 6
    while "Desktop Pilot smoke base" not in text and time.time() < deadline:
        time.sleep(0.25)
        read, _ = call("uia", "--window", str(handle), "--find", "文本编辑器", "--read", "--depth", "10")
        text = ((read.get("matched") or {}).get("read") or {}).get("text", "")
    if "Desktop Pilot smoke base" not in text:
        print("debug read:", json.dumps(read, ensure_ascii=False, indent=2))
    assert "Desktop Pilot smoke base" in text, text
    print(f"initial_read={len(text)} chars")

    call("key", "--keys", "ctrl+end")
    typed, _ = call(
        "type",
        "--window",
        str(handle),
        "--uia",
        "文本编辑器",
        "--text",
        f"\n{marker}",
        "--depth",
        "10",
    )
    assert typed.get("ok"), typed
    time.sleep(0.2)

    read2, _ = call("uia", "--window", str(handle), "--find", "文本编辑器", "--read", "--depth", "10")
    text2 = ((read2.get("matched") or {}).get("read") or {}).get("text", "")
    assert marker in text2, text2
    print(f"marker_read_back={marker!r} chars={len(text2)}")

    out = TMP / f"smoke-gui-{os.getpid()}.png"
    shot, _ = call("screen", "--window", str(handle), "--out", str(out))
    assert out.exists() and out.stat().st_size > 1000, shot
    print(f"screenshot={out} size={shot['size']}")
    print("note: the Notepad tab is left open for inspection; close it manually.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gui", action="store_true", help="include the real Notepad round trip")
    args = parser.parse_args()

    started = time.time()
    test_doctor()
    test_windows()
    test_screen()
    test_ocr()
    test_stop()
    if args.gui:
        test_gui()
    print(f"\nOK in {time.time() - started:.1f}s" + (" (with gui)" if args.gui else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())