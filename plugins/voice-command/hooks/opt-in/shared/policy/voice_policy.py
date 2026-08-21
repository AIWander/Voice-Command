#!/usr/bin/env python3
"""Shared opt-in hook policy for the Voice-Command plugin.

One policy source serves the Claude-style, Grok, and Codex adapters so the
rules never drift into competing owners. The engine is deliberately small:

- SessionStart and UserPromptSubmit are advisory orientation only.
- PreToolUse is the single potentially blocking stage, and it blocks only a
  listen call whose arguments try to point speech capture away from the
  loopback listener, or a managed call whose payload cannot be parsed.
- PostToolUse and PostToolUseFailure keep a metadata-only audit trail.

Privacy rule: spoken or speakable text is never written to disk by this
policy. Audit entries record value lengths, never value contents.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VOICE_PREFIXES = ("mcp__voice__", "voice__", "mcp__voice-command__", "voice-command__")
WRAPPER_NAMES = {"use_tool", "CallMcpTool"}
VOICE_TOOLS = {
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
}
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
LONG_SPEAK_CHARS = 700
MONOLOGUE_WARN_TURNS = 3


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    path = Path(base) / "voice-command-hooks"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _first_present(mapping: dict[str, Any], keys: tuple[str, ...], default: Any) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return default


def _parse_object(value: Any, label: str) -> tuple[dict[str, Any], str | None]:
    if isinstance(value, dict):
        return value, None
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}, f"could not parse {label}"
        if isinstance(parsed, dict):
            return parsed, None
        return {}, f"{label} is not an object"
    if value is None:
        return {}, None
    return {}, f"{label} is not an object"


def canonicalize_tool_name(name: str) -> tuple[str | None, str]:
    for prefix in VOICE_PREFIXES:
        if name.startswith(prefix):
            return "voice", name[len(prefix):]
    if name in VOICE_TOOLS:
        return "voice", name
    return None, name


def resolve_call(payload: dict[str, Any]) -> tuple[str, dict[str, Any], str | None, bool]:
    """Return (tool, args, parse_error, managed) for direct and wrapped calls."""
    raw_name = str(
        _first_present(payload, ("tool_name", "toolName", "name"), "")
    )
    namespace, tool = canonicalize_tool_name(raw_name)
    is_wrapper = raw_name in WRAPPER_NAMES or raw_name.endswith("use_tool")
    outer_raw = _first_present(payload, ("toolInput", "tool_input", "input"), {})
    outer, outer_error = _parse_object(outer_raw, "tool input")
    if outer_error:
        return tool, {}, outer_error, namespace is not None or is_wrapper

    if is_wrapper:
        qualified = str(_first_present(outer, ("tool_name", "name", "tool"), ""))
        server = str(_first_present(outer, ("server_name", "server"), ""))
        server_key = server.strip().lower().replace("_", "-")
        namespace, tool = canonicalize_tool_name(qualified)
        if namespace is None and server_key in {"voice", "voice-command"} and qualified:
            namespace, tool = "voice", qualified
        nested_raw = _first_present(outer, ("tool_input", "arguments", "input"), {})
        nested, nested_error = _parse_object(nested_raw, "wrapped tool arguments")
        return tool, nested, nested_error, namespace is not None

    if "arguments" in outer:
        nested, nested_error = _parse_object(outer["arguments"], "tool arguments")
        return tool, nested, nested_error, namespace is not None
    return tool, outer, None, namespace is not None


def _redact(value: Any) -> Any:
    """Replace every string value with its length so speech text never lands on disk."""
    if isinstance(value, str):
        return f"<len {len(value)}>"
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _non_loopback_target(args: dict[str, Any]) -> str | None:
    """Find an argument that points the listener away from loopback, if any."""
    suspicious_keys = ("url", "endpoint", "server", "server_url", "host", "address", "listener")
    for key, value in args.items():
        if key.lower() not in suspicious_keys or not isinstance(value, str):
            continue
        text = value.strip().lower()
        if not text:
            continue
        host = text
        if "://" in host:
            host = host.split("://", 1)[1]
        host = host.split("/", 1)[0].rsplit(":", 1)[0].strip("[]")
        if host and host not in LOOPBACK_HOSTS:
            return key
    return None


def _session_key(payload: dict[str, Any]) -> str:
    session = (
        payload.get("session_id")
        or payload.get("sessionId")
        or os.environ.get("CODEX_THREAD_ID")
        or os.environ.get("CLAUDE_SESSION_ID")
        or os.environ.get("GROK_SESSION_ID")
        or "default"
    )
    return str(session)


def _read_state() -> dict[str, Any]:
    path = data_dir() / "session-state.json"
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _write_state(state: dict[str, Any]) -> bool:
    path = data_dir() / "session-state.json"
    temporary = path.with_suffix(".tmp")
    try:
        temporary.write_text(
            json.dumps(state, ensure_ascii=True, sort_keys=True) + "\n", encoding="utf-8"
        )
        temporary.replace(path)
    except OSError:
        return False
    return True


def _state_entry(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    state = _read_state()
    sessions = state.setdefault("sessions", {})
    entry = sessions.setdefault(_session_key(payload), {"speaks_since_listen": 0})
    if not isinstance(entry, dict):
        entry = {"speaks_since_listen": 0}
        sessions[_session_key(payload)] = entry
    return state, entry


def evaluate_pre_tool(tool: str, args: dict[str, Any], parse_error: str | None) -> tuple[str, str | None]:
    if parse_error:
        return "deny", f"Voice-Command policy could not evaluate this call: {parse_error}"
    if tool == "listen_for_speech":
        bad_key = _non_loopback_target(args)
        if bad_key:
            return (
                "deny",
                f"listen_for_speech argument '{bad_key}' points away from the loopback listener; "
                "Voice-Command only captures speech on localhost:5123",
            )
        return "allow", None
    if tool == "speak":
        text = args.get("text")
        if isinstance(text, str) and len(text) > LONG_SPEAK_CHARS:
            return (
                "allow",
                f"speak text is {len(text)} characters; spoken turns land better under "
                f"{LONG_SPEAK_CHARS} characters - consider splitting and listening between chunks",
            )
    return "allow", None


def handle_lifecycle_event(event: str, payload: dict[str, Any]) -> str:
    state, entry = _state_entry(payload)
    normalized = event.lower()
    if normalized == "sessionstart":
        entry["speaks_since_listen"] = 0
        entry["started_at"] = utc_now().isoformat()
        _write_state(state)
        return (
            "Voice-Command is available. It adds speech input and output only and grants no "
            "other privilege. start_voice_mode checks listener readiness without opening the "
            "microphone. The listener and its widget window stay on localhost:5123. Open the "
            "microphone only after a direct user request in the active conversation."
        )
    streak = entry.get("speaks_since_listen", 0)
    if isinstance(streak, int) and streak >= MONOLOGUE_WARN_TURNS:
        return (
            f"Voice-Command: {streak} consecutive speak calls without listening. Keep spoken "
            "turns short and call listen_for_speech so the user can answer or interrupt."
        )
    return "Voice-Command state: ready. Speak short, listen after speaking, stop always wins."


def update_post_tool(tool: str, payload: dict[str, Any], failed: bool) -> None:
    state, entry = _state_entry(payload)
    streak = entry.get("speaks_since_listen", 0)
    if not isinstance(streak, int):
        streak = 0
    if tool == "speak" and not failed:
        entry["speaks_since_listen"] = streak + 1
    elif tool == "listen_for_speech" and not failed:
        entry["speaks_since_listen"] = 0
    _write_state(state)


def audit(event: str, host: str, tool: str, args: dict[str, Any], decision: str, reason: str | None) -> bool:
    entry = {
        "ts": utc_now().isoformat(),
        "event": event,
        "host": host,
        "tool": tool,
        "decision": decision,
        "reason": reason,
        "input": _redact(args),
    }
    try:
        with (data_dir() / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=True) + "\n")
    except OSError:
        return False
    return True


def emit_context(event: str, message: str) -> None:
    output = {"hookSpecificOutput": {"hookEventName": event, "additionalContext": message}}
    sys.stdout.write(json.dumps(output, ensure_ascii=True))


def emit_decision(decision: str, reason: str | None, event: str) -> None:
    specific: dict[str, Any] = {"hookEventName": event, "permissionDecision": decision}
    output: dict[str, Any] = {"decision": decision, "hookSpecificOutput": specific}
    if reason:
        output["reason"] = reason
        specific["permissionDecisionReason"] = reason
    sys.stdout.write(json.dumps(output, ensure_ascii=True))


def run(event: str, host: str, payload: dict[str, Any]) -> int:
    normalized = event.lower()
    if normalized in {"sessionstart", "userpromptsubmit"}:
        message = handle_lifecycle_event(event, payload)
        audit(event, host, "", {}, "allow", None)
        emit_context(event, message)
        return 0

    tool, args, parse_error, managed = resolve_call(payload)
    if not managed:
        if normalized == "pretooluse":
            emit_decision("allow", None, event)
        return 0

    if normalized == "pretooluse":
        decision, reason = evaluate_pre_tool(tool, args, parse_error)
        audit(event, host, tool, args, decision, reason)
        emit_decision(decision, reason, event)
        return 0

    if normalized == "posttooluse":
        update_post_tool(tool, payload, failed=False)
        audit(event, host, tool, args, "observed", None)
        return 0

    if normalized == "posttoolusefailure":
        update_post_tool(tool, payload, failed=True)
        audit(event, host, tool, args, "failed", None)
        if tool in {"speak", "listen_for_speech", "start_voice_mode"}:
            emit_context(
                event,
                "A Voice-Command call failed. The local listener may not be running: start the "
                "Voice App widget (Start-CPC-Voice.bat or START_VOICE_APP.bat), confirm GET "
                "http://localhost:5123/status reports the app ready, then retry start_voice_mode.",
            )
        return 0

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Voice-Command shared hook policy")
    parser.add_argument("--event", required=True)
    parser.add_argument("--host", default="claude-grok")
    parsed = parser.parse_args(argv)
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return run(parsed.event, parsed.host, payload)


if __name__ == "__main__":
    raise SystemExit(main())
