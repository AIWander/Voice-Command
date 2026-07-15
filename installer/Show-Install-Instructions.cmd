@echo off
setlocal
title Voice-Command activation instructions
set "GuidePath=%~dp0..\APPLY_TO_YOUR_AI.txt"
set "StatusPath=%~dp0..\clipboard-status.txt"
set "ClipboardStatus=unknown"
if exist "%StatusPath%" set /p "ClipboardStatus="<"%StatusPath%"
echo.
echo Voice-Command is installed but not enabled in an AI client.
if /I "%ClipboardStatus%"=="copied" (
    echo The instructions shown below were copied to your clipboard.
) else if /I "%ClipboardStatus%"=="unavailable" (
    echo Clipboard copy was unavailable. Open or copy from:
    echo "%GuidePath%"
) else if /I "%ClipboardStatus%"=="instructions-missing" (
    echo The activation guide could not be loaded. Re-run the installer.
) else (
    echo Clipboard copy could not be confirmed. Open or copy from:
    echo "%GuidePath%"
)
echo No AI config was changed and the microphone was not started.
echo.
if exist "%GuidePath%" type "%GuidePath%"
echo.
if /I not "%~1"=="--no-pause" pause
