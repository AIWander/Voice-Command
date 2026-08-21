# Optional Voice-Command hooks

These fragments are inert templates. The plugin, marketplace, and installer do not merge them
into any host configuration. Enabling them is an explicit, reviewed user step.

Use only one policy owner for Voice-Command. Replace `__VOICE_COMMAND_PLUGIN_ROOT__` with the
absolute plugin path (or run `scripts/render-hooks.ps1`), review the rendered JSON, archive the
host's live hook file, then apply it through that host's supported mechanism.

The adapters require Python 3.10 or newer on `PATH` as `python`. Run `python --version` and a
harmless rendered-hook probe before enabling the definition. The Rust MCP wrapper and the skills
work without Python; only these optional hooks need it.

The shared engine (`shared/policy/voice_policy.py`):

- surfaces a one-line orientation at `SessionStart` and turn state at `UserPromptSubmit`
  (both advisory, never blocking);
- reminds the agent to listen when several `speak` calls run without a `listen_for_speech`;
- denies a `listen_for_speech` call whose arguments point speech capture away from the
  loopback listener on `localhost:5123`;
- denies a managed pre-tool call when its payload cannot be parsed;
- adds an advisory note when a single `speak` text is long enough to read as a monologue;
- writes a metadata-only audit line per event in which every string value is replaced by its
  length, so spoken or speakable text is never persisted by the hooks.

A hook definition is not enforcement merely because it exists. It becomes a hard boundary only
when the host trusts that exact definition, the runtime can block that event, and a harmless
probe proves the hook actually fired. The microphone boundary itself - open the microphone only
on a direct user request - remains a behavioral rule carried by the skills; no hook can decide
why an agent chose to listen.

The lifecycle shape matches the AI-Hands and Programmer-Wander opt-in packs so Claude, Grok,
and Codex adapters share one rule owner. `PreToolUse` is the only blocking stage, and only on a
host that proves the exact definition can deny.
