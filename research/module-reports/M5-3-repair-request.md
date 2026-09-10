# M5-3-R1: Paired Container Identity Consistency

Status: pending itemized author repair approval. Date:2026-09-10.
Independent Task3 spec/quality verdict: REQUEST CHANGES.
Exact technical target:20cb819c19c6c4c6edf632ba1d6d21bc0e53fffd.

## Confirmed Defect

At validate/behavior.py:157 and:199, container identities are checked within
individual run/capture records but not across the complete old/new/checker
roles of one pair. Authenticated synthetic host records that reuse an old
executor container for the new executor or for a pair checker yield valid
authenticated differential reports. The reproduction uses nonoverlapping
executor timestamps, so it is not an impossible concurrent-use artifact.

This is a P2 consistency-validation defect in the evaluator. It does not show
actual Docker escape or an untrusted caller signing records. Actual Docker
isolation belongs to Task4; the existing capture identities already allow
Task3 to reject this contradiction with the accepted separate-container design.

Independent report:M5-3-independent-review.md, SHA256
d9608cd6c1c70e14c93d53a15b7ce3803520944cd76d9215e3d7eafd5037fdf7.
Executed reviewer source:M5-3-review-diagnostic.py.txt. The controller independently
reran it against unchanged technical bytes and confirmed actual AssertionError,
exit1; output:M5-3-review-confirmation.log. The distinct-container positive
control passed. No code repair has been performed.

## Proposed Authorized Work Upon Approval

Repair ID: **M5-3-R1**.

1. Add focused failing regressions for reused old/new executor identity and
   pair checker/probe identity overlapping either run, including sequential
   timestamps and a distinct-container positive control.
2. In behavior.py validate disjoint container IDs across both authenticated
   RunEvidence values and the complete paired check/probe collection. Apply
   the same validation when verifying a persisted differential/group report.
3. Preserve all separate TER/PIP/BSR counters, snapshot/role/time/check binding,
   repeat behavior, report authentication and negative records. Do not impose
   a new global uniqueness policy across different repetitions or groups.
4. Run focused regression plus cumulative928originalnodes and new cases,
   Ruff/Mypy/complexity/lock/frozen checks. Mutate the new pair guard to prove
   the regression catches actual bad acceptance, then independently rereview.
5. Only after Task3 PASS continue already-authorized Tasks4-7 in order.

Expected technical scope: validate/behavior.py and test_behavior_contract.py.
No schema, public model, dependency, M1-M4, Docker, pointer or approval-policy
change is needed on present evidence. Any new blocking finding beyond this
scope remains subject to the author's existing itemized repair rule.

## Current Execution State

M5-1 andM5-2 have independent spec/quality PASS. M5-3 implementation exists,
with71new/928cumulative tests passing, but its independent task review is not
passed. Tasks4-7 remain unstarted. These are engineering test counts, not
formal experimental results. M0-M4 remain5/12approved modules; no M5 exit orM6.

The author asked for no intermediate reasoning or reports until completion;
the only reason to pause now is the previously chosen itemized approval gate
and the derived plan's instruction: "New blocking findings require itemized
repair approval." No skill-derived extra permission is being invented.
