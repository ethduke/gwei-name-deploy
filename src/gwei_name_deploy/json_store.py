from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class JsonStoreError(RuntimeError):
    """Raised when owner-only JSON state cannot be read or written safely."""


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    if not path.is_file():
        raise JsonStoreError(f"state path is not a file: {path}")
    if path.stat().st_mode & 0o077:
        raise JsonStoreError(f"state file is not owner-only: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise JsonStoreError(f"could not read state file {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise JsonStoreError(f"state file must contain a JSON object: {path}")
    return value


def save_json(path: Path, value: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.parent.chmod(0o700)
        temporary = path.with_suffix(path.suffix + ".tmp")
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        temporary.replace(path)
        path.chmod(0o600)
    except OSError as exc:
        raise JsonStoreError(f"could not write state file {path}: {exc}") from exc
