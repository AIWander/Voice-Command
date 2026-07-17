@echo off
setlocal

set "ROOT=%~dp0.."
if not defined CARGO_TARGET_DIR set "CARGO_TARGET_DIR=C:\temp\rust-build-staged\voice-command"
set "VCVARS64=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"

if not exist "%VCVARS64%" (
  echo ERROR: Visual Studio x64 build tools were not found at:
  echo   %VCVARS64%
  exit /b 1
)

call "%VCVARS64%" >nul
if errorlevel 1 exit /b %errorlevel%

pushd "%ROOT%\voice-mcp"
cargo build --release --target x86_64-pc-windows-msvc
if errorlevel 1 (
  popd
  exit /b 1
)
popd

set "SOURCE=%CARGO_TARGET_DIR%\x86_64-pc-windows-msvc\release\voice-mcp.exe"
set "DIST=%ROOT%\dist"
if not exist "%DIST%" mkdir "%DIST%"
copy /y "%SOURCE%" "%DIST%\voice-mcp-x64.exe" >nul
if errorlevel 1 exit /b %errorlevel%

echo Built x64 MCP wrapper:
echo   %DIST%\voice-mcp-x64.exe
endlocal
