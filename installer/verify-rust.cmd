@echo off
setlocal EnableExtensions
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
set "MANIFEST=%ROOT%\voice-mcp\Cargo.toml"
set "TARGET_DIR=%TEMP%\voice-command-verify-rust"

cargo fmt --manifest-path "%MANIFEST%" -- --check
if errorlevel 1 exit /b %errorlevel%

cargo clippy --locked --manifest-path "%MANIFEST%" --target-dir "%TARGET_DIR%" -- -D warnings
if errorlevel 1 exit /b %errorlevel%

cargo test --locked --manifest-path "%MANIFEST%" --target-dir "%TARGET_DIR%"
if errorlevel 1 exit /b %errorlevel%

exit /b 0
