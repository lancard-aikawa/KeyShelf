@echo off
rem Start KeyShelf (local web UI on 127.0.0.1:20002) and open the browser.
rem Close this window or press Ctrl+C to stop the server.
setlocal
cd /d "%~dp0"
set "URL=http://127.0.0.1:20002/"

rem Already running: just open the browser.
curl -s -o nul -m 2 "%URL%api/list" >nul 2>nul
if not errorlevel 1 (
  echo KeyShelf is already running: %URL%
  start "" "%URL%"
  exit /b 0
)

where uv >nul 2>nul
if errorlevel 1 (
  echo uv was not found. Install uv first: https://docs.astral.sh/uv/
  pause
  exit /b 1
)

title KeyShelf
uv run keyshelf serve
if errorlevel 1 pause
