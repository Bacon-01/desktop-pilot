# Desktop Pilot — 给 DSH 装上眼睛和手

## 意图

DSH 已经能读写文件、执行命令、调度子代理，但它看不见屏幕，也不能操作图形界面。很多真实任务最后一步恰恰卡在这里：点一个按钮、在某个只提供 GUI 的系统里填一张表、确认一个弹窗、从一块画布上读数。

Desktop Pilot 是一个 Windows 桌面控制层：把“看屏幕、找控件、点、输入、验证”变成一组 JSON 命令行原语，让 DSH 可以像操作文件一样操作桌面。

它不是又一个自动化脚本，也不是一个演示网页。它是 DSH 的一项新能力，装进 `~/.dsh/skills` 后，每个新会话都能直接调用。

## 目标

- 从任意 DSH 会话，能枚举窗口、截图、读取 UIA 树、OCR、点击、输入、按键、拖拽、滚动。
- 优先使用 UI Automation 的语义定位（名称、类型、AutomationId），坐标点击只作为兜底。
- 每一步都能被验证：截图、UIA 读回、OCR 文本、动作日志。
- 有一条随时可触发的停止路径：`STOP` 文件 + 控制台红色按钮。
- 安装后不需要常驻服务；控制台是可选的人类观察窗口。

## 非目标

- 跨平台。先只做 Windows。
- 绕过系统安全机制、提权、隐藏行为。
- 7×24 无人值守。它由 DSH 在需要时调用。
- 替代 DSH 已有的文件/命令工具。

## 架构

```
desktop-pilot/
  SKILL.md                 # DSH 技能说明与操作规程
  bin/dp.py                # CLI 入口，统一 JSON 输出
  lib/win32.py             # DPI、窗口、截图、键鼠、剪贴板
  lib/uia_bridge.py        # UI Automation 树、查找、调用
  lib/ocr_bridge.py        # Windows 内置 OCR（PowerShell WinRT）
  lib/runtime.py           # 路径、日志、STOP、脱敏
  scripts/ocr.ps1          # Windows.Media.Ocr 封装
  scripts/install.ps1      # 安装为 DSH 技能（目录联接）
  scripts/uninstall.ps1    # 只移除联接，不删项目
  console/server.py        # 本地观察台：实时截图 + 动作日志 + STOP
  console/static/index.html
  tests/smoke_test.py      # 端到端自检
```

## 关键决策

- **Python + ctypes，不依赖 pyautogui。** Pillow 和 `uiautomation` 已可用；输入、窗口、剪贴板用 Win32 API 直接实现，避免额外二进制和版本问题。
- **UIA 优先，OCR 兜底，坐标最后。** UIA 能给出控件名称和边界，比猜坐标稳；OCR 解决画布、游戏、自绘界面；坐标点击只在前两者都失效时使用。
- **文本输入默认走剪贴板。** 中文、emoji、长文本用 `SendInput` 的 Unicode 注入容易被输入法拦截或乱序；剪贴板粘贴更可靠，并在粘贴后恢复原剪贴板。
- **截图带鼠标标记。** 截图时在光标位置画一个红白十字，方便人工观察或多模态模型确认光标；纯 UIA/OCR 路径不依赖这个标记。
- **动作日志，按需截图。** 每次操作记录参数、结果和耗时；截图由 `screen`/`ocr`/`tour` 显式生成，不偷偷常驻录屏。敏感文本用 `--secret` 脱敏。
- **STOP 是文件，不是进程信号。** 任何命令执行前检查 `runtime/STOP`；控制台按钮和 `dp.py stop` 都只是创建这个文件。跨进程、跨会话都有效。
- **安装用目录联接。** `~/.dsh/skills/desktop-pilot` 指向本项目。项目是唯一真源；删掉项目，技能就断了。这是“不可删除性”的实际来源，而不是口号。

## 命令面

```
doctor
tour
windows [--pid|--title|--class]
screen [--window|--region|--monitor] [--out]
focus (--window|--title|--pid)
launch --target <exe|url|file> [--wait-title]
uia [--window|--foreground] [--depth] [--find NAME] [--type TYPE] [--click|--invoke|--set-value]
click (--x/--y | --window --rel | --uia NAME)
type --text <text> [--window] [--method auto|clipboard|sendinput] [--secret]
key --keys "ctrl+s" [--repeat]
scroll --amount <n>
drag --from x,y --to x,y
clipboard [--set TEXT]
ocr [--window|--screen] [--find TEXT] [--click]
wait --window-title <substr> [--timeout]
stop | resume | status
log [--tail N]
console [--port]
```

所有命令输出 JSON；失败时输出 `{"ok": false, "error": ...}` 并以非零退出。

## 安全与边界

- 只绑定 `127.0.0.1`；控制台 POST 需要启动时生成的 token。
- `--secret` 不记录明文；日志中的 `password/token/secret` 字段统一替换。
- 危险按键（`alt+f4`、`win+r`、`ctrl+shift+esc` 等）需要 `--allow-dangerous`，并记录。
- 不主动读取浏览器密码库、不截取登录后的敏感页面；用户明确要求时除外。
- 任何时刻 `dp.py stop` 或控制台 STOP 后，下一条命令立即拒绝执行。

## 验收

1. `dp.py doctor` 在真实桌面会话中返回屏幕、DPI、UIA、OCR、前台窗口。
2. `dp.py windows` 能看到 DSH、浏览器、记事本等窗口。
3. `dp.py screen` 生成有效 PNG，尺寸与虚拟屏幕一致。
4. 打开记事本，输入一段中英混排文本，UIA 读回逐字一致。
5. `dp.py uia --find "文件" --click` 能打开记事本菜单；`key esc` 关闭。
6. `dp.py tour` 能打开便签、写入文本、UIA 读回并生成截图。
7. `dp.py ocr --screen --find "..."` 能找到屏幕上的文字并给出坐标。
8. `dp.py stop` 后任何点击/输入返回 stopped；`resume` 恢复。
9. 安装后新开 DSH 会话，技能目录中出现 `desktop-pilot`。
10. 观察台 `/api/status`、`/api/screen`、`/api/stop`、`/api/resume` 在 `127.0.0.1` 上可用。