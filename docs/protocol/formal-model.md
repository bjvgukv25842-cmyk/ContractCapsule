# ContractCapsule M1 Formal Model

Status: frozen M1 protocol candidate, 2026-08-01. Author approval at G0 is
required before M2. This document defines falsifiable obligations; it is not a
claim that the M2-M6 production prototype or the M7-M10 empirical evidence
already exists.

## Normative Basis and Scope

- CCS-2.1 SHA-256:
  `aaddaa8def8df1ef2efbe4f9487de0ba86a60ae5aed8955ca76f5e070fa01e5c`.
- Frozen execution-plan SHA-256:
  `7c1feebb36776c09de5c0ba5462540072374b9902d8e04d405585a8efb8659c0`.
- The executable M1 reference semantics are in
  `src/contractcapsule/formal.py` and are exercised by exactly ten case
  fixtures under `tests/fixtures/formal_cases/cases/`.

M1 models one in-memory replacement decision. Content-addressed persistence,
schemas, registry state, production compilation, adapters, and durable active
pointers remain M2-M6 work. The hashes in the executable model bind objects
within a decision; they do not replace the signed integrity bundle required by
later modules.

## Domains and Frozen Interfaces

Let a capsule be the ordered seven-module product:

```python
Capsule = tuple[
    Manifest,
    set[Atom],
    set[Evidence],
    DependencyGraph,
    ReplacementContract,
    CompressionPolicy,
    IntegrityBundle,
]

compile_view(capsules, task, principal, budget, adapter) -> CompiledView
validate_view(view, capsules, principal) -> ValidationReport
can_replace(old, new, task) -> ReplacementDecision
activate(candidate, safe_boundary) -> ActivationReceipt
rollback(receipt) -> RollbackReceipt
```

The Python reference uses frozen dataclasses and `frozenset` values to realize
the tuple and set notation without permitting mutation. Define:

- `ref(C) = capsule_id(C) @ version(C)`;
- `core(C)` as the ordered seven-module value;
- `kappa(C) = SHA256(canonical(core(C)))` for decision binding;
- `T` as a task with repository, path, environment, required interfaces, and
  irreversible-action controls;
- `P` as a principal;
- `B >= 0` as a runtime-view token budget;
- `A` as an adapter identifier; and
- `active` as the reference used by the next agent action.

`kappa` is a model-level identity witness. CCS-2.1 production identity also
requires the manifest digest, lock, and integrity verification defined in the
frozen specification.

## Definition 1: Capsule Well-Formedness

`WF(C)` holds iff all of the following are true:

1. The manifest has non-empty identity and version, a valid published/active
   lifecycle, at least one repository, path prefix, and environment.
2. The integrity bundle validates.
3. Atom IDs are unique within `C`; evidence IDs are unique within `C`.
4. Each formal atom has a non-empty ID and statement, non-negative token cost,
   at least one evidence reference, and one of `P0_EXACT`, `P1_STRUCTURED`,
   `P2_EXCERPT`, `P3_SUMMARY`, or `P4_TRANSIENT`.
5. Every atom evidence reference resolves to an evidence item in `C`.
6. Every evidence item has a non-empty ID, digest, and exact source text or
   immutable source representation.
7. A P0 atom is governed by an exact, non-lossy compression policy.

For a simultaneously compiled capsule set `K`, `WF_set(K)` also requires that
the same capsule, atom, or evidence identifier never denotes conflicting
content. Conflicting duplicate identities are malformed and fail closed.

Published-core immutability is represented by frozen values in M1. Later
modules must prove that published values are content-addressed and cannot be
overwritten in storage.

## Definition 2: Evidence Preservation

For atom `a`, let `E(a)` be its evidence-reference set. For view `V`, let
`S(V)` be the selected formal atoms and `H(V)` its evidence handles.

```text
EvidencePreserved(V, K) iff
  for every a in S(V):
    E(a) is non-empty
    and E(a) is a subset of EvidenceIDs(K)
    and E(a) is a subset of H(V)
    and every referenced evidence digest is valid and fresh.
```

