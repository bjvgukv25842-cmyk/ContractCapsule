# Task 4 report — bounded Docker reference execution

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
