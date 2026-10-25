"""Offline-only, local-private adapter dataset preparation.

This module never contacts a model service or mutates neural weights. Values
in the operator-authored manifest are declarations, NOT independent proofs of
license, consent, base-model revision, or tokenizer/GGUF compatibility.
"""

import hashlib
import json
import os
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PreparationPlan:
    manifest_sha256: str
    base_model_binding_sha256: str
    source_revision: str
    corpus_sha256: str
    training_count: int
    evaluation_count: int
    training_ids: tuple[str, ...]
    evaluation_ids: tuple[str, ...]
    training_group_ids: tuple[str, ...]
    evaluation_group_ids: tuple[str, ...]


@dataclass(frozen=True)
class _Prepared:
    plan: PreparationPlan
    train: tuple[dict, ...]
    evaluation: tuple[dict, ...]


def _object(value: object, description: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{description} must be a JSON object")
    return value


def _keys(value: dict, expected: set[str], description: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{description} fields must be exactly {sorted(expected)}")


def _sha(value: object, length: int, description: str) -> str:
    if not isinstance(value, str) or re.fullmatch(rf"[0-9a-f]{{{length}}}", value) is None:
        raise ValueError(f"{description} must be a pinned lowercase {length}-character hex digest")
    return value


def _reject_git_checkout(path: Path, description: str) -> None:
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink():
            raise ValueError(f"{description} must not traverse a symlink directory")
        marker = ancestor / ".git"
        is_worktree = marker.is_file()
        is_repo = marker.is_dir() and (marker / "HEAD").is_file()
        if is_worktree or is_repo:
            raise ValueError(f"{description} cannot be within a Git checkout")


_PRIVATE_LINUX_FILESYSTEMS = frozenset({
    "ext2", "ext3", "ext4", "xfs", "btrfs", "f2fs", "zfs", "tmpfs", "overlay",
})


def _require_private_filesystem(path: Path, description: str) -> None:
    """Reject Windows-backed or other unqualified Linux mounts, including WSL DrvFs.

    A 0600 st_mode on a WSL-mounted Windows drive is not proof that Windows
    principals cannot access the file. We fail closed on unknown backing FS.
    """
    if not sys.platform.startswith("linux"):
        return
    try:
        mounts = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"{description} private filesystem qualification unavailable") from exc
    candidate = path.resolve(strict=False)
    best_mount: Path | None = None
    best_types: set[str] = set()
    for line in mounts:
        fields = line.split(" - ", 1)
        if len(fields) != 2:
            continue
        before, after = fields[0].split(), fields[1].split()
        if len(before) < 5 or not after:
            continue
        decoded = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), before[4])
        mountpoint = Path(decoded)
        if candidate == mountpoint or mountpoint in candidate.parents:
            if best_mount is None or len(mountpoint.parts) > len(best_mount.parts):
                best_mount, best_types = mountpoint, {after[0]}
            elif len(mountpoint.parts) == len(best_mount.parts):
                # Stacked mounts with conflicting types are ambiguous unless
                # fully resolved by mount-ID ancestry; refuse the ambiguity.
                best_types.add(after[0])
    if len(best_types) != 1 or not best_types <= _PRIVATE_LINUX_FILESYSTEMS:
        raise ValueError(f"{description} requires a qualified private Linux filesystem")


def _load_snapshot(path: Path, description: str, max_bytes: int) -> bytes:
    if os.name == "nt":
        raise ValueError("Windows private ACL qualification is not implemented; refuse private sample access")
    _reject_git_checkout(path.parent, description)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError(f"{description} requires an existing absolute non-symlink regular file")
    _require_private_filesystem(path, description)
    if os.name == "posix" and stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ValueError(f"{description} requires private file permissions (0600)")
    if path.stat().st_size > max_bytes:
        raise ValueError(f"{description} exceeds allowed size")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ValueError(f"{description} is not a regular file")
        if os.name == "posix" and stat.S_IMODE(os.fstat(handle.fileno()).st_mode) & 0o077:
            raise ValueError(f"{description} requires private file permissions (0600)")
        data = handle.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"{description} exceeds allowed size")
    return data


