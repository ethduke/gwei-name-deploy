from __future__ import annotations

import json
import mimetypes
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

import requests
from multiformats import CID

IGNORED_DIRECTORIES = {".git", ".venv", "__pycache__", "node_modules"}
SENSITIVE_NAMES = {".npmrc", ".pypirc", "id_ed25519", "id_rsa"}
SENSITIVE_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}


class IpfsError(RuntimeError):
    """Raised when a site cannot be safely prepared or uploaded."""


@dataclass(frozen=True, slots=True)
class SiteFile:
    path: Path
    relative_path: str
    size: int


@dataclass(frozen=True, slots=True)
class SiteManifest:
    root: Path
    files: tuple[SiteFile, ...]
    total_bytes: int


class SiteUploader(Protocol):
    def upload(self, manifest: SiteManifest, name: str) -> str: ...


def build_manifest(site_dir: Path) -> SiteManifest:
    root = site_dir.expanduser().resolve()
    if not root.is_dir():
        raise IpfsError(f"site directory does not exist: {site_dir}")
    if not (root / "index.html").is_file():
        raise IpfsError("site directory must contain index.html at its root")

    files: list[SiteFile] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in IGNORED_DIRECTORIES for part in relative.parts):
            continue
        if path.is_symlink():
            raise IpfsError(f"site contains a symlink: {relative}")
        if not path.is_file():
            continue
        _reject_sensitive_file(relative)
        files.append(
            SiteFile(
                path=path,
                relative_path=relative.as_posix(),
                size=path.stat().st_size,
            )
        )

    if not files:
        raise IpfsError("site directory contains no publishable files")
    return SiteManifest(
        root=root,
        files=tuple(files),
        total_bytes=sum(item.size for item in files),
    )


def encode_ipfs_contenthash(cid_value: str) -> bytes:
    try:
        cid = CID.decode(cid_value)
    except Exception as exc:
        raise IpfsError(f"IPFS provider returned an invalid CID: {cid_value}") from exc
    cid_v1 = cid if cid.version == 1 else CID("base32", 1, cid.codec, cid.digest)
    return bytes.fromhex("e301") + bytes(cid_v1)


class KuboUploader:
    def __init__(self, api_url: str, http=requests) -> None:
        parsed = urlparse(api_url)
        if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise IpfsError("Kubo RPC must use localhost; never expose it publicly")
        self.api_url = api_url.rstrip("/")
        self.http = http

    def upload(self, manifest: SiteManifest, name: str) -> str:
        with ExitStack() as stack:
            files = _multipart_files(manifest, stack)
            try:
                response = self.http.post(
                    f"{self.api_url}/api/v0/add",
                    params={
                        "recursive": "true",
                        "wrap-with-directory": "true",
                        "pin": "true",
                        "cid-version": "1",
                    },
                    files=files,
                    timeout=300,
                )
                response.raise_for_status()
            except requests.RequestException as exc:
                raise IpfsError(f"Kubo upload failed: {exc}") from exc

        try:
            rows = [json.loads(line) for line in response.text.splitlines() if line]
            return str(rows[-1]["Hash"])
        except (
            IndexError,
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            raise IpfsError("Kubo returned an invalid upload response") from exc


class PinataUploader:
    endpoint = "https://api.pinata.cloud/pinning/pinFileToIPFS"

    def __init__(self, token: str, http=requests) -> None:
        if not token:
            raise IpfsError("GWEI_IPFS_TOKEN is required for the Pinata provider")
        self.token = token
        self.http = http

    def upload(self, manifest: SiteManifest, name: str) -> str:
        with ExitStack() as stack:
            files = _multipart_files(manifest, stack)
            try:
                response = self.http.post(
                    self.endpoint,
                    headers={"Authorization": f"Bearer {self.token}"},
                    files=files,
                    data={
                        "pinataMetadata": json.dumps({"name": name}),
                        "pinataOptions": json.dumps({"cidVersion": 1}),
                    },
                    timeout=300,
                )
                response.raise_for_status()
                value = response.json()
            except (requests.RequestException, ValueError) as exc:
                raise IpfsError(f"Pinata upload failed: {exc}") from exc

        cid = value.get("IpfsHash") if isinstance(value, dict) else None
        if not cid:
            raise IpfsError("Pinata returned an invalid upload response")
        return str(cid)


def create_uploader(
    provider: str, api_url: str | None, token: str | None
) -> SiteUploader:
    normalized = provider.strip().lower()
    if normalized == "local":
        return KuboUploader(api_url or "http://127.0.0.1:5001")
    if normalized == "pinata":
        return PinataUploader(token or "")
    raise IpfsError("unsupported IPFS provider; choose local or pinata")


def _multipart_files(manifest: SiteManifest, stack: ExitStack) -> list[tuple]:
    values = []
    for item in manifest.files:
        handle = stack.enter_context(item.path.open("rb"))
        mime = mimetypes.guess_type(item.relative_path)[0] or "application/octet-stream"
        values.append(("file", (item.relative_path, handle, mime)))
    return values


def _reject_sensitive_file(relative: Path) -> None:
    name = relative.name.lower()
    if name == ".env" or name.startswith(".env."):
        raise IpfsError(f"refusing to upload environment file: {relative}")
    if name in SENSITIVE_NAMES or relative.suffix.lower() in SENSITIVE_SUFFIXES:
        raise IpfsError(f"refusing to upload likely secret file: {relative}")
