from pathlib import Path

import os

import r8a0.lifecycle as lifecycle_module
import r8a0.process as process_module
import r8a0.memory as memory_module
import r8a0.trust as trust_module


def test_recovery_layer_has_no_unix_only_fcntl_or_etc_vera_dependency():
    package_root = Path(lifecycle_module.__file__).resolve().parent
    violations = []
    for path in package_root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "import fcntl" in text or "from fcntl" in text:
            violations.append((path.name, "fcntl"))
        if "/etc/vera" in text:
            violations.append((path.name, "/etc/vera"))
        if "os.kill(" in text and path.name != "process.py":
            violations.append((path.name, "direct os.kill"))
    assert violations == []


def test_trust_provisioning_root_is_explicit_local_state(tmp_path):
    original = trust_module.PROVISIONING_ROOT
    try:
        root = trust_module.configure_provisioning_root(tmp_path / "state")
        paths = (
            trust_module.AUTHORITY_ROOT_CONFIG_PATH,
            trust_module.TRUST_REGISTRY_CONFIG_PATH,
            trust_module.LIFECYCLE_REGISTRY_KEY_PATH,
        )
        assert root == (tmp_path / "state").resolve()
        assert all(path.is_absolute() for path in paths)
        assert all("/etc/vera" not in path.as_posix() for path in paths)
        assert all(path.parent == root / "recovery" / "trust" for path in paths)
    finally:
        trust_module.configure_provisioning_root(original)


def test_lifecycle_registry_uses_portable_sqlite_lock(tmp_path):
    registry = lifecycle_module.LifecycleRegistry(
        tmp_path / "lifecycle.json",
        b"0123456789abcdef0123456789abcdef",
    )
    head = registry.current_head()
    next_head = registry.consume(
        termination_signature="term-1",
        checkpoint_signature="checkpoint-1",
        predecessor_runtime_id="before",
        successor_runtime_id="after",
        resumption_claim_digest="a" * 64,
        expected_head=head,
    )
    assert next_head != head
    assert registry.lock.suffix == ".sqlite3"
    assert registry.event("term-1")["state"] == "CONSUMED"


def test_process_liveness_is_hidden_behind_portable_adapter():
    assert process_module.process_is_alive(os.getpid()) is True
    assert process_module.process_is_alive(-1) is False
