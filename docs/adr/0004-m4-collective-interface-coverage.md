# ADR-0004: M4 Collective Interface Coverage Before Ranking

## Status

**PROPOSED - AUTHOR APPROVAL REQUIRED BEFORE IMPLEMENTATION.**

Date: 2026-09-05. Module: M4. Proposed runtime profile:
`CCS-2.1-m4-collective-interfaces-v1`.

The author selected collective coverage with a prior ADR during planning,
then approved M3's exit at `4dbf484` and authorized M4 startup. Those decisions
authorize preparing this ADR, not marking its final text Accepted. M3 approval
is recorded in governance commit `9743b34168e160878b9b9e8132512c540954f511`.

Numbers 0001-0003 describe other intended topics in the frozen plan's file map;
this change does not claim those planned ADR files already exist.

## Context and Normative Boundaries

CCS-2.1 sections 6, 9, 14, 15 and 22 define composable capsules, capsule/atom
dependencies, interface compatibility, eligibility before ranking and auditable
views. Frozen M4 requires a resolver and compiler without changing core identity
or weakening any of the twelve invariants.

M1 Definition 3 in `docs/protocol/formal-model.md` and `_eligibility_blockers`
in `src/contractcapsule/formal.py` currently require:

```text
T.required_interfaces subset_of C.manifest.provides
```

for each individual capsule. That excludes two otherwise compatible capsules
that provide different required interfaces jointly. The author chose collective
coverage to support the multi-capsule M4 use case, with an explicit compatibility
record rather than silently changing M1.

This proposal adds a versioned M4 runtime-composition interpretation. It does
not edit CCS-2.1, the frozen execution plan, the approved M1 model or fixtures,
the eight A-zone schemas, existing capsule identities, or the analysis protocol.
If review identifies a conflict with the frozen normative semantics rather than
an implementation refinement, stop: this ADR alone cannot rewrite a frozen
baseline, and a separately approved versioned baseline would be required.

## Proposed Decision

### 1. Local admission is necessary, not sufficient

`eligible(capsule, task, principal)` in the new M4 resolver reports local
admission. It is not a complete view-validity or activation receipt.

Each candidate must pass Registry publication revalidation and local lifecycle,
tenant, authorization, sensitivity, repository/path/environment, validity,
freshness and interface-compatibility checks. The nominal `PublishedCapsule`
class is not proof: it is directly constructible, so Registry must supply the
authoritative record for the request's exact identity/publication projection.

Missing an unrelated task interface does not itself reject a locally admissible
capsule. Malformed declarations or an incompatible advertised version do.
For a capability family requested by the task, a capsule advertising that family
must offer at least one exact requested `/vN` interface; a capsule not advertising
that family contributes no coverage for it. Additional unrelated interfaces do
not create permissions or satisfy missing requirements.

### 2. Coverage belongs to the admitted collection

Let `K` be the supplied candidate collection, `R(T)` the exact required interface
identifiers, and `Provides(C)` the capsule's verified declarations:

```text
K_e = { C in K | LocalEligible(C, T, P) }
Coverage(K_e, T) = R(T) subset_of union(Provides(C) for C in K_e)
```

For M4, a task interface is provided by the complete capsule payload, not a
guessed atom subset. Its required membership is exactly every atom in the chosen
provider's `semantic_payload.atoms`, plus mandatory dependency closure. Every
member must be validated, individually admissible and evidence-resolvable;
denied, stale, candidate, revoked or otherwise unusable members invalidate the
provider for that requirement. A selected unrelated atom cannot stand in for
the capsule's advertised interface.

This whole-payload rule deliberately avoids inventing an interface-to-atom field
or interpreting `provides` graph edges as an undocumented fine-grained membership
map. Fine-grained membership is outside this profile and would need a new ADR.
Root interface provider units are mandatory at the task-required/P1 assembly
stage, without changing any atom's original compression class. Thus P2-P4 atoms
inside such a required unit cannot be discarded as optional background. If the
unit cannot fit the budget, compilation fails. Capsules may need to be authored
as smaller capability units; the compiler must not infer an unsafe smaller unit.

