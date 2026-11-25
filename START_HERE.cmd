@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo.
echo  Desktop Pilot / 首次桌面握手
echo  --------------------------------
echo.

python bin\dp.py tour
if errorlevel 1 (
  echo.
  echo  [!] Tour failed. Run `python bin\dp.py doctor` for diagnostics.
)

echo.
echo  Screenshot and note are under runtime\shots and runtime\tmp.
echo  Console: python bin\dp.py console
echo.
pause