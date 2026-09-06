# M4 Services Review Repair Checkpoint

The independent review at73f99ae identified three P1 blockers; its original
report and reproducer are preserved in research/module-reports. The main agent
implemented the bounded M4 repairs while the integration worker owned disjoint
compiler/session/manifest files. No M3 source/helper was changed.

Actual initial focused RED: 8 failed, consisting of seven true boundary
failures (four foreign-source edges, one partial-clone implicit-fetch attempt,
two locator/source-map mismatches) and one fixture assumption error. The latter
modified both locator and approval-bound map; real M3 correctly rejected it
before M4, so it is not counted as an M4 bypass. It was removed from the native
M4 rejection parameterization, and separate pure legacy-anchor coverage added.

Repairs: graph explicit declaration sources are restricted to actual declaring
payload/capsule and exact release; consumer lock selection follows that owner.
New M4 git_evidence.py sanitizes Git env, disables lazy fetch/replacement and all
transports for every object query, without touching M3 ingestion. Git locator
must agree with present approved x-source-map and exact deterministic source
anchor. Absent-map legacy Git still verifies its stable anchor. No published
data is rewritten or re-signed to resolve a mismatch.

Focused service review regressions9PASS; combined original graph/evidence suite
74PASS before extra owner-release/legacy-anchor additions. Full worktree suite
including ongoing compiler integration742PASS in27.87s; full Mypy70 and all4
complexity PASS. Original reviewer has not yet re-reviewed this repair; final
independent audit remains necessary. No M4 author exit, M5 or empirical results.

One SIM117 new-test lint issue was mechanically corrected. Diagnostic-only
transport prohibition prevented external traffic even on RED; fixed regression
also checks no fetch subprocess and no Git object-cache mutation. The source
publication tests use genuine collector/approval/loader/permit/Registry.
