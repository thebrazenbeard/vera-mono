"""Host-bound public-memory broker: source tests, not an installed host policy."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import sqlite3
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
            revision=13, record_ids=("work-1",),
            record_digests=(("work-1", self.ledger.read("work-1").record_digest),),
            approval_epoch=1,
            authority_revision=10,
            expires_at_unix=1_000_600)
        self.permission = {"grant": self.grant, "allow_record": True,
                           "authority_revision": 10}
        self.seen_records = []
        self.host_floor = -1

    def atomic_host_floor(self, revision):
        # Synthetic host custody retained across newly created broker instances.
        # Production must supply a separately authenticated, durable atomic CAS.
        self.host_floor = max(self.host_floor, revision)
        return self.host_floor

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
            atomic_host_revision_floor=self.atomic_host_floor,
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
            atomic_host_revision_floor=self.atomic_host_floor,
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
            atomic_host_revision_floor=self.atomic_host_floor,
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

    def test_host_durable_floor_required_and_invalid_attestation_rejected(self):
        with self.assertRaisesRegex(CompositionRejected, "atomic durable authority floor required"):
            bind_host_public_memory(
                self.ledger, integrity_key=KEY,
                current_grant=lambda: self.grant,
                current_authority_revision=lambda: 10,
                approve_record=lambda _record, _grant: True,
                now_seconds=lambda: 1_000_000)
        for bad in (None, True, -1, 2**64, "10", 9, 11):
            with self.subTest(bad=bad):
                provider = bind_host_public_memory(
                    self.ledger, integrity_key=KEY,
                    current_grant=lambda: self.grant,
                    current_authority_revision=lambda: 10,
                    atomic_host_revision_floor=lambda _: bad,
                    approve_record=lambda _record, _grant: True,
                    now_seconds=lambda: 1_000_000)
                with self.assertRaisesRegex(CompositionRejected, "durable authority floor|rollback"):
                    provider()

    def test_host_authority_revision_changes_during_projection_are_refused(self):
        def changing_policy(_record, _grant):
            self.permission["authority_revision"] += 1
            self.permission["grant"] = replace(
                self.grant, authority_revision=self.permission["authority_revision"])
            return True

        provider = bind_host_public_memory(
            self.ledger, integrity_key=KEY,
            current_grant=lambda: self.permission["grant"],
            current_authority_revision=lambda: self.permission["authority_revision"],
            atomic_host_revision_floor=self.atomic_host_floor,
            approve_record=changing_policy, now_seconds=lambda: 1_000_000)
        with self.assertRaisesRegex(CompositionRejected, "changed during projection"):
            provider()

    def test_host_authority_revision_rollback_is_refused_after_prior_observation(self):
        provider = self.broker()
        provider()
        self.permission["authority_revision"] = 9
        with self.assertRaisesRegex(CompositionRejected, "rollback"):
            provider()

    def test_broker_recreation_must_not_reaccept_an_older_host_revision(self):
        # A fresh broker object is equivalent to restarting the Python process:
        # an in-process max starts at -1 and cannot protect the new process.
        prior_process = self.broker()
        prior_process()
        self.permission["authority_revision"] = 11
        self.permission["grant"] = replace(self.grant, authority_revision=11)
        prior_process()
        self.permission["authority_revision"] = 10
        self.permission["grant"] = self.grant
        with self.assertRaisesRegex(CompositionRejected, "rollback"):
            self.broker()()

    def test_revocation_observation_must_durably_pin_new_revision_before_refusal(self):
        # A revoked/absent grant is still evidence of a newer host authority
        # revision. Dropping it before the atomic floor allows a cold broker
        # to resurrect a revision-10 grant after revision 11 was observed.
        self.broker()()
        self.permission["authority_revision"] = 11
        self.permission["grant"] = None
        with self.assertRaisesRegex(CompositionRejected, "revoked"):
            self.broker()()
        self.assertEqual(11, self.host_floor)
        self.permission["authority_revision"] = 10
        self.permission["grant"] = self.grant
        with self.assertRaisesRegex(CompositionRejected, "rollback"):
            self.broker()()

    def test_expired_grant_observation_still_durably_pins_new_revision(self):
        self.broker()()
        self.permission["authority_revision"] = 11
        self.permission["grant"] = replace(
            self.grant, authority_revision=11, expires_at_unix=1_000_000)
        with self.assertRaisesRegex(CompositionRejected, "expired"):
            self.broker()()
        self.assertEqual(11, self.host_floor)
        self.permission["authority_revision"] = 10
        self.permission["grant"] = self.grant
        with self.assertRaisesRegex(CompositionRejected, "rollback"):
            self.broker()()

    def test_host_owned_floor_survives_discarded_broker_and_store_reopen(self):
        # The following SQLite table is a *synthetic host custody fixture*, not
        # an authorization provider installed in Vera. Distinct connections
        # model the protected state surviving independent process lifetimes.
        floor_path = self.folder / "host-floor-test.sqlite"

        def open_atomic_floor():
            connection = sqlite3.connect(floor_path)
            connection.execute(
                "CREATE TABLE IF NOT EXISTS authority_floor ("
                "id INTEGER PRIMARY KEY CHECK (id = 1), revision INTEGER NOT NULL)")

            def advance(revision):
                connection.execute("BEGIN IMMEDIATE")
                try:
                    connection.execute(
                        "INSERT INTO authority_floor (id, revision) VALUES (1, ?) "
                        "ON CONFLICT(id) DO UPDATE SET revision = "
                        "max(authority_floor.revision, excluded.revision)",
                        (revision,))
                    floor = connection.execute(
                        "SELECT revision FROM authority_floor WHERE id = 1").fetchone()[0]
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
                return floor

            return connection, advance

        first_connection, first_floor = open_atomic_floor()
        try:
            provider = bind_host_public_memory(
                self.ledger, integrity_key=KEY,
                current_grant=lambda: self.permission["grant"],
                current_authority_revision=lambda: self.permission["authority_revision"],
                atomic_host_revision_floor=first_floor,
                approve_record=lambda record, _grant: record.record_id == "work-1",
                now_seconds=lambda: 1_000_000)
            provider()
            self.permission["authority_revision"] = 11
            self.permission["grant"] = replace(self.grant, authority_revision=11)
            provider()
        finally:
            first_connection.close()

        # Reopen the durable fixture as a distinct host callback; the broker
        # itself has no retained Python state from the prior producer.
        second_connection, second_floor = open_atomic_floor()
        try:
            self.permission["authority_revision"] = 10
            self.permission["grant"] = self.grant
            provider_after_restart = bind_host_public_memory(
                self.ledger, integrity_key=KEY,
                current_grant=lambda: self.permission["grant"],
                current_authority_revision=lambda: self.permission["authority_revision"],
                atomic_host_revision_floor=second_floor,
                approve_record=lambda record, _grant: record.record_id == "work-1",
                now_seconds=lambda: 1_000_000)
            with self.assertRaisesRegex(CompositionRejected, "rollback"):
                provider_after_restart()
            self.permission["authority_revision"] = 12
            self.permission["grant"] = replace(self.grant, authority_revision=12)
            provider_after_restart()  # new forward revision is allowed
        finally:
            second_connection.close()

    def test_unavailable_host_floor_fails_closed_without_leaking_exception(self):
        def failed_floor(_revision):
            raise RuntimeError("host-private-persistence-location")

        provider = bind_host_public_memory(
            self.ledger, integrity_key=KEY,
            current_grant=lambda: self.grant,
            current_authority_revision=lambda: 10,
            atomic_host_revision_floor=failed_floor,
            approve_record=lambda _record, _grant: True,
            now_seconds=lambda: 1_000_000)
        with self.assertRaisesRegex(CompositionRejected, "durable authority floor unavailable") as failure:
            provider()
        self.assertNotIn("host-private", str(failure.exception))

    def test_stale_cached_grant_cannot_be_rebound_to_new_revision(self):
        # Independent host reader advanced on revoke, but cached grant issuer
        # still returns a prior authorized grant: this must fail before use.
        provider = self.broker()
        prior = provider()[0]
        self.permission["authority_revision"] = 11
        with self.assertRaisesRegex(CompositionRejected, "grant authority revision mismatch"):
            provider()
        # A newly minted decision at rev11 is usable even with the unchanged
        # PUBLIC records and approval epoch, but has a different HMAC binding.
        self.permission["grant"] = replace(self.grant, authority_revision=11)
        updated = provider()[0]
        self.assertNotEqual(prior["hmac_sha256"], updated["hmac_sha256"])

    def test_issued_revision_type_and_range_must_be_exact(self):
        for bad in (None, True, -1, 2**64, "10"):
            with self.subTest(bad=bad):
                self.permission["grant"] = replace(self.grant, authority_revision=bad)
                with self.assertRaisesRegex(CompositionRejected, "issued host grant authority revision"):
                    self.broker()()

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
            atomic_host_revision_floor=self.atomic_host_floor,
            approve_record=hostile_policy,
            now_seconds=lambda: 1_000_000)
        with self.assertRaisesRegex(CompositionRejected, "immutable and exact"):
            provider()
        self.assertEqual(["work-1"], mutable_ids)
        self.assertEqual(0, record_approval_calls)

    def test_record_digest_grant_requires_exact_immutable_ordered_pairs(self):
        issued = self.grant.record_digests[0][1]
        for invalid in (
            [],
            (("work-1", issued.upper()),),
            (("not-selected", issued),),
            (["work-1", issued],),
            (("work-1", "0" * 63),),
            (),
        ):
            with self.subTest(invalid=invalid):
                self.permission["grant"] = replace(self.grant, record_digests=invalid)
                with self.assertRaisesRegex(CompositionRejected, "immutable and exact|record digest selection"):
                    self.broker()()

    def test_grant_digest_mismatch_refuses_content_even_when_record_policy_approves(self):
        self.permission["grant"] = replace(
            self.grant, record_digests=(("work-1", "0" * 64),))
        with self.assertRaisesRegex(CompositionRejected, "selected record digest mismatch"):
            self.broker()()
        self.assertEqual([], self.seen_records)

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
            atomic_host_revision_floor=self.atomic_host_floor,
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
                self.permission["grant"] = replace(
                    self.grant, authority_revision=self.permission["authority_revision"])
                # Identical epoch/IDs/expiry/head, new host-minted authority rev.
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
            revision=14, approval_epoch=2, record_ids=("private-1",),
            record_digests=(("private-1", self.ledger.read("private-1").record_digest),))
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

    def test_stale_grant_refuses_rewritten_content_when_ledger_head_is_unchanged(self):
        # A local SQLite writer can replace the canonical row *and its digest*
        # while leaving the ledger metadata head untouched. The host reviewer
        # in this fixture is deliberately permissive, so the broker itself
        # must pin the issued record digest, not only an ID and an event head.
        old_head = self.ledger.current_head
        with sqlite3.connect(self.folder / "memory.sqlite") as db:
            raw = db.execute("SELECT payload_json FROM records WHERE record_id='work-1'").fetchone()[0]
            payload = json.loads(raw)
            payload["text"] = "Tampered row remains syntactically PUBLIC."
            from tools.mini_vera.compose import canonical
            replacement = canonical(payload)
            db.execute("UPDATE records SET payload_json=?, record_digest=? WHERE record_id='work-1'",
                       (replacement.decode("utf-8"), hashlib.sha256(replacement).hexdigest()))
            db.commit()
        self.assertEqual(old_head, self.ledger.current_head)
        with self.assertRaisesRegex(CompositionRejected, "selected record digest mismatch"):
            self.broker()()

    def test_approval_exception_not_leaked_to_local_session(self):
        def sensitive_record_policy(record, grant):
            raise RuntimeError("secret-policy-internal-details")

        provider = bind_host_public_memory(
            self.ledger, integrity_key=KEY,
            current_grant=lambda: self.grant,
            current_authority_revision=lambda: 10,
            atomic_host_revision_floor=self.atomic_host_floor,
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
