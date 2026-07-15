import json
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "voice-command"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_codex_marketplace_points_to_optional_plugin():
    market = load_json(ROOT / ".agents" / "plugins" / "marketplace.json")
    assert market["name"] == "aiwander-voice-command"
    assert len(market["plugins"]) == 1
    entry = market["plugins"][0]
    assert entry["name"] == "voice-command"
    assert entry["source"]["path"] == "./plugins/voice-command"
    assert entry["policy"]["installation"] == "AVAILABLE"


def test_claude_marketplace_points_to_same_plugin():
    market = load_json(ROOT / ".claude-plugin" / "marketplace.json")
    assert market["name"] == "aiwander-voice-command"
    assert market["plugins"][0]["source"] == "./plugins/voice-command"


def test_manifests_and_mcp_registration_are_consistent():
    codex = load_json(PLUGIN / ".codex-plugin" / "plugin.json")
    claude = load_json(PLUGIN / ".claude-plugin" / "plugin.json")
    mcp = load_json(PLUGIN / ".mcp.json")
    cargo = tomllib.loads((ROOT / "voice-mcp" / "Cargo.toml").read_text(encoding="utf-8"))
    assert codex["name"] == claude["name"] == "voice-command"
    assert codex["version"] == claude["version"] == cargo["package"]["version"]
    assert codex["mcpServers"] == "./.mcp.json"
    assert "hooks" not in codex
    assert mcp == {
        "mcpServers": {
            "voice": {"command": "voice-mcp.exe", "args": []}
        }
    }


def test_two_concise_voice_skills_have_valid_names():
    skill_paths = sorted(PLUGIN.glob("skills/*/SKILL.md"))
    assert [path.parent.name for path in skill_paths] == [
        "voice-command",
        "voice-command-setup",
    ]
    for path in skill_paths:
        text = path.read_text(encoding="utf-8")
        assert text.startswith("---\nname: ")
        assert "\ndescription: " in text
        assert "[TODO:" not in text
        assert len(text.splitlines()) < 90


def test_rust_contract_is_ten_voice_tools_and_loopback_only():
    source = (ROOT / "voice-mcp" / "src" / "main.rs").read_text(encoding="utf-8")
    tool_block = source.split("fn tool_definitions()", 1)[1].split("fn rolling_log_path", 1)[0]
    names = re.findall(r'"name": "([a-z_]+)"', tool_block)
    assert names == [
        "speak",
        "playback_control",
        "listen_for_speech",
        "start_voice_mode",
        "voice_checkpoint",
        "voice_load_checkpoint",
        "voice_get_transcript",
        "voice_add_note",
        "list_voices",
        "get_config",
    ]
    assert "0.0.0.0" not in source
    for url in re.findall(r'http://[^"\s]+', source):
        assert url.startswith("http://localhost:5123")
    assert '"version": env!("CARGO_PKG_VERSION")' in source


def test_full_installer_bundles_backend_plugin_and_ui_handoff():
    iss = (ROOT / "installer" / "Voice-Command-Full.iss").read_text(encoding="utf-8")
    readme = (ROOT / "installer" / "README.md").read_text(encoding="utf-8")
    finalize = (ROOT / "installer" / "Finalize-Install.ps1").read_text(encoding="utf-8")
    notify = (ROOT / "installer" / "Notify-Install.ps1").read_text(encoding="utf-8")
    assert "PrivilegesRequired=lowest" in iss
    assert "ChangesEnvironment=no" in iss
    assert "cpc_config_editor" not in iss.lower()
    for payload in (
        "\\python\\*",
        "\\models\\*",
        "\\app\\voice_app.py",
        "\\app\\voice.config.toml",
        "Start-CPC-Voice.bat",
    ):
        assert payload in iss
    assert "\\app\\*" not in iss
    assert "AGENTS.md" not in iss
    assert "VOICE_SYSTEM.md" not in iss
    assert "marketplace\\plugins\\voice-command" in iss
    assert "does not open the microphone" in iss
    assert "Flags: postinstall nowait skipifsilent unchecked" in iss
    assert "Set-Clipboard" in notify
    assert "MessageBox" in notify
    assert "full_runtime_bundled" in finalize
    assert "client_configs_changed = $false" in finalize
    assert "microphone_started = $false" in finalize
    assert "complete offline" not in iss.lower()
    assert "full offline" not in readme.lower()
    assert "edge-tts requires network access" in iss
    assert "not fully offline" in readme
    assert "C:\\CPC" not in iss
    assert "C:\\Users\\josep" not in iss


