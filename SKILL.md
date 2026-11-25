---
name: desktop-pilot
description: Windows 桌面控制技能。需要在图形界面里看屏幕、找控件、点击、输入、按键、拖拽、OCR 读字，或验证某个桌面操作是否真的发生时使用。优先 UIA 语义定位，其次 OCR，坐标点击只作兜底。
---

# Desktop Pilot

给 DSH 装上眼睛和手：把 Windows 桌面变成一组可组合、可验证的 JSON 原语。

## 什么时候用

当任务卡在“最后一步只能点 GUI”时：

- 某个系统只有图形界面，没有 CLI/API。
- 需要在浏览器、记事本、Office、设置面板、游戏启动器里点一个按钮。
- 需要把一段中文/emoji/长文本输入到不接受命令行参数的应用。
- 需要确认弹窗、菜单、画布上到底显示了什么。
- 需要把屏幕上的文字读出来，并拿到它的坐标。

不适用于：跨平台、提权、绕过安全机制、无人值守 7×24 跑批。

## 入口

技能安装后，每个 DSH 会话都可以直接调用：

```bash
python "$env:USERPROFILE\.dsh\skills\desktop-pilot\bin\dp.py" doctor
```

上面是目录联接安装的入口。如果通过 DSH 插件市场安装，入口在插件包内，技能正文末尾会注入它的绝对路径；优先用那个路径。

在项目目录内也可以：

```bash
python desktop-pilot/bin/dp.py doctor
```

所有命令输出**一行 JSON**。成功 `ok: true`，失败 `ok: false` 且退出码非零。不要解析人类可读文本，解析 JSON。

## 先跑一次自证

```bash
dp.py tour
```

打开一个记事本便签，写入宿主/屏幕/DPI/时间，再用 UIA 读回并追加 `[read-back ok]`，最后截图。返回 `before`、`after`、`screenshot`。它一次性验证窗口、UIA、剪贴板输入、读回和截图五条链路。

## 黄金路径

1. **确认能力**
   ```bash
   dp.py doctor
   ```
   看 `checks.uia.ok`、`checks.ocr.languages`、`screen`、`dpi`、`foreground`。

2. **找窗口**
   ```bash
   dp.py windows
   dp.py windows --title "记事本"
   dp.py windows --class Notepad
   ```
   拿到 `handle`。后续 `--window <handle>` 比反复按标题找更稳。

3. **看结构**
   ```bash
   dp.py uia --window <handle> --depth 6
   dp.py uia --window <handle> --find "保存" --type Button
   dp.py uia --window <handle> --find "文本编辑器" --read
   ```
   `uia` 输出每个节点的 `name/type/class/automation_id/rect/path/patterns`。
   `path` 是子索引路径（如 `0.1.2`），可在同一次命令里用 `--path` 精确选中。

4. **操作**
   ```bash
   dp.py uia --window <handle> --find "保存" --click
   dp.py click --window <handle> --rel 120,80
   dp.py type --window <handle> --text "你好，世界" --enter
   dp.py key --keys "ctrl+s"
   dp.py scroll --amount -3
   dp.py drag --from 100,200 --to 500,600
   ```

5. **验证**
   ```bash
   dp.py screen --window <handle> --out runtime/shots/after.png
   dp.py uia --window <handle> --find "文本编辑器" --read
   dp.py ocr --window <handle> --find "已完成"
   ```
   不要假设点击生效；用 UIA 读回、OCR 或截图确认。

## 命令面

```
doctor
tour
windows [--all] [--title T] [--class C] [--pid P]
screen [--window H|--title T|--pid P] [--monitor N] [--region x,y,w,h] [--out PATH] [--no-cursor]
focus (--window H|--title T|--pid P)
launch --target EXE|URL|FILE [--args "..."] [--wait-title T] [--timeout S]
uia [--window H|--title T|--pid P|--foreground] [--depth N] [--find NAME] [--type TYPE] [--id ID] [--class C] [--path P] [--read] [--click] [--invoke] [--set-value TEXT] [--focus] [--all]
click (--x X --y Y | --point x,y | --rel x,y [--client] | --uia NAME) [--button left|right|middle] [--count N] [--hold-ms N]
type --text T [--file PATH] [--window H|--title T] [--uia NAME] [--replace] [--clear] [--enter] [--method auto|clipboard|sendinput] [--secret]
key --keys "ctrl+s" [--repeat N] [--allow-dangerous]
scroll --amount N [--x X --y Y]
drag --from x,y --to x,y [--duration S]
clipboard [--set TEXT|--clear] [--secret]
ocr [--window H|--title T|--monitor N|--region x,y,w,h] [--find TEXT] [--all] [--click] [--language zh-Hans-CN]
wait --window-title T [--pid P] [--process NAME] [--timeout S]
stop [--reason TEXT]
resume
status
log [--tail N]
console [--port 8765] [--no-open]
install [--force]
uninstall
```

