@echo off
rem Windows 用の起動: アダルト用ボード(+設定があればエンタメ用・占い用)を裏で動かし、ブラウザで開く。
rem 同じボードが動いていたら、二重には起動しない。
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" ( echo 先に scripts\setup.ps1 を実行してください & pause & exit /b 1 )
if not exist ".env" ( echo .env がありません & pause & exit /b 1 )
if not exist "logs" mkdir logs

call :board 8765 ""
findstr /b /c:"CHANNEL_IDS_ENT=" .env >nul && call :board 8766 ent
findstr /b /c:"CHANNEL_IDS_URANAI=" .env >nul && call :board 8767 uranai

timeout /t 8 /nobreak >nul
start "" http://localhost:8765
exit /b 0

:board
netstat -ano | findstr /r /c:":%1 .*LISTENING" >nul && exit /b 0
rem pythonw で窓を出さずに裏で動かす。ログは logs\ に出る
start "" /b cmd /c ".venv\Scripts\python.exe -m xdeck %~2 >> logs\board_%1.log 2>&1"
exit /b 0
