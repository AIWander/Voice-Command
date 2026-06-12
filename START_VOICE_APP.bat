@echo off
REM Voice App — unified playback + listening window (no terminal needed).
REM Windows only for now; on macOS use ./START_VOICE_SERVER.sh instead.
setlocal
cd /d "%~dp0"

REM Optional: pin a config file alongside the script
if exist "%~dp0voice.config.toml" set "VOICE_CONFIG_PATH=%~dp0voice.config.toml"

REM Use local .venv if present, otherwise fall back to the windowless launcher.
REM On Windows ARM64 you'll want a .venv built from x64 Python 3.11 because
REM ctranslate2 (a faster-whisper dependency) doesn't ship ARM64 wheels.
if exist "%~dp0.venv\Scripts\pythonw.exe" (
    start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0voice_app.py"
) else (
    start "" pyw -3 "%~dp0voice_app.py"
)
