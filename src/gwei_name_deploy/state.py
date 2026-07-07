from __future__ import annotations

import json
import os
import re
from pathlib import Path

from gwei_name_deploy.registration import RegistrationRun

RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class StateError(RuntimeError):
    """Raised when local registration state is missing or unsafe."""


class RunStore:
    def __init__(self, state_dir: Path) -> None:
        self.runs_dir = state_dir / "runs"

    def save(self, run: RegistrationRun) -> None:
        self.runs_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            self.runs_dir.chmod(0o700)
        except OSError as exc:
            raise StateError(f"could not secure state directory: {exc}") from exc

        destination = self._path(run.run_id)
        temporary = destination.with_suffix(".tmp")
        payload = json.dumps(run.to_dict(), indent=2, sort_keys=True) + "\n"
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                0o600,
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.chmod(0o600)
            temporary.replace(destination)
            destination.chmod(0o600)
        except OSError as exc:
            raise StateError(f"could not save registration state: {exc}") from exc

    def load(self, run_id: str) -> RegistrationRun:
        path = self._path(run_id)
        if not path.is_file():
            raise StateError(f"registration run not found: {run_id}")
        if path.stat().st_mode & 0o077:
            raise StateError(f"registration state is not owner-only: {path}")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return RegistrationRun.from_dict(value)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise StateError(f"invalid registration state: {path}") from exc

    def path_for(self, run_id: str) -> Path:
        return self._path(run_id)

    def _path(self, run_id: str) -> Path:
        if not RUN_ID_PATTERN.fullmatch(run_id):
            raise StateError("invalid registration run ID")
        return self.runs_dir / f"{run_id}.json"
