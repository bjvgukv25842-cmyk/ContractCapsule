#!/usr/bin/env python3
"""Codex pre-tool hook wrapper for the core fail-closed decision function."""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime

from contractcapsule.adapters.hook import PreToolHook


def main() -> int:
    try:
        request = json.load(sys.stdin)
        key = bytes.fromhex(os.environ.get("CCS_HOOK_KEY", ""))
        result = PreToolHook(key=key, clock=lambda: datetime.now(UTC)).decide(request)
    except Exception:  # noqa: BLE001 - a hook must never expose internals.
        result = {"decision": "deny", "code": "HOOK_INPUT_INVALID"}
    sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
