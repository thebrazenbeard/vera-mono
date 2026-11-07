# Natural-input withheld-dialogue experiment: source-only contract

`tools/mini_vera/withheld_dialogue.py` adds a separate experimental track from
the single-turn JSON-envelope ablation. The model receives natural user
questions and the *same* public source records in three treatment arms:
`bare_natural`, `minimal_natural`, and `governed_natural`. The last is the
governed composer's **system instructions** with natural user text; it is not
the exact production composer request format. The generated assistant replies
are fed back only into their own arm's subsequent turns, enabling qualitative
within-session correction/coherence tests but introducing history differences.
Any truncated (`finish_reason=length`) response invalidates the whole trial
before it can be replayed as dialogue history. The output reservations remain
explicitly incomplete if any local response fails validation.
Aborted/truncated trials must be counted separately in future qualification;
scoring only complete trials would select on non-truncation and bias results.
For controlled invalid/truncated replies, the failed receipt records exact
observed HTTP **attempts** (not falsely claimed completions), a reason code,
and the failed masked label; the arm mapping remains in the private receipt.
Likewise, a valid but long first-turn model response can make a later replay
request exceed the 32 KiB input budget. Once any call has occurred, this is a
`FOLLOWUP_HISTORY_EXCEEDS_BOUND` aborted trial: the attempted-call count and
private masked label are retained, and no partial transcript is scored.
Unexpected crashes can still leave the honest `UNKNOWN_IF_INTERRUPTED` marker.

An independent human evaluator controls a case JSON stored **outside Git**:

```json
{
  "schema": "MINI_VERA_HUMAN_WITHHELD_DIALOGUE_V1",
  "case_id": "PRIVATE-UNGUESSABLE-CASE-ID",
  "rights": {
    "origin": "HUMAN_AUTHORED_OPERATOR_ASSERTED",
    "permitted_use": "WITHHELD_EVALUATION_ONLY",
    "training_use": "PROHIBITED",
    "custody": "INDEPENDENT_EVALUATOR_OPERATOR_ASSERTED"
  },
  "turns": [
    {"kind": "query", "user_text": "<independent human-authored question>"},
    {"kind": "correction", "user_text": "<human-authored correction after an initial answer>"}
  ]
}
```

The placeholders are **not** a real evaluation case. The source composer's
first synthetic turn must exactly match the case's first question; later turns
may query, contradict, or correct, and a correction is mandatory. Maximum
three turns and nine opt-in local requests. The parser rejects training-use
claims and non-loopback endpoints. No desired responses, secret solutions,
training examples, scoring rubric answers, or actual withheld cases ship with
the repository. The operator's rights and independence attestations are
**not cryptographically or independently established** by the parser.

Example dry-run (zero HTTP calls):

```powershell
python tools/mini_vera/withheld_dialogue.py --request C:\temp\synthetic-composer.json --scenario C:\private\withheld-case.json --endpoint http://127.0.0.1:11434/v1
```

Explicit opt-in additionally needs `--execute --host-idle-confirmed`,
`--rater-sheet` and `--private-key`, pointing to two separate existing,
writable directories. Their files are reserved before calls and left as
incomplete receipts on failure; final replacements and readback are checked.
Windows file mode `0o600` is **not** an NTFS permission attestation. A host
operator must protect the private mapping path with appropriate ACLs.

The external human rater gets an A/B/C transcript with the task and common
source evidence, but not the arm mapping or latency. The separately held key
contains SHA-256 bindings and declared model identity (never resident-weight
proof), along with each turn's exact masked HTTP call order to reconstruct
warmup/position effects. Response style can still reveal treatment. Score only after all
independent ratings are finished, and keep the rating sheet/cases private.
**A fixed correction may be true for one arm's generated reply and false for
another.** Score correction *appropriateness against each arm's actual prior
answer*, including warranted resistance to false correction; independently
pre-register case-specific criteria. Never reward automatic capitulation.
Small synthetic fake-server tests are not a representative semantic trial.

Cold restart, protected memory admission, source-base weight identity,
rights provenance, actual model quality, and behavioral qualification are
explicitly **not** established by this harness.
