from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
from http.client import HTTPException
from typing import Protocol, runtime_checkable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from ..model import Acquisition, GitHubFileSource, SourceRef, StreamingAcquisition, now_iso
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

    def _headers(self, accept: str) -> dict[str, str]:
        headers = {
            "Accept": accept,
            "User-Agent": "vera-ingest/0.1",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _json(
        self,
        url: str,
        *,
        accept: str = "application/vnd.github+json",
    ) -> dict:
        try:
            with urlopen(
                Request(url, headers=self._headers(accept)),
                timeout=15,
            ) as response:
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

    @staticmethod
    def _git_object_hasher(blob_sha: str, size: int):
        if len(blob_sha) == 40:
            digest = hashlib.sha1(usedforsecurity=False)
        elif len(blob_sha) == 64:
            digest = hashlib.sha256()
        else:
            raise AcquisitionFailed(
                "GitHub blob identity uses an unsupported digest length"
            )
        digest.update(f"blob {size}\\0".encode("ascii"))
        return digest

    def _open_raw_blob(
        self,
        owner: str,
        repository: str,
        blob_sha: str,
    ):
        url = (
            f"{self.api_base}/repos/{quote(owner)}/"
            f"{quote(repository)}/git/blobs/"
            f"{quote(blob_sha, safe='')}"
        )
        try:
            return urlopen(
                Request(
                    url,
                    headers=self._headers(
                        "application/vnd.github.raw+json"
                    ),
                ),
                timeout=15,
            )
        except HTTPError as exc:
            raise AcquisitionFailed(
                f"GitHub API returned HTTP {exc.code}"
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise AcquisitionFailed(
                "GitHub API request failed"
            ) from exc

    def fetch_file_stream(
        self,
        owner: str,
        repository: str,
        commit: str,
        path: str,
        max_bytes: int,
    ):
        payload = self._json(
            f"{self.api_base}/repos/{quote(owner)}/"
            f"{quote(repository)}/contents/{quote(path)}"
            f"?ref={quote(commit)}",
            accept="application/vnd.github.object+json",
        )
        if payload.get("type") != "file":
            raise AcquisitionFailed("GitHub source is not a file")
        size = payload.get("size")
        if (
            not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
        ):
            raise AcquisitionFailed(
                "GitHub file payload has invalid size metadata"
            )
        if size > max_bytes:
            raise PolicyRejected(
                f"GitHub file exceeds max_bytes={max_bytes}"
            )
        blob_sha = payload.get("sha")
        if not isinstance(blob_sha, str):
            raise AcquisitionFailed(
                "GitHub file payload is missing blob identity"
            )
        digest = self._git_object_hasher(blob_sha, size)
        response = self._open_raw_blob(
            owner,
            repository,
            blob_sha,
        )

        def chunks():
            observed_bytes = 0
            try:
                while True:
                    remaining = size + 1 - observed_bytes
                    if remaining <= 0:
                        raise AcquisitionFailed(
                            "GitHub raw blob exceeds metadata size"
                        )
                    try:
                        chunk = response.read(
                            min(64 * 1024, remaining)
                        )
                    except (
                        HTTPException,
                        URLError,
                        TimeoutError,
                        OSError,
                    ) as exc:
                        raise AcquisitionFailed(
                            "GitHub raw blob read failed"
                        ) from exc
                    if not chunk:
                        break
                    next_size = observed_bytes + len(chunk)
                    if next_size > size:
                        raise AcquisitionFailed(
                            "GitHub raw blob exceeds metadata size"
                        )
                    if next_size > max_bytes:
                        raise PolicyRejected(
                            f"GitHub file exceeds max_bytes={max_bytes}"
                        )
                    digest.update(chunk)
                    observed_bytes = next_size
                    yield chunk

                if observed_bytes != size:
                    raise AcquisitionFailed(
                        "GitHub raw blob size does not match metadata"
                    )
                if digest.hexdigest() != blob_sha.lower():
                    raise AcquisitionFailed(
                        "GitHub blob identity does not match acquired bytes"
                    )
            finally:
                response.close()

        return (
            chunks(),
            None,
            {"git_blob_sha": blob_sha, "size": size},
        )

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

    @staticmethod
    def _media_type(path: str, media_type: str | None) -> str | None:
        if media_type is not None:
            return media_type
        lower_path = path.lower()
        if lower_path.endswith(".json"):
            return "application/json"
        if lower_path.endswith((".jsonl", ".ndjson")):
            return "application/x-ndjson"
        guessed, _ = mimetypes.guess_type(path)
        return guessed

    def _source_ref(
        self,
        source: GitHubFileSource,
        commit: str,
        observed: dict,
    ) -> SourceRef:
        locator = (
            f"github://{source.owner}/{source.repository}"
            f"@{commit}/{source.path}"
        )
        return SourceRef(
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
        )

    @staticmethod
    def _validate_source(source: GitHubFileSource) -> None:
        if not all(
            (
                source.owner,
                source.repository,
                source.ref,
                source.path,
            )
        ):
            raise PolicyRejected(
                "GitHub owner/repository/ref/path must be non-empty"
            )

    def acquire_stream(
        self,
        source: GitHubFileSource,
        policy: IngestPolicy,
    ) -> StreamingAcquisition | None:
        self._validate_source(source)
        fetch_stream = getattr(
            self.transport,
            "fetch_file_stream",
            None,
        )
        if not callable(fetch_stream):
            return None
        commit = self.transport.resolve_ref(
            source.owner,
            source.repository,
            source.ref,
        )
        chunks, media_type, observed = fetch_stream(
            source.owner,
            source.repository,
            commit,
            source.path,
            policy.max_bytes,
        )
        return StreamingAcquisition(
            chunks=chunks,
            source=self._source_ref(
                source,
                commit,
                observed,
            ),
            claimed_media_type=self._media_type(
                source.path,
                media_type,
            ),
        )

    def acquire(
        self,
        source: GitHubFileSource,
        policy: IngestPolicy,
    ) -> Acquisition:
        self._validate_source(source)
        commit = self.transport.resolve_ref(
            source.owner,
            source.repository,
            source.ref,
        )
        data, media_type, observed = self.transport.fetch_file(
            source.owner,
            source.repository,
            commit,
            source.path,
            policy.max_bytes,
        )
        return Acquisition(
            data=data,
            source=self._source_ref(
                source,
                commit,
                observed,
            ),
            claimed_media_type=self._media_type(
                source.path,
                media_type,
            ),
        )
