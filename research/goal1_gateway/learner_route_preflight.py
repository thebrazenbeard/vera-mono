"""Read-only Goal 1 learner-process raw-model socket preflight.

This probe is a falsifier, not an OS-enforced security boundary. A successful
connection shows a possible bypass path; a refused connection does not prove
the selected learner cannot reach a different model route. No inference POST,
service change, credential, firewall rule, or gateway claim is performed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import errno
import json
import os
import socket
import sys
from typing import Callable

LOOPBACK = "127.0.0.1"
OLLAMA_PORT = 11434
_TIMEOUT = 0.5


@dataclass(frozen=True, slots=True)
class RouteProbe:
    schema: str
    pid: int
    uid: int | None
    target: str
    observed_utc: str
    tcp_observation: str
    sole_route_qualified: bool
    denied_direct_model_inference_verified: bool
    actual_selected_learner_identity_verified: bool
    evaluation_claim_authorized: bool
    reason: str

    def as_dict(self) -> dict:
        return asdict(self)


def probe_raw_provider_socket(
    *, port: int = OLLAMA_PORT,
    timeout: float = _TIMEOUT,
    dial: Callable[..., object] | None = None,
) -> RouteProbe:
    """Exactly one local TCP connect; observable, bounded, and no model usage.

    The host/process identity is a local observation, not independent attestation.
    Avoid claiming HTTP model inference from mere TCP reachability.
    """
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("port must be a numeric TCP port")
    if type(timeout) not in (int, float) or not 0 < timeout <= 1.0:
        raise ValueError("timeout must be bounded to one second")
    dialer = socket.create_connection if dial is None else dial
    if not callable(dialer):
        raise TypeError("dialer must be callable")
    observation = "INCONCLUSIVE"
    reason = "connection could not be classified; access remains UNKNOWN"
    connection = None
    try:
        connection = dialer((LOOPBACK, port), timeout=timeout)
        observation = "TCP_REACHABLE"
        reason = "raw model-server TCP listener reachable from this process; FAIL"
    except ConnectionRefusedError:
        observation = "TCP_REFUSED"
        reason = "this specific socket refused a connect; sole-route still UNKNOWN"
    except TimeoutError:
        reason = "TCP attempt timed out; network restriction and server absence indistinguishable"
    except OSError as exc:
        if exc.errno == errno.ECONNREFUSED:
            observation = "TCP_REFUSED"
            reason = "this specific socket refused a connect; sole-route still UNKNOWN"
        else:
            reason = "TCP attempt returned an unclassified OS error; sole-route UNKNOWN"
    finally:
        if connection is not None:
            close = getattr(connection, "close", None)
            if callable(close):
                close()
    return RouteProbe(
        schema="VERA_GOAL1_LEARNER_RAW_PROVIDER_PREFLIGHT_V1",
        pid=os.getpid(),
        uid=os.getuid() if hasattr(os, "getuid") else None,
        target=f"{LOOPBACK}:{port}",
        observed_utc=datetime.now(timezone.utc).isoformat(),
        tcp_observation=observation,
        sole_route_qualified=False,
        denied_direct_model_inference_verified=False,
        actual_selected_learner_identity_verified=False,
        evaluation_claim_authorized=False,
        reason=reason,
    )


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        raise SystemExit("no command-line overrides: selected port is 127.0.0.1:11434")
    observation = probe_raw_provider_socket()
    print(json.dumps(observation.as_dict(), sort_keys=True))
    # Qualification must NEVER be granted by this single probe, even on refusal.
    if observation.tcp_observation == "TCP_REACHABLE":
        print("GOAL1_SOLE_ROUTE=FAIL_RAW_TCP_REACHABLE", file=sys.stderr)
    else:
        print("GOAL1_SOLE_ROUTE=HOLD_INDEPENDENT_CUSTODY_REQUIRED", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
