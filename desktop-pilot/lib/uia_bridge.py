"""UI Automation bridge.

The rest of Desktop Pilot never imports `uiautomation` directly; it goes
through this module so that every UIA call is defensive. UIA providers in the
wild raise COM errors, hang, or return partial trees, and none of that should
take down a CLI command.
"""

from __future__ import annotations

import time
from typing import Any, Iterable, Iterator

import win32


def _auto():
    import uiautomation as auto  # imported lazily; costs ~200ms

    return auto


def _rect(value: Any) -> list[int] | None:
    if value is None:
        return None
    try:
        return [int(value.left), int(value.top), int(value.right), int(value.bottom)]
    except Exception:
        return None


def _safe(getter, default=None):
    try:
        return getter()
    except Exception:
        return default


def control_info(ctrl: Any) -> dict[str, Any]:
    info = {
        "name": _safe(lambda: ctrl.Name, ""),
        "type": _safe(lambda: ctrl.ControlTypeName, ""),
        "localized_type": _safe(lambda: ctrl.LocalizedControlType, ""),
        "class": _safe(lambda: ctrl.ClassName, ""),
        "automation_id": _safe(lambda: ctrl.AutomationId, ""),
        "rect": _rect(_safe(lambda: ctrl.BoundingRectangle)),
        "enabled": bool(_safe(lambda: ctrl.IsEnabled, False)),
        "offscreen": bool(_safe(lambda: ctrl.IsOffscreen, True)),
        "focused": bool(_safe(lambda: ctrl.HasKeyboardFocus, False)),
        "pid": _safe(lambda: ctrl.ProcessId, None),
    }
    info["patterns"] = _patterns(ctrl)
    return info


def _patterns(ctrl: Any) -> list[str]:
    found = []
    checks = [
        ("invoke", "GetInvokePattern"),
        ("value", "GetValuePattern"),
        ("text", "GetTextPattern"),
        ("toggle", "GetTogglePattern"),
        ("selection", "GetSelectionItemPattern"),
        ("expand", "GetExpandCollapsePattern"),
        ("scroll_item", "GetScrollItemPattern"),
        ("legacy", "GetLegacyIAccessiblePattern"),
    ]
    for name, method in checks:
        try:
            pattern = getattr(ctrl, method)()
            if pattern is not None:
                found.append(name)
        except Exception:
            pass
    return found


def root_control(window_handle: int | None = None, foreground: bool = False):
    auto = _auto()
    if window_handle:
        ctrl = auto.ControlFromHandle(int(window_handle))
        if ctrl is None:
            raise LookupError(f"no UIA control for window handle {window_handle}")
        return ctrl
    if foreground:
        ctrl = auto.GetForegroundControl()
        if ctrl is None:
            raise LookupError("no foreground UIA control")
        return ctrl
    ctrl = auto.GetRootControl()
    if ctrl is None:
        raise LookupError("no UIA root control")
    return ctrl


def control_at(x: int, y: int):
    auto = _auto()
    ctrl = auto.ControlFromPoint(int(x), int(y))
    if ctrl is None:
        raise LookupError(f"no UIA control at ({x}, {y})")
    return ctrl


def children(ctrl: Any) -> list[Any]:
    try:
        return list(ctrl.GetChildren())
    except Exception:
        return []


def walk(ctrl: Any, max_depth: int = 8, max_nodes: int = 3000) -> Iterator[tuple[str, int, Any]]:
    """Yield (path, depth, control) in DFS order.

    Path is a dot-separated child index from the root, e.g. "0.2.1".
    """
    stack: list[tuple[str, int, Any]] = [("0", 0, ctrl)]
    count = 0
    while stack and count < max_nodes:
        path, depth, node = stack.pop()
        yield path, depth, node
        count += 1
        if depth >= max_depth:
            continue
        kids = children(node)
        for index in range(len(kids) - 1, -1, -1):
            child_path = f"{path}.{index}" if path else str(index)
            stack.append((child_path, depth + 1, kids[index]))