Provider choice has two distinct owners, both resolved before ranking:

- **Root task interfaces:** the input is the exact Registry-verified candidate
  collection in CompileRequest. For each exact required interface, zero usable
  providers blocks as missing, one is selected, and more than one blocks as
  ambiguous. M4 adds no request-level tie-breaker. The caller can disambiguate
  by supplying a collection containing only the intended exact provider. No
  unrelated capsule's A-zone dependency lock can make this root choice.
- **Capsule dependencies:** each requirement belongs to its consumer capsule.
  A provider must match the declared capability/release constraint AND an exact
  `(capsule_id, version, digest)` entry in that consumer's IntegrityLock.
  Zero matches blocks; multiple matches still block as ambiguous. Locks from
  other consumers cannot broaden or replace this decision. Contradictory
  selected identities (including two versions/digests for the same capsule ID)
  or declared provider conflicts block rather than merging locks or choosing
  one by relevance/order.

Discovery of an otherwise usable provider does not grant authority to ignore
missing mandatory dependency locks. Their entire reachable requirement graph
must resolve with consumer-owned locks; cycles use a terminating fixed point
and are subject to the same missing/conflict checks.

Only those usable resolved providers contribute to successful coverage. Missing,
rejected or ambiguous providers block before a ranker is called. Each successful
root requirement and consumer dependency gets its own exact provider witness
in the B-zone output manifest/lock. A unique root provider needs no preexisting
task-provider lock; it emits a new output witness. That output is not authority
for its own initial selection. Replay reconstructs the exact recorded input
collection, reauthorizes it and recomputes choices; a witness mismatch blocks.

Interface names retain `/vN` for exact matching. Requirements of
the form `capability@constraint` constrain the provider capsule's release SemVer,
not the integer N in its advertised interface name. SemVer build metadata does
not affect precedence, but the lock retains the exact published version string
and digest. Numeric shorthand is expanded to a three-component version before
comparison; supported comparisons and comma conjunctions are explicit, with
invalid constraints rejected rather than guessed.

### 3. The ordering and selection obligations remain strict

```text
Registry revalidation
-> local security/scope/freshness/interface admission
-> collection coverage and exact provider resolution
-> relevance ranking of admitted atoms only
-> selection and capsule/atom mandatory closure
-> final selected-provider, conflict, evidence and budget validation
-> compiled content plus auditable manifest
```

Coverage of the candidate pool is not sufficient for successful output. Chosen
providers' full payload memberships above must survive actual selection and
mandatory closure under the M4 assembly rules. If the compiler cannot retain
that exact required provider payload,
it blocks rather than counting an unselected capsule's metadata as coverage.
Capsule-level mandatory dependencies load the provider's whole formal payload;
atom-level dependencies use explicit referenced atoms. A required member failing
admission or budget cannot be silently dropped.

All eligible P0 atoms and task-related P1 atoms plus their mandatory closures
remain mandatory. No ranking decision can waive authorization, freshness,
evidence, dependency closure, P0/P1 budget behavior or unresolved conflicts.
Any mandatory failure yields an invalid report and empty content, not a partial
view that could be mistaken for an activation-ready result.

Rejected candidates cannot contribute providers or content, nor leak their
identifiers through rejection diagnostics: only aggregate reasons/counts are
exported for rejected objects. A denied irrelevant candidate need not poison
an otherwise valid admitted set, but denial of a necessary provider blocks.

### 4. M1 compatibility is explicit and limited

Keep M1's code, Definition 3 and thirty formal tests unchanged. Add the M4
collection definition as a separate runtime-profile supplement after approval;
do not retroactively reinterpret M1 results as multi-provider evidence.

On the common representable domain, holding all non-interface gates equal:

```text
M4PreRankInterfaceGate({C}, T) == M1InterfaceGate(C, T)
```