The source evidence remains in the immutable evidence plane. A runtime view
may carry an exact excerpt and handle, but a lossy summary never overwrites the
source. Exact source expansion and digest verification are empirical/system
obligations for M3-M5 and RQ2, not results produced by M1.

## Definition 3: Eligibility Before Ranking

`Eligible(C, T, P)` holds only after `WF(C)` and all of these gates pass:

- `P` is authorized by the manifest;
- `T.repository`, `T.path`, and `T.environment` are within capsule scope;
- evidence is fresh;
- task-required interfaces are provided; and
- no integrity or identity conflict is present.

Let `K_e = {C in K | Eligible(C, T, P)}`. Ranking is a function only of
`K_e`:

```text
Rank(K, T, P) = RankByRelevance(K_e, T)
```

No unauthorized, out-of-scope, stale, malformed, or interface-incompatible
capsule may enter the ranked set. The view records an eligibility phase before
any ranking phase so this ordering is auditable.

## Definition 4: Selection and Mandatory Dependency Closure

Let `S0` contain every eligible P0 atom plus every eligible task-relevant atom.
For mandatory edge `a requires b`, define the least fixed point:

```text
S_(i+1) = S_i union {b | a in S_i and (a requires b)}
Closure(S0) = least S_n such that S_(n+1) = S_n
```

`DependencyClosed(V)` holds iff `S(V) = Closure(S0)` and every required target
exists. A missing target or a closure that cannot fit the budget blocks
compilation. It is never treated as optional context.

## Definition 5: Conflict Visibility

For declared symmetric or directed conflict edges `G_conflict`:

```text
VisibleConflicts(V) = {(a, b) in G_conflict | a in S(V) and b in S(V)}
```

The view must record this set exactly. `VisibleConflicts(V) != empty` blocks
automatic activation. Clearing the view metadata cannot clear the conflict:
`validate_view` recomputes it from the capsule graph.

## Definition 6: P0 Preservation and Budget Safety

Let `P0(K_e)` be all P0 atoms in eligible capsules and `Exact(V)` the atoms
rendered without loss.

```text
P0Preserved(V) iff P0(K_e) is a subset of S(V) intersection Exact(V)
                     and every selected P0 policy is exact.
```

Let `cost(X)` be the deterministic token-cost estimate:

- if `cost(P0(K_e)) > B`, return `P0_BUDGET_OVERFLOW`;
- else if `cost(Closure(S0)) > B`, return
  `MANDATORY_CLOSURE_BUDGET_OVERFLOW`;
- otherwise no mandatory atom may be silently dropped or compressed.

Budget failure and P0 fidelity are separate conditions: overflow does not
mislabel exact P0 content as lossy; it simply prevents activation.

## Definition 7: View Validity

`ValidView(V, K, T, P, B, A)` is true iff:

1. the capsule, task, principal, budget, and adapter bindings match;
2. `WF_set(K)` holds;
3. eligibility preceded ranking;
4. selected atoms, rendered content, evidence handles, closure, conflicts, and
   P0 fields equal values recomputed from `K`;
5. `EvidencePreserved`, `DependencyClosed`, and `P0Preserved` hold;
6. no unresolved conflict exists;
7. neither the P0 set nor mandatory closure exceeds `B`; and
8. the validation report is bound to the exact view fingerprint.

Validation is not a trust in compiler flags. Any inconsistency yields
`VIEW_INCONSISTENT`; report reuse across a changed view yields
`VALIDATION_MISMATCH`.

## Definition 8: Interface Compatibility

For old capsule `O`, new capsule `N`, task `T`, and new replacement contract
`R_N`:

```text
InterfaceCompatible(O, N, T) iff
  R_N.replaces = ref(O)
  and provides(O) is a subset of R_N.accepts_interfaces
  and T.required_interfaces is a subset of provides(N).
```

A reference match alone is insufficient. Compatibility failure blocks both
eligibility and replacement.

## Definition 9: Measurable Replacement Correctness

