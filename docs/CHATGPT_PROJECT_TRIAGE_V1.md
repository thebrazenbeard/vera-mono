# Native ChatGPT Project triage — V1 source candidate

Status: **synthetic-tested source only; NOT installed in ChatGPT or Lappy.**

`ingest.project_triage.triage_projects` accepts already-reviewed, privately
staged *metadata* with exact source digest, observed inventory coverage, and
explicit tri-state checks for active work, unique material, and external
references. It returns a deterministic, content-free, local-only dry-run
manifest. Every row has `delete_authorized=false`; the module exposes no delete,
archive, move, provider, import, or memory-admission operation.

## Why the separate step matters

- The existing `export_inventory` reports local file metadata; that is not a
  complete Project conversation/attachment inventory or a native Project
  access grant.
- The existing `historical_export_projection` can represent already-staged
  private records as **unverified historical evidence**; it is not a Project
  migration or current memory admission.
- A native Project configured for `PROJECT_ONLY` memory with a disabled File
  Library is explicitly protected in this V1 even when other fields look quiet.
  Those settings must not be mistaken for an ordinary exportable folder.
- `chat-communication-bus` and `deepmemorystorage` GitHub repositories are
  public. Neither is an authorized destination for personal conversations,
  relationship data, trauma narratives, source exports, or private receipt logs.

## Decision semantics

`PRESERVE` wins whenever active work, unique material, outstanding references,
or **any Project-only memory boundary** is explicitly present, regardless of
whether Library access is enabled.
`INSPECT_MISSING_EVIDENCE` retains incomplete, unknown, or unresolved target
cases. `REVIEW_FOR_CONSOLIDATION` asks for duplicate evidence and a separately
verified private custody copy. **Caller-supplied review or archive receipt strings
can never elevate a Project to retirement review.** This source-only V1 never
emits `REVIEW_FOR_RETIREMENT`. That would require a separately authenticated
verifier which does not exist in this module; deletion remains unavailable.
Any Project named as a proposed duplicate target is preserved, and duplicate
cycles are rejected: an audit must never nominate every copy for retirement.

Output rows carry deterministic ordinal references rather than repeating private
Project IDs, source hashes, duplicate target IDs or receipt strings. The private
input inventory retains exact identity correlation. Do not publish manifests.

No state is promoted to governed current Vera memory; no model training is
authorized; no actual project is modified. A separately trusted host must
verify identity, source completeness, attachments, precise refs, confidential
storage custody and receipt readback, plus irreversible-action consent, before
an exact Project deletion could even be proposed. The safe source-only triage
will remain no-delete regardless of those future decisions.

## Minimal synthetic example

```python
from ingest.project_triage import ProjectEvidence, triage_projects

source = ProjectEvidence(
    project_id="synthetic:one", source_digest="a" * 64,
    coverage="PARTIAL", active_work=None, unique_material=None,
    outstanding_references=None, memory_scope="PROJECT_ONLY",
    file_library_enabled=False,
)
assert triage_projects((source,))["records"][0]["disposition"] == "PRESERVE"
```

Run the synthetic tests with `PYTHONPATH=packages/vera_ingest/src python -m
unittest discover -s tests -p test_project_triage.py` from the monorepo root.

The exact disposition depends on caller-supplied facts and does not establish
which specific real Project should be archived or removed. Never publish live
private triage manifests, even if they contain no transcript bodies.
