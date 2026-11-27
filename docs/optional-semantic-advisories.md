# Optional semantic advisories

These two opt-in local CLI commands evaluate only the JSON you explicitly send.
They do not intercept `chat` or `advise`, discover omitted claims, authenticate
receipts, grant approvals, or execute a proposed route. No automatic chat-wide
coverage is provided. A host must deliberately select and invoke an assessment
and independently decide what to do with it.

Every successful envelope **and nested result** carries:

```json
{"source_advisory": true, "executed": false, "verified": false,
 "authority": "NONE", "evidence_origin": "CALLER_SUPPLIED_UNVERIFIED"}
```

These labels describe the advisory, not a security guarantee about arbitrary
installed Python. The adapters do not install packages or invoke shell, network,
or execution transports. Imported packages nevertheless execute in-process:
module initializers and replacement implementations can access the host. Python
stdout/stderr suppression is best-effort hygiene, not a sandbox or independent
resource limit. Review and trust the exact package bytes before exposing them to
the CLI. Do not send credentials or sensitive evidence unnecessarily.

## Supply packages separately, only with permission

Vera Mono has no mandatory dependency, automatic download, or vendored copy of
either implementation. `claim-assess` lazily imports `humility.runtime`;
`opportunities` lazily imports `freerowcochkar.opportunities`, after validating
input. The distribution names are `humility-research` and `freerowcochkar`.
Do not assume similarly named public package-index projects are these sources.

For a permitted private, noncommercial evaluation, an operator can review an
exact local source checkout, preserve its notices, and separately install that
checkout into a dedicated environment. Use an already available Python 3.12+
environment with the required build/runtime dependencies; the following is an
**operator action**, not something the adapter performs or this document claims
has happened:

```sh
# Only after source/license review and permission for this private use:
/path/to/private-venv/bin/python -m pip install --no-index --no-deps --no-build-isolation /path/to/reviewed/lou-pole
```

This command disables index lookup, dependency installation, and build-isolation
provisioning; required build/runtime dependencies must already exist. Review
the source tree, build configuration, and provenance too: installing or importing
an untrusted package can run code. No automatic source pinning, signature check,
provider trust provisioning, or installation verification is implemented here.

Lou-pole's `LICENSE` is source-available proprietary, not an open-source license.
Its limited noncommercial private evaluation/research/interoperability permission
is not permission for commercial use, redistribution, or hosted deployment.
Consult its exact `LICENSE` and `COMMERCIAL_LICENSE.md`; obtain separate written
permission where required. The reviewed humility checkout had no root license
file establishing a general installation/distribution grant: clarify permission
with the owner before installing or using it beyond the explicitly authorized
source evaluation. Package metadata or source visibility is not a license.
Nothing here grants commercial authorization for either package or Vera Mono.

For authorized source evaluation only, an operator may instead expose the
reviewed humility checkout root and lou-pole `src` directory on a process-local
`PYTHONPATH`. This executes source directly; it is **not installation evidence**
and retains exactly the same trust and permission requirements. Keep dependency
caches read-only and disable bytecode creation when checking source examples.

## Explicit stdin JSON

The examples assume the `vera-mono` entry point and the separately trusted,
permitted optional package are available in the selected environment. Equivalently
use `python -m vera_core.cli` with that environment. These are local stdin filters:
provide EOF and apply host-owned time/resource isolation if needed. There is no
stdin deadline or independent process sandbox.

### Assess a declared claim

```sh
vera-mono claim-assess <<'JSON'
{
  "claim": {
    "claim_id": "example-1",
    "subject_ref": "example@revision-1",
    "proposition": "The focused test passed at this exact revision",
    "required_classes": ["TEST"]
  },
  "receipts": []
}
JSON
```

With the reviewed humility source this returns `result.disposition=UNVERIFIED`:
there is no declared TEST receipt. Other dispositions are `SUPPORTED` and
`CONTRADICTED`. `SUPPORTED` only means the component found the required declared
evidence classes; it is not authenticated proof. Claim fingerprints bind declared
receipt scope to the full claim, not issuer identity or truth.

A receipt has exactly `receipt_id`, `claim_id`, `subject_ref`, `source_group`,
`kind`, `outcome` (`PASS`/`FAIL`), and `claim_digest` (64 lowercase hexadecimal
characters). Use the exact full-claim fingerprint from the reviewed public API,
never invent a digest or rewrite a mismatched receipt to fit. Claim
`required_classes` and receipt `kind` accept `DOC`, `DEP_METADATA`,
`SOURCE_INSPECTION`, `TEST`, `BUILD`, `INSTALL`, `REAL_SYSTEM_PROBE`, and
`FORMAL_VERIFY`. These are caller declarations, not performed checks.

