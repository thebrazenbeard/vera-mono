"""Host-validated OS model principals and per-message Linux credentials.

The *privileged launcher* must create a dedicated OS account for each model,
launch it under that account, pin PID/start time and keep the authorization
service under a different account. This module validates those facts; it does
not create accounts, launch models, or establish trusted host custody by itself.

Linux SO_PEERCRED identifies the process that connected. A connected socket
descriptor can be inherited by a child, so additionally require Linux
SO_PASSCRED/SCM_CREDENTIALS on EVERY received chunk. The parent authority
must use this reader (or an independently verified equivalent), not the
SO_PEERCRED-only reader in ipc.py, before treating the message as authorized.

Source tests are not proof of Lappy/VN1/VN2 operating-system isolation.
"""

from __future__ import annotations

from collections import namedtuple
import os
from pathlib import Path
import re
import select
import socket
import struct
import sys
from types import MappingProxyType
from typing import Mapping

from .bindings import HostBindingSnapshot, PrincipalBinding
from .windows_peer import principal_key_for_sid


class PeerIsolationDenied(PermissionError):
    """Host could not prove a unique, live, authorized model OS principal."""


_UID_RE = re.compile(r"uid:(0|[1-9][0-9]*)\Z", re.ASCII)
_UCRED_SIZE = struct.calcsize("3i")


_ProcessPinTuple = namedtuple("_ProcessPinTuple", ("pid", "uid", "start_ticks"))


class LinuxProcessPin(_ProcessPinTuple):
    """Host-launched PID, kernel UID and /proc start time (clock ticks)."""

    __slots__ = ()

    def __new__(cls, pid: int, uid: int, start_ticks: int):
        if (type(pid) is not int or pid <= 0 or
                type(uid) is not int or uid < 0 or
                type(start_ticks) is not int or start_ticks <= 0):
            raise PeerIsolationDenied("invalid exact Linux launch pin")
        return super().__new__(cls, pid, uid, start_ticks)


def _platform_for_peer(peer_key: str) -> str:
    if type(peer_key) is not str:
        raise PeerIsolationDenied("peer identity must be a kernel-derived string")
    match = _UID_RE.fullmatch(peer_key)
    if match is not None:
        return "linux"
    if peer_key.startswith("sid:"):
        try:
            if principal_key_for_sid(peer_key[4:]) == peer_key:
                return "windows"
        except Exception as exc:
            raise PeerIsolationDenied("invalid Windows principal SID") from exc
    raise PeerIsolationDenied("peer identity is not a canonical OS principal")


_IsolationTuple = namedtuple(
    "_IsolationTuple", ("service_peer_key", "bindings", "process_pins", "platform")
)


