from pathlib import Path

import pytest

from gwei_name_deploy.inputs import InputError, collect_names


def test_collects_and_deduplicates_csv(tmp_path: Path) -> None:
    path = tmp_path / "names.csv"
    path.write_text("name\nalice\nbob.gwei\nalice\n", encoding="utf-8")

    assert collect_names(None, path) == ["alice", "bob.gwei"]


def test_rejects_name_and_file_together(tmp_path: Path) -> None:
    path = tmp_path / "names.txt"
    path.write_text("alice\n", encoding="utf-8")

    with pytest.raises(InputError, match="either NAME or --file"):
        collect_names("bob", path)
