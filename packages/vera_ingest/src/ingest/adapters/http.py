from __future__ import annotations

import ipaddress
import socket
from http.client import HTTPConnection, HTTPException, HTTPSConnection
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.request import Request

from ..canonical import sha256_bytes
from ..model import Acquisition, SourceRef, UrlSource, now_iso
from ..policy import IngestPolicy
from .base import AcquisitionFailed, PolicyRejected


def _ip_is_forbidden(value: str) -> bool:
    ip = ipaddress.ip_address(value)
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _resolve_addresses(host: str) -> tuple[str, ...]:
    try:
        resolved = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise AcquisitionFailed(f"DNS resolution failed for {host}") from exc
    addresses = tuple(dict.fromkeys(item[4][0] for item in resolved))
    if not addresses:
        raise AcquisitionFailed(f"DNS resolution returned no addresses for {host}")
    return addresses


def _safe_url_provenance(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    try:
        port = parsed.port
    except ValueError as exc:
        raise PolicyRejected("URL contains an invalid port") from exc
    netloc = host + (f":{port}" if port is not None else "")
    locator = parsed._replace(netloc=netloc, query="", fragment="").geturl()
    return locator, sha256_bytes(url.encode("utf-8"))


class _PinnedHTTPConnection(HTTPConnection):
    def __init__(self, host: str, port: int, connect_ip: str, timeout: float):
        self._connect_ip = connect_ip
        super().__init__(host, port=port, timeout=timeout)

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self._connect_ip, self.port), self.timeout, self.source_address
        )
        if self._tunnel_host:
            self._tunnel()


class _PinnedHTTPSConnection(HTTPSConnection):
    def __init__(self, host: str, port: int, connect_ip: str, timeout: float):
        self._connect_ip = connect_ip
        super().__init__(host, port=port, timeout=timeout)

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self._connect_ip, self.port), self.timeout, self.source_address
        )
        server_hostname = self.host
        if self._tunnel_host:
            self._tunnel()
            server_hostname = self._tunnel_host
        self.sock = self._context.wrap_socket(self.sock, server_hostname=server_hostname)


class _PinnedResponse:
    def __init__(self, response, connection, url: str):
        self._response = response
        self._connection = connection
        self._url = url
        self.status = response.status
        self.headers = response.headers

    def geturl(self) -> str:
        return self._url

    def read(self, limit: int) -> bytes:
        return self._response.read(limit)

    def close(self) -> None:
        try:
            self._response.close()
        finally:
            self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
        return False


class _PinnedOpener:
    def open(self, request: Request, timeout: float, resolved_addresses: tuple[str, ...]):
        parsed = urlparse(request.full_url)
        try:
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
        except ValueError as exc:
            raise PolicyRejected("URL contains an invalid port") from exc
        target = urlunparse(("", "", parsed.path or "/", parsed.params, parsed.query, ""))
        headers = dict(request.header_items())
        last_error = None
        for connect_ip in resolved_addresses:
            connection_cls = (
                _PinnedHTTPSConnection if parsed.scheme == "https" else _PinnedHTTPConnection
            )
            connection = connection_cls(parsed.hostname or "", port, connect_ip, timeout)
            try:
                connection.request(request.get_method(), target, body=request.data, headers=headers)
                response = connection.getresponse()
                if not 200 <= response.status < 300:
                    code, reason, response_headers = (
                        response.status,
                        response.reason,
                        response.headers,
                    )
                    response.close()
                    connection.close()
                    raise HTTPError(request.full_url, code, reason, response_headers, None)
                return _PinnedResponse(response, connection, request.full_url)
            except HTTPError:
                raise
            except (OSError, HTTPException) as exc:
                connection.close()
                last_error = exc
        raise URLError(last_error or "no validated address could be reached")


class HttpAdapter:
    name = "http"
    version = "1"

    def __init__(self, opener=None):
        self._uses_pinned_default = opener is None
        self.opener = opener or _PinnedOpener()

    def supports(self, source) -> bool:
        return isinstance(source, UrlSource)

    @staticmethod
    def _check_url(url: str, policy: IngestPolicy) -> tuple[str, ...] | None:
        parsed = urlparse(url)
        if parsed.scheme not in {"https", "http"}:
            raise PolicyRejected("URL scheme must be http or https")
        if parsed.scheme == "http" and not policy.allow_http:
            raise PolicyRejected("plain HTTP is disabled by policy")
        if not parsed.hostname:
            raise PolicyRejected("URL must include a host")
        if not policy.deny_private_networks:
            return None
        addresses = _resolve_addresses(parsed.hostname)
        if any(_ip_is_forbidden(address) for address in addresses):
            raise PolicyRejected("private/loopback/link-local destination denied")
        return addresses

    def acquire(self, source: UrlSource, policy: IngestPolicy) -> Acquisition:
        current = source.url
        redirects = 0
        while True:
            resolved_addresses = self._check_url(current, policy)
            request = Request(current, headers={"User-Agent": "vera-ingest/0.1"})
            try:
                if self._uses_pinned_default:
                    if resolved_addresses is None:
                        resolved_addresses = _resolve_addresses(urlparse(current).hostname or "")
                    response = self.opener.open(
                        request,
                        timeout=policy.timeout_seconds,
                        resolved_addresses=resolved_addresses,
                    )
                else:
                    response = self.opener.open(request, timeout=policy.timeout_seconds)
            except HTTPError as exc:
                if exc.code in {301, 302, 303, 307, 308} and exc.headers.get("Location"):
                    if redirects >= policy.max_redirects:
                        raise PolicyRejected("redirect limit exceeded") from exc
                    current = urljoin(current, exc.headers["Location"])
                    redirects += 1
                    continue
                raise AcquisitionFailed(f"HTTP error {exc.code}") from exc
            except URLError as exc:
                raise AcquisitionFailed(f"HTTP acquisition failed: {exc.reason}") from exc
            with response:
                final_url = response.geturl()
                self._check_url(final_url, policy)
                data = response.read(policy.max_bytes + 1)
                if len(data) > policy.max_bytes:
                    raise PolicyRejected(f"response exceeds max_bytes={policy.max_bytes}")
                content_type = response.headers.get("Content-Type")
                status = getattr(response, "status", None)
            final_locator, final_url_sha256 = _safe_url_provenance(final_url)
            _, requested_url_sha256 = _safe_url_provenance(source.url)
            return Acquisition(
                data=data,
                source=SourceRef(
                    scheme=urlparse(final_url).scheme,
                    locator=final_locator,
                    adapter=self.name,
                    adapter_version=self.version,
                    observed_at=now_iso(),
                    source_identity={
                        "url_locator": final_locator,
                        "url_sha256": final_url_sha256,
                    },
                    claimed_metadata={"requested_url_sha256": requested_url_sha256},
                    observed_metadata={"status": status, "redirects": redirects},
                ),
                claimed_media_type=content_type,
            )
