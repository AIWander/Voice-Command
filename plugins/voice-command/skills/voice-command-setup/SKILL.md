---
name: voice-command-setup
description: Install, enable, diagnose, or verify the Voice-Command plugin and its local Rust MCP server across Codex, Claude Code, Grok CLI, ChatGPT, or another MCP client. Trigger for setup, plugin activation, missing voice tools, listener readiness, client configuration, or uninstall questions.
---

# Voice Command Setup

Separate four layers when diagnosing setup:

1. The plugin supplies skills and MCP registration metadata.
2. `voice-mcp.exe` supplies ten STDIO MCP tools.
3. The local Voice App or Python listener supplies speech capture on `localhost:5123`.
4. The AI client decides whether the plugin and MCP server are enabled.

A skill cannot create a missing executable, and `start_voice_mode` checks readiness without opening the microphone.

## Verify in order

1. Confirm the installed plugin's `.mcp.json` contains an absolute path to `voice-mcp.exe`.
2. Restart or start a fresh task after enabling the plugin.
3. Confirm `tools/list` exposes exactly ten Voice-Command tools.
4. Call `start_voice_mode`; if it reports unavailable, start the local Voice App directly as the user.
5. Test `speak` before testing `listen_for_speech`.

Do not auto-edit another AI client's configuration, auto-trust a plugin, or auto-start microphone capture. Use the installer-generated `APPLY_TO_YOUR_AI.txt` for the exact per-client activation commands and preserve the user's normal permission controls.