def dump_tree(ctrl: Any, max_depth: int = 8, max_nodes: int = 3000) -> dict[str, Any]:
    nodes = []
    truncated = False
    for path, depth, node in walk(ctrl, max_depth=max_depth, max_nodes=max_nodes):
        item = control_info(node)
        item["path"] = path
        item["depth"] = depth
        item["children"] = len(children(node)) if depth < max_depth else 0
        nodes.append(item)
    if len(nodes) >= max_nodes:
        truncated = True
    return {"root": control_info(ctrl), "nodes": nodes, "truncated": truncated, "count": len(nodes)}


def _type_matches(actual: str, wanted: str) -> bool:
    a = (actual or "").lower()
    b = (wanted or "").lower()
    if not b:
        return True
    if a == b:
        return True
    if a.endswith("control"):
        a = a[: -len("control")]
    if b.endswith("control"):
        b = b[: -len("control")]
    return a == b


def _matches(info: dict[str, Any], name: str | None, control_type: str | None, automation_id: str | None, class_name: str | None, exact: bool) -> bool:
    if name:
        actual = info.get("name") or ""
        if exact:
            if actual != name:
                return False
        elif name.lower() not in actual.lower():
            return False
    if control_type and not _type_matches(info.get("type", ""), control_type):
        return False
    if automation_id and automation_id.lower() not in (info.get("automation_id") or "").lower():
        return False
    if class_name and class_name.lower() not in (info.get("class") or "").lower():
        return False
    return True


def find_all(
    ctrl: Any,
    name: str | None = None,
    control_type: str | None = None,
    automation_id: str | None = None,
    class_name: str | None = None,
    exact: bool = False,
    max_depth: int = 12,
    max_nodes: int = 5000,
    include_offscreen: bool = True,
) -> list[dict[str, Any]]:
    out = []
    for path, depth, node in walk(ctrl, max_depth=max_depth, max_nodes=max_nodes):
        info = control_info(node)
        if not include_offscreen and info["offscreen"]:
            continue
        if _matches(info, name, control_type, automation_id, class_name, exact):
            info["path"] = path
            info["depth"] = depth
            out.append(info)
    if out:
        # Multiple tabs/panes can expose same-named controls. Prefer what the
        # user can actually see and what currently has focus; keep the rest as
        # fallback instead of returning a hidden duplicate first.
        out.sort(key=lambda item: (bool(item.get("offscreen")), not bool(item.get("focused"))))
    return out


def find_first(ctrl: Any, **kwargs) -> dict[str, Any] | None:
    matches = find_all(ctrl, **kwargs)
    return matches[0] if matches else None


def select_path(ctrl: Any, path: str):
    node = ctrl
    parts = str(path).split(".")
    # walk() labels the root "0"; a child path is "0.2.1". The leading "0"
    # denotes the root itself, not its first child.
    if parts and parts[0] == "0":
        parts = parts[1:]
    for part in parts:
        if part == "":
            continue
        kids = children(node)
        index = int(part)
        if index < 0 or index >= len(kids):
            raise LookupError(f"path {path!r} does not exist at segment {part!r}")
        node = kids[index]
    return node


def read_text(ctrl: Any) -> dict[str, Any]:
    """Best-effort text extraction, trying value, text, then legacy patterns.

    A ValuePattern on a background tab can legitimately return "" while the
    TextPattern still holds the document. Treat empty as "try the next
    pattern", and only fall back to an empty successful read if every pattern
    is empty (a genuinely empty document).
    """
    empty_pattern = None
    for pattern_name, getter in (
        ("value", lambda: ctrl.GetValuePattern().Value),
        ("text", lambda: ctrl.GetTextPattern().DocumentRange.GetText(-1)),
        ("legacy", lambda: ctrl.GetLegacyIAccessiblePattern().Value),
    ):
        try:
            value = getter()
            if value is None:
                continue
            text = str(value)
            if text != "":
                return {"ok": True, "pattern": pattern_name, "text": text}
            empty_pattern = pattern_name
        except Exception:
            continue
    if empty_pattern:
        return {"ok": True, "pattern": empty_pattern, "text": ""}
    return {"ok": False, "error": "no readable text pattern", "info": control_info(ctrl)}


