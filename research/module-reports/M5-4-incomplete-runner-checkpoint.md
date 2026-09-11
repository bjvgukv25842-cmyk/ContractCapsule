# Task 4 report — bounded Docker reference execution

Controller qualification2026-09-11: this is the incomplete worker's historical
handoff, not accepted Task4 evidence. One passing happy-path test did not verify
all named guarantees. Subsequent inspection found missing status/error handling,
code/workspace volume aliasing and no full approval/checker/attempt integration.
The worker's partial twin API accepted separate old/new program strings, which
does not fulfill the approved same-executor/context-only paired contract.
No independent review or Task4 PASS exists for e54026f..f44e8d4. The tracked
scratch report was removed from Git tracking after this preserved copy; the
scratch file remains on disk. Main resumes bounded stage service then full
Task4 orchestration, retaining all original source commits as history.

Implemented bounded Docker transport and paired execution in commit e54026f.
The runner uses fixed argv, digest locked image, no pull/network, read-only
root, UID 65534, dropped capabilities, no-new-privileges, process/CPU/memory
ceilings, and bounded streams. Subject state is held in a controller-created
size/inode-limited tmpfs volume. A fresh named subject container executes the
pinned Python entrypoint; host inspection confirms it is stopped before a
separate read-only keeper exports the complete tree. Unsafe tree entries and
limits fail closed. TwinRunner performs two independent runs and rejects reused
container identities.

Verification: docker 29.5.2; integration test 1 passed; Ruff and mypy passed.
Full contract/checker orchestration and authenticated Task 3 evidence binding
remain consumers and were not duplicated. No M6 work started.
