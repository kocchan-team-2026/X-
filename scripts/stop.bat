@echo off
rem ボード(8765〜8767)を止める。Xdeck 本体は止めない
for %%P in (8765 8766 8767) do (
  for /f "tokens=5" %%A in ('netstat -ano ^| findstr /r /c:":%%P .*LISTENING"') do taskkill /PID %%A /F >nul 2>&1
)
echo stopped
