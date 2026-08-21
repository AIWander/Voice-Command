import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "voice-command"
POLICY_DIR = PLUGIN / "hooks" / "opt-in" / "shared" / "policy"


def load_policy(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    sys.path.insert(0, str(POLICY_DIR))
    try:
        module = importlib.import_module("voice_policy")
        module = importlib.reload(module)
    finally:
        sys.path.remove(str(POLICY_DIR))
    return module


def test_fragments_are_valid_json_with_placeholder_and_adapters_share_one_policy():
    for name in ("claude-grok-hooks.fragment.json", "codex-hooks.fragment.json"):
        text = (PLUGIN / "hooks" / "opt-in" / name).read_text(encoding="utf-8")
        parsed = json.loads(text)
        assert "__VOICE_COMMAND_PLUGIN_ROOT__" in text
        assert set(parsed["hooks"]) == {
            "SessionStart",
            "UserPromptSubmit",
            "PreToolUse",
            "PostToolUse",
            "PostToolUseFailure",
        }
    for adapter in ("claude-grok", "codex"):
        source = (
            PLUGIN / "hooks" / "opt-in" / "adapters" / adapter / "hook_adapter.py"
        ).read_text(encoding="utf-8")
        assert "from voice_policy import main" in source


def test_hooks_stay_inert_in_both_plugin_manifests():
    for manifest in (".claude-plugin", ".codex-plugin"):
        parsed = json.loads((PLUGIN / manifest / "plugin.json").read_text(encoding="utf-8"))
        assert "hooks" not in parsed


def test_pre_tool_denies_non_loopback_listen_and_unparseable_payloads(tmp_path, monkeypatch):
    policy = load_policy(tmp_path, monkeypatch)
    decision, reason = policy.evaluate_pre_tool(
        "listen_for_speech", {"server_url": "http://192.168.1.20:5123"}, None
    )
    assert decision == "deny"
    assert "loopback" in reason
    decision, reason = policy.evaluate_pre_tool("listen_for_speech", {}, "could not parse tool input")
    assert decision == "deny"


def test_pre_tool_allows_loopback_listen_and_flags_only_long_speak(tmp_path, monkeypatch):
    policy = load_policy(tmp_path, monkeypatch)
    assert policy.evaluate_pre_tool(
        "listen_for_speech", {"server_url": "http://localhost:5123"}, None
    ) == ("allow", None)
    assert policy.evaluate_pre_tool("listen_for_speech", {"timeout": 60}, None) == ("allow", None)
    assert policy.evaluate_pre_tool("speak", {"text": "Short and friendly."}, None) == ("allow", None)
    decision, reason = policy.evaluate_pre_tool("speak", {"text": "x" * 800}, None)
    assert decision == "allow"
    assert "800 characters" in reason


def test_redaction_replaces_every_string_value_with_its_length(tmp_path, monkeypatch):
    policy = load_policy(tmp_path, monkeypatch)
    redacted = policy._redact({"text": "secret words", "nested": {"voice": "en-US"}, "count": 3})
    assert redacted == {"text": "<len 12>", "nested": {"voice": "<len 5>"}, "count": 3}
    assert "secret" not in json.dumps(redacted)


def test_monologue_streak_counts_speaks_and_resets_on_listen(tmp_path, monkeypatch):
    policy = load_policy(tmp_path, monkeypatch)
    payload = {"session_id": "abc"}
    policy.handle_lifecycle_event("SessionStart", payload)
    for _ in range(3):
        policy.update_post_tool("speak", payload, failed=False)
    message = policy.handle_lifecycle_event("UserPromptSubmit", payload)
    assert "3 consecutive speak calls" in message
    policy.update_post_tool("listen_for_speech", payload, failed=False)
    message = policy.handle_lifecycle_event("UserPromptSubmit", payload)
    assert "ready" in message


def test_resolve_call_unwraps_codex_wrapper_and_ignores_foreign_tools(tmp_path, monkeypatch):
    policy = load_policy(tmp_path, monkeypatch)
    tool, args, error, managed = policy.resolve_call(
        {
            "tool_name": "use_tool",
            "toolInput": {
                "server_name": "voice",
                "tool_name": "speak",
                "tool_input": {"text": "hello"},
            },
        }
    )
    assert (tool, error, managed) == ("speak", None, True)
    assert args == {"text": "hello"}
    _, _, _, managed = policy.resolve_call({"tool_name": "Read", "toolInput": {"file_path": "x"}})
    assert managed is False