This compares the complete singleton pre-ranking decision, not M4's local
`eligible` return alone. A lone capsule missing a required interface is still
rejected before ranking. This is an interface-gate equivalence obligation, not
a claim that the different M1/M4 models, token counters or scope matchers are
identical in every respect.

The intentional extension is multi-capsule coverage. Future evidence must
identify the profile used, so results from the two semantics are not pooled
without disclosure. The M4 public functions live in their new resolver/compiler
modules; they do not replace the M1 reference functions in place.

## Alternatives Considered

| Alternative | Assessment |
|---|---|
| Keep every-capsule full coverage | Preserves M1 literally, but prevents complementary providers and contradicts the author's selected M4 direction |
| Union declarations before admission | Rejected: denied, stale or tampered capsules could satisfy the task on paper and influence resolution |
| Rank first, then test union | Rejected: violates the required eligibility-before-ranking order |
| Silently modify M1's existing gate | Rejected: erases the original formal baseline and makes old evidence ambiguous |
| Versioned admitted-collection coverage | Proposed: supports composition while retaining local fail-closed gates and testable singleton compatibility |

## Compatibility, Security and Research Impact

- No A-zone data migration, schema change, digest change or signature-input change.
- Whole-payload task-interface units trade token efficiency for an explicit
  sound membership boundary. They can cause additional budget failures; this
  cost must be reported, not hidden by dropping provider atoms or changing
  baselines. Fine-grained atom membership is not claimed by this profile.
- B-zone manifests carry the composition profile and provider witnesses; an
  incompatible or missing runtime-profile lock cannot be silently reused.
- Permissions and evidence are rechecked for rebuild/expansion. Reproducibility
  never authorizes use of revoked or currently unauthorized content.
- All 339 baseline tests remain; new tests prove the extension rather than
  modifying old assertions. No M5 activation or behavior contract implementation.
- C1 formal-to-runtime traceability and C2 implementation are affected. RQ1 may
  observe different token costs because complementary providers become usable;
  RQ2 must expose the chosen providers. These are prospective effects, not
  empirical results. RQ3 gates and RQ4 baseline fairness are not weakened.
- No benchmark label, formal experiment, research outcome, frozen schedule or
  submission gate is changed by accepting this runtime-composition decision.

## Required Acceptance Tests After Approval

These are planned obligations, not tests already implemented or run:

1. Singleton complete/incomplete/wrong-version/empty-required-interface cases
   match M1's interface decision with common non-interface gates held fixed.
2. Two admitted capsules providing `auth/v2` and `audit/v1` satisfy a task
   requiring both; the provider witness map names exact verified references.
3. Removing or denying either necessary provider blocks before the ranker;
   denied extra capsules do not enter indexes or leak identifiers.
4. Highest-score unauthorized providers and directly forged PublishedCapsule
   instances cannot satisfy coverage or reach the ranker.
5. Version constraints use capsule release SemVer independently of `/vN`;
   digest/version lock mismatch, incompatible versions and ambiguity block.
   An unrelated consumer's lock must not resolve a root-interface ambiguity;
   an exact dependency lock must not be replaced by another consumer's lock.
6. Dependency cycles terminate; missing required members and incompatible
   provider conflicts block; optional edges do not create mandatory coverage.
7. Post-selection provider loss, P0/P1 closure overflow or evidence failure
   returns empty content with an invalid validation report.
   Retaining one unrelated provider atom must fail when any other member of
   its whole required payload is missing; denied members invalidate the unit.
8. Input permutations yield the same provider map and canonical manifest;
   an old runtime profile cannot silently replay under the new semantics.
9. Fault injection of admission-before-coverage and final-provider preservation
   must cause the relevant persistent tests to fail.

## Approval Gate

The requested decision is acceptance or rejection of this ADR's M4 collective
coverage semantics and the stated M1 compatibility obligations. Acceptance will
be recorded separately with the ADR digest and exact commit before implementation.

Until then: document preparation and baseline verification only. No M4 runtime
model, resolver, compiler, new dependency or semantic test is implemented here.
M4's eventual technical and author exit gates remain separate. M5 is unstarted.