### Plan a caller-declared opportunity

```sh
vera-mono opportunities <<'JSON'
{
  "goal": "reviewed",
  "initial_capabilities": [],
  "allowed_effects": ["read"],
  "cost_ceiling": 0,
  "actions": [{
    "id": "inspect",
    "requires": [],
    "provides": ["reviewed"],
    "effects": ["read"],
    "cost": 0,
    "required_approvals": ["review-permission"],
    "provenance": "caller-example"
  }]
}
JSON
```

With the reviewed lou-pole source this returns `result.status=NEEDS_APPROVAL`,
`action_ids=["inspect"]`, `missing_approvals=["review-permission"]`, and
`total_cost=0`. No inspection occurs. `granted_approvals`, if supplied, is still
unverified caller data, never real authorization. `AVAILABLE` means a route
within the supplied model, not verified feasibility or permission. `NO_ROUTE`
means no route was found under that model; `INCOMPLETE_UNKNOWN` preserves a
bounded-search limitation and must not be treated as proof no route exists.

Both `cost_ceiling` and each action `cost` must be integer `0` (omitted action
cost defaults to `0`). Positive/negative amounts, floats, and booleans are
rejected. **$0 is asserted, not a price quote or verified operating cost.**
Capabilities, allowed effects, approvals, action provenance, and failures are
also caller assertions. A route is not an `AuthorizationEnvelope`, `TaskPacket`,
or dispatch request. Do not use it to bypass `runtime_cohesion` admission or any
protected-effect gate.

## Bounds and safe absence

Input is one strict JSON document of at most 65,536 UTF-8 bytes. Unknown or
duplicate keys, nonfinite numbers, invalid types, and invalid schemas are
rejected before optional imports. Lists contain at most 64 entries; identifiers
are nonempty and at most 128 characters, propositions 4,096, provenance 512.
`max_steps` is an integer from 1 to 32 (default 16). Serialized output is also
bounded to 65,536 bytes. These bounds are not a package security boundary.

With valid input and a missing optional package, exit status is 2, stdout is
empty, and stderr is one of:

```text
vera-mono: OPTIONAL_ADVISORY_UNAVAILABLE: humility.runtime
vera-mono: OPTIONAL_ADVISORY_UNAVAILABLE: freerowcochkar.opportunities
```

An `ImportError` while loading the optional module, including a missing or
incompatible internal dependency, also produces the unavailable diagnostic.
Invalid input gives `vera-mono: INVALID_ADVISORY_INPUT: bounded strict JSON required`;
other import or assessment failures give
`vera-mono: OPTIONAL_ADVISORY_FAILED: no assessment completed` (exit 2).
An interrupted advisory gives
`vera-mono: OPTIONAL_ADVISORY_INTERRUPTED: no assessment completed` (exit 130).
Ordinary Python errors/prints are sanitized; malicious descriptor writes or
process/host effects are outside this in-process hygiene boundary. Absence does
not trigger installation or change normal CLI behavior.

## Evidence and memory boundaries

| Evidence | What it establishes here | What it does not establish |
| --- | --- | --- |
| SOURCE / SOURCE_INSPECTION | Reviewed code and exact Git revision | Installation or live behavior |
| TEST | Stated checks passed for exact sources in the stated test environment | Production qualification or authenticated caller receipts |
| INSTALL | Separately verified package presence/content in a named environment | Route selection or runtime consumption |
| RUNTIME / REAL_SYSTEM_PROBE | Separately observed exact live consumer/subject | Truth beyond that observation, or effect authority |

This feature supplies no INSTALL or live-runtime qualification receipt. A local
CLI test with checkout paths is TEST, not proof of deployed integration. None of
these labels establishes consciousness, identity, or subjective experience.

No canonical memory/currentness admission is added. LLM-authored or caller-supplied
receipts remain unverified, including those labeled `SUPPORTED`. This local CLI
cannot alter ChatGPT-hosted Shared or Project-only memory, change ChatGPT's
memory settings, or install a response gate in hosted chats. Those are separate
hosted product surfaces; neither optional module nor this adapter controls them.