def _center(ctrl: Any) -> tuple[int, int]:
    rect = _rect(_safe(lambda: ctrl.BoundingRectangle))
    if not rect or rect[2] <= rect[0] or rect[3] <= rect[1]:
        raise ValueError("control has no clickable rectangle")
    return (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2


def _scroll_into_view(ctrl: Any) -> bool:
    try:
        ctrl.GetScrollItemPattern().ScrollIntoView()
        time.sleep(0.15)
        return True
    except Exception:
        return False


def activate(ctrl: Any, method: str = "auto") -> dict[str, Any]:
    """Activate a control, preferring semantic patterns over coordinates."""
    info = control_info(ctrl)
    # Text surfaces often expose a legacy default action that does not move
    # keyboard focus. A real click is what puts the caret where the next
    # keystroke will land.
    if method in {"auto", "click"} and info.get("type") in {"DocumentControl", "EditControl"}:
        _scroll_into_view(ctrl)
        x, y = _center(ctrl)
        win32.mouse_click(x, y)
        return {"ok": True, "method": "click", "x": x, "y": y}
    if method in {"auto", "invoke"}:
        try:
            ctrl.GetInvokePattern().Invoke()
            return {"ok": True, "method": "invoke"}
        except Exception as exc:
            if method == "invoke":
                return {"ok": False, "error": f"invoke failed: {exc}", "info": control_info(ctrl)}
    if method in {"auto", "select"}:
        try:
            ctrl.GetSelectionItemPattern().Select()
            return {"ok": True, "method": "selection"}
        except Exception:
            pass
    if method in {"auto", "toggle"}:
        try:
            ctrl.GetTogglePattern().Toggle()
            return {"ok": True, "method": "toggle"}
        except Exception:
            pass
    if method in {"auto", "legacy"}:
        try:
            ctrl.GetLegacyIAccessiblePattern().DoDefaultAction()
            return {"ok": True, "method": "legacy-default"}
        except Exception:
            pass
    if method in {"auto", "click"}:
        _scroll_into_view(ctrl)
        x, y = _center(ctrl)
        win32.mouse_click(x, y)
        return {"ok": True, "method": "click", "x": x, "y": y}
    return {"ok": False, "error": f"no activation method worked (requested {method})", "info": control_info(ctrl)}


def set_value(ctrl: Any, text: str) -> dict[str, Any]:
    try:
        ctrl.GetValuePattern().SetValue(text)
        return {"ok": True, "method": "value"}
    except Exception as exc:
        # Fall back to focus + clipboard typing.
        try:
            ctrl.SetFocus()
            time.sleep(0.05)
            ctrl.GetValuePattern().SetValue("")
            win32.type_text(text, method="clipboard")
            return {"ok": True, "method": "focus+clipboard", "note": str(exc)}
        except Exception as exc2:
            return {"ok": False, "error": f"set value failed: {exc}; fallback failed: {exc2}", "info": control_info(ctrl)}


def expand(ctrl: Any) -> dict[str, Any]:
    try:
        ctrl.GetExpandCollapsePattern().Expand()
        return {"ok": True, "method": "expand"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def collapse(ctrl: Any) -> dict[str, Any]:
    try:
        ctrl.GetExpandCollapsePattern().Collapse()
        return {"ok": True, "method": "collapse"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def focused() -> dict[str, Any]:
    auto = _auto()
    ctrl = auto.GetFocusedControl()
    if ctrl is None:
        return {"ok": False, "error": "no focused control"}
    return {"ok": True, "info": control_info(ctrl)}


def resolve(
    window_handle: int | None = None,
    foreground: bool = False,
    path: str | None = None,
    name: str | None = None,
    control_type: str | None = None,
    automation_id: str | None = None,
    class_name: str | None = None,
    exact: bool = False,
    max_depth: int = 12,
) -> tuple[Any, dict[str, Any]]:
    root = root_control(window_handle=window_handle, foreground=foreground)
    if path:
        ctrl = select_path(root, path)
        return ctrl, control_info(ctrl)
    if name or control_type or automation_id or class_name:
        matches = find_all(
            root,
            name=name,
            control_type=control_type,
            automation_id=automation_id,
            class_name=class_name,
            exact=exact,
            max_depth=max_depth,
        )
        usable = [m for m in matches if not m["offscreen"] and m["enabled"]]
        chosen = (usable or matches or [None])[0]
        if chosen is None:
            raise LookupError("no matching UIA control")
        ctrl = select_path(root, chosen["path"])
        return ctrl, chosen
    return root, control_info(root)