class HostPeerIsolationPlan(_IsolationTuple):
    """Pinned, immutable account-to-model deployment admission plan.

    This plan must be constructed from a trusted host launcher. It does not
    convert a model-provided UID/SID/PID into authority. The host must call
    ``assert_host_process_identity`` on startup and hand the plan only to an
    authenticated OS message reader.
    """

    __slots__ = ()

    def __new__(cls, service_peer_key: str, bindings: HostBindingSnapshot,
                process_pins: Mapping[str, LinuxProcessPin] | None = None):
        platform = _platform_for_peer(service_peer_key)
        if type(bindings) is not HostBindingSnapshot:
            raise PeerIsolationDenied("host bindings must be exact snapshot")
        if type(process_pins) not in (dict, MappingProxyType, type(None)):
            raise PeerIsolationDenied("process pins must be builtin host mapping")
        pins = process_pins or {}
        if platform == "linux" and set(pins) != set(bindings.principals):
            raise PeerIsolationDenied("every Linux model needs a host launch pin")
        if platform == "windows" and pins:
            raise PeerIsolationDenied("Windows model validation uses SID, not Linux pins")
        copied: dict[str, LinuxProcessPin] = {}
        seen_model_ids: set[str] = set()
        seen_pids: set[int] = set()
        for peer_key, principal in bindings.principals.items():
            if _platform_for_peer(peer_key) != platform:
                raise PeerIsolationDenied("mixed operating-system principal types")
            if peer_key == service_peer_key:
                raise PeerIsolationDenied("service OS principal cannot run model")
            if principal.model_id in seen_model_ids:
                raise PeerIsolationDenied("same model cannot use multiple OS principals")
            seen_model_ids.add(principal.model_id)
            if platform == "linux":
                uid = int(peer_key[4:])
                if uid == 0:
                    raise PeerIsolationDenied("model must not run as root")
                pin = pins[peer_key]
                if type(pin) is not LinuxProcessPin or pin.uid != uid:
                    raise PeerIsolationDenied("host launch pin does not bind OS UID")
                if pin.pid in seen_pids:
                    raise PeerIsolationDenied("same process cannot host multiple models")
                seen_pids.add(pin.pid)
                copied[peer_key] = LinuxProcessPin(pin.pid, pin.uid, pin.start_ticks)
        return super().__new__(
            cls, service_peer_key, bindings, MappingProxyType(copied), platform
        )

    def assert_host_process_identity(self) -> None:
        """Startup gate; fail closed if host daemon identity is not provisioned."""
        if self.platform == "linux":
            if sys.platform != "linux":
                raise PeerIsolationDenied("authorization daemon platform mismatch")
            host_uid, _ = read_linux_process_identity(os.getpid())
            if (f"uid:{host_uid}" != self.service_peer_key or
                    host_uid != os.geteuid()):
                raise PeerIsolationDenied("authorization daemon is not its bound OS user")
        else:
            # Windows host daemon SID must come from its OS token; caller
            # supplied text cannot prove it. A qualified Windows launcher
            # must perform this check before accepting any model requests.
            raise PeerIsolationDenied("Windows service SID attestation unavailable")

    def principal_for_kernel_peer(self, peer_key: str, *, pid: int,
                                  start_ticks: int) -> PrincipalBinding:
        if self.platform != "linux" or _platform_for_peer(peer_key) != "linux":
            raise PeerIsolationDenied("not a Linux kernel peer")
        if type(pid) is not int or type(start_ticks) is not int:
            raise PeerIsolationDenied("noncanonical OS process identity")
        pin = self.process_pins.get(peer_key)
        if pin is None or pid != pin.pid or start_ticks != pin.start_ticks:
            raise PeerIsolationDenied("kernel credentials do not match host-launched process")
        return self.bindings.principal_for_peer(peer_key)

    def principal_for_authenticated_sid(self, sid: str) -> PrincipalBinding:
        if self.platform != "windows":
            raise PeerIsolationDenied("Windows SID presented to Linux deployment")
        try:
            return self.bindings.principal_for_peer(principal_key_for_sid(sid))
        except Exception as exc:
            raise PeerIsolationDenied("Windows OS principal was not launched by host") from exc


def _read_proc_file(pid_fd: int, name: str) -> bytes:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=pid_fd)
    try:
        data = os.read(fd, 65537)
        if len(data) > 65536:
            raise PeerIsolationDenied("kernel process metadata too large")
        return data
    finally:
        os.close(fd)


