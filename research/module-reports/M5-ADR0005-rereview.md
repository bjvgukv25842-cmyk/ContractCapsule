# Independent M5 Proposal Rereview

Verdict: **READY FOR AUTHOR APPROVAL** for the exact proposal identified below.
All four findings from the original document review are addressed coherently.
No new blocking issue was found in the revised areas or their immediate
interactions. This is a bounded document-review verdict, not author approval
or evidence that the proposed implementation works.

## Exact Review Subject

- Date: 2026-09-09.
- Revised commit: `2842a13ddc3e1bb29479017a50e4eae5ad6f239b`.
- Previous reviewed commit: `198616e57fe8b2a2ca701c97701086ebe3a546aa`.
- M5 branch base: `3bcdbc638de4c10e30fc7dee666e2517450bf1f5`.
- Independent physical archive:
  `/private/tmp/contractcapsule-m5-adr-rereview.FnuNvV`.
- ADR: `docs/adr/0005-m5-executable-contracts-and-swap.md`.
- ADR SHA-256:
  `da92462f397a82a6d5c2a2320b6ab98280f5af69edc538ed09ac6533e3115687`.
- Plan: `docs/superpowers/plans/2026-09-09-m5-validation-swap-execution-plan.md`.
- Plan SHA-256:
  `afaf6ebd8d8edc2c16afcff222c5389111e984e3cc22749def15e27deee26b83`.

All line anchors below refer to the revised commit, not a moving worktree HEAD.

## Finding Disposition

| Original ID | Disposition | Revised anchors |
|---|---|---|
| M5-ADR-R1 [P1] | Addressed | ADR 332-342; plan 181-185 |
| M5-ADR-R2 [P1] | Addressed | ADR 62-97, 153-171, 198-202; plan 48-49, 100-101, 125-128 |
| M5-ADR-R3 [P1] | Addressed | ADR 72-78, 173-196; plan 48-49, 132-135 |
| M5-ADR-R4 [P2] | Addressed | ADR 153-171, 217-229; plan 100-104 |

R1: The approval predicate now explicitly uses effective high/critical risk OR
the contract flag. An execution-subject approval cannot substitute. The
activation subject binds the prepared evidence/request/scope and old generation,
excludes its own envelope to avoid recursion, and is rechecked for expiry and
revocation inside the commit transaction. Independent irreversible-action
controls are retained. The plan names flag/risk mismatch, execution-only and
late-revocation tests.

R2: Strict phase-discriminated bindings separate pre/post expectations from a
single pair expectation. Both initial-state precondition sets must pass before
either executor starts; static checks are explicitly final-state checks, and
initial-source tests belong in preconditions. Post checks follow verified
termination, pair checks follow both final states, and phase/snapshot identity
is included in authoritative records. The planned repairable-precondition
negative test directly covers the original failure scenario.

R3: Every untrusted behavioral subject probe now requires its own restricted
container. The host orchestrates only predeclared probes and supplies captured
observations to the checker. Closed artifact subsets and per-stage visible
mounts distinguish executor, probe and checker material; a mixed entry point,
whole mixed-package mount or undeclared helper is not an allowed shortcut.
Subject processes receive neither checker material nor its result descriptors,
and trusted checker captures bind the exact container/phase. Planned sentinel,
helper-access and result-channel forgery tests match the original finding.

R4: S0 is a complete verified source tree; both final states are complete trees
after all writers terminate. Both source-relative deltas enforce scope, so
identical forbidden edits cannot disappear in a pairwise comparison. The
old/new delta remains separate relational evidence. Deleted/untracked files,
entry types and modes are included; bookkeeping remains outside subject trees.
A differential check runs once on the exact triple and binds both run IDs,
both final digests, S0 and repetition. Its single pair expectation no longer
requires invented per-state differential results. The plan names the requested
identical-edit, deletion, creation, mode and swapped-operand tests.

## Author Decision Still Required

The proposed source-relative scope rule is deliberately conservative: even an
identical out-of-scope change in both runs blocks. The revised ADR expressly
puts acceptance of that interpretation in the author's exact-text decision.
This review finds it coherent; it does not make that author decision.

ADR lines 5-10 and 371-373 still mark the document PROPOSED and prohibit semantic
implementation until the separate author approval. Neither this verdict nor
module-start authorization approves M5 exit, M6, formal experiments or a new
schedule. No frozen baseline or existing schema is changed by this proposal.

## Independent Checks and Limits

- Read the full revised ADR and plan from a fresh physical git archive and
  reviewed the entire exact-commit diff against the original proposal.
- Rechecked the original findings against each changed requirement and its
  corresponding planned negative test. Applied the code-review skill's scoped
  correctness, architecture and security checks.
- Exact previous-to-revised diff: only the two proposal documents, 110
  insertions and 28 deletions. `git diff --check` exited 0.
- Exact M5-base-to-revised name-only diff also contains only those two docs;
  no implementation, tests, schemas, dependencies or frozen files changed.
- Fresh archive spec SHA-256 remains
  `aaddaa8def8df1ef2efbe4f9487de0ba86a60ae5aed8955ca76f5e070fa01e5c`.
- Fresh archive frozen-plan SHA-256 remains
  `7c1feebb36776c09de5c0ba5462540072374b9902d8e04d405585a8efb8659c0`.
- Original report remains unchanged at
  `/private/tmp/contractcapsule-m5-adr-review.iU3JIg/preimplementation-review.md`,
  freshly verified SHA-256
  `834c7e7ad3572b4c6a7ea1838270042c7b322dfa25f36c74a631c7b1c8f42e89`.

No Docker process or test suite was run, and no controller verification was
relabelled as independent evidence. No repository/governance/index/branch
writes or subagent dispatch occurred. Only this report was authored outside
the repository. Enforcement of these requirements, fault-injection outcomes,
resource controls and actual swap safety remain future implementation-review
and runtime-test obligations after author approval.
