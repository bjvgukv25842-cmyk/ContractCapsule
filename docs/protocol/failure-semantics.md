# ContractCapsule M1 Failure Semantics

Status: frozen M1 protocol candidate, 2026-08-01. These semantics are governed
by CCS-2.1 and fail closed for safety, permission, evidence, dependency,
integrity, and behavioral-contract failures.

## State Rule

Let `old` be the active capsule before activation and `new` the candidate.
Every activation attempt returns a receipt, never an unstructured exception as
its only safety signal.

```text
gate success: active_after = new; activated = true
gate failure: active_after = old; activated = false; blockers != empty
```

Multiple independent failures may be retained in stable order for audit. A
fixture's primary expected blocker is exact when the fixture injects only one
failure. An exception during construction is not evidence of fail-closed
behavior unless the active-state preservation assertion also passes.

## Failure Classes

| Class | Representative blocker | Required behavior |
|---|---|---|
| Malformed or conflicting core | `MALFORMED_CAPSULE` | Exclude before ranking; preserve old active reference |
| Missing source binding | `MISSING_EVIDENCE` | Do not validate or activate |
| Integrity failure | `INTEGRITY_FAILED` | Do not rank or activate |
| Permission or scope | `UNAUTHORIZED_CAPSULE`, `OUT_OF_SCOPE` | Filter before relevance ranking |
| Freshness | `STALE_EVIDENCE` | Revalidate; current M1 decision blocks |
| Missing closure | `MISSING_MANDATORY_DEPENDENCY` | Compilation fails; no best-effort omission |
| Unresolved conflict | `UNRESOLVED_CONFLICT` | Expose the pair and block automatic activation |
| P0 fidelity or budget | `P0_NOT_EXACT`, `P0_BUDGET_OVERFLOW` | Use exact P0 or request a larger/split task |
| Closure budget | `MANDATORY_CLOSURE_BUDGET_OVERFLOW` | Preserve closure and fail; never trim dependencies |
| Interface or target mismatch | `INCOMPATIBLE_INTERFACE`, `INCOMPATIBLE_REPLACEMENT_TARGET` | Reject replacement |
| Behavioral contract | `TARGET_EFFECT_FAILED`, `PROTECTED_INVARIANT_FAILED`, `FORBIDDEN_SPILLOVER` | Reject replacement and retain negative result |
| Irreversible action | `IRREVERSIBLE_SIDE_EFFECT_UNCONTROLLED` | Require preflight, approval, or compensation |
| View tampering | `VIEW_INCONSISTENT` | Recompute and reject inconsistent metadata/content |
| Report substitution | `VALIDATION_MISMATCH`, `CANDIDATE_MISMATCH`, `TASK_MISMATCH` | Reject cross-wired or stale reports |
| Unsafe timing | `UNSAFE_ACTIVATION_BOUNDARY` | Preserve old reference until before the next action |
| Invalid rollback request | `ACTIVATION_NOT_APPLIED` | Leave active reference unchanged |

Only a purely observational telemetry outage may degrade to a local buffered
audit record under CCS-2.1. Telemetry loss never bypasses a gate above.

## Ten Frozen Executable Cases

Each row is backed by one JSON fixture. Expected state is asserted in addition
to the blocker.

| Case | Expected result | Primary blocker | Active state after attempt |
|---|---|---|---|
| Valid replacement | Activate | `NONE` | `auth-policy@2` |
| Missing mandatory dependency | Block | `MISSING_MANDATORY_DEPENDENCY` | `auth-policy@1` |
| Unresolved conflict | Block and expose conflict | `UNRESOLVED_CONFLICT` | `auth-policy@1` |
| Stale evidence | Block before ranking | `STALE_EVIDENCE` | `auth-policy@1` |
| P0 exceeds budget | Block; do not compress/drop P0 | `P0_BUDGET_OVERFLOW` | `auth-policy@1` |
| Unauthorized capsule | Block before ranking | `UNAUTHORIZED_CAPSULE` | `auth-policy@1` |
| Interface incompatible | Block before ranking/replacement | `INCOMPATIBLE_INTERFACE` | `auth-policy@1` |
| Protected invariant fails | Block and retain unfavorable result | `PROTECTED_INVARIANT_FAILED` | `auth-policy@1` |
| Safe rollback | Activate, then restore prior reference | `NONE` | `auth-policy@1` after rollback |
| Irreversible external effect without control | Block | `IRREVERSIBLE_SIDE_EFFECT_UNCONTROLLED` | `auth-policy@1` |

The inventory test requires exactly these ten fixture files. Additional tests
attack the semantics without adding frozen cases: stripped view metadata,
cleared graph failures, report reuse, task substitution, candidate-core
substitution, duplicate identities, unknown compression classes, missing
evidence, core mutation, and mid-action activation.

## Phase-Specific Semantics

### Compile

1. Check well-formedness, integrity, permission, scope, freshness, and required
   interfaces.
2. Rank only eligible capsules.
3. Select P0 and relevant atoms, then compute mandatory closure.
4. Recompute visible conflicts.
5. Enforce P0 and closure budgets.
6. Return an auditable view with blockers; never silently repair a hard
   failure by removing mandatory information.

### Validate

Validation takes the capsule cores again. It recomputes selected content,
evidence handles, closure, conflicts, exact P0, and budgets. Compiler booleans
are evidence to compare, not trusted authority. A changed field yields
`VIEW_INCONSISTENT`. The report binds the exact view, capsule identities, and
principal.

### Decide Replacement

The decision independently binds old core, new core, and full task semantics.
It checks replacement target, interfaces, TER gate, PIP gate, BSR gate, and the
irreversible-action boundary. Each failed component remains separately
observable.

### Activate

Activation checks:

- safe boundary;
- old/new candidate fingerprints;
- candidate presence in the compiled input;
- task equality between compilation and replacement decision;
- validation-view-principal binding;
- view, validation, and replacement blockers.

The transition is all-or-nothing. Any mismatch or blocker leaves `old` active.

### Roll Back

Successful activation receipts retain the old reference and can restore it.
Rollback after a blocked activation is rejected as not applied. Rollback never
claims to reverse external side effects.

## Irreversible Effects and Compensation

The safe rollback claim is deliberately narrow:

```text
recoverable: the context reference used by future agent actions
not inherently recoverable: an already completed external action
```

Preflight can prevent the action, approval can authorize its risk, and a
compensation plan can define a separate corrective action. None makes an
external effect transactionally identical to a context pointer. Experiments
must score these controls and must not label context rollback as full external
rollback.

## Audit and Research Integrity

- Every injected formal atom must retain an evidence handle.
- Valid unfavorable runs and every blocker remain in the raw record.
- Only records explicitly marked as infrastructure failures are retryable.
- Formal fixtures are synthetic falsifiers, not empirical benchmark results.
- Codex-generated cases, contracts, and interpretations require author review
  and are not benchmark ground truth.
- A later implementation that returns the correct blocker but changes the
  active reference still fails the case.

