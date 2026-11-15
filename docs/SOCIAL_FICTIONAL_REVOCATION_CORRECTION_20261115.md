# Fictional message-boundary correction: stale allowance invalidation

Date: 2026-11-15
Repository: thebrazenbeard/vera-mono
Scope: existing research-only Draft PR #214.
Source parent: b30c70cefdda06bc65774bb9831a72a8a3eecfb6.

## Proven source defect

The bounded active-state route used explicitly marked fictional user
updates to answer questions about named actor -> message-owner pairs.
It recognized literal may read or may not read as reported
fictional claims and invalidated several alternative wording patterns
without promoting those alternatives into a permission.

Two previously unhandled direct correction wordings left a stale
reported allowance active:

- Correction: Nia can no longer read Omar's messages.
- Correction: Nia is no longer allowed to read Omar's messages.

Initial source: State: Nia may read Omar's messages.
Before the change, the answer to the explicitly scoped fictional
question incorrectly remained positive.

## Test-first repair and narrow semantics

A new regression exercises both exact current-user corrections.
Both RED subcases initially returned CURRENT instead of UNRESOLVED.
The test also checks that the reversal of actor/owner and an
unrelated pair remain unchanged, the correction carries provenance
from current user turn 2, and no external effect is authorized.

The minimum production change extends the existing unsupported
message-correction recognition grammar with can no longer and
is no longer allowed to. It does not turn these new patterns
into new direct denied claims. The affected pair is invalidated,
and the source-only question receives UNKNOWN, with the literal
correction quote and turn reference. It leaves other pairs intact.

Focused GREEN (Lappy Python 3.12): 1 test and 2 subtests;
related tests GREEN: 53 tests and 33 subtests.

Fresh full Lappy Python3.12 test suite: 1264 passed, 106 skipped, 365 subtests passed, one preexisting TestVerifier collection warning, exit0, 116.91 seconds. Related source tests under Python3.12 -O: 45 passed, 20 subtests, exit0; Python3.14: 45 passed, exit0 (existing pytest-asyncio deprecations). Python3.12 compileall: exit0.

## Material challenges

> UNKNOWN after an unsupported correction is deliberately not a
> reliable proof of denial or a permission for the assistant to act.

> This only handles a small explicit grammar in a user-described
> fictional scene. Unrecognized phrasings, indirect negations,
> quotation and attribution complexities, and pronoun references
> remain outside the parser's guaranteed competence. It cannot
> generalize to actual messages, accounts, or private data.

> A current user claim is not an independently verified third-party
> consent statement. This source state grants no real access, tool
> authorization, canonical memory admission, native installation,
> or durable private preference.

Evidence class: source inspection, reproducible test-first regression,
local tests. Not independent human review, model behavior qualification
or observed deployed behavior. No paid compute.


## Cross-workstation exact-commit check

On exact committed source HEAD d1bebcc88c7f9a334ca8ab1f9c067d951514d5ae,
VN1 Windows Python3.13 and VN2 Linux Mint Python3.12 each passed
38 bounded source tests, including the two newly red-then-green
revocation cases and the entire social_active_state test class.
Each isolated runner imported the real committed social_active_state.py
source through a test-only package namespace, with no changes to
source files, credentials or native runtime.

The broader sparse-checkout tests initially failed on both workstations
at module collection because the vera_core package initializer eagerly
imports other packages. The first failure was missing portfolio_runtime
from the sparse checkout; after expanding all 12 package source roots
the next failure was uninstalled jsonschema. Tests using the exact
CLI in a subprocess and a frozen fixture also could not run in that
limited environment without those dependencies and fixture assets.

These secondary host failures are **environmental/integration gaps**,
not evidence of a parser regression. The Lappy full integrated suite
passed earlier at this commit before publication. The secondary
38-test checks only qualify the bounded module behavior and do not
establish a working native deployment or full-package compatibility
on VN1 or VN2.
