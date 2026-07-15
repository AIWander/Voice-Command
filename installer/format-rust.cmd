@echo off
setlocal EnableExtensions
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
cargo fmt --manifest-path "%ROOT%\voice-mcp\Cargo.toml"
exit /b %errorlevel%