def _prepare(manifest_path: Path) -> _Prepared:
    raw_manifest = _load_snapshot(Path(manifest_path), "manifest", 65536)
    try:
        manifest = _object(json.loads(raw_manifest.decode("utf-8")), "manifest")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("manifest must be valid UTF-8 JSON") from exc
    _keys(manifest, {"schema_version", "base_model", "data", "split", "execution"}, "manifest")
    if type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1:
        raise ValueError("unsupported manifest schema_version")

    base = _object(manifest["base_model"], "base_model")
    _keys(base, {"hf_repo", "revision_sha", "tokenizer_revision_sha", "chat_template_sha256", "license_review", "gguf_base_sha256"}, "base_model")
    if (not isinstance(base["hf_repo"], str)
            or re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", base["hf_repo"]) is None
            or any(segment in {".", ".."} for segment in base["hf_repo"].split("/"))):
        raise ValueError("base_model hf_repo must be a fixed owner/model identifier")
    revision = _sha(base["revision_sha"], 40, "base_model revision")
    _sha(base["tokenizer_revision_sha"], 40, "tokenizer revision")
    _sha(base["chat_template_sha256"], 64, "chat template")
    _sha(base["gguf_base_sha256"], 64, "GGUF inference base")
    if not isinstance(base["license_review"], str) or not base["license_review"].strip():
        raise ValueError("base_model license_review declaration required")

    data = _object(manifest["data"], "data")
    _keys(data, {"path", "sha256", "classification", "approval_reference"}, "data")
    if data["classification"] != "private-local-only":
        raise ValueError("data classification must be private-local-only; never use public bootcamp")
    if not isinstance(data["approval_reference"], str) or not data["approval_reference"].strip():
        raise ValueError("data approval_reference must be nonempty")
    digest = _sha(data["sha256"], 64, "data digest")
    if not isinstance(data["path"], str):
        raise ValueError("data path must be a string")
    raw_data = _load_snapshot(Path(data["path"]), "training data", 64 * 1024 * 1024)
    if hashlib.sha256(raw_data).hexdigest() != digest:
        raise ValueError("training data digest mismatch")

    config = _object(manifest["split"], "split")
    _keys(config, {"seed", "evaluation_fraction"}, "split")
    if type(config["seed"]) is not int or not (0 <= config["seed"] <= 2**32 - 1):
        raise ValueError("split seed must be a uint32 integer")
    fraction = config["evaluation_fraction"]
    if type(fraction) not in (int, float) or not (0.05 <= fraction <= 0.5):
        raise ValueError("evaluation_fraction must be between 0.05 and 0.5")

    execution = _object(manifest["execution"], "execution")
    _keys(execution, {"allow_network", "allow_weight_update"}, "execution")
    if execution["allow_network"] is not False:
        raise ValueError("network must remain disabled in offline preparation")
    if execution["allow_weight_update"] is not False:
        raise ValueError("weight update must remain disabled in preparation")

    rows: list[dict] = []
    seen_ids: set[str] = set()
    seen_content: set[str] = set()
    try:
        decoded = raw_data.decode("utf-8")
        for n, line in enumerate(decoded.splitlines(), 1):
            if not line.strip():
                raise ValueError(f"training data line {n} empty")
            row = _object(json.loads(line), f"training example {n}")
            _keys(row, {"example_id", "group_id", "provenance", "consent", "messages"}, f"training example {n}")
            sample_id = row["example_id"]
            if not isinstance(sample_id, str) or re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", sample_id) is None:
                raise ValueError("example_id must be a bounded opaque identifier")
            if sample_id in seen_ids:
                raise ValueError("duplicate example_id")
            seen_ids.add(sample_id)
            if not isinstance(row["group_id"], str) or re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", row["group_id"]) is None:
                raise ValueError("group_id must be a bounded opaque source group")
            if not isinstance(row["provenance"], str) or not row["provenance"].strip():
                raise ValueError("training example provenance required")
            if row["consent"] != "owner-approved-local-training":
                raise ValueError("training example consent declaration missing")
            messages = row["messages"]
            if not isinstance(messages, list) or len(messages) != 2:
                raise ValueError("training example requires exactly user+assistant messages")
            if any(not isinstance(m, dict) or set(m) != {"role", "content"} for m in messages):
                raise ValueError("training message schema invalid")
            if [m["role"] for m in messages] != ["user", "assistant"]:
                raise ValueError("training example roles must be user then assistant")
            if any(not isinstance(m["content"], str) or not m["content"].strip() for m in messages):
                raise ValueError("training message content must be nonempty")
            body_hash = hashlib.sha256(json.dumps(messages, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
            if body_hash in seen_content:
                raise ValueError("duplicate training conversation content")
            seen_content.add(body_hash)
            rows.append(row)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("training data must be strict UTF-8 JSONL") from exc

    if len(rows) < 4:
        raise ValueError("at least four distinct approved examples required")
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row["group_id"], []).append(row)
    if len(groups) < 2:
        raise ValueError("at least two independent source groups required")
    ordered_groups = sorted(groups, key=lambda gid: hashlib.sha256(f"{config['seed']}:{gid}".encode("utf-8")).digest())
    held = max(1, min(len(groups) - 1, round(len(groups) * fraction)))
    eval_groups = set(ordered_groups[:held])
    evaluation = tuple(row for row in rows if row["group_id"] in eval_groups)
    train = tuple(row for row in rows if row["group_id"] not in eval_groups)
    binding = hashlib.sha256(json.dumps(base, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    plan = PreparationPlan(
        manifest_sha256=hashlib.sha256(raw_manifest).hexdigest(),
        base_model_binding_sha256=binding,
        source_revision=revision,
        corpus_sha256=digest,
        training_count=len(train),
        evaluation_count=len(evaluation),
        training_ids=tuple(item["example_id"] for item in train),
        evaluation_ids=tuple(item["example_id"] for item in evaluation),
        training_group_ids=tuple(sorted({item["group_id"] for item in train})),
        evaluation_group_ids=tuple(sorted({item["group_id"] for item in evaluation})),
    )
    return _Prepared(plan, train, evaluation)


def build_plan(manifest_path: Path) -> PreparationPlan:
    return _prepare(manifest_path).plan


def write_private_splits(manifest_path: Path, output_dir: Path) -> PreparationPlan:
    prepared = _prepare(manifest_path)
    out = Path(output_dir)
    _reject_git_checkout(out.parent, "output")
    if not out.is_absolute() or out.is_symlink() or out.exists():
        raise FileExistsError("new absolute non-symlink output directory required")
    if not out.parent.is_dir() or out.parent.is_symlink():
        raise ValueError("output parent must exist and not be a symlink")
    _require_private_filesystem(out.parent, "output")
    out.mkdir(mode=0o700)
    if os.name == "posix":
        os.chmod(out, 0o700)
    def write_exclusive(name: str, payload: bytes) -> None:
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(out / name, flags, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    for name, rows in [("train.jsonl", prepared.train), ("eval.jsonl", prepared.evaluation)]:
        write_exclusive(name, b"".join((json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8") for row in rows))
    audit = {
        "schema_version": 1,
        "manifest_sha256": prepared.plan.manifest_sha256,
        "base_model_binding_sha256": prepared.plan.base_model_binding_sha256,
        "base_revision": prepared.plan.source_revision,
        "corpus_sha256": prepared.plan.corpus_sha256,
        "training_count": prepared.plan.training_count,
        "evaluation_count": prepared.plan.evaluation_count,
        "training_sha256": hashlib.sha256((out / "train.jsonl").read_bytes()).hexdigest(),
        "evaluation_sha256": hashlib.sha256((out / "eval.jsonl").read_bytes()).hexdigest(),
        "status": "PREPARED_ONLY_NOT_TRAINED_OR_QUALIFIED",
        "identity_and_consent_notes": "Operator-declared only; no independent license, consent, model, tokenizer, GGUF or host ACL verification",
    }
    write_exclusive("PLAN.json", (json.dumps(audit, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return prepared.plan
