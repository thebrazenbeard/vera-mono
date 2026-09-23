# Vera Unbound R10A0 — Semantic Responsibility Audit R10

Status: **FROZEN SOURCE AUDIT / ONE-0070 REPAIRS STRUCTURALLY BOUND**

coordination_id: `VERA-BEHAVIOR-AUDIT-20260905`
round_id: `R10`
integration_base: `main@3a0f0fcb8db842bb4641959bfbfdb0737136b28d`
predecessor_evidence: R6 failed review; R7/R8 failed self-review; R9 failed blind review at `c449e1eb96825af4245c3edcc923fc6f5ad35f0e`.

R10 preserves the accepted semantic responsibility set while structurally correcting all four `one-0070` findings before registry/manifest/native/publication binding.

| Responsibility / finding | R10 owner/test | Disposition |
|---|---|---|
| Vera admission + identity/state separation | full owner §1; ADMIT-* | preserved |
| negative admission test on non-Vera/pre-admission subject | `Q-ADMISSION-NEG`; QUAL-ROUTE-MATRIX | corrected from R9 |
| R4 `ID-ADMIT-1` negative route | manifest exception -> Q-ADMISSION-NEG | corrected from R9 |
| freshness is evidence ceiling, not categorical negation | full owner §1; native; FRESHNESS-EVIDENCE-1 | corrected from R9 |
| publication-root direction | full owner §4; native; PUB-ROOT-1 | corrected from R9 |
| SSC-04 two-fresh-terminal pair contract | SSC mapping + paired_execution_units + SSC-04-PAIR-1 | corrected from R9 |
| exact proposition/referent/correction | full owner §3; R4 BUG/REL | preserved |
| authority/protected-effect gates | full owner §2; R4 CAD/LIVE | preserved |
| exact release owner consistency | OWNER-CONSISTENCY-1/CROSS-BIND-1 | preserved |
| clean mergeable branch | CLEAN-BASE-1 | preserved |
| Bus exact topology route `bus/vera-v2` | registry BUS_TOPOLOGY_OWNER; ROUTE-* | preserved |
| CENTER SAVE-only owner/scope | CENTER_SAVE; CENTER-* | preserved |
| R9B0 dual-store + ORIGINAL verification | full owner §7; R9B0-VERIFY-1 | preserved |
| generic steering preserves task | full owner §5; STEER-FRAME-1 | preserved |
| R3 SSC-01..10 | R3 basis + R10 mapping | preserved |
| predecessor release-specific supplements as R10 corpora | PREDECESSOR-SUPPLEMENT-NONEXEC-1 | prohibited |
| predecessor review result transfer | PREDECESSOR-REVIEW-CEILING-1 | prohibited |
| route applicability + intermittent 5/5 | R10 qualification manifest | frozen |
| noncircular publication binding | PUB-ROOT-1/PUB-RECEIPT-1 | strengthened |
| source integration != runtime/acceptance | SOURCE-INTEGRATED-FAILED-1 | preserved |
| recovery quarantine/currentness | REC_RECOVERY + R4 | preserved |
| live concurrency/no blind retry | LIVE_CONCURRENCY | preserved |
| privacy/domain firewalls | full owner §§8,11 | preserved |
| rollback honesty | full owner §11 + rollback subject | preserved |
| recognizable independent Vera behavior | full owner §13 + PRES profile | preserved |
| completion/action truth | full owner §13 + CAD execution | preserved |

Normative R10 qualification is exactly R4 hostile + R3 SSC basis through R10 SSC mapping + R10 successor-native supplement. R6/R7/R8/R9 candidate/review artifacts may be retrieved as external evidence by immutable locator only and are excluded from R10 candidate core unless a later explicit release changes that fact.

Any later unmapped responsibility change, admitted/negative route contradiction, pair-contract weakening, publication-direction regression, or cross-binding mismatch is a candidate defect. Published R10 bytes are never patched in place; correction creates a new immutable successor.
