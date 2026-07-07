import stat
from pathlib import Path

import pytest

from gwei_name_deploy.models import NamePlan
from gwei_name_deploy.registration import prepare_run
from gwei_name_deploy.state import RunStore, StateError


def plan() -> NamePlan:
    return NamePlan(
        input_name="alice",
        name="alice.gwei",
        label="alice",
        label_bytes=5,
        token_id=123,
        status="available",
        available=True,
        owner=None,
        expires_at=None,
        fee_wei=1,
        premium_wei=0,
    )


def test_round_trip_uses_owner_only_permissions(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    run = prepare_run(
        [plan()], "sepolia", 11155111, "0x1234567890123456789012345678901234567890"
    )

    store.save(run)
    path = store.path_for(run.run_id)
    loaded = store.load(run.run_id)

    assert loaded.to_dict() == run.to_dict()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_rejects_path_traversal(tmp_path: Path) -> None:
    store = RunStore(tmp_path)

    with pytest.raises(StateError, match="invalid registration run ID"):
        store.load("../../secret")
