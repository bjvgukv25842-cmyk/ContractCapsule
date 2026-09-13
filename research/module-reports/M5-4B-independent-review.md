# M5-4B independent review — REQUEST CHANGES

Date: 2026-09-13. Native reviewer: `m5_4b_review_retry`.
Technical target: `6bdc657fa8305b6b7fa6bd38d0d30fe0f3496043`.
Base: `650fb2c`; review package was `M5-4B-review.diff`, retained losslessly as
`M5-4B-review.diff.gz` because raw unified-diff context lines contain deliberate
trailing spaces that would fail repository whitespace checks.

The following is the independent reviewer's returned assessment. Main assigned
stable repair IDs M5-4B-R1 and M5-4B-R2 in the separate repair plan. The review
did not rerun the implementation suite. Its conclusion is REQUEST CHANGES;
there is no independent Task4B PASS. The reference to an author Task4B gate
in the returned text means the established itemized repair gate here; the
plan's module exit approval remains M5, not an additional invented subtask exit.

## Returned assessment

Spec verdict: Conditionally compliant. The implementation meets the core
M5-4B obligations for same-executor/view-only composition, distinct old/new
validation services, per-stage fresh approval/revocation checks, Git-object S0
integrity, Docker isolation, authenticated Task3 records, low/high repeat
counts, HMAC-backed attempt persistence, replay, and no favorable retries.

Quality verdict: Request changes before accepting M5-4B evidence, due to two
important missing behavior-level regressions.

Important findings:

1. `tests/unit/test_twin_orchestration.py:26`
   - Impact: The source path uses `--no-replace-objects` in `source.py:28-32`,
     but no test proves a configured replacement ref cannot substitute the
     locked commit/tree. A future change could silently re-enable replacement-
     object resolution while dirty-worktree and blob-rehash tests still pass.
   - Reproduction: Create a repository with a `refs/replace/<locked-commit>`
     pointing to a different commit, then require `git_tree(..., locked_commit)`
     to return/reject based on the real object, never the replacement.
   - Fix scope: Add one source-unit regression using a real replacement ref.
     No production change appears necessary.

2. `tests/integration/test_twin_pair.py:22`
   - Impact: The required real-Docker resource failure cases are not covered
     by the supplied M5-4B tests. `DockerRunner._execute` implements timeout/
     output-limit handling at `docker_runner.py:105-123`, and `PairRunner` maps
     unavailable/uncertain stages to negative records at `twin_stages.py:87-120`,
     but neither a timeout nor output-limit orchestration outcome is exercised.
     This leaves the claimed fail-closed, retained-negative-record behavior
     unproven at the twin layer.
   - Reproduction: Use real fixture executor/check programs that respectively
     exceed `timeout_seconds` and stdout/stderr limits; assert no valid outcome,
     persisted incomplete/FAILED or UNCERTAIN record as appropriate, no rerun
     for the same attempt, and no active container is treated as a safe
     completion.
   - Fix scope: Add two real-Docker integration tests and preserve exact
     captured negative records.

No Critical findings.

New breakage: None identified from the reviewed diff. The removal of the prior
program-string facade is intentional and consistent with the task brief.

Out-of-scope observations: M5 activation, rollback, pointer state, and
ActivationApproval transaction semantics remain unimplemented, as explicitly
excluded from M5-4B. The implementation report's test-pass claims were not
independently rerun, per review instruction.

Final verdict: REQUEST CHANGES for the two missing required regressions above.
After they pass in real Docker, this change is otherwise suitable to proceed
to the author's M5-4B review gate.
