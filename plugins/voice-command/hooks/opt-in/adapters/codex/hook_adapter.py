#!/usr/bin/env python3
"""Thin Codex adapter for the shared Voice-Command policy."""

from __future__ import annotations

import sys
from pathlib import Path

POLICY_DIR = Path(__file__).resolve().parents[2] / "shared" / "policy"
sys.path.insert(0, str(POLICY_DIR))

from voice_policy import main  # noqa: E402 - import follows portable path setup


if __name__ == "__main__":
    raise SystemExit(main([*sys.argv[1:], "--host", "codex"]))
