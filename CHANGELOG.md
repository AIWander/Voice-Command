# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- **Voice App** (`voice_app.py`, Windows x64 + ARM64) — a single windowed app that replaces the listening terminal: TTS playback queue with true pause/resume, listening with live mic level, color-coded transcript, and status display. Launch with `START_VOICE_APP.bat`.
- **Headset pause/resume** — the app registers a native Windows media session (SMTC via `winsdk`), so the play/pause button on your headset (or keyboard) pauses Claude's voice exactly like any other media. Fallback path (no `winsdk`): a persistent PowerShell-hosted WPF player plus a global media-key hook that only captures the key while the app's audio is active.
- **Listen handoff gated on playback end** — `listen_for_speech` now waits for queued/paused playback to finish before the ready-beep, so pausing the voice stalls the switch back to listening; the AI can finish responding while you're still hearing it.
- `speak` is **non-blocking** when the Voice App is running (queues audio and returns; `wait=true` restores blocking), with automatic fallback to the old direct playback when only the legacy listening server is up.
- New `playback_control` MCP tool: `pause | resume | toggle | skip | stop | status`.
- `voice.config.example.toml`: new `[playback]` section (backend, media-key hook, always-on-top) and `[listen] beam_size` (Whisper beam width, default 5).
- `requirements.txt`: `winsdk` on Windows for the native media session.
- Experimental macOS Voice App backend: `voice_app.py` can now start on Darwin using PyObjC `AVAudioPlayer` playback plus `MPNowPlayingInfoCenter` / `MPRemoteCommandCenter` hooks for pause/resume media controls.
- CI compile check now covers `voice_app.py`.

- Experimental macOS bootstrap support (#23 by @LeonidasZhak): `START_VOICE_SERVER.sh` launcher, Homebrew install notes, `afplay` playback on Darwin for both the Python MCP fallback and the Rust wrapper, macOS CI legs, and Darwin release targets. The terminal listening server remains the supported path on macOS.

## [0.3.0] - 2026-05-15

### Added

- `install.ps1` — single-script installer that detects ARM64/x64, downloads `voice-mcp.exe` from the latest GitHub release, installs Python listening-server deps, and auto-wires the `voice` MCP entry into Claude Code, Claude Desktop, Gemini CLI, and LM Studio configs (backed up first). Codex TOML config gets a printed snippet to append manually. Flags: `-Verify`, `-DryRun`, `-SkipPython`, `-InstallDir <path>`, `-PythonExe <path>`.
- README "Installer script" section documenting `install.ps1` usage and flags
- README "Config snippets per client" section with copy-paste templates for all 5 supported clients (Claude Code, Claude Desktop, Codex Windows app, Gemini CLI, LM Studio) with exact config paths
- README "Verify by saying hi" subsection — replaces formal health-check ceremony with a `speak` + `listen_for_speech` round-trip check that maps each half-failure to a specific cause (TTS off, MCP wiring broken, mic permission off, server not running)
- README "Microphone permission" mention moved into the symptom-driven `Verify by saying hi` diagnostic — most installs have "Let desktop apps access your microphone" ON by default, so it doesn't need a standalone preventative callout; flagging it only when the matching symptom (beep but no transcription) appears reads less alarmist
- README "Running headless on Windows" section covering `pythonw.exe` + `Start-Process -WindowStyle Hidden` pattern, persistence via `shell:startup` or Scheduled Task at logon, stop instructions, and resource footprint
- `voice.config.example.toml` at repo root — documented defaults users can copy to `voice.config.toml`
- CI workflow with smoke tests
- Test suite scaffold (tests/test_imports.py)
- README status badges
- `voice-mcp/` Rust source subdirectory (the MCP wrapper that voice-mcp.exe is built from)
- `voice-mcp/Cargo.lock` so the embedded Rust binary build is reproducible
- Release workflow (`.github/workflows/release.yml`) that builds ARM64 + x64 Windows binaries on `v*` tag push and attaches them to a GitHub release
- Rust check workflow (`.github/workflows/rust-check.yml`) that runs `cargo check` on every push
- README "Building voice-mcp from source" section with cargo build instructions
- README "Troubleshooting" section covering PortAudio ARM64, ffmpeg PATH, Python 3.13 wheel mismatch, microphone permissions, MCP connector toggles, listener connectivity, Whisper model download
- `.pre-commit-config.yaml` with trailing-whitespace, end-of-file-fixer, check-yaml, check-toml, ruff, ruff-format hooks
- `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1 — community contact method placeholder pending)
- Dependabot Cargo tracking for the embedded `voice-mcp/` crate
- Link from upstream [`AIWander/voice`](https://github.com/AIWander/voice) to the standalone [`AIWander/voice-mcp`](https://github.com/AIWander/voice-mcp) Rust wrapper

### Changed

- README restart language softened — most MCP clients pick up new STDIO servers on next tool-list refresh, no full restart required. Only Claude Desktop and Codex Windows app are flagged as occasionally needing a full quit-and-reopen on first wire-up.
- Documented listen defaults tuned for natural back-and-forth: `silence_timeout_secs` 4.0 → 3.0, `min_speech_duration_secs` 3.0 → 2.0. README still notes that typing-replacement / long-prose dictation benefits from raising `silence_timeout_secs` to 5.0+.

### Removed

- `speak_and_listen` tool from `voice-mcp` (Rust). It was a combined TTS-then-STT helper. The same flow works by calling `speak` then `listen_for_speech` separately — `speak` already blocks until playback finishes (half-duplex safety), so chaining the granular tools is equally safe and avoids parameter duplication. Reduces voice-mcp tool count from 10 to 9.

### Dependencies

- Bumped `tokio` 1.52.1 → 1.52.3 (#17), `openssl` 0.10.77 → 0.10.79 (#15), `reqwest` 0.12.28 → 0.13.3 (#14) — closes 5 HIGH + 1 medium + 1 low Dependabot security alerts on the embedded `voice-mcp` Rust crate
- Bumped GitHub Actions: `actions/checkout` 4 → 6 (#11), `actions/setup-python` 5 → 6 (#13), `softprops/action-gh-release` 2 → 3 (#10)

### Notes

- Sibling repo [`AIWander/voice-mcp`](https://github.com/AIWander/voice-mcp) holds the same Rust source as a standalone crate for users who want only the binary without the Python pieces
- `toml` 0.8 → 1.1 major-version bump (PR #16) held for manual review — major version usually has API churn that CI smoke tests don't catch
