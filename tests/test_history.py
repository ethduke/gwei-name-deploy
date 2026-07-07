import stat
from pathlib import Path

from gwei_name_deploy.history import HistoryStore


def test_revision_history_and_address_mapping(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path)
    first = store.record_revision(
        1,
        "alice.gwei",
        123,
        "bafyfirst",
        b"first",
        "0xtx1",
    )
    second = store.record_revision(
        1,
        "alice.gwei",
        123,
        "bafysecond",
        b"second",
        "0xtx2",
    )
    store.upsert_address_name(
        1, "0x1234567890123456789012345678901234567890", "alice.gwei"
    )

    assert [item.revision_id for item in store.list_revisions(1, "alice.gwei")] == [
        second.revision_id,
        first.revision_id,
    ]
    assert store.get_revision(first.revision_id).cid == "bafyfirst"
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
