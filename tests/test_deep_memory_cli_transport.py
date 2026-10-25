"""Pinned CLI transport contract tests using a synthetic evidence producer."""

import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime_cohesion.deep_memory_cli_transport import PinnedDeepMemoryCLITransport
from runtime_cohesion.deep_memory_evidence import (
    DEFAULT_REGISTRY,
    DeepMemoryEvidenceAdapter,
    EvidenceAuthorizationError,
    EvidenceContractError,
    EvidenceSearchRequest,
)


def _record(identifier, privacy):
    return {
        "memory_id": identifier,
        "memory_class": "EVENT",
        "stored_historical_canonicity": "UNRESOLVED_HISTORY",
        "historical_canonicity": "UNRESOLVED_HISTORY",
        "event_time": "2026-01-01T00:00:00Z",
        "recorded_at": "2026-01-02T00:00:00Z",
        "recorded_at_status": "SOURCE_RECORDED",
        "chronology_semantics": "EVENT_TIME_RECORD_TIME_EFFECTIVE_TIME_RETRIEVAL_TIME_SEPARATE",
        "provenance_ceiling": "HISTORICAL_ONLY",
        "privacy_scope": privacy,
        "currentness_rule": "HISTORICAL_ONLY",
        "governed_memory_admission": "NOT_ADMITTED",
        "source_ids": ["tranche:1", "tranche:2"],
        "ledger_path": "ledger/memories_001.jsonl",
        "ledger_line": 1,
        "amendments": [
            {
                "source_ids": ["tranche:2"],
                "privacy_scope": privacy,
                "recorded_at": "2026-02-02T00:00:00Z",
                "recorded_at_status": "SOURCE_RECORDED",
                "effective_from": None,
                "effective_from_status": "UNKNOWN_NOT_RECORDED_IN_SOURCE_ROW",
                "chronology_semantics": "EVENT_TIME_RECORD_TIME_EFFECTIVE_TIME_RETRIEVAL_TIME_SEPARATE",
            }
        ],
        "historical_canon_overlays": [],
        "classification_corrections": [],
        "overlay_privacy_semantics": "OVERLAY_INHERITS_TARGET_PRIVACY_UNLESS_EXPLICIT_SCOPE_REQUIRES_SEPARATE_AUTHORIZATION",
        "result_semantics": "HISTORICAL_EVIDENCE_ONLY_NOT_CURRENT_MEMORY_OR_AUTHORITY",
    }


