# M5 Task 2 independent specification and quality review

Date: 2026-09-10. Reviewer: independent m5_2_task_review agent.

Specification verdict: PASS within the explicitly bounded Task 2 scope.
Quality verdict: PASS. No actionable blocking or nonblocking defect found.
This is not M5 exit approval, integration approval, or empirical safety evidence.

## Scope and authority

Reviewed base 31e7b49b2533a1366978ef6c272707c3812ea56d through candidate
917e702078440d9eeabad192beacf78640e7c5ab. Technical commits are c4fa931
and 917e702; intervening 90b8394 contains controller governance.
The six new technical files total 1,279 lines: validation compression (158),
evidence (63), integrity/service (310), journal (132), reports (48), and tests (568).
The supplied task-2-review.diff describes these same six entirely new files;
their tests and complete implementation were read. Existing code was read only
to resolve the named admission, rendering, handle, manifest and artifact boundaries.

Read AGENTS.md, complete CCS-2.1 and frozen execution plan, accepted ADR-0005,
Task 2 brief/report/diff and latest decision-log entries. Used the
code-review-and-quality skill; meta-skill instructions were also inspected.
The using-superpowers skill explicitly exempts dispatched subagents.
No subagents were created. No source, index, branch or governance file was edited.
Existing controller governance modifications were preserved. All review output
and synthetic diagnostic state were written only under this temporary directory.

Frozen SHA-256 values independently matched:

- CCS-2.1: aaddaa8def8df1ef2efbe4f9487de0ba86a60ae5aed8955ca76f5e070fa01e5c
- Plan: 7c1feebb36776c09de5c0ba5462540072374b9902d8e04d405585a8efb8659c0

The accepted ADR and whole-M5 authorization permit this task review without
another routine author gate. The original M5 Aug 22–24 schedule is missed;
this review grants no schedule, G1/G2/G3 or formal-experiment waiver.

## Specification assessment

1. Independent compression validation recomputes admitted core atoms, related
   P1 membership, all P0 atoms, required task atoms and root-provider membership.
   It closes both mandatory and selected sets, checks conflicts, exact
   participating capsule references and closure links. These checks precede
   the supplemental compiler replay. The self-consistent P0/P1 omission tests
   therefore test a meaningful boundary rather than merely malformed transport.

2. Native evidence is reread with current authorization and freshness, then
   independently compared to core owner, evidence IDs, full content digest,
   span, mode, admitted sibling membership and resolver version. Neutral
   rendering and complete text token accounting are reconstructed from these
   materials. Unknown expanded handles are rejected by the reused neutral
   renderer. Manifest projection is reconstructed with the independent graph,
   admission, selection and recount; its expected digest is checked directly.

3. The original request.as_of is used for reconstruction; an injected UTC
   current clock is used for separate admission checks before and after
   evaluation. Current membership/rejection changes and configuration changes
   fail closed. Successful cached report verification checks current admission
   rather than treating historical time or a signed success as renewed access.
   Failure reports withhold capsule/atom identities, scope/subject digests and
   token measurements. Invalid clocks do not fabricate a validation timestamp.

4. Binding covers full CompileRequest, expected output lock, exact
   core/signature/status projections, artifact identities, complete view bytes,
   manifest and handles, principal and configured services/policies. The
   integrity/evidence/compression method shapes are retained on a request-scoped
   composition. Public report models carry data, not credential authority.

5. RecordJournal persists actual exact bytes in additive m5_records state in
   the existing Registry database. Its HMAC binds domain, record ID, kind,
   scope, subject and payload digest; verification authenticates the stored
   payload and compares it to the supplied reference. Append-only triggers,
   fresh-instance reads, wrong keys and persisted tampering have concrete tests.
   The trusted writer and consumer-facing verifier are separate interfaces.
   Publication facts are not changed. The configured host owns the private key
   and must keep it distinct from the approval authority, as documented.

## Quality and verification assessment

Correctness, architecture, security, readability and performance were reviewed.
The implementation is proportionate to the bounded service and journal, uses
existing deterministic lower-level services without replacing M4 algorithms,
and introduces no dependency or schema expansion. The direct path's reuse of
manifest wire projection and graph/render primitives is explicitly delimited;
it does not invoke Compilation.run/select as its preservation proof.

Reviewed test evidence includes real Registry/M3 publications, source byte
corruption, current revocation/expiry, request/configuration mismatches, forged
models/manifests, missing P0/P1/provider/dependency members and actual journal
tampering. Stored implementation logs were inspected and report:

- Focused suite: 48 passed in 12.22 s, exit 0.
- Cumulative suite: 857 passed in 50.59 s, exit 0.
- Membership bypass mutant: two intended tests fail, exit 1.
- HMAC verification bypass mutant: wrong-key rejection test fails, exit 1.

These are implementation-run results, not independently rerun full-suite claims.
The implementation report also records Ruff/Mypy/complexity/lock/hash checks;
those broad checks were not rerun during this bounded review.

Three additional reviewer-authored diagnostics ran independently using the
existing virtual environment with bytecode generation disabled, exit 0:

- A lying compiler's self-consistent request/manifest claims an unavailable
  expansion handle: independent validation rejects it.
- An attacker changes persisted payload bytes and supplies a matching new
  public digest: HMAC verification still rejects it.
- A valid authenticated database row is copied under another record ID:
  signature verification rejects the copied identity.

Exact runnable diagnostic: diagnostics.py. Exact returned command output is
transcribed in diagnostics-output.txt. All fixtures/databases are external to
the repository under this report directory. No broad suite or Docker run occurred.

## Integration boundaries, not findings

- This slice provides no AgentRun, behavioral result, Docker sandbox, action
  lease, safe-boundary ticket, active pointer, activation receipt or rollback.
  Consequently it cannot yet establish that unsafe activation preserves a
  real pointer; later M5 tasks must prove that on actual durable state.
- verify_report authenticates the stored report and current scope; it is not
  fresh source/render validation or an activation credential. Consumers must
  request fresh validation immediately before execution/activation, check the
  required report kind, and bind it to the exact operation. Atomic policy and
  record verification belong in the later transactional owner as planned.
- The local HMAC design assumes a trusted host and private composition state;
  it does not protect against privileged host/key compromise or represent PKI.
- Optional selection/reason correctness uses supplemental compiler replay;
  direct preservation, evidence, rendering, cost and lock checks are separate.
- Evidence supports C1/C2/C5 and prospective RQ2/RQ3 engineering claims only;
  no benchmark ground truth, C3/C4 result or statistical safety claim follows.

There are no severity/file:line/reproducer findings to request changes for.
Proceeding to the already authorized next internal M5 task is reasonable.
未开始下一模块（M6）；本审查未执行其他 M5 子任务。
