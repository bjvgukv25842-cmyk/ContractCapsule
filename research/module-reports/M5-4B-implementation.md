# M5-4B authenticated Docker twin orchestration

Current verdict (2026-09-13): independent review REQUEST CHANGES for two
required regressions, M5-4B-R1/R2. See `M5-4B-independent-review.md` and
`M5-4B-repair-plan.md`. This report was reconstructed by main from recovered
committed source and test output after worker interruption; it is not the
missing worker's original final report or a Task4B completion certificate.

Implementation commit: `6bdc657`; task diff base: `650fb2c`. The unsafe
program-string twin facade is replaced by explicit trusted composition:
Task1 binding and execution approval, paired ValidationServices, current policy
checks, Git S0 snapshots, M4 view compilation plus independent Task2 reports,
restricted Docker stages, Task3 authenticated records, and HMAC-authenticated
single-attempt persistence.

The real fixture uses one deterministic executor whose only semantic input
difference is the old/new compiled view. It does not receive role labels,
expected outcomes or checker artifacts. S0 comes from the exact local Git
commit despite a dirty worktree. Low risk runs one pair; high risk runs three.
Precondition, revocation/expiry, malformed precondition output, current permission,
replay/restart/idempotence, source object rehash and failed manifest persistence
have twin-level negative tests. Resource-failure tests so far exercise the
low-level stage; independent review requires timeout/output-limit propagation
tests at the twin layer. No external network target is contacted.

Verification before independent review: Task4-focused suite `69 passed in
150.80s` (38 stage plus 31 twin/source/attempt/admission cases). Full repository
after M5-4A repair was `979 passed in 84.52s`; subsequent exact Task4B code
passes `1007 passed in 211.11s`. Ordinary/no-ignore default and complexity
Ruff, Mypy67, offline lock46 and frozen hashes pass. Both Ruff inventories
match the actual109 Python source/test files. Neither current test count is
independent reviewer execution evidence. M5-5/6/7, activation, rollback,
formal experiments and M6 remain unstarted.
