# Mini-Vera three-arm masked comparison (source and fake-server tested)

This is a **controlled prompt/runtime comparison**, not neural model creation,
identity transfer, host qualification, or an independent behavioral verdict.

The comparison accepts only a synthetic, public, single-turn request generated
by the current Mini-Vera composer and accepted by the existing strict
`loopback.validate_candidate` shape validator. **That validator cannot prove
the prompt was actually composed from authentic pinned source bytes.** Keep
source custody and identity-file digest checks outside this test seam.

### Treatments and what is controlled

| Arm (mapping stays private) | Treatment | Same across arms |
| --- | --- | --- |
| Bare | No system prompt | User turn and embedded public/untrusted project records |
| Minimal persona | Short fixed Vera characterization | Model alias, temperature=0, seed=20261106, max_tokens=128 |
| Governed composer | Existing larger source-pinned persona/provenance system text | Endpoint, single HTTP transport, no tools/memory/effects |

Different instruction lengths **are a confounder** for latency and output
quality. The source content/behavioral guidance is necessarily unequal across
treatments, but the user evidence and test turn are byte-for-byte identical.
The bare/minimal arms receive the composer's JSON user envelope rather than
a natural human utterance. This tests a system-instruction ablation, **not** an
ecologically valid bare-Qwen chat baseline; a separate natural-interface
comparison remains necessary.
This comparison does not establish neural adaptation. The apparent resident
model name is a response echo and never proves weights, source ancestry,
loaded adapters, prompt contamination, or genuine model identity. A host-side
artifact hash, selected model layer, loaded-template inspection, and process
measurement are separate prerequisites for qualification.

### Running

Create an operator-controlled **synthetic/public** composed request with the
existing Mini-Vera composer, with a human/rights-cleared prompt. Never use
private memories or withheld evaluation cases as model training data. Do not
commit actual withheld cases, gold answers, ratings, rater sheets, or the
mapping key to the repository.

Dry-run validation performs **zero** network calls:

```powershell
python tools/mini_vera/blind_compare.py --request C:\temp\synthetic-request.json --endpoint http://127.0.0.1:11434/v1
```

After a real host probe confirms resources are free, explicitly opt into three
local calls. Write the private key somewhere *not visible to the rater*:

```powershell
python tools/mini_vera/blind_compare.py --request C:\temp\synthetic-request.json --endpoint http://127.0.0.1:11434/v1 --execute --host-idle-confirmed --rater-sheet C:\temp\rater-sheet.json --private-key C:\private\mapping.json
```

These paths are examples, not attestations that such files or directories exist.
No overwrite, remote URLs, tool calls, memory admission, model weight
changes, paid compute, or service manipulation is included. The operator flag
is **not** an automated RAM/GPU qualification. The response sheet contains the
common task/evidence plus opaque `A/B/C` labels, text, response hashes and
finish reasons; latency is withheld because it can reveal treatment. The
separately stored mapping contains the arms, wall-clock latency, request hashes,
declared model alias/digest, and limitations. A single turn cannot establish
correction behavior, multi-turn coherence or cold-restart memory. Human raters must not see
the mapping until they finish independent ratings.

Do not infer victory from three outputs or one curated synthetic scenario.
For real qualification, an independent evaluator must hold enough diverse
novel cases off-repo; preregister human scoring criteria; rotate labels and
order across cases; counterbalance carryover and system prompt effects;
measure process working set, resident model hash, first token/time-to-complete
and tokens/s where supported; and analyze variance. A memory-assisted system
needs a **separate** end-to-end track from this matched evidence track.

### Evidence as of this source

- `SOURCE`: three-arm blinded-output harness with source-contract validator.
- `TEST`: fake HTTP loopback model server only; 6 synthetic tests pass locally.
- `MODEL_INFERENCE`: none observed here.
- `HUMAN_REVIEW`: none conducted here.
- `BEHAVIORAL_QUALIFICATION`: not established.