For a valid run `r` with preregistered contract checks:

```text
TER_r = passed required target-effect checks / required target-effect checks
PIP_r = passed protected-invariant checks / protected-invariant checks
BSR_r = triggered forbidden-spillover checks / forbidden-spillover checks
```

Required check sets must be non-empty in CapsuleBench. At the decision gate:

```text
TargetOK(r)    iff TER_r = 1
InvariantOK(r) iff PIP_r = 1
SpilloverOK(r) iff BSR_r = 0
```

`ReplacementCorrect(O, N, T, V, r)` holds iff:

- `ValidView(V, {N}, T, P, B, A)`;
- `InterfaceCompatible(O, N, T)`;
- `TargetOK(r)`, `InvariantOK(r)`, and `SpilloverOK(r)`;
- mandatory dependencies are closed and conflicts are empty;
- every selected formal atom is traceable to immutable evidence; and
- any irreversible action has preflight, approval, or compensation.

M1 fixtures model these check results as booleans to exercise gate semantics.
The benchmark records check-level numerators and denominators so TER, PIP, and
BSR remain separately measurable. Across runs, each component is reported
separately with confidence intervals. The descriptive
`RCS = TER * PIP * (1 - BSR)` never replaces a component.

## Definition 10: Atomic Activation

An activation candidate binds `(O, N, V, validation, decision, T)` by object
fingerprints and task fingerprint. At a safe boundary:

```text
if ReplacementCorrect and every binding matches:
    active' = ref(N)
    receipt = (activated, previous=ref(O), active=ref(N))
else:
    active' = ref(O)
    receipt = (blocked, previous=ref(O), active=ref(O), blockers)
```

There is no intermediate observable state in which only part of the active
reference is changed. Reused reports, another task's decision, a different
candidate core, or activation during an action all fail closed. Durable atomic
pointer update is an M5 implementation obligation; M1 establishes the state
transition and executable counterexamples.

## Definition 11: Safe Rollback

For a successful activation receipt `q`:

```text
rollback(q).active = q.previous
rollback(q).rolled_back = true
```

For a receipt that never activated, rollback leaves the current reference
unchanged and reports `ACTIVATION_NOT_APPLIED`. A valid receipt retains the
prior immutable version, so rollback never reconstructs old context from a
lossy view.

## Definition 12: Irreversible-Side-Effect Boundary

Context rollback affects only future agent context. It does not undo an email,
payment, deployment, deletion, or other completed external effect. For a task
that can cause an irreversible action:

```text
ExternalActionControlled(T) iff
  preflight_completed(T)
  or approval_granted(T)
  or compensation_available(T).
```

If false, replacement and activation are blocked. If true, a later rollback
restores context only; the declared compensation process governs external
effects. The paper must not claim complete rollback of reality.

## Safety Properties and Falsifiers

- **No partial activation:** every blocked receipt retains `ref(O)`.
- **No report substitution:** task, view, candidate, and decision bindings must
  agree.
- **No hidden dependency or conflict:** validation recomputes both from capsule
  cores.
- **No silent P0 loss:** exact P0 is complete or compilation fails.
- **No source-free formal atom:** every selected formal atom resolves to
  evidence.
- **No uncontrolled irreversible action:** one of the three controls is
  mandatory.

The ten frozen cases and additional adversarial tests are counterexamples that
must remain executable. Passing M1 is evidence that the reference semantics
distinguish safe from unsafe decisions; it is not a mathematical proof of all
Python implementations or of stochastic agent behavior.

## Contribution and Paper Mapping

- C1: Definitions 1-12 and executable reference semantics; paper Sections 2-4.
- C2: no working production prototype evidence yet; M2-M6.
- C3: case shape informs CapsuleBench, but no approved benchmark yet; M7.
- C4: TER/PIP/BSR and paired comparisons are preregistered, but no run results
  exist; M8-M10.
- C5: frozen hashes, tests, protocol, literature verification, and AI-use
  records provide an early audit trail; the anonymous artifact remains M11.