def read_linux_process_identity(pid: int, *, proc_root: Path = Path("/proc")) -> tuple[int, int]:
    """No-follow /proc UID + PID start pin, with a live pidfd when available."""
    if sys.platform != "linux" or type(pid) is not int or pid <= 0:
        raise PeerIsolationDenied("Linux kernel process lookup unavailable")
    if type(proc_root) is not type(Path("/proc")):
        raise PeerIsolationDenied("proc_root must be exact host path")
    root_fd = proc_fd = pidfd = None
    try:
        root_fd = os.open(proc_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        proc_fd = os.open(str(pid), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                          dir_fd=root_fd)
        if proc_root == Path("/proc"):
            if not hasattr(os, "pidfd_open"):
                raise PeerIsolationDenied("pidfd kernel pin unavailable")
            pidfd = os.pidfd_open(pid, 0)
        status = _read_proc_file(proc_fd, "status").decode("ascii", "strict")
        fields = [line.split() for line in status.splitlines() if line.startswith("Uid:")]
        if len(fields) != 1 or len(fields[0]) != 5:
            raise PeerIsolationDenied("missing kernel UID identity")
        uids = tuple(int(item) for item in fields[0][1:])
        if len(set(uids)) != 1:
            raise PeerIsolationDenied("peer process has mutable/different credential UIDs")
        contents = _read_proc_file(proc_fd, "stat").decode("ascii", "strict").strip()
        close = contents.rfind(")")
        if close <= 0 or not contents.startswith(f"{pid} ("):
            raise PeerIsolationDenied("invalid kernel process stat")
        rest = contents[close + 2:].split()
        if len(rest) <= 19:
            raise PeerIsolationDenied("missing process start time")
        start_ticks = int(rest[19])
        if start_ticks <= 0:
            raise PeerIsolationDenied("invalid process start time")
        if pidfd is not None:
            poll = select.poll()
            poll.register(pidfd, select.POLLIN)
            if poll.poll(0):
                raise PeerIsolationDenied("peer exited while inspecting kernel identity")
        return uids[0], start_ticks
    except (OSError, UnicodeError, ValueError, IndexError) as exc:
        raise PeerIsolationDenied("kernel process identity unavailable") from exc
    finally:
        for fd in (pidfd, proc_fd, root_fd):
            if fd is not None:
                os.close(fd)


def receive_authenticated_linux_frame(
    connection: socket.socket,
    plan: HostPeerIsolationPlan,
    *,
    max_message_bytes: int = 65536,
) -> tuple[PrincipalBinding, bytes]:
    """Receive one LF-framed request with kernel connection AND message creds.

    This prevents a child inheriting an already-connected socket from
    impersonating its parent via SO_PEERCRED alone. A caller-authored model ID
    or UID inside the returned JSON frame has zero authority.
    """
    if (sys.platform != "linux" or type(connection) is not socket.socket or
            type(plan) is not HostPeerIsolationPlan or plan.platform != "linux" or
            not hasattr(socket, "SO_PASSCRED") or not hasattr(socket, "SCM_CREDENTIALS")):
        raise PeerIsolationDenied("kernel authenticated Linux IPC unavailable")
    if type(max_message_bytes) is not int or not 1 <= max_message_bytes <= 65536:
        raise PeerIsolationDenied("invalid message size bound")
    try:
        credential_bytes = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED,
                                                 _UCRED_SIZE)
        pid, uid, gid = struct.unpack("3i", credential_bytes)
        if pid <= 0 or uid <= 0 or gid < 0:
            raise PeerIsolationDenied("invalid/privileged model socket peer")
        peer_key = f"uid:{uid}"
        known_uid, start = read_linux_process_identity(pid)
        if known_uid != uid:
            raise PeerIsolationDenied("kernel process UID differs from socket peer")
        principal = plan.principal_for_kernel_peer(peer_key, pid=pid,
                                                   start_ticks=start)
        connection.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
        body = bytearray()
        while b"\n" not in body:
            remaining = max_message_bytes + 1 - len(body)
            if remaining <= 0:
                raise PeerIsolationDenied("model request exceeded bound")
            chunk, ancillary, flags, _ = connection.recvmsg(
                min(4096, remaining), socket.CMSG_SPACE(_UCRED_SIZE)
            )
            if not chunk or flags & (socket.MSG_CTRUNC | socket.MSG_TRUNC):
                raise PeerIsolationDenied("missing/oversized kernel message")
            credentials = [struct.unpack("3i", data[:_UCRED_SIZE])
                           for level, kind, data in ancillary
                           if level == socket.SOL_SOCKET and kind == socket.SCM_CREDENTIALS
                           and len(data) >= _UCRED_SIZE]
            if credentials != [(pid, uid, gid)]:
                raise PeerIsolationDenied("kernel message credential differs from launch pin")
            body.extend(chunk)
        frame, _, extra = bytes(body).partition(b"\n")
        if extra or not frame:
            raise PeerIsolationDenied("multiple/empty model request frames")
        post_uid, post_start = read_linux_process_identity(pid)
        if (post_uid, post_start) != (uid, start):
            raise PeerIsolationDenied("model process changed during request")
        return principal, frame
    except (OSError, ValueError, struct.error) as exc:
        raise PeerIsolationDenied("OS peer/message credential validation failed") from exc
