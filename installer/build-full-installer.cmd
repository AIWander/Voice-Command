@echo off
setlocal EnableExtensions

set "ARCH=%~1"
set "RUNTIME_ROOT=%~2"
set "APP_VERSION=%~3"
if not defined ARCH (
  if /I "%PROCESSOR_ARCHITECTURE%"=="ARM64" (set "ARCH=arm64") else (set "ARCH=x64")
)
if not defined RUNTIME_ROOT set "RUNTIME_ROOT=%VOICE_COMMAND_RUNTIME_ROOT%"
if not defined APP_VERSION set "APP_VERSION=3.0.0"

if /I "%ARCH%"=="arm64" (
  set "RUST_TARGET=aarch64-pc-windows-msvc"
) else if /I "%ARCH%"=="x64" (
  set "RUST_TARGET=x86_64-pc-windows-msvc"
) else (
  echo Usage: %~nx0 [arm64^|x64] ^<runtime-root^> [app-version]
  exit /b 2
)

if not defined RUNTIME_ROOT (
  echo Runtime root is required. Pass it as argument 2 or set VOICE_COMMAND_RUNTIME_ROOT.
  exit /b 3
)
for %%D in (python models app) do (
  if not exist "%RUNTIME_ROOT%\%%D" (
    echo Missing runtime directory: "%RUNTIME_ROOT%\%%D"
    exit /b 4
  )
)
if not exist "%RUNTIME_ROOT%\Start-CPC-Voice.bat" (
  echo Missing runtime launcher: "%RUNTIME_ROOT%\Start-CPC-Voice.bat"
  exit /b 4
)
for %%F in (voice_app.py voice.config.toml) do (
  if not exist "%RUNTIME_ROOT%\app\%%F" (
    echo Missing public runtime file: "%RUNTIME_ROOT%\app\%%F"
    exit /b 4
  )
)

for %%I in ("%~dp0..") do set "ROOT=%%~fI"
set "TARGET_DIR=%TEMP%\voice-command-full-build-%ARCH%"
set "VOICE_EXE=%TARGET_DIR%\%RUST_TARGET%\release\voice-mcp.exe"
set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"

if not exist "%ISCC%" (
  echo Inno Setup 6 was not found at "%ISCC%".
  exit /b 5
)

cargo build --locked --release --manifest-path "%ROOT%\voice-mcp\Cargo.toml" --target "%RUST_TARGET%" --target-dir "%TARGET_DIR%"
if errorlevel 1 exit /b %errorlevel%

"%ISCC%" /DArch=%ARCH% /DVoiceExe="%VOICE_EXE%" /DRuntimeRoot="%RUNTIME_ROOT%" /DAppVersion=%APP_VERSION% "%ROOT%\installer\Voice-Command-Full.iss"
if errorlevel 1 exit /b %errorlevel%

for %%I in ("%ROOT%\dist\CPC-Voice-Setup-%ARCH%.exe") do (
  echo Built %%~fI
  certutil -hashfile "%%~fI" SHA256
)

echo The installer is unsigned. Signing and release publication are separate owner actions.
exit /b 0
