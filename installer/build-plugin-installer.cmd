@echo off
setlocal EnableExtensions

set "ARCH=%~1"
if not defined ARCH (
  if /I "%PROCESSOR_ARCHITECTURE%"=="ARM64" (set "ARCH=arm64") else (set "ARCH=x64")
)

if /I "%ARCH%"=="arm64" (
  set "RUST_TARGET=aarch64-pc-windows-msvc"
) else if /I "%ARCH%"=="x64" (
  set "RUST_TARGET=x86_64-pc-windows-msvc"
) else (
  echo Usage: %~nx0 [arm64^|x64]
  exit /b 2
)

for %%I in ("%~dp0..") do set "ROOT=%%~fI"
set "TARGET_DIR=%TEMP%\voice-command-plugin-build-%ARCH%"
set "VOICE_EXE=%TARGET_DIR%\%RUST_TARGET%\release\voice-mcp.exe"
set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"

if not exist "%ISCC%" (
  echo Inno Setup 6 was not found at "%ISCC%".
  exit /b 3
)

cargo build --locked --release --manifest-path "%ROOT%\voice-mcp\Cargo.toml" --target "%RUST_TARGET%" --target-dir "%TARGET_DIR%"
if errorlevel 1 exit /b %errorlevel%

"%ISCC%" /DArch=%ARCH% /DVoiceExe="%VOICE_EXE%" "%ROOT%\installer\Voice-Command-Plugin.iss"
if errorlevel 1 exit /b %errorlevel%

for %%I in ("%ROOT%\dist\Voice-Command-Plugin-Setup-%ARCH%.exe") do (
  echo Built %%~fI
  certutil -hashfile "%%~fI" SHA256
)

echo The installer is unsigned. Signing and release publication are separate owner actions.
exit /b 0
