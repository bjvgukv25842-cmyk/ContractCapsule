# M5-4B authenticated Docker twin orchestration

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
Precondition, revocation/expiry, malformed execution, current permission,
resource failure, replay/restart/idempotence, source object rehash and failed
manifest persistence are explicit negative evidence. No external network target
is contacted.

Verification before independent review: Task4-focused suite `69 passed in
150.80s`; stage/source/attempt suite `31 passed in 131.95s`; full repository
after M5-4A repair `979 passed in 84.52s`; changed-source Ruff and Mypy pass;
frozen hashes remain exact. The implementation worker later hit provider 429
after committing; files and tests are intact. This is not Task4 acceptance:
complete independent review remains required. M5-5/6/7, activation, rollback,
formal experiments and M6 are unstarted.
