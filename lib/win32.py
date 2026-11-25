"""Win32 primitives for Desktop Pilot.

Everything here is deliberately dependency-light: ctypes + Pillow only.
The module is imported by the CLI and the console; importing it enables
per-monitor DPI awareness before any coordinates are read.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import os
import time
from dataclasses import dataclass, asdict
from typing import Any, Iterable

from PIL import Image, ImageDraw, ImageGrab

# ---------------------------------------------------------------------------
# DLLs and basic types
# ---------------------------------------------------------------------------

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
try:
    dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
except OSError:  # pragma: no cover - older Windows
    dwmapi = None

ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


def enable_dpi_awareness() -> None:
    """Make this process per-monitor DPI aware.

    Python may start DPI-unaware; without this, GetSystemMetrics reports
    logical pixels while ImageGrab returns physical pixels, and every click
    lands in the wrong place on a scaled display.
    """
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        pass
    try:
        user32.SetProcessDpiAwarenessContext(-4)  # PER_MONITOR_AWARE_V2
    except Exception:
        pass


enable_dpi_awareness()

# ---------------------------------------------------------------------------
# Structures
# ---------------------------------------------------------------------------


class RECT(ctypes.Structure):
    _fields_ = [("left", w.LONG), ("top", w.LONG), ("right", w.LONG), ("bottom", w.LONG)]

    def as_list(self) -> list[int]:
        return [self.left, self.top, self.right, self.bottom]

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


class POINT(ctypes.Structure):
    _fields_ = [("x", w.LONG), ("y", w.LONG)]


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", w.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", w.DWORD),
        ("szDevice", w.WCHAR * 32),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", w.DWORD),
        ("biWidth", w.LONG),
        ("biHeight", w.LONG),
        ("biPlanes", w.WORD),
        ("biBitCount", w.WORD),
        ("biCompression", w.DWORD),
        ("biSizeImage", w.DWORD),
        ("biXPelsPerMeter", w.LONG),
        ("biYPelsPerMeter", w.LONG),
        ("biClrUsed", w.DWORD),
        ("biClrImportant", w.DWORD),
    ]


class RGBQUAD(ctypes.Structure):
    _fields_ = [("rgbBlue", ctypes.c_ubyte), ("rgbGreen", ctypes.c_ubyte), ("rgbRed", ctypes.c_ubyte), ("rgbReserved", ctypes.c_ubyte)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", RGBQUAD * 1)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", w.LONG),
        ("dy", w.LONG),
        ("mouseData", w.DWORD),
        ("dwFlags", w.DWORD),
        ("time", w.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", w.WORD),
        ("wScan", w.WORD),
        ("dwFlags", w.DWORD),
        ("time", w.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", w.DWORD), ("wParamL", w.WORD), ("wParamH", w.WORD)]


class INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", w.DWORD), ("u", INPUTUNION)]


# ---------------------------------------------------------------------------
# Win32 constants
# ---------------------------------------------------------------------------

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_EXTENDEDKEY = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x01000
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SW_RESTORE = 9
PW_RENDERFULLCONTENT = 2
DIB_RGB_COLORS = 0
MONITORINFOF_PRIMARY = 1
DWMWA_EXTENDED_FRAME_BOUNDS = 9
ASFW_ANY = -1

# Virtual key codes used by the key parser.
VK = {
    "backspace": 0x08,
    "tab": 0x09,
    "enter": 0x0D,
    "return": 0x0D,
    "shift": 0x10,
    "ctrl": 0x11,
    "control": 0x11,
    "alt": 0x12,
    "pause": 0x13,
    "capslock": 0x14,
    "esc": 0x1B,
    "escape": 0x1B,
    "space": 0x20,
    "pageup": 0x21,
    "pagedown": 0x22,
    "end": 0x23,
    "home": 0x24,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "printscreen": 0x2C,
    "insert": 0x2D,
    "delete": 0x2E,
    "win": 0x5B,
    "lwin": 0x5B,
    "rwin": 0x5C,
    "apps": 0x5D,
    "sleep": 0x5F,
    "numlock": 0x90,
    "scrolllock": 0x91,
    "multiply": 0x6A,
    "add": 0x6B,
    "subtract": 0x6D,
    "decimal": 0x6E,
    "divide": 0x6F,
}
for _i in range(1, 25):
    VK[f"f{_i}"] = 0x6F + _i  # F1=0x70 ... F24=0x87
for _c in "abcdefghijklmnopqrstuvwxyz":
    VK[_c] = ord(_c.upper())
for _d in "0123456789":
    VK[_d] = ord(_d)
VK.update(
    {
        "minus": 0xBD,
        "-": 0xBD,
        "plus": 0xBB,
        "=": 0xBB,
        "comma": 0xBC,
        ",": 0xBC,
        "period": 0xBE,
        ".": 0xBE,
        "slash": 0xBF,
        "/": 0xBF,
        "backtick": 0xC0,
        "`": 0xC0,
        "semicolon": 0xBA,
        ";": 0xBA,
        "quote": 0xDE,
        "'": 0xDE,
        "lbracket": 0xDB,
        "[": 0xDB,
        "rbracket": 0xDD,
        "]": 0xDD,
        "backslash": 0xDC,
        "\\": 0xDC,
    }
)
EXTENDED_VKS = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B, 0x5C, 0x5D, 0x6F, 0x90}

# ---------------------------------------------------------------------------
# Function signatures
# ---------------------------------------------------------------------------

user32.SendInput.argtypes = [w.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = w.UINT
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.SetCursorPos.restype = w.BOOL
user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.GetCursorPos.restype = w.BOOL
user32.mouse_event.argtypes = [w.DWORD, w.DWORD, w.DWORD, w.DWORD, ULONG_PTR]
user32.GetForegroundWindow.restype = w.HWND
user32.GetWindowDC.argtypes = [w.HWND]
user32.GetWindowDC.restype = w.HDC
user32.ReleaseDC.argtypes = [w.HWND, w.HDC]
user32.ReleaseDC.restype = ctypes.c_int
user32.PrintWindow.argtypes = [w.HWND, w.HDC, w.UINT]
user32.PrintWindow.restype = w.BOOL
user32.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(RECT)]
user32.GetWindowRect.restype = w.BOOL
user32.GetClientRect.argtypes = [w.HWND, ctypes.POINTER(RECT)]
user32.GetClientRect.restype = w.BOOL
user32.ClientToScreen.argtypes = [w.HWND, ctypes.POINTER(POINT)]
user32.ClientToScreen.restype = w.BOOL
user32.GetWindowTextLengthW.argtypes = [w.HWND]
user32.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
user32.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
user32.GetWindowThreadProcessId.restype = w.DWORD
user32.IsWindowVisible.argtypes = [w.HWND]
user32.IsIconic.argtypes = [w.HWND]
user32.IsZoomed.argtypes = [w.HWND]
user32.ShowWindow.argtypes = [w.HWND, ctypes.c_int]
user32.SetForegroundWindow.argtypes = [w.HWND]
user32.BringWindowToTop.argtypes = [w.HWND]
user32.AttachThreadInput.argtypes = [w.DWORD, w.DWORD, w.BOOL]
user32.SetFocus.argtypes = [w.HWND]
user32.AllowSetForegroundWindow.argtypes = [w.DWORD]
user32.OpenClipboard.argtypes = [w.HWND]
user32.GetClipboardData.argtypes = [w.UINT]
user32.GetClipboardData.restype = w.HANDLE
user32.SetClipboardData.argtypes = [w.UINT, w.HANDLE]
user32.SetClipboardData.restype = w.HANDLE
kernel32.GlobalAlloc.argtypes = [w.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = w.HGLOBAL
kernel32.GlobalLock.argtypes = [w.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [w.HGLOBAL]
kernel32.GlobalFree.argtypes = [w.HGLOBAL]
kernel32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
kernel32.OpenProcess.restype = w.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
kernel32.QueryFullProcessImageNameW.restype = w.BOOL
kernel32.CloseHandle.argtypes = [w.HANDLE]
gdi32.CreateCompatibleDC.argtypes = [w.HDC]
gdi32.CreateCompatibleDC.restype = w.HDC
gdi32.CreateCompatibleBitmap.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = w.HBITMAP
gdi32.SelectObject.argtypes = [w.HDC, w.HGDIOBJ]
gdi32.SelectObject.restype = w.HGDIOBJ
gdi32.DeleteObject.argtypes = [w.HGDIOBJ]
gdi32.DeleteDC.argtypes = [w.HDC]
gdi32.GetDIBits.argtypes = [w.HDC, w.HBITMAP, w.UINT, w.UINT, ctypes.c_void_p, ctypes.POINTER(BITMAPINFO), w.UINT]
gdi32.GetDIBits.restype = ctypes.c_int


# ---------------------------------------------------------------------------
# Basic queries
# ---------------------------------------------------------------------------


def is_admin() -> bool:
    try:
        return bool(shell32.IsUserAnAdmin())
    except Exception:
        return False


def session_id() -> int | None:
    try:
        sid = w.DWORD()
        if kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(sid)):
            return int(sid.value)
    except Exception:
        pass
    return None


def get_cursor_pos() -> tuple[int, int]:
    pt = POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return int(pt.x), int(pt.y)


def get_screen_metrics() -> dict[str, int]:
    return {
        "screen_width": user32.GetSystemMetrics(0),
        "screen_height": user32.GetSystemMetrics(1),
        "virtual_x": user32.GetSystemMetrics(76),
        "virtual_y": user32.GetSystemMetrics(77),
        "virtual_width": user32.GetSystemMetrics(78),
        "virtual_height": user32.GetSystemMetrics(79),
    }


def get_dpi() -> int:
    try:
        return int(user32.GetDpiForSystem())
    except Exception:
        return 96


def get_monitors() -> list[dict[str, Any]]:
    monitors: list[dict[str, Any]] = []
    MonitorEnumProc = ctypes.WINFUNCTYPE(w.BOOL, w.HMONITOR, w.HDC, ctypes.POINTER(RECT), w.LPARAM)

    def callback(hmonitor, hdc, lprect, lparam):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
            monitors.append(
                {
                    "device": info.szDevice,
                    "rect": info.rcMonitor.as_list(),
                    "work": info.rcWork.as_list(),
                    "primary": bool(info.dwFlags & MONITORINFOF_PRIMARY),
                }
            )
        return True

    user32.EnumDisplayMonitors(None, None, MonitorEnumProc(callback), 0)
    return monitors


def get_foreground_window() -> int:
    return int(user32.GetForegroundWindow() or 0)


# ---------------------------------------------------------------------------
# Window enumeration
# ---------------------------------------------------------------------------


def _window_text(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def _class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _process_name(pid: int) -> str | None:
    if not pid:
        return None
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        size = w.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
    finally:
        kernel32.CloseHandle(handle)
    return None


def get_window_rect(hwnd: int) -> RECT:
    rect = RECT()
    if dwmapi is not None:
        try:
            hr = dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rect), ctypes.sizeof(rect))
            if hr == 0 and rect.width > 0 and rect.height > 0:
                return rect
        except Exception:
            pass
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect


def get_client_rect_screen(hwnd: int) -> RECT | None:
    rect = RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    pt = POINT(rect.left, rect.top)
    if not user32.ClientToScreen(hwnd, ctypes.byref(pt)):
        return None
    return RECT(pt.x, pt.y, pt.x + rect.width, pt.y + rect.height)


def get_window_info(hwnd: int, foreground: int | None = None) -> dict[str, Any]:
    hwnd = int(hwnd)
    pid = w.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    rect = get_window_rect(hwnd)
    client = get_client_rect_screen(hwnd)
    fg = get_foreground_window() if foreground is None else foreground
    iconic = bool(user32.IsIconic(hwnd))
    zoomed = bool(user32.IsZoomed(hwnd))
    state = "minimized" if iconic else ("maximized" if zoomed else "normal")
    return {
        "handle": hwnd,
        "title": _window_text(hwnd),
        "class": _class_name(hwnd),
        "process": _process_name(int(pid.value)),
        "pid": int(pid.value),
        "rect": rect.as_list(),
        "client_rect": client.as_list() if client else None,
        "state": state,
        "visible": bool(user32.IsWindowVisible(hwnd)),
        "foreground": hwnd == fg,
    }


def list_windows(include_hidden: bool = False, include_untitled: bool = False) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    fg = get_foreground_window()
    EnumWindowsProc = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)

    def callback(hwnd, lparam):
        hwnd = int(hwnd)
        if not include_hidden and not user32.IsWindowVisible(hwnd):
            return True
        title = _window_text(hwnd)
        cls = _class_name(hwnd)
        if not include_untitled and not title and cls not in {"Progman", "Shell_TrayWnd"}:
            return True
        result.append(get_window_info(hwnd, foreground=fg))
        return True

    user32.EnumWindows(EnumWindowsProc(callback), 0)
    result.sort(key=lambda x: (not x["foreground"], x["title"].lower()))
    return result


def find_windows(title: str | None = None, pid: int | None = None, class_name: str | None = None, include_hidden: bool = False) -> list[dict[str, Any]]:
    windows = list_windows(include_hidden=include_hidden, include_untitled=True)
    out = []
    for item in windows:
        if title and title.lower() not in (item["title"] or "").lower():
            continue
        if pid is not None and item["pid"] != pid:
            continue
        if class_name and class_name.lower() not in (item["class"] or "").lower():
            continue
        out.append(item)
    return out


def resolve_window(handle: int | None = None, title: str | None = None, pid: int | None = None) -> dict[str, Any]:
    if handle:
        return get_window_info(int(handle))
    matches = find_windows(title=title, pid=pid)
    if not matches:
        raise LookupError(f"window not found (title={title!r}, pid={pid})")
    return matches[0]


def focus_window(hwnd: int) -> bool:
    hwnd = int(hwnd)
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.15)
    if get_foreground_window() == hwnd:
        return True
    user32.AllowSetForegroundWindow(ASFW_ANY)
    fg = get_foreground_window()
    target_thread = user32.GetWindowThreadProcessId(hwnd, None)
    fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    current_thread = kernel32.GetCurrentThreadId()
    attached: list[int] = []
    for thread in {target_thread, fg_thread}:
        if thread and thread != current_thread:
            if user32.AttachThreadInput(current_thread, thread, True):
                attached.append(thread)
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetFocus(hwnd)
    finally:
        for thread in attached:
            user32.AttachThreadInput(current_thread, thread, False)
    time.sleep(0.2)
    return get_foreground_window() == hwnd


# ---------------------------------------------------------------------------
# Screen capture
# ---------------------------------------------------------------------------


def _virtual_rect() -> tuple[int, int, int, int]:
    m = get_screen_metrics()
    return m["virtual_x"], m["virtual_y"], m["virtual_width"], m["virtual_height"]


def _draw_cursor(img: Image.Image, origin_x: int, origin_y: int) -> None:
    cx, cy = get_cursor_pos()
    x, y = cx - origin_x, cy - origin_y
    if 0 <= x < img.width and 0 <= y < img.height:
        draw = ImageDraw.Draw(img)
        r = 7
        draw.line((x - r, y, x + r, y), fill=(255, 255, 255), width=4)
        draw.line((x, y - r, x, y + r), fill=(255, 255, 255), width=4)
        draw.line((x - r, y, x + r, y), fill=(220, 30, 30), width=2)
        draw.line((x, y - r, x, y + r), fill=(220, 30, 30), width=2)


def capture_screen(cursor: bool = True) -> tuple[Image.Image, dict[str, Any]]:
    vx, vy, vw, vh = _virtual_rect()
    img = ImageGrab.grab(all_screens=True)
    # Pillow's all_screens image is anchored at the virtual-screen origin.
    if img.size != (vw, vh):
        # Keep the pixels we have, but report the mismatch instead of guessing.
        pass
    img = img.convert("RGB")
    if cursor:
        _draw_cursor(img, vx, vy)
    return img, {"bbox": [vx, vy, vx + img.width, vy + img.height], "size": list(img.size)}


def capture_region(x: int, y: int, width: int, height: int, cursor: bool = True) -> tuple[Image.Image, dict[str, Any]]:
    vx, vy, vw, vh = _virtual_rect()
    x0 = max(vx, min(x, vx + vw))
    y0 = max(vy, min(y, vy + vh))
    x1 = max(vx, min(x + width, vx + vw))
    y1 = max(vy, min(y + height, vy + vh))
    if x1 <= x0 or y1 <= y0:
        raise ValueError("region is outside the virtual screen")
    full, _ = capture_screen(cursor=False)
    img = full.crop((x0 - vx, y0 - vy, x1 - vx, y1 - vy))
    if cursor:
        _draw_cursor(img, x0, y0)
    return img, {"bbox": [x0, y0, x1, y1], "size": list(img.size)}


def capture_window(hwnd: int, cursor: bool = True) -> tuple[Image.Image, dict[str, Any]]:
    hwnd = int(hwnd)
    if user32.IsIconic(hwnd):
        raise ValueError("window is minimized; restore it before capturing")
    rect = get_window_rect(hwnd)
    if rect.width <= 0 or rect.height <= 0:
        raise ValueError("window has no drawable area")
    width, height = rect.width, rect.height
    hdc = user32.GetWindowDC(hwnd)
    if not hdc:
        raise OSError("GetWindowDC failed")
    memdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, width, height)
    old = gdi32.SelectObject(memdc, bmp)
    method = "PrintWindow"
    img: Image.Image | None = None
    try:
        ok = user32.PrintWindow(hwnd, memdc, PW_RENDERFULLCONTENT)
        if ok:
            bmi = BITMAPINFO()
            bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = width
            bmi.bmiHeader.biHeight = -height
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 32
            bmi.bmiHeader.biCompression = 0
            buf = ctypes.create_string_buffer(width * height * 4)
            got = gdi32.GetDIBits(memdc, bmp, 0, height, buf, ctypes.byref(bmi), DIB_RGB_COLORS)
            if got:
                img = Image.frombuffer("RGBA", (width, height), buf, "raw", "BGRA", 0, 1).convert("RGB")
                # Some Chromium/Electron windows return an all-black image.
                extrema = img.convert("L").getextrema()
                if extrema[1] <= 2:
                    img = None
    finally:
        gdi32.SelectObject(memdc, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(memdc)
        user32.ReleaseDC(hwnd, hdc)
    if img is None:
        method = "screen-crop"
        vx, vy, vw, vh = _virtual_rect()
        x0, y0 = max(vx, rect.left), max(vy, rect.top)
        x1, y1 = min(vx + vw, rect.right), min(vy + vh, rect.bottom)
        if x1 <= x0 or y1 <= y0:
            raise ValueError("window is outside the virtual screen")
        full, _ = capture_screen(cursor=False)
        img = full.crop((x0 - vx, y0 - vy, x1 - vx, y1 - vy))
    if cursor:
        _draw_cursor(img, rect.left, rect.top)
    return img, {"bbox": rect.as_list(), "size": list(img.size), "method": method}


def save_image(img: Image.Image, path: str, quality: int = 88) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    ext = os.path.splitext(path)[1].lower()
    if ext in {".jpg", ".jpeg"}:
        img.convert("RGB").save(path, quality=quality, optimize=True)
    else:
        img.save(path)
    return os.path.abspath(path)


# ---------------------------------------------------------------------------
# Clipboard
# ---------------------------------------------------------------------------


def get_clipboard_text() -> str | None:
    for _ in range(12):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.04)
    else:
        return None
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return None
        try:
            return ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def set_clipboard_text(text: str) -> bool:
    data = (text + "\0").encode("utf-16-le")
    for _ in range(12):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.04)
    else:
        return False
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            return False
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            kernel32.GlobalFree(handle)
            return False
        ctypes.memmove(ptr, data, len(data))
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            kernel32.GlobalFree(handle)
            return False
        return True
    finally:
        user32.CloseClipboard()


def clear_clipboard() -> bool:
    for _ in range(12):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.04)
    else:
        return False
    try:
        return bool(user32.EmptyClipboard())
    finally:
        user32.CloseClipboard()


# ---------------------------------------------------------------------------
# Keyboard and mouse
# ---------------------------------------------------------------------------


def _send_inputs(inputs: Iterable[INPUT]) -> int:
    items = list(inputs)
    if not items:
        return 0
    array = (INPUT * len(items))(*items)
    return int(user32.SendInput(len(items), array, ctypes.sizeof(INPUT)))


def _key_input(vk: int, up: bool = False, extended: bool = False) -> INPUT:
    flags = (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_EXTENDEDKEY if extended else 0)
    return INPUT(type=INPUT_KEYBOARD, u=INPUTUNION(ki=KEYBDINPUT(vk, 0, flags, 0, 0)))


def _unicode_input(scan: int, up: bool = False) -> INPUT:
    flags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0)
    return INPUT(type=INPUT_KEYBOARD, u=INPUTUNION(ki=KEYBDINPUT(0, scan, flags, 0, 0)))


def press_vk(vk: int, extended: bool | None = None) -> None:
    if extended is None:
        extended = vk in EXTENDED_VKS
    _send_inputs([_key_input(vk, False, extended)])
    time.sleep(0.01)
    _send_inputs([_key_input(vk, True, extended)])


def key_down(vk: int, extended: bool | None = None) -> None:
    if extended is None:
        extended = vk in EXTENDED_VKS
    _send_inputs([_key_input(vk, False, extended)])


def key_up(vk: int, extended: bool | None = None) -> None:
    if extended is None:
        extended = vk in EXTENDED_VKS
    _send_inputs([_key_input(vk, True, extended)])


def _vk_for_token(token: str) -> int:
    key = token.strip().lower()
    if key in VK:
        return VK[key]
    if len(key) == 1:
        if key.isalpha():
            return ord(key.upper())
        if key.isdigit():
            return ord(key)
    raise ValueError(f"unknown key: {token!r}")


def key_combo(keys: str, repeat: int = 1) -> None:
    raw = keys.strip()
    if not raw:
        raise ValueError("empty key combo")
    # A trailing/standalone '+' means the plus key.
    if raw == "+":
        tokens = ["plus"]
    else:
        tokens = [t.strip() for t in raw.split("+") if t.strip()]
        if raw.endswith("+"):
            tokens.append("plus")
    if not tokens:
        raise ValueError("empty key combo")
    modifiers = tokens[:-1]
    main = tokens[-1]
    mod_vks = [_vk_for_token(m) for m in modifiers]
    main_vk = _vk_for_token(main)
    for _ in range(max(1, repeat)):
        for vk in mod_vks:
            key_down(vk)
        press_vk(main_vk)
        for vk in reversed(mod_vks):
            key_up(vk)
        time.sleep(0.02)


def type_text_sendinput(text: str, interval: float = 0.004) -> None:
    for ch in text:
        if ch == "\r":
            continue
        if ch == "\n":
            press_vk(VK["enter"])
            time.sleep(interval)
            continue
        if ch == "\t":
            press_vk(VK["tab"])
            time.sleep(interval)
            continue
        units = ch.encode("utf-16-le")
        for i in range(0, len(units), 2):
            scan = int.from_bytes(units[i : i + 2], "little")
            _send_inputs([_unicode_input(scan, False), _unicode_input(scan, True)])
            time.sleep(interval)


def type_text_clipboard(text: str, restore_delay: float = 0.35) -> None:
    old = get_clipboard_text()
    if not set_clipboard_text(text):
        raise OSError("could not write to clipboard")
    time.sleep(0.06)
    key_combo("ctrl+v")
    time.sleep(restore_delay)
    if old is None:
        clear_clipboard()
    else:
        set_clipboard_text(old)


def type_text(text: str, method: str = "auto", interval: float = 0.004) -> str:
    if method == "auto":
        use_clipboard = any(ord(ch) > 127 for ch in text) or len(text) > 32 or "\n" in text
        method = "clipboard" if use_clipboard else "sendinput"
    if method == "clipboard":
        type_text_clipboard(text)
        return "clipboard"
    type_text_sendinput(text, interval=interval)
    return "sendinput"


def mouse_click(x: int, y: int, button: str = "left", count: int = 1, interval: float = 0.08, hold_ms: int = 0) -> None:
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.03)
    down, up = {
        "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
        "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
        "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
    }.get(button, (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP))
    for i in range(max(1, count)):
        user32.mouse_event(down, 0, 0, 0, 0)
        if hold_ms:
            time.sleep(hold_ms / 1000)
        user32.mouse_event(up, 0, 0, 0, 0)
        if i + 1 < count:
            time.sleep(interval)


def mouse_move(x: int, y: int, duration: float = 0.0) -> None:
    if duration <= 0:
        user32.SetCursorPos(int(x), int(y))
        return
    sx, sy = get_cursor_pos()
    steps = max(2, int(duration * 60))
    for i in range(1, steps + 1):
        t = i / steps
        user32.SetCursorPos(int(sx + (x - sx) * t), int(sy + (y - sy) * t))
        time.sleep(duration / steps)


def mouse_drag(x1: int, y1: int, x2: int, y2: int, button: str = "left", duration: float = 0.4) -> None:
    down, up = {
        "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
        "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
        "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
    }.get(button, (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP))
    user32.SetCursorPos(int(x1), int(y1))
    time.sleep(0.05)
    user32.mouse_event(down, 0, 0, 0, 0)
    steps = max(4, int(duration * 60))
    for i in range(1, steps + 1):
        t = i / steps
        user32.SetCursorPos(int(x1 + (x2 - x1) * t), int(y1 + (y2 - y1) * t))
        time.sleep(duration / steps)
    user32.mouse_event(up, 0, 0, 0, 0)


def mouse_scroll(amount: int, x: int | None = None, y: int | None = None) -> None:
    if x is not None and y is not None:
        user32.SetCursorPos(int(x), int(y))
        time.sleep(0.03)
    delta = int(amount) * 120
    user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, ctypes.c_ulong(delta & 0xFFFFFFFF).value, 0)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def rect_center(rect: list[int]) -> tuple[int, int]:
    return (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2


def describe() -> dict[str, Any]:
    return {
        "dpi": get_dpi(),
        "screen": get_screen_metrics(),
        "monitors": get_monitors(),
        "cursor": get_cursor_pos(),
        "foreground": get_window_info(get_foreground_window()) if get_foreground_window() else None,
        "admin": is_admin(),
        "session": session_id(),
    }


if __name__ == "__main__":
    import json
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(json.dumps(describe(), ensure_ascii=False, indent=2))