`screen` / `ocr` 默认截全屏；`--window` 截窗口，`--monitor` 截某个显示器，`--region` 截区域。截图默认保存到 `runtime/shots/`，路径在 JSON 的 `path` 字段。

## UIA 优先，OCR 兜底，坐标最后

- **UIA** 能给出控件名称、类型、边界和可用的 Pattern（`invoke/value/toggle/selection/expand`）。先 `uia` 找，再 `--click`/`--invoke`/`--set-value`。
- **OCR** 用于画布、游戏、自绘界面、Electron/Chrome 页面。Chrome 的 UIA 往往只暴露窗口框架，不暴露 DOM；这时用 `ocr --find "文字" --click`。
- **坐标** 只在 UIA 和 OCR 都失效时用。坐标是**物理像素**，进程已做 per-monitor DPI 感知；不要再用逻辑像素换算。

### Windows 11 记事本参考结构

```
WindowControl class=Notepad
  PaneControl class=NotepadTextBox
    DocumentControl name=文本编辑器 class=RichEditD2DPT
```

读取正文：

```bash
dp.py uia --window <handle> --find "文本编辑器" --read
```

写入正文：先 `--find "文本编辑器" --click` 把焦点放进文档，再 `type`。或者直接：

```bash
dp.py type --window <handle> --uia "文本编辑器" --replace --text "..."
```

## 输入规则

- 中文、emoji、长文本默认走**剪贴板粘贴**，并在粘贴后恢复原剪贴板。`SendInput` 的 Unicode 注入容易被输入法拦截、乱序或丢字。
- `--method sendinput` 只适合 ASCII 短文本。
- `--secret` 让动作日志不记录明文；输出也不回显 `text`。
- 危险组合键（`alt+f4`、`win+r`、`ctrl+shift+esc`、`alt+tab` 等）必须显式加 `--allow-dangerous`。
- `type --enter` 在输入结束后按回车；不会自动提交表单，除非应用自己这么做。

## STOP

任何动作前都会检查 `runtime/STOP`。触发方式：

```bash
dp.py stop --reason "manual"
dp.py resume
```

或打开 `dp.py console`，点红色 STOP。STOP 是文件，不是进程信号，跨进程、跨会话有效。触发后 `click/type/key/drag/scroll/launch/focus` 返回 `code: "stopped"` 和退出码 3；`windows/screen/status/log/doctor` 仍可读。

## 观察台

```bash
dp.py console --port 8765 --no-open
```

只绑定 `127.0.0.1`，启动时打印 URL 和 token。页面实时截屏、列窗口、看动作日志、跑 OCR、STOP/RESUME。POST 需要 token；没有远程点击/输入接口。

## 安装与卸载

```bash
dp.py install
dp.py uninstall
```

安装做的是目录联接：`~/.dsh/skills/desktop-pilot` → 本项目。项目是唯一真源；删掉项目，技能就断。卸载只移除联接，不删项目文件。

新开一个 DSH 会话后，技能列表中应出现 `desktop-pilot`。如果没出现，检查：

```bash
dp.py status
```

看 `skill.exists`、`skill.points_to_project`。

## 失败排查

| 现象 | 检查 |
| --- | --- |
| 点击位置偏了 | 是否在 150% 缩放？`doctor` 的 `dpi` 应为 144，`screen` 应为 2560×1600；进程已做 DPI 感知，不要手动乘 1.5 |
| `uia` 找不到控件 | Chrome/Electron 可能不暴露 DOM；改用 `ocr --find`；或提高 `--depth` |
| 中文输入乱序 | 用默认 `--method auto` 或 `--method clipboard`，不要用 `sendinput` |
| OCR 乱码 | PowerShell 输出必须是 UTF-8；`scripts/ocr.ps1` 已设置 `Console.OutputEncoding` |
| 窗口最小化截图为空 | 先 `focus` 恢复窗口；`capture_window` 对最小化窗口会报错 |
| `PrintWindow` 全黑 | 已自动回退到屏幕裁剪；窗口必须在虚拟屏幕内且未被遮挡 |
| 命令返回 `stopped` | `runtime/STOP` 存在；`dp.py resume` |
| 安装时报 target 已存在 | 目标不是指向本项目的联接；确认后可 `dp.py install --force`，旧目标会备份为 `.bak-时间戳` |

## 输出契约

成功：

```json
{"ok": true, "...": "..."}
```

失败：

```json
{"ok": false, "error": "human readable", "code": "ExceptionClass", "detail": "traceback"}
```

动作日志在 `runtime/actions.jsonl`，每行一个 JSON，字段：`ts/action/ok/pid/payload`。敏感键（`password/token/secret/authorization/cookie/...`）自动替换为 `***`。

## 边界

- 只操作当前登录会话的可见桌面；不跨会话、不提权。
- 不主动读取浏览器密码库、不抓取登录后的敏感页面。
- 不做隐藏、不做持久化、不做绕过检测。
- 任何自动化都可能点错；高风险动作前先截图，动作后用 UIA/OCR 验证。