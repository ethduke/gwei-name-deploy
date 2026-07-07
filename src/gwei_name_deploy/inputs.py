from __future__ import annotations

import csv
from pathlib import Path


class InputError(ValueError):
    """Raised when no usable name input can be loaded."""


def collect_names(name: str | None, input_file: Path | None) -> list[str]:
    """Collect a single CLI name or the first column of a text/CSV file."""
    if name and input_file:
        raise InputError("provide either NAME or --file, not both")
    if not name and not input_file:
        raise InputError("provide NAME or --file")

    values = [name] if name else _read_names(input_file)  # type: ignore[arg-type]
    cleaned = [value.strip() for value in values if value and value.strip()]
    unique = list(dict.fromkeys(cleaned))
    if not unique:
        raise InputError("no names found in input")
    return unique


def _read_names(path: Path) -> list[str]:
    if not path.is_file():
        raise InputError(f"input file does not exist: {path}")

    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.reader(handle))
        if rows and rows[0] and rows[0][0].strip().lower() in {"name", "gwei_name"}:
            rows = rows[1:]
        return [row[0] for row in rows if row]

    return [
        line
        for raw in path.read_text(encoding="utf-8").splitlines()
        if (line := raw.strip()) and not line.startswith("#")
    ]
