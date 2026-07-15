# Windows installer sources

## Full bundled release package

`Voice-Command-Full.iss` is the release path. It bundles all runtime layers in one installer:

- private Python runtime and dependencies;
- local speech-to-text model;
- Voice App and launcher bound to `localhost:5123`;
- architecture-matched Rust STDIO MCP server;
- one portable plugin surface for Codex, Claude-compatible hosts, and Grok;
- two concise operation and setup skills;
- Codex and Claude marketplace metadata;
- per-AI activation instructions rendered with installed absolute paths.

Speech recognition and its model run locally. Speech output currently uses
`edge-tts`, which calls Microsoft Edge's online text-to-speech service; the
package is therefore self-contained for installation, not fully offline.

The installer changes no AI configuration and trusts no plugin. During an interactive install, it copies the activation text to the clipboard, shows a popup, and offers a terminal copy. Silent installs skip clipboard and UI actions; they leave the rendered `APPLY_TO_YOUR_AI.txt` and `install-result.json` files for the operator or deployment system to consume. Starting the Voice App is an unchecked option and does not open the microphone; recording begins only after a direct `listen_for_speech` call.

The runtime root supplied at build time must contain:

```text
runtime-root/
  python/
  models/
  app/
    voice_app.py
  Start-CPC-Voice.bat
```

Build on Windows with Rust and Inno Setup 6:

```bat
installer\build-full-installer.cmd arm64 C:\path\to\runtime-root 3.0.0
installer\build-full-installer.cmd x64 C:\path\to\runtime-root 3.0.0
```

The build script uses locked Cargo dependencies and a temporary target directory, then writes an unsigned `CPC-Voice-Setup-<arch>.exe` under `dist`. Signing and GitHub publication are separate owner actions.

Use an appropriately licensed Inno Setup compiler for production builds. Inno
Setup 6.7 can label an unlicensed compiler as non-commercial; review the
[official commercial-license guidance](https://jrsoftware.org/isorder.php)
before publishing a commercial installer.

## Plugin-surface-only developer package

`Voice-Command-Plugin.iss` installs the Rust wrapper, plugin, skills, and activation handoff for a machine that already has a working Voice App or Python listener. It is not standalone: listening and playback control still require the backend on `localhost:5123`, and direct TTS fallback still requires `edge-tts`.

Build it only for development or an existing runtime:

```bat
installer\build-plugin-installer.cmd arm64
installer\build-plugin-installer.cmd x64
```

Do not publish the plugin-surface-only package as the all-in-one Voice-Command installer.

## Validate

Run the repository tests, Rust gate, and installed platform validators:

```powershell
py -3.11 -m pytest tests -q
.\installer\verify-rust.cmd
claude plugin validate --strict .\plugins\voice-command
grok plugin validate .\plugins\voice-command
```

Also validate the Codex plugin and both skills with the current Codex plugin-creator and skill-creator validators. Do not make a release claim from validator output alone. Smoke the built Rust executable over JSON-RPC, compile the Inno source, and inspect or install the package in a disposable environment before signing.
