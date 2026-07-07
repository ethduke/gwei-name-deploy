from pathlib import Path

import pytest

from gwei_name_deploy.ipfs import (
    IpfsError,
    KuboUploader,
    PinataUploader,
    build_manifest,
    encode_ipfs_contenthash,
)

CID = "bafybeigdyrzt5sfp7udm7hu76izb6w4spq7zrz6ml3wx6qgsbi4k43q7sy"


class FakeResponse:
    text = f'{{"Name":"","Hash":"{CID}","Size":"1"}}\n'

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"IpfsHash": CID, "PinSize": 1}


class FakeHttp:
    def __init__(self) -> None:
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse()


def make_site(tmp_path: Path) -> Path:
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<h1>Hello</h1>", encoding="utf-8")
    assets = site / "assets"
    assets.mkdir()
    (assets / "style.css").write_text("body {}", encoding="utf-8")
    return site


def test_manifest_collects_relative_files(tmp_path: Path) -> None:
    manifest = build_manifest(make_site(tmp_path))

    assert [item.relative_path for item in manifest.files] == [
        "assets/style.css",
        "index.html",
    ]
    assert manifest.total_bytes > 0


def test_manifest_rejects_environment_file(tmp_path: Path) -> None:
    site = make_site(tmp_path)
    (site / ".env.production").write_text("SECRET=value", encoding="utf-8")

    with pytest.raises(IpfsError, match="environment file"):
        build_manifest(site)


def test_contenthash_uses_ipfs_namespace_and_cid_v1() -> None:
    encoded = encode_ipfs_contenthash(CID)

    assert encoded.hex().startswith("e3010170")
    assert len(encoded) == 38


def test_kubo_upload_parses_root_cid(tmp_path: Path) -> None:
    http = FakeHttp()
    uploader = KuboUploader("http://127.0.0.1:5001", http=http)

    assert uploader.upload(build_manifest(make_site(tmp_path)), "alice.gwei") == CID
    assert http.calls[0][0].endswith("/api/v0/add")


def test_kubo_rejects_remote_rpc() -> None:
    with pytest.raises(IpfsError, match="localhost"):
        KuboUploader("https://ipfs.example.com")


def test_pinata_upload_uses_bearer_token(tmp_path: Path) -> None:
    http = FakeHttp()
    uploader = PinataUploader("test-token", http=http)

    assert uploader.upload(build_manifest(make_site(tmp_path)), "alice.gwei") == CID
    assert http.calls[0][1]["headers"] == {"Authorization": "Bearer test-token"}
