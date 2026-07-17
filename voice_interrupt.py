"""Pure helpers for Voice App interruption-listener behavior.

This module deliberately has no audio or UI dependencies.  The Voice App owns
the microphone state machine; these helpers keep phrase matching, persisted
phrase overrides, and the AI handoff contract deterministic and testable.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Iterable, Mapping, Sequence


DEFAULT_TRIGGER_PHRASES = ("umm",)
RESPONSE_INSTRUCTION = (
    "Address the new input and preserve relevant unfinished content from the "
    "interrupted response without repeating wording already heard."
)
EMPTY_CAPTURE_ERRORS = {"No speech detected", "Could not understand audio"}

_FILLER_TOKEN = re.compile(r"^(?:u+m+|uhm+)$")
_NON_WORD = re.compile(r"[^\w']+", flags=re.UNICODE)
_SPACE = re.compile(r"\s+")


def normalize_text(value: object) -> str:
    """Normalize speech text for case- and punctuation-insensitive matching."""
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = _SPACE.sub(" ", _NON_WORD.sub(" ", text)).strip()
    tokens = ["umm" if _FILLER_TOKEN.fullmatch(token) else token for token in text.split()]
    return " ".join(tokens)


def normalize_trigger_phrases(
    values: str | Iterable[object] | None,
    *,
    default_if_empty: bool = True,
) -> list[str]:
    """Validate, normalize, deduplicate, and bound a phrase selection."""
    if isinstance(values, str):
        raw_values: Iterable[object] = values.split(",")
    elif values is None:
        raw_values = ()
    else:
        raw_values = values

    phrases: list[str] = []
    for raw in raw_values:
        phrase = normalize_text(raw)
        if not phrase or phrase in phrases:
            continue
        if len(phrase) > 64:
            raise ValueError("interruption phrases must be 64 characters or fewer")
        phrases.append(phrase)
        if len(phrases) == 12:
            break

    if not phrases and default_if_empty:
        return list(DEFAULT_TRIGGER_PHRASES)
    return phrases


def match_trigger(transcript: object, phrases: Sequence[str]) -> str | None:
    """Return the first configured phrase found on normalized word boundaries."""
    normalized = normalize_text(transcript)
    if not normalized:
        return None
    haystack = f" {normalized} "
    for phrase in normalize_trigger_phrases(phrases, default_if_empty=False):
        if f" {phrase} " in haystack:
            return phrase
    return None


def default_settings_path() -> Path:
    override = os.environ.get("VOICE_INTERRUPT_SETTINGS_PATH")
    if override:
        return Path(override).expanduser()
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "CPC" / "Voice" / "interrupt-listener.json"
    return Path.home() / ".config" / "voice" / "interrupt-listener.json"


def load_phrase_override(path: str | os.PathLike[str] | None = None) -> list[str] | None:
    """Read the widget's per-user phrase override; invalid files fail closed."""
    target = Path(path) if path is not None else default_settings_path()
    if not target.exists():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        phrases = normalize_trigger_phrases(
            payload.get("trigger_phrases"), default_if_empty=False
        )
        return phrases or None
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def save_phrase_override(
    phrases: str | Iterable[object],
    path: str | os.PathLike[str] | None = None,
) -> tuple[list[str], Path]:
    """Atomically persist the widget's validated per-user phrase selection."""
    normalized = normalize_trigger_phrases(phrases, default_if_empty=False)
    if not normalized:
        raise ValueError("enter at least one interruption phrase")

    target = Path(path) if path is not None else default_settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    payload = {"schema": 1, "trigger_phrases": normalized}
    temp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, target)
    return normalized, target


def build_interruption_context(
    source: str,
    trigger_phrase: str | None,
    snapshot: Mapping[str, object],
    queued_responses: Sequence[str] = (),
) -> dict[str, object]:
    """Capture enough prior-response state for context-preserving revision."""
    position_ms = max(int(snapshot.get("position_ms") or 0), 0)
    duration_ms = max(int(snapshot.get("duration_ms") or 0), 0)
    fraction = round(min(position_ms / duration_ms, 1.0), 4) if duration_ms else 0.0
    return {
        "source": source,
        "trigger_phrase": trigger_phrase,
        "prior_response": str(snapshot.get("text") or ""),
        "position_ms": position_ms,
        "duration_ms": duration_ms,
        "played_fraction": fraction,
        "queued_responses": [str(text) for text in queued_responses if text],
    }


def decorate_listen_result(
    result: Mapping[str, object],
    reason: str,
    interruption: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Attach the stable turn-reason and optional AI revision contract."""
    decorated = dict(result)
    decorated["listen_reason"] = reason
    if interruption:
        decorated["interruption"] = dict(interruption)
        decorated["response_instruction"] = RESPONSE_INSTRUCTION
    return decorated


def is_empty_capture(result: Mapping[str, object]) -> bool:
    return not bool(result.get("success")) and result.get("error") in EMPTY_CAPTURE_ERRORS
