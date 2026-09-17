@echo off
setlocal EnableExtensions

set "ARCH=%~1"
set "RUNTIME_ROOT=%~2"
set "APP_VERSION=%~3"
if not defined ARCH (
  if /I "%PROCESSOR_ARCHITECTURE%"=="ARM64" (set "ARCH=arm64") else (set "ARCH=x64")
)
if not defined RUNTIME_ROOT set "RUNTIME_ROOT=%VOICE_COMMAND_RUNTIME_ROOT%"
if not defined APP_VERSION set "APP_VERSION=3.1.0"

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
for %%F in (voice_app.py voice_interrupt.py voice.config.toml) do (
  if not exist "%RUNTIME_ROOT%\app\%%F" (
    echo Missing public runtime file: "%RUNTIME_ROOT%\app\%%F"
    exit /b 4
  )
)

for %%I in ("%~dp0..") do set "ROOT=%%~fI"
set "TARGET_DIR=%TEMP%\voice-command-full-build-%ARCH%"
set "VOICE_EXE=%TARGET_DIR%\%RUST_TARGET%\release\voice-mcp.exe"
set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"

rem Measure the deepest path inside the runtime payload, relative to {app}, and
rem hand it to the installer as PayloadMaxRelLen. The .iss uses it to reject an
rem over-long destination BEFORE copying: Windows caps a usable path at 259, and a
rem 254-char destination previously made ONNX payload creation fail, Setup exit 5,
rem and the whole install roll back.
rem
rem TWO IMPLEMENTATION TRAPS, both hit for real while writing this:
rem  1. Get-ChildItem -Recurse does NOT traverse junctions or symlinks. A runtime
rem     root that junctions in the heavy python/ and models/ trees - a normal way
rem     to assemble one without copying 2 GB - measured 22 instead of 159, which
rem     would have handed the installer a 236 budget instead of 99 and silently
rem     disarmed the guard. dir /s /b follows junctions, so it sees the payload.
rem  2. Computing the max length with a batch subroutine per file meant 67,000+
rem     CALL invocations and took minutes. dir pipes straight into ONE PowerShell
rem     pass instead, which is why the length maths lives there and not in cmd.
set "PAYLOAD_MAX_REL="
set "PAYLOAD_FILE_COUNT=0"
set "RR=%RUNTIME_ROOT%"
if "%RR:~-1%"=="\" set "RR=%RR:~0,-1%"
for /f "usebackq tokens=1,2" %%A in (`dir /s /b /a-d "%RR%" 2^>nul ^| powershell -NoProfile -Command "$n=(Get-Item -LiteralPath $env:RR).FullName.Length+1; $m=0; $c=0; foreach($line in $input){ if($line){ $c++; $l=$line.Length-$n; if($l -gt $m){$m=$l} } }; \"$m $c\""`) do (
  set "PAYLOAD_MAX_REL=%%A"
  set "PAYLOAD_FILE_COUNT=%%B"
)
if not defined PAYLOAD_MAX_REL (
  echo Could not measure the payload depth under "%RUNTIME_ROOT%".
  echo Refusing to build with an unverified destination-length guard.
  exit /b 6
)
rem Sanity floor: the bundled CPython tree alone is tens of thousands of files, so a
rem tiny count means the traversal missed the payload, not that the payload is small.
if %PAYLOAD_FILE_COUNT% LSS 1000 (
  echo Measured only %PAYLOAD_FILE_COUNT% payload files under "%RUNTIME_ROOT%".
  echo Too few to be the bundled runtime - the traversal probably missed a junction,
  echo or the runtime root is incomplete. Refusing to build.
  exit /b 7
)
echo Payload files measured: %PAYLOAD_FILE_COUNT%
echo Deepest payload path relative to the install folder: %PAYLOAD_MAX_REL% characters.
echo Installer will reject destinations longer than 259-1-%PAYLOAD_MAX_REL% characters.



if not exist "%ISCC%" (
  echo Inno Setup 6 was not found at "%ISCC%".
  exit /b 5
)

rem Keep the build machine out of the shipped binary. Without this, voice-mcp.exe
rem carried 900+ copies of the builder's profile path: Rust panic locations point
rem at %USERPROFILE%\.rustup and %USERPROFILE%\.cargo\registry, and the bundled
rem aws-lc C code embeds __FILE__ for every source file. Both need their own flag:
rem  - Rust: --remap-path-prefix (appended, so a caller's RUSTFLAGS survive).
rem  - C:    aws-lc-sys compiles with clang-cl on arm64 and cl.exe on x64, and each
rem          compiler only understands its own spelling. /d1trimfile is silently
rem          ignored by clang-cl, which is how the first attempt still leaked 84 paths.
rem Verified 2026-09-16: 0 hits for the profile path, repo path or host name in
rem either architecture's binary, and both still answer MCP initialize + tools/list.
set "RUSTFLAGS=%RUSTFLAGS% --remap-path-prefix=%USERPROFILE%=/build --remap-path-prefix=%ROOT%=/voice-command"
if defined CARGO_HOME set "RUSTFLAGS=%RUSTFLAGS% --remap-path-prefix=%CARGO_HOME%=/cargo"
if defined RUSTUP_HOME set "RUSTFLAGS=%RUSTFLAGS% --remap-path-prefix=%RUSTUP_HOME%=/rustup"
set "CFLAGS_aarch64_pc_windows_msvc=%CFLAGS_aarch64_pc_windows_msvc% /clang:-ffile-prefix-map=%USERPROFILE%=/build"
set "CFLAGS_x86_64_pc_windows_msvc=%CFLAGS_x86_64_pc_windows_msvc% /d1trimfile:%USERPROFILE%\"

cargo build --locked --release --manifest-path "%ROOT%\voice-mcp\Cargo.toml" --target "%RUST_TARGET%" --target-dir "%TARGET_DIR%"
if errorlevel 1 exit /b %errorlevel%

"%ISCC%" /DArch=%ARCH% /DVoiceExe="%VOICE_EXE%" /DRuntimeRoot="%RUNTIME_ROOT%" /DAppVersion=%APP_VERSION% /DPayloadMaxRelLen=%PAYLOAD_MAX_REL% "%ROOT%\installer\Voice-Command-Full.iss"
if errorlevel 1 exit /b %errorlevel%

for %%I in ("%ROOT%\dist\CPC-Voice-Setup-%ARCH%.exe") do (
  echo Built %%~fI
  certutil -hashfile "%%~fI" SHA256
)

echo The installer is unsigned. Signing and release publication are separate owner actions.
exit /b 0

