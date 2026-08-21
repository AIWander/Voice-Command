# voice-command (plugin)

Speech input and output for Claude Code, Grok CLI, Codex, and other MCP clients, with the
operating skills that make an agent a good voice partner. The plugin changes the conversation
channel only; it grants no file, browser, network, shell, or account privilege.

Contents:

- `.mcp.json` - registers the `voice` STDIO server (`voice-mcp.exe`, ten tools). The installed
  copy carries an absolute path written by the installer.
- `skills/` - voice-command (turn discipline and the microphone boundary), voice-command-setup
  (install, enable, diagnose per client), voice-widget (the Voice App window: Pause, Interrupt,
  Stop, and the interruption-phrase field, and how the agent must react to each).
- `hooks/opt-in/` - optional single-owner policy hooks (never auto-loaded; see
  `hooks/opt-in/README.md`): advisory session orientation, a listen-stays-on-loopback guard,
  a monologue reminder, and a metadata-only audit that never persists speech text.
- `scripts/render-hooks.ps1` - renders the hook fragments with this plugin's real path into
  `rendered-hooks/` for review before any host wiring.

The widget itself (the Voice App window) ships with the full installer or runs from a repo
checkout via `START_VOICE_APP.bat`; the plugin teaches the agent to launch-check and cooperate
with it but never starts the microphone. Per-client activation commands live in the
installer-generated `APPLY_TO_YOUR_AI.txt` and the repository README.

Hook wiring is an explicit, reviewed user step. Install the plugin as-is for skills plus MCP
registration with no hook code active.
