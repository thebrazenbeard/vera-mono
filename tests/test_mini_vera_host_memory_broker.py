"""Host-bound public-memory broker: source tests, not an installed host policy."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import io
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
for package in ("vera_memory", "portfolio_runtime"):
    sys.path.insert(0, str(ROOT / "packages" / package / "src"))

from vera_memory import AdmissionRequest, MemoryClass, MemoryLedger  # noqa: E402
from tests.test_mini_vera_source_bindings import KEY, ledger_fixture  # noqa: E402
from tests.test_mini_vera_loopback import FakeLocal, response  # noqa: E402
from tools.mini_vera import local_session  # noqa: E402
from tools.mini_vera.compose import CompositionRejected  # noqa: E402
from tools.mini_vera.host_memory_broker import (  # noqa: E402
    PublicMemoryGrant, bind_host_public_memory,
)


class HostMemoryBrokerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.ledger, head = ledger_fixture(self.folder)
        self.grant = PublicMemoryGrant(
            project_id="vera-mono", identity_id="vera", ledger_head=head,
            revision=13, record_ids=("work-1",), approval_epoch=1,
            expires_at_unix=1_000_600)
        self.permission = {"grant": self.grant, "allow_record": True,
                           "authority_revision": 10}
        self.seen_records = []

    def broker(self):
        def record_policy(record, grant):
            self.seen_records.append((record.record_id, grant.approval_epoch))
            return (self.permission["allow_record"]
                    and record.authority_ref == "synthetic-approved"
                    and record.provenance_refs == ("synthetic-source",))

        return bind_host_public_memory(
            self.ledger, integrity_key=KEY,
            current_grant=lambda: self.permission["grant"],
            current_authority_revision=lambda: self.permission["authority_revision"],
            approve_record=record_policy,
            now_seconds=lambda: 1_000_000)

    def test_host_grant_builds_usable_public_state_without_ledger_writes(self):
        provider = self.broker()
        head = self.ledger.current_head
        state, key, revision = provider()
        self.assertEqual(head, self.ledger.current_head)
        self.assertEqual(32, len(key))
        self.assertNotEqual(key, KEY)  # secret is grant-bound, not direct root key
        self.assertEqual(revision, 13)
        self.assertEqual("ledger:" + head, state["source_id"])
        self.assertEqual(["work-1"], [r["record_id"] for r in state["records"]])
        self.assertEqual("DATA_NOT_INSTRUCTION", state["records"][0]["instruction_trust"])
        self.assertEqual([("work-1", 1)], self.seen_records)
        with FakeLocal(answer=response(model="vera:local")) as server:
            output = io.StringIO()
            args = ["--endpoint", server.url, "--model", "vera:local",
                    "--model-digest", "b" * 64, "--prompt", "Cold-start test"]
            with redirect_stdout(output):
                self.assertEqual(0, local_session.main(args, live_public_provider=provider))
            self.assertIn("VALIDATED_NOT_EXECUTED", output.getvalue())
            self.assertEqual([], server.requests)

    def test_revoked_denied_expired_and_scoped_grants_fail_closed(self):
        provider = self.broker()
        self.permission["grant"] = None
        with self.assertRaisesRegex(CompositionRejected, "revoked"):
            provider()
        self.permission["grant"] = replace(self.grant, expires_at_unix=1_000_000)
        with self.assertRaisesRegex(CompositionRejected, "expired"):
            provider()
        self.permission["grant"] = replace(self.grant, expires_at_unix=1_004_000)
        with self.assertRaisesRegex(CompositionRejected, "expired"):
            provider()
        self.permission["grant"] = replace(self.grant, identity_id="not-vera")
        with self.assertRaisesRegex(CompositionRejected, "scope mismatch"):
            provider()
        self.permission["grant"] = self.grant
        self.permission["allow_record"] = False
        with self.assertRaisesRegex(CompositionRejected, "host rejected"):
            provider()

    def test_revocation_during_projection_is_detected(self):
        callbacks = 0

        def changing_grant():
            nonlocal callbacks
            callbacks += 1
            return self.grant if callbacks == 1 else None

        provider = bind_host_public_memory(
            self.ledger, integrity_key=KEY,
            current_grant=changing_grant,
            current_authority_revision=lambda: 10,
            approve_record=lambda record, grant: record.record_id == "work-1",
            now_seconds=lambda: 1_000_000)
        with self.assertRaisesRegex(CompositionRejected, "revoked"):
            provider()
        self.assertEqual(2, callbacks)

    def test_changed_approval_epoch_during_projection_is_detected(self):
        callbacks = 0

        def changing_grant():
            nonlocal callbacks
            callbacks += 1
            return replace(self.grant, approval_epoch=callbacks)

        provider = bind_host_public_memory(
            self.ledger, integrity_key=KEY,
            current_grant=changing_grant,
            current_authority_revision=lambda: 10,
            approve_record=lambda record, grant: True,
            now_seconds=lambda: 1_000_000)
        with self.assertRaisesRegex(CompositionRejected, "changed during projection"):
            provider()

    def test_host_authority_revision_required_and_type_checked(self):
        with self.assertRaisesRegex(CompositionRejected, "authority revision"):
            bind_host_public_memory(
                self.ledger, integrity_key=KEY,
                current_grant=lambda: self.grant,
                approve_record=lambda _record, _grant: True,
                now_seconds=lambda: 1_000_000)
        provider = self.broker()
        for bad in (None, True, -1, 2**64, "10"):
            with self.subTest(bad=bad):
                self.permission["authority_revision"] = bad
                with self.assertRaisesRegex(CompositionRejected, "authority revision"):
                    provider()

    def test_host_authority_revision_changes_during_projection_are_refused(self):
        def changing_policy(_record, _grant):
            self.permission["authority_revision"] += 1
            return True

        provider = bind_host_public_memory(
            self.ledger, integrity_key=KEY,
            current_grant=lambda: self.permission["grant"],
            current_authority_revision=lambda: self.permission["authority_revision"],
            approve_record=changing_policy, now_seconds=lambda: 1_000_000)
        with self.assertRaisesRegex(CompositionRejected, "changed during projection"):
            provider()

    def test_host_authority_revision_rollback_is_refused_after_prior_observation(self):
        provider = self.broker()
        provider()
        self.permission["authority_revision"] = 9
        with self.assertRaisesRegex(CompositionRejected, "rollback"):
            provider()

    def test_mutable_record_ids_list_is_rejected_before_callback_can_change_it(self):
        # A frozen dataclass only freezes the reference, not a nested list.
        mutable_ids = ["work-1"]
        invalid_grant = replace(self.grant, record_ids=mutable_ids)
        record_approval_calls = 0

        def hostile_policy(record, grant):
            nonlocal record_approval_calls
            record_approval_calls += 1
            mutable_ids.append("private-future")
            return True

        provider = bind_host_public_memory(
            self.ledger, integrity_key=KEY,
            current_grant=lambda: invalid_grant,
            current_authority_revision=lambda: 10,
            approve_record=hostile_policy,
            now_seconds=lambda: 1_000_000)
        with self.assertRaisesRegex(CompositionRejected, "immutable and exact"):
            provider()
        self.assertEqual(["work-1"], mutable_ids)
        self.assertEqual(0, record_approval_calls)

    def test_same_object_field_mutation_during_projection_is_detected(self):
        # Even a deliberately hostile Python callback that circumvents the
        # frozen dataclass via object.__setattr__ cannot rely on `grant == grant`.
        grant = self.grant

        def hostile_policy(record, grant_used):
            object.__setattr__(grant_used, "approval_epoch", 2)
            return True

        provider = bind_host_public_memory(
            self.ledger, integrity_key=KEY,
            current_grant=lambda: grant,
            current_authority_revision=lambda: 10,
            approve_record=hostile_policy,
            now_seconds=lambda: 1_000_000)
        with self.assertRaisesRegex(CompositionRejected, "changed during projection"):
            provider()
        self.assertEqual(2, grant.approval_epoch)

    def test_epoch_change_during_model_call_withholds_output_even_if_memory_identical(self):
        provider = self.broker()
        initial_state = provider()[0]

        with FakeLocal(answer=response(model="vera:local", text="Withhold on regrant.")) as server:
            original_execute = local_session.loopback.execute

            def revoke_and_regrant(request, **kwargs):
                result = original_execute(request, **kwargs)
                # Content, public record IDs, ledger head and revision unchanged;
                # only the externally governed authorization generation moved.
                self.permission["grant"] = replace(self.grant, approval_epoch=2)
                return result

            from unittest.mock import patch
            errors, output = io.StringIO(), io.StringIO()
            args = ["--endpoint", server.url, "--model", "vera:local",
                    "--model-digest", "b" * 64, "--prompt", "One approved input",
                    "--execute", "--host-idle-confirmed"]
            with patch.object(local_session.loopback, "execute", side_effect=revoke_and_regrant), \
                    redirect_stdout(output), redirect_stderr(errors):
                self.assertEqual(2, local_session.main(args, live_public_provider=provider))
            self.assertEqual(1, len(server.requests))
            self.assertNotIn("Withhold on regrant", output.getvalue())
            self.assertIn("post-inference", errors.getvalue())
        self.assertEqual(initial_state["records"], provider()[0]["records"])
        self.assertNotEqual(initial_state["hmac_sha256"], provider()[0]["hmac_sha256"])

    def test_same_epoch_regrant_with_advanced_authority_revision_withholds_output(self):
        provider = self.broker()
        initial_state = provider()[0]
        with FakeLocal(answer=response(model="vera:local", text="Do not show after ABA.")) as server:
            original_execute = local_session.loopback.execute

            def revoke_then_regrant_identical_epoch(request, **kwargs):
                result = original_execute(request, **kwargs)
                self.permission["grant"] = None
                self.permission["authority_revision"] += 1
                self.permission["grant"] = self.grant  # identical epoch, IDs, expiry, head
                return result

            from unittest.mock import patch
            errors, output = io.StringIO(), io.StringIO()
            args = ["--endpoint", server.url, "--model", "vera:local",
                    "--model-digest", "b" * 64, "--prompt", "Approved public turn",
                    "--execute", "--host-idle-confirmed"]
            with patch.object(local_session.loopback, "execute",
                              side_effect=revoke_then_regrant_identical_epoch), \
                    redirect_stdout(output), redirect_stderr(errors):
                self.assertEqual(2, local_session.main(args, live_public_provider=provider))
            self.assertEqual(1, len(server.requests))
            self.assertNotIn("Do not show after ABA", output.getvalue())
            self.assertIn("post-inference", errors.getvalue())
        self.assertEqual(initial_state["records"], provider()[0]["records"])
        self.assertNotEqual(initial_state["hmac_sha256"], provider()[0]["hmac_sha256"])

    def test_private_memory_cannot_be_projected_by_a_host_grant(self):
        self.ledger.admit(AdmissionRequest(
            record_id="private-1", text="Private secret excluded from inference.",
            memory_class=MemoryClass.WORKING_PROJECT,
            source_actor="synthetic", authority_ref="synthetic-approved",
            privacy_ref="PRIVATE", provenance_refs=("synthetic-source",),
            operation_id="private-op", project_id="vera-mono",
            governed_identity_id="vera"), expected_head=self.grant.ledger_head)
        self.permission["grant"] = replace(
            self.grant, ledger_head=self.ledger.current_head,
            revision=14, approval_epoch=2, record_ids=("private-1",))
        with self.assertRaisesRegex(CompositionRejected, "stored privacy class"):
            self.broker()()

    def test_stale_external_head_is_refused_even_with_record_approval(self):
        self.ledger.admit(AdmissionRequest(
            record_id="work-2", text="New project milestone.",
            memory_class=MemoryClass.WORKING_PROJECT,
            source_actor="synthetic", authority_ref="synthetic-approved",
            privacy_ref="PUBLIC", provenance_refs=("synthetic-source",),
            operation_id="new-op", project_id="vera-mono",
            governed_identity_id="vera"), expected_head=self.grant.ledger_head)
        with self.assertRaisesRegex(CompositionRejected, "head drift"):
            self.broker()()

    def test_approval_exception_not_leaked_to_local_session(self):
        def sensitive_record_policy(record, grant):
            raise RuntimeError("secret-policy-internal-details")

        provider = bind_host_public_memory(
            self.ledger, integrity_key=KEY,
            current_grant=lambda: self.grant,
            current_authority_revision=lambda: 10,
            approve_record=sensitive_record_policy,
            now_seconds=lambda: 1_000_000)
        errors = io.StringIO()
        args = ["--endpoint", "http://127.0.0.1:11434/v1", "--model", "vera:local",
                "--model-digest", "b" * 64, "--prompt", "Do not contact model"]
        with redirect_stderr(errors):
            self.assertEqual(2, local_session.main(args, live_public_provider=provider))
        self.assertNotIn("secret-policy", errors.getvalue())
        self.assertIn("record policy unavailable", errors.getvalue())

    def test_new_ledger_instance_rehydrates_and_rechecks_host_grant(self):
        # The new object models a fresh process reopening the already-admitted
        # durable ledger. The broker itself does not persist chat or admission.
        first = self.broker()()[0]
        self.ledger = MemoryLedger(self.folder / "memory.sqlite", project_id="vera-mono", identity_id="vera")
        second = self.broker()()[0]
        self.assertEqual(first, second)
        self.permission["grant"] = None
        with self.assertRaisesRegex(CompositionRejected, "revoked"):
            self.broker()()


if __name__ == "__main__":
    unittest.main()
