"""Refuse unsafe file ownership overlap between built Python wheels.

This is a source/release preflight. It does not install, uninstall, or import a
package and must not be mistaken for an installed-host ownership attestation.

Usage: python scripts/check_wheel_overlap.py first.whl second.whl
Exit 0 = no shared site-packages paths, 1 = collision, 2 = invalid input.
The output is a machine-readable JSON receipt with both wheel SHA-256 hashes.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import csv
import hashlib
import hmac
from io import BytesIO, StringIO
import json
from email.parser import Parser
from pathlib import Path, PurePosixPath
import re
import sys
import unicodedata
import zlib
from zipfile import BadZipFile, LargeZipFile, ZipFile

MAX_WHEEL_BYTES = 256 * 1024 * 1024
MAX_ENTRIES = 20000
MAX_METADATA_BYTES = 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
_WINDOWS_DEVICES = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{n}" for prefix in ("COM", "LPT") for n in range(1, 10)
}


class InvalidWheel(ValueError):
    """The supplied archive has an unsafe or ambiguous installed path."""


def _portable_key(path: str) -> str:
    """Conservative Windows/macOS ownership key, independent of host OS."""
    return unicodedata.normalize(
        "NFC", unicodedata.normalize("NFC", path).casefold()
    )


def _installed_path(archive_name: str) -> str | None:
    """Validate every ZIP entry and map files to site-packages destinations."""
    is_directory = archive_name.endswith("/")
    name = archive_name[:-1] if is_directory else archive_name
    if not name or "\\" in name or ":" in name:
        raise InvalidWheel("wheel entry has unsafe path syntax")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in name):
        raise InvalidWheel("wheel entry contains control characters")
    parts = name.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise InvalidWheel("unsafe wheel entry path")
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts:
        raise InvalidWheel("unsafe wheel entry path")
    for part in path.parts:
        if part.endswith((" ", ".")) or part.upper().split(".", 1)[0] in _WINDOWS_DEVICES:
            raise InvalidWheel("wheel entry is ambiguous on Windows")
    if is_directory:
        return None
    if path.parts[0].endswith(".data"):
        if len(path.parts) < 3:
            raise InvalidWheel("unrecognized wheel data entry")
        if path.parts[1] in ("purelib", "platlib"):
            return _portable_key("/".join(path.parts[2:]))
        return None  # scripts, headers, data are outside site-packages
    return _portable_key("/".join(path.parts))


def _read_wheel_bytes(wheel: Path) -> bytes:
    with wheel.open("rb") as stream:
        raw = stream.read(MAX_WHEEL_BYTES + 1)
    if len(raw) > MAX_WHEEL_BYTES:
        raise InvalidWheel("wheel exceeds bounded source size")
    return raw


def _read_entry(archive: ZipFile, name: str, bound: int) -> bytes:
    info = archive.getinfo(name)
    if info.file_size > bound or info.flag_bits & 1:
        raise InvalidWheel("unbounded or encrypted wheel member")
    try:
        with archive.open(info, "r") as member:
            data = member.read(bound + 1)
    except (NotImplementedError, RuntimeError, ValueError, EOFError,
            BadZipFile, OSError, zlib.error) as exc:
        raise InvalidWheel("unreadable or unsupported wheel member") from exc
    if len(data) != info.file_size or len(data) > bound:
        raise InvalidWheel("wheel member size does not match ZIP declaration")
    return data


def _inspect_wheel(wheel: Path) -> tuple[set[str], str]:
    """Pin the inventory and SHA-256 to one immutable byte snapshot."""
    raw = _read_wheel_bytes(wheel)
    seen: set[str] = set()
    archive_keys: set[str] = set()
    with ZipFile(BytesIO(raw)) as archive:
        entries = archive.infolist()
        if len(entries) > MAX_ENTRIES:
            raise InvalidWheel("wheel entry count exceeds bound")
        if sum(e.file_size for e in entries if not e.is_dir()) > MAX_UNCOMPRESSED_BYTES:
            raise InvalidWheel("wheel expanded content exceeds bound")
        for entry in entries:
            target = _installed_path(entry.filename)
            key = _portable_key(entry.filename.rstrip("/"))
            if key in archive_keys:
                raise InvalidWheel("duplicate or aliased ZIP path")
            archive_keys.add(key)
            if target is None:
                continue
            if target in seen:
                raise InvalidWheel(f"duplicate installed path in {wheel.name}: {target}")
            seen.add(target)

        names = {entry.filename for entry in entries if not entry.is_dir()}
        wheels = [n for n in names if re.fullmatch(r"[^/]+\.dist-info/WHEEL", n)]
        metas = [n for n in names if re.fullmatch(r"[^/]+\.dist-info/METADATA", n)]
        records = [n for n in names if re.fullmatch(r"[^/]+\.dist-info/RECORD", n)]
        if len(wheels) != 1 or len(metas) != 1 or len(records) != 1:
            raise InvalidWheel("wheel requires WHEEL, METADATA, and RECORD")
        owners = {n.split("/", 1)[0] for n in (wheels[0], metas[0], records[0])}
        if len(owners) != 1:
            raise InvalidWheel("wheel metadata owners differ")
        try:
            metadata = Parser().parsestr(
                _read_entry(archive, wheels[0], MAX_METADATA_BYTES).decode("utf-8")
            )
            if (not re.fullmatch(r"1\.[0-9]+", metadata.get("Wheel-Version", ""))
                    or metadata.get("Root-Is-Purelib", "").lower() not in ("true", "false")):
                raise InvalidWheel("invalid WHEEL metadata contract")
            pkg = Parser().parsestr(
                _read_entry(archive, metas[0], MAX_METADATA_BYTES).decode("utf-8")
            )
            if not pkg.get("Name") or not pkg.get("Version") or not pkg.get("Metadata-Version"):
                raise InvalidWheel("invalid METADATA identity")
            rows = list(csv.reader(StringIO(
                _read_entry(archive, records[0], MAX_METADATA_BYTES).decode("utf-8")
            )))
        except (UnicodeError, csv.Error) as exc:
            raise InvalidWheel("undecodable wheel metadata") from exc
        if any(len(row) != 3 for row in rows):
            raise InvalidWheel("RECORD rows must have three fields")
        record_names = [row[0] for row in rows]
        for name in record_names:
            if not name or name.endswith("/"):
                raise InvalidWheel("invalid RECORD file path")
            _installed_path(name)
        if len(record_names) != len(set(record_names)) or set(record_names) != names:
            raise InvalidWheel("RECORD inventory differs from ZIP file entries")
        for name, digest_field, size_field in rows:
            if name == records[0]:
                continue  # RECORD itself is explicitly exempt under wheel semantics.
            algorithm, sep, encoded = digest_field.partition("=")
            if (not sep or algorithm not in {"sha256", "sha384", "sha512"}
                    or not re.fullmatch(r"[A-Za-z0-9_-]+", encoded or "")
                    or not re.fullmatch(r"[0-9]{1,10}", size_field)):
                raise InvalidWheel("missing or invalid RECORD hash/size")
            declared_size = int(size_field)
            if declared_size != archive.getinfo(name).file_size:
                raise InvalidWheel("RECORD size disagrees with ZIP declaration")
            try:
                expected = base64.b64decode(
                    encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True
                )
            except (binascii.Error, ValueError) as exc:
                raise InvalidWheel("malformed RECORD digest") from exc
            payload = _read_entry(archive, name, declared_size)
            actual = hashlib.new(algorithm, payload).digest()
            if not hmac.compare_digest(actual, expected):
                raise InvalidWheel("RECORD member digest mismatch")

    return seen, hashlib.sha256(raw).hexdigest()


def compare(wheel_a: Path, wheel_b: Path) -> dict:
    a, a_digest = _inspect_wheel(wheel_a)
    b, b_digest = _inspect_wheel(wheel_b)
    shared = sorted(a & b)
    return {
        "schema": "WHEEL_OWNERSHIP_PREFLIGHT_V1",
        "path_key_policy": "NFC_CASEFOLD_PORTABLE",
        "status": "COLLISION" if shared else "DISJOINT",
        "wheels": [
            {"filename": wheel_a.name, "sha256": a_digest, "site_paths": len(a)},
            {"filename": wheel_b.name, "sha256": b_digest, "site_paths": len(b)},
        ],
        "overlap_count": len(shared),
        "overlapping_site_paths": shared,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel_a", type=Path)
    parser.add_argument("wheel_b", type=Path)
    args = parser.parse_args(argv)
    try:
        result = compare(args.wheel_a, args.wheel_b)
    except (OSError, BadZipFile, LargeZipFile, NotImplementedError,
            RuntimeError, EOFError, zlib.error, InvalidWheel) as exc:
        print(json.dumps({"schema": "WHEEL_OWNERSHIP_PREFLIGHT_V1",
                          "status": "INVALID", "error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 1 if result["status"] == "COLLISION" else 0


if __name__ == "__main__":
    raise SystemExit(main())
