# Mini-Vera: source-level suppression of unsupported durable-memory claims

Date: 2026-11-14. Parent: thebrazenbeard/vera-mono OPEN DRAFT PR #233, pinned HEAD `66b43bbde83f08596f885f1870a0ae622f14a93a`. Source-only isolated VN1 branch `bt2/mini-vera-volatile-claim-guard-20261114`. **Not** installed, merged, or weight-trained.

## Reproduced problem

In an earlier actual CPU-only 4B dialogue pilot using parent PR #232's sealed package, the full governed prompt told an operator: "This update is recorded in the persistent context." That claim was unsupported: `local_session.py` keeps at most two exchange pairs in volatile RAM; it has no persistent write operation. The full prompt also truncated three of four replies. PR #233 changed only the owned managed 4B launcher's default to the already-existing shorter prompt. Prompt choice cannot prevent all such hallucinations.

## Implemented boundary

`tools/mini_vera/local_session.py` now checks **model-produced text after local inference and post-inference public-source approval, but before ALL output formatting and before volatile history admission**. A deliberately narrow deterministic pattern finds affirmative assertions of completed persistent/permanent/long-term/durable writes to memory, context or state. In the matched case, no model text is displayed or emitted as structured output, volatile conversation history is cleared, the operator gets an explicit host-side stderr notice, one-shot CLI returns exit 2, and interactive chat may continue without replaying the claim. The check makes no persistent write itself and grants no external tools.

The guard is an output-boundary consistency check, **not** proof that the neural model understands memory. It does not infer intent or audit other processes. It does not detect all paraphrases, indirect promises ("I will remember forever"), euphemisms, or context-dependent lies. It may withhold a benign quotation containing the exact affirmative phrase. Neither true memory nor verifiable learning is added. Avoid promoting this to a general hallucination detector.

## Executed targeted red/green tests (synthetic offline fake loopback)

The initial three tests FAILED against the parent with **three assertion failures, exit 1**:
- exact observed false claim on one-shot must not display and must return 2;
- "I've saved that to my permanent memory" interactive first reply must not enter second request history;
- "This correction has been saved to long-term memory" must not leak into JSONL structured output.

After the minimal guard, three targeted tests PASSED. A hostile fourth claim, "I saved your new fictional ship name to my permanent memory", initially FAILED (exit 1), exposing an unsupported object phrase and bare first-person "I saved"; the guard was corrected and all local-session integration tests passed (**20 tests, exit 0**). An additional truncated-reply case checks that even incomplete false assertions are withheld; negative truthful case "I did not save this to persistent memory" remains visible. All are source-level deterministic tests with fake HTTP responses, not genuine model calls. No new 4B inference or external independent rater is claimed. Full VN1 Python3.13 Mini-Vera regression was executed **472 tests, 17 skipped, zero failures, exit 0**, 118.649 seconds unittest time (119.882 seconds shell time), offGit log at `C:\\Temp\\MiniVeraGGUFHauhau_20261114_One\\vn1-mini-vera-memory-claim-guard-full-20261114.log`, SHA-256 `afbc95b5953ed7733f96a639d072fb3a72d419669cab241a8ad33903ffc7db5a`. The log preserves a nonfatal, preexisting Windows fake-HTTP teardown `ConnectionAbortedError [WinError 10053]`; it did not fail an assertion. Additional Python3.13 optimized `-O` focused tests (local_session and managed 4B job containment) **33 tests PASS, exit 0**, offGit log SHA-256 `a8ce59c59f41e1f34e56ab3fc2110e1d4b4c07f7d32bad7c31cb8a152a872193`. Green test suite evidence remains SOURCE/TEST, not model qualification or a completed real-world memory write.

## Effect and remaining limits

Only the source branch's `local_session.py`, focused tests and this evidence note change. Original PR #233 package, model blob, shared Ollama service, Lappy's processes, training checkpoints and memory stores are unchanged. This guard applies to the existing local shell's output boundary, including both compact and full dialogue modes; it cannot be treated as model-behavior qualification. Any future persistent-memory writer needs a separate explicit host receipt and source/effect authority, rather than model text as evidence.