class PinnedCLITest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "dms"
        (self.root / "tools").mkdir(parents=True)
        rows = [_record("history-a", "PROJECT"), _record("history-b", "PRIVATE")]
        # The synthetic program tests the exact CLI transport/adapter contract.
        # It is not a stand-in for DeepMemoryStorage's independent union tests.
        program = (
            "import argparse,json,os\n"
            "if 'DEEP_MEMORY_FAKE_TOKEN' in os.environ: raise SystemExit(90)\n"
            "p=argparse.ArgumentParser()\n"
            "p.add_argument('query')\n"
            "p.add_argument('--authorized-privacy',action='append',default=[])\n"
            "p.add_argument('--limit',type=int)\n"
            "p.add_argument('--json',action='store_true')\n"
            "a=p.parse_args()\n"
            f"rows={rows!r}\n"
            "rows=[r for r in rows if r['privacy_scope'] in a.authorized_privacy][:a.limit]\n"
            "print(json.dumps({'schema':'VERA_DEEP_MEMORY_EVIDENCE_RESULT_V1',"
            "'query':a.query,'privacy_mode':'AUTHORIZED_SCOPE_FILTER',"
            "'retrieved_at':'2026-10-25T00:00:00Z',"
            "'authorized_privacy_scopes':sorted(a.authorized_privacy),"
            "'count':len(rows),'results':rows}))\n"
        )
        (self.root / "tools" / "query_deep_memory.py").write_text(
            program, encoding="utf-8"
        )
        (self.root / "tools" / "deep_memory_catalog.py").write_text(
            "# fixture\n", encoding="utf-8"
        )
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "add", "tools"], check=True)
        git_env = dict(
            os.environ,
            GIT_AUTHOR_NAME="test",
            GIT_AUTHOR_EMAIL="test@example.invalid",
            GIT_COMMITTER_NAME="test",
            GIT_COMMITTER_EMAIL="test@example.invalid",
        )
        subprocess.run(
            ["git", "-C", str(self.root), "commit", "-qm", "fixture"],
            check=True,
            env=git_env,
        )
        self.sha = subprocess.run(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        registry = json.loads(DEFAULT_REGISTRY.read_text(encoding="utf-8"))
        self.source_repository = registry["providers"][0]["source"]["repository"]
        registry["providers"][0]["source"]["source_merged_commit"] = self.sha
        self.registry_path = Path(self.temp.name) / "registry.json"
        self.registry_path.write_text(json.dumps(registry), encoding="utf-8")

    def transport(self, sha=None):
        return PinnedDeepMemoryCLITransport(
            self.root,
            source_repository=self.source_repository,
            source_commit=sha or self.sha,
        )

    def search(self, *scopes):
        return DeepMemoryEvidenceAdapter(
            self.transport(), registry_path=self.registry_path
        ).search(EvidenceSearchRequest("witness", scopes))

    def recommit_fixture_program(self, source):
        (self.root / "tools" / "query_deep_memory.py").write_text(
            source, encoding="utf-8"
        )
        subprocess.run(
            ["git", "-C", str(self.root), "add", "tools/query_deep_memory.py"],
            check=True,
        )
        git_env = dict(
            os.environ,
            GIT_AUTHOR_NAME="test",
            GIT_AUTHOR_EMAIL="test@example.invalid",
            GIT_COMMITTER_NAME="test",
            GIT_COMMITTER_EMAIL="test@example.invalid",
        )
        subprocess.run(
            ["git", "-C", str(self.root), "commit", "-qm", "fixture variant"],
            check=True,
            env=git_env,
        )
        self.sha = subprocess.run(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        registry = json.loads(self.registry_path.read_text(encoding="utf-8"))
        registry["providers"][0]["source"]["source_merged_commit"] = self.sha
        self.registry_path.write_text(json.dumps(registry), encoding="utf-8")

    def test_provenance_from_two_tranches_remains_unpromoted(self):
        batch = self.search("PROJECT")
        self.assertEqual(batch.count, 1)
        self.assertEqual(batch.results[0]["source_ids"], ["tranche:1", "tranche:2"])
        self.assertEqual(batch.results[0]["amendments"][0]["source_ids"], ["tranche:2"])
        self.assertEqual(
            batch.results[0]["historical_canonicity"], "UNRESOLVED_HISTORY"
        )
        self.assertFalse(batch.canonical_memory_transfer)
        self.assertFalse(batch.execution_authorized)
        self.assertEqual(
            batch.claim_ceiling,
            "HISTORICAL_EVIDENCE_ONLY_NOT_CURRENT_MEMORY_OR_AUTHORITY",
        )

    def test_private_result_is_filtered(self):
        self.assertEqual(
            [r["memory_id"] for r in self.search("PROJECT").results], ["history-a"]
        )
        self.assertEqual(
            [r["memory_id"] for r in self.search("PRIVATE").results], ["history-b"]
        )

    def test_unscoped_and_archive_audit_are_denied(self):
        with self.assertRaises(EvidenceAuthorizationError):
            self.search()
        with self.assertRaises(EvidenceAuthorizationError):
            self.transport()(
                operation="EVIDENCE_SEARCH",
                query="witness",
                privacy_mode="EXPLICIT_ARCHIVE_AUDIT_ALL",
                authorized_privacy_scopes=[],
                provider_source_binding={
                    "repository": "thebrazenbeard/deepmemorystorage",
                    "commit": self.sha,
                },
            )

    def test_wrong_pin_and_dirty_source_are_denied(self):
        with self.assertRaises(EvidenceContractError):
            self.transport("0" * 40)(
                operation="EVIDENCE_SEARCH",
                query="witness",
                privacy_mode="AUTHORIZED_SCOPE_FILTER",
                authorized_privacy_scopes=["PROJECT"],
                provider_source_binding={
                    "repository": "thebrazenbeard/deepmemorystorage",
                    "commit": "0" * 40,
                },
            )
        (self.root / "tools" / "query_deep_memory.py").write_text(
            "raise RuntimeError('tampered')\n", encoding="utf-8"
        )
        with self.assertRaises(EvidenceContractError):
            self.search("PROJECT")

    def test_binding_mismatch_and_duplicate_scopes_are_denied(self):
        with self.assertRaises(EvidenceContractError):
            self.transport()(
                operation="EVIDENCE_SEARCH",
                query="witness",
                privacy_mode="AUTHORIZED_SCOPE_FILTER",
                authorized_privacy_scopes=["PROJECT"],
                provider_source_binding={
                    "repository": "thebrazenbeard/deepmemorystorage",
                    "commit": "0" * 40,
                },
            )
        with self.assertRaises(EvidenceAuthorizationError):
            self.transport()(
                operation="EVIDENCE_SEARCH",
                query="witness",
                privacy_mode="AUTHORIZED_SCOPE_FILTER",
                authorized_privacy_scopes=["PROJECT", "PROJECT"],
                provider_source_binding={
                    "repository": "thebrazenbeard/deepmemorystorage",
                    "commit": self.sha,
                },
            )

    def test_inherited_overlay_with_foreign_effective_scope_fails_closed(self):
        def poisoned(**payload):
            result = dict(self.transport()(**payload))
            result["results"][0]["amendments"][0].pop("privacy_scope")
            result["results"][0]["amendments"][0]["effective_privacy_scope"] = "PRIVATE"
            return result

        adapter = DeepMemoryEvidenceAdapter(poisoned, registry_path=self.registry_path)
        with self.assertRaises(EvidenceAuthorizationError):
            adapter.search(EvidenceSearchRequest("witness", ("PROJECT",)))

    def test_explicit_and_effective_overlay_scope_disagreement_is_rejected(self):
        def poisoned(**payload):
            result = dict(self.transport()(**payload))
            result["results"][0]["amendments"][0]["effective_privacy_scope"] = "PRIVATE"
            return result

        adapter = DeepMemoryEvidenceAdapter(poisoned, registry_path=self.registry_path)
        # Both scopes are granted, but a self-contradictory overlay is invalid.
        with self.assertRaises(EvidenceContractError):
            adapter.search(EvidenceSearchRequest("witness", ("PROJECT", "PRIVATE")))

    def test_nontext_effective_privacy_scope_has_controlled_denial(self):
        def poisoned(**payload):
            result = dict(self.transport()(**payload))
            result["results"][0]["amendments"][0]["effective_privacy_scope"] = []
            return result

        adapter = DeepMemoryEvidenceAdapter(poisoned, registry_path=self.registry_path)
        with self.assertRaises(EvidenceAuthorizationError):
            adapter.search(EvidenceSearchRequest("witness", ("PROJECT",)))

    def test_assume_unchanged_poison_does_not_execute(self):
        script = self.root / "tools" / "query_deep_memory.py"
        sentinel = Path(self.temp.name) / "poison-ran"
        subprocess.run(
            [
                "git",
                "-C",
                str(self.root),
                "update-index",
                "--assume-unchanged",
                "tools/query_deep_memory.py",
            ],
            check=True,
        )
        script.write_text(
            f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('ran')\n"
        )
        self.assertEqual(
            subprocess.run(
                ["git", "-C", str(self.root), "status", "--porcelain"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout,
            "",
        )  # The old git-status-only gate was bypassable.
        with self.assertRaises(EvidenceContractError):
            self.search("PROJECT")
        self.assertFalse(sentinel.exists())

    def test_skip_worktree_poison_does_not_execute(self):
        script = self.root / "tools" / "query_deep_memory.py"
        sentinel = Path(self.temp.name) / "skip-ran"
        subprocess.run(
            [
                "git",
                "-C",
                str(self.root),
                "update-index",
                "--skip-worktree",
                "tools/query_deep_memory.py",
            ],
            check=True,
        )
        script.write_text(
            f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('ran')\n"
        )
        with self.assertRaises(EvidenceContractError):
            self.search("PROJECT")
        self.assertFalse(sentinel.exists())

    def test_git_excluded_extra_ledger_cannot_change_search_results(self):
        (self.root / ".git" / "info" / "exclude").write_text(
            "ledger/memories_999.jsonl\n"
        )
        (self.root / "ledger").mkdir()
        (self.root / "ledger" / "memories_999.jsonl").write_text(
            '{"memory_id":"poison"}\n'
        )
        self.assertEqual(
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.root),
                    "status",
                    "--porcelain",
                    "--untracked-files=all",
                ],
                check=True,
                capture_output=True,
                text=True,
            ).stdout,
            "",
        )
        with self.assertRaises(EvidenceContractError):
            self.search("PROJECT")

    def test_ignored_bytecode_cannot_be_imported(self):
        (self.root / ".git" / "info" / "exclude").write_text("tools/__pycache__/\n")
        cache = self.root / "tools" / "__pycache__"
        cache.mkdir()
        (cache / "deep_memory_catalog.cpython-312.pyc").write_bytes(b"fake bytecode")
        self.assertEqual(
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.root),
                    "status",
                    "--porcelain",
                    "--untracked-files=all",
                ],
                check=True,
                capture_output=True,
                text=True,
            ).stdout,
            "",
        )
        with self.assertRaises(EvidenceContractError):
            self.search("PROJECT")

    def test_parent_credentials_are_not_inherited(self):
        with patch.dict(os.environ, {"DEEP_MEMORY_FAKE_TOKEN": "never-forward"}):
            self.assertEqual(self.search("PROJECT").count, 1)

    def _prepare_clean_crlf_checkout(self):
        # Git for Windows may check out a clean text working tree with CRLF,
        # even though its pinned Git objects contain canonical LF bytes.
        subprocess.run(
            ["git", "-C", str(self.root), "config", "core.autocrlf", "true"],
            check=True,
        )
        for filename in ("query_deep_memory.py", "deep_memory_catalog.py"):
            path = self.root / "tools" / filename
            canonical_lf = path.read_bytes().replace(b"\r\n", b"\n")
            path.write_bytes(canonical_lf.replace(b"\n", b"\r\n"))
        subprocess.run(["git", "-C", str(self.root), "add", "tools"], check=True)
        git_env = dict(
            os.environ,
            GIT_AUTHOR_NAME="test",
            GIT_AUTHOR_EMAIL="test@example.invalid",
            GIT_COMMITTER_NAME="test",
            GIT_COMMITTER_EMAIL="test@example.invalid",
        )
        subprocess.run(
            ["git", "-C", str(self.root), "commit", "--allow-empty", "-qm", "CRLF fixture"],
            check=True,
            env=git_env,
        )
        self._rebind_fixture_commit()
        status = subprocess.run(
            ["git", "-C", str(self.root), "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        self.assertEqual(status, "")

    def test_clean_git_crlf_checkout_uses_canonical_blob_bytes(self):
        self._prepare_clean_crlf_checkout()
        script = self.root / "tools" / "query_deep_memory.py"
        self.assertIn(b"\r\n", script.read_bytes())
        git_blob = subprocess.run(
            ["git", "-C", str(self.root), "show", "HEAD:tools/query_deep_memory.py"],
            check=True,
            capture_output=True,
        ).stdout
        self.assertNotIn(b"\r\n", git_blob)
        self.assertEqual(
            self.transport()._attest_source_files()["tools/query_deep_memory.py"],
            git_blob,
        )
        self.assertEqual(self.search("PROJECT").count, 1)

    def test_crlf_conversion_does_not_admit_altered_script(self):
        self._prepare_clean_crlf_checkout()
        subprocess.run(
            [
                "git",
                "-C",
                str(self.root),
                "update-index",
                "--assume-unchanged",
                "tools/query_deep_memory.py",
            ],
            check=True,
        )
        script = self.root / "tools" / "query_deep_memory.py"
        script.write_bytes(script.read_bytes() + b"# unauthorized edit\r\n")
        with self.assertRaises(EvidenceContractError):
            self.transport()._attest_source_files()

    def test_crlf_conversion_does_not_rewrite_binary_files(self):
        binary = self.root / "opaque.bin"
        binary.write_bytes(b"opaque\x00\n")
        subprocess.run(["git", "-C", str(self.root), "add", "opaque.bin"], check=True)
        git_env = dict(
            os.environ,
            GIT_AUTHOR_NAME="test",
            GIT_AUTHOR_EMAIL="test@example.invalid",
            GIT_COMMITTER_NAME="test",
            GIT_COMMITTER_EMAIL="test@example.invalid",
        )
        subprocess.run(
            ["git", "-C", str(self.root), "commit", "-qm", "binary fixture"],
            check=True,
            env=git_env,
        )
        self._rebind_fixture_commit()
        subprocess.run(
            [
                "git",
                "-C",
                str(self.root),
                "update-index",
                "--assume-unchanged",
                "opaque.bin",
            ],
            check=True,
        )
        binary.write_bytes(b"opaque\x00\r\n")
        with self.assertRaises(EvidenceContractError):
            self.transport()._attest_source_files()

    def _rebind_fixture_commit(self):
        self.sha = subprocess.run(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        registry = json.loads(self.registry_path.read_text(encoding="utf-8"))
        registry["providers"][0]["source"]["source_merged_commit"] = self.sha
        self.registry_path.write_text(json.dumps(registry), encoding="utf-8")

    def test_execution_uses_attested_snapshot_not_changed_worktree(self):
        transport = self.transport()
        original_attest = transport._attest_source_files
        sentinel = Path(self.temp.name) / "race-poison-ran"

        def attest_then_mutate():
            checked = original_attest()
            (self.root / "tools" / "query_deep_memory.py").write_text(
                f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('ran')\n"
            )
            return checked

        transport._attest_source_files = attest_then_mutate
        batch = DeepMemoryEvidenceAdapter(
            transport, registry_path=self.registry_path
        ).search(EvidenceSearchRequest("witness", ("PROJECT",)))
        self.assertEqual(batch.count, 1)
        self.assertFalse(sentinel.exists())

    def test_huge_stdout_kills_child_before_post_output_effect(self):
        pid_file = Path(self.temp.name) / "oversize.pid"
        post_output = Path(self.temp.name) / "oversize-survived"
        self.recommit_fixture_program(
            "import os,sys,time\nfrom pathlib import Path\n"
            f"Path({str(pid_file)!r}).write_text(str(os.getpid()))\n"
            "sys.stdout.write('X'*1_000_000)\nsys.stdout.flush()\n"
            "time.sleep(5)\n"
            f"Path({str(post_output)!r}).write_text('executed')\n"
        )
        transport = PinnedDeepMemoryCLITransport(
            self.root,
            source_repository=self.source_repository,
            source_commit=self.sha,
            max_result_bytes=1024,
        )
        start = time.monotonic()
        with self.assertRaisesRegex(EvidenceContractError, "byte limit"):
            DeepMemoryEvidenceAdapter(
                transport, registry_path=self.registry_path
            ).search(EvidenceSearchRequest("witness", ("PROJECT",)))
        self.assertLess(time.monotonic() - start, 3)
        self.assertFalse(post_output.exists())
        self.assertTrue(pid_file.is_file())
        if os.name == "posix":
            with self.assertRaises(ProcessLookupError):
                os.kill(int(pid_file.read_text()), 0)

    def test_slow_stdout_is_killed_at_deadline(self):
        pid_file = Path(self.temp.name) / "timeout.pid"
        self.recommit_fixture_program(
            "import os,sys,time\nfrom pathlib import Path\n"
            f"Path({str(pid_file)!r}).write_text(str(os.getpid()))\n"
            "sys.stdout.write('partial')\nsys.stdout.flush()\ntime.sleep(5)\n"
        )
        transport = PinnedDeepMemoryCLITransport(
            self.root,
            source_repository=self.source_repository,
            source_commit=self.sha,
            timeout_seconds=0.2,
        )
        start = time.monotonic()
        with self.assertRaisesRegex(EvidenceContractError, "timed out"):
            DeepMemoryEvidenceAdapter(
                transport, registry_path=self.registry_path
            ).search(EvidenceSearchRequest("witness", ("PROJECT",)))
        self.assertLess(time.monotonic() - start, 3)
        self.assertTrue(pid_file.is_file())
        if os.name == "posix":
            with self.assertRaises(ProcessLookupError):
                os.kill(int(pid_file.read_text()), 0)


if __name__ == "__main__":
    unittest.main()
