from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
from typing import Protocol, runtime_checkable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from ..model import Acquisition, GitHubFileSource, SourceRef, now_iso
from ..policy import IngestPolicy
from .base import AcquisitionFailed, PolicyRejected


@runtime_checkable
class GitHubTransport(Protocol):
    def resolve_ref(self, owner: str, repository: str, ref: str) -> str: ...
    def fetch_file(self, owner: str, repository: str, commit: str, path: str, max_bytes: int) -> tuple[bytes, str | None, dict]: ...


class GitHubApiTransport:
    def __init__(self, token: str | None = None, api_base: str = "https://api.github.com"):
        self._token = token
        self.api_base = api_base.rstrip("/")

    def _json(self, url: str) -> dict:
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "vera-ingest/0.1"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            with urlopen(Request(url, headers=headers), timeout=15) as response:
                raw = response.read()
        except HTTPError as exc:
            raise AcquisitionFailed(f"GitHub API returned HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise AcquisitionFailed("GitHub API request failed") from exc
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AcquisitionFailed("GitHub API returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise AcquisitionFailed("GitHub API returned a non-object payload")
        return payload

    def resolve_ref(self, owner: str, repository: str, ref: str) -> str:
        payload = self._json(f"{self.api_base}/repos/{quote(owner)}/{quote(repository)}/commits/{quote(ref, safe='')}")
        sha = payload.get("sha")
        if not isinstance(sha, str) or not sha:
            raise AcquisitionFailed("GitHub ref did not resolve to a commit")
        return sha

    def fetch_file(self, owner: str, repository: str, commit: str, path: str, max_bytes: int):
        payload = self._json(
            f"{self.api_base}/repos/{quote(owner)}/{quote(repository)}/contents/{quote(path)}?ref={quote(commit)}"
        )
        if payload.get("type") != "file" or payload.get("encoding") != "base64":
            raise AcquisitionFailed("GitHub source is not a base64 file payload")
        size = payload.get("size")
        if isinstance(size, int) and size > max_bytes:
            raise PolicyRejected(f"GitHub file exceeds max_bytes={max_bytes}")
        try:
            data = base64.b64decode(payload["content"], validate=False)
        except Exception as exc:
            raise AcquisitionFailed("GitHub file content could not be decoded") from exc
        if len(data) > max_bytes:
            raise PolicyRejected(f"GitHub file exceeds max_bytes={max_bytes}")

        blob_sha = payload.get("sha")
        if not isinstance(blob_sha, str):
            raise AcquisitionFailed("GitHub file payload is missing blob identity")
        git_object = f"blob {len(data)}\0".encode("ascii") + data
        if len(blob_sha) == 40:
            actual_blob_sha = hashlib.sha1(git_object, usedforsecurity=False).hexdigest()
        elif len(blob_sha) == 64:
            actual_blob_sha = hashlib.sha256(git_object).hexdigest()
        else:
            raise AcquisitionFailed("GitHub blob identity uses an unsupported digest length")
        if actual_blob_sha != blob_sha.lower():
            raise AcquisitionFailed("GitHub blob identity does not match acquired bytes")

        return data, None, {"git_blob_sha": blob_sha, "size": size}


class GitHubAdapter:
    name = "github"
    version = "1"

    def __init__(self, transport: GitHubTransport | None = None):
        self.transport = transport or GitHubApiTransport()

    def supports(self, source) -> bool:
        return isinstance(source, GitHubFileSource)

    def acquire(self, source: GitHubFileSource, policy: IngestPolicy) -> Acquisition:
        if not all((source.owner, source.repository, source.ref, source.path)):
            raise PolicyRejected("GitHub owner/repository/ref/path must be non-empty")
        commit = self.transport.resolve_ref(source.owner, source.repository, source.ref)
        data, media_type, observed = self.transport.fetch_file(
            source.owner, source.repository, commit, source.path, policy.max_bytes
        )
        if media_type is None:
            lower_path = source.path.lower()
            if lower_path.endswith(".json"):
                media_type = "application/json"
            elif lower_path.endswith((".jsonl", ".ndjson")):
                media_type = "application/x-ndjson"
            else:
                media_type, _ = mimetypes.guess_type(source.path)
        locator = f"github://{source.owner}/{source.repository}@{commit}/{source.path}"
        return Acquisition(
            data=data,
            source=SourceRef(
                scheme="github",
                locator=locator,
                adapter=self.name,
                adapter_version=self.version,
                observed_at=now_iso(),
                source_identity={
                    "owner": source.owner,
                    "repository": source.repository,
                    "commit": commit,
                    "path": source.path,
                },
                claimed_metadata={"requested_ref": source.ref},
                observed_metadata=observed,
            ),
            claimed_media_type=media_type,
        )