def test_notify_reports_forced_clipboard_failure_without_ui(tmp_path):
    powershell = shutil.which("powershell.exe") or shutil.which("powershell") or shutil.which("pwsh")
    command_prompt = shutil.which("cmd.exe") or shutil.which("cmd")
    if not powershell or not command_prompt:
        pytest.skip("The Windows installer shell is unavailable on this CI runner")

    app_dir = tmp_path / "Voice Command Test"
    app_dir.mkdir()
    installer_dir = app_dir / "installer"
    installer_dir.mkdir()
    instructions_path = app_dir / "APPLY_TO_YOUR_AI.txt"
    instructions_path.write_text("Test activation instructions\n", encoding="utf-8")
    terminal_path = installer_dir / "Show-Install-Instructions.cmd"
    shutil.copy2(ROOT / "installer" / "Show-Install-Instructions.cmd", terminal_path)

    completed = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "installer" / "Notify-Install.ps1"),
            "-AppDir",
            str(app_dir),
            "-ForceClipboardFailure",
            "-NoUi",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert (app_dir / "clipboard-status.txt").read_text(encoding="utf-8").strip() == "unavailable"
    output = completed.stdout + completed.stderr
    assert "Clipboard copy was unavailable." in output
    assert str(instructions_path) in output
    assert "copied to your clipboard" not in output

    terminal = subprocess.run(
        [command_prompt, "/d", "/c", str(terminal_path), "--no-pause"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert terminal.returncode == 0, terminal.stderr
    assert "Clipboard copy was unavailable." in terminal.stdout
    assert "were copied to your clipboard" not in terminal.stdout


def test_terminal_message_uses_recorded_clipboard_status():
    terminal = (ROOT / "installer" / "Show-Install-Instructions.cmd").read_text(encoding="utf-8")
    assert "clipboard-status.txt" in terminal
    assert 'if /I "%ClipboardStatus%"=="copied"' in terminal
    assert 'if /I "%ClipboardStatus%"=="unavailable"' in terminal
    assert "Clipboard copy could not be confirmed." in terminal
    assert "The same instructions shown below are on your clipboard." not in terminal


def test_silent_install_renders_files_without_clipboard_or_ui_steps():
    for name in ("Voice-Command-Full.iss", "Voice-Command-Plugin.iss"):
        installer = (ROOT / "installer" / name).read_text(encoding="utf-8")
        lines = installer.splitlines()
        finalize = next(line for line in lines if "Finalize-Install.ps1" in line and line.startswith("Filename:"))
        notify = next(line for line in lines if "Notify-Install.ps1" in line and line.startswith("Filename:"))
        terminal = next(
            line for line in lines if "Show-Install-Instructions.cmd" in line and line.startswith("Filename:")
        )
        assert "skipifsilent" not in finalize
        assert "skipifsilent" in notify
        assert "skipifsilent" in terminal
        assert '[InstallDelete]\nType: files; Name: "{app}\\clipboard-status.txt"' in installer
        uninstall = installer.split("[UninstallDelete]", 1)[1]
        assert 'Type: files; Name: "{app}\\clipboard-status.txt"' in uninstall


def test_plugin_surface_only_package_is_not_claimed_as_standalone():
    readme = (ROOT / "installer" / "README.md").read_text(encoding="utf-8")
    assert "Plugin-surface-only developer package" in readme
    assert "It is not standalone" in readme
    assert "Do not publish the plugin-surface-only package" in readme


def test_clipboard_instructions_cover_each_supported_surface_and_boundaries():
    text = (ROOT / "installer" / "APPLY_TO_YOUR_AI.txt").read_text(encoding="utf-8")
    for heading in (
        "CODEX CLI OR CODEX DESKTOP",
        "CLAUDE CODE",
        "GROK CLI",
        "CHATGPT WEB OR DESKTOP",
        "OTHER MCP CLIENTS",
    ):
        assert heading in text
    for placeholder in ("__MARKETPLACE_ROOT__", "__PLUGIN_ROOT__", "__VOICE_EXE__"):
        assert placeholder in text
    assert "does not auto-start the microphone" in text
    assert "Do not expose localhost:5123" in text
    assert "sends the response text to Microsoft Edge's online TTS" in text
    assert "not fully offline" in text
    assert "Secure MCP Tunnel" in text


def test_installer_build_uses_locked_rust_build_and_never_signs_or_publishes():
    for name in ("build-full-installer.cmd", "build-plugin-installer.cmd"):
        build = (ROOT / "installer" / name).read_text(encoding="utf-8")
        assert "cargo build --locked --release" in build
        assert "--target-dir" in build
        assert "signtool" not in build.lower()
        assert "gh release" not in build.lower()
