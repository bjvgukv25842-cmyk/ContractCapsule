# M5-4B command evidence summary (main, 2026-09-13)

Technical source: 6bdc657. Subsequent commits before review completion were
governance-only. This is a transcript-derived summary, not raw tool output or
an independent verification claim.

| Check | Result |
|---|---|
| `uv run --locked --offline pytest -q` | exit0,1007 passed in211.11s |
| Stage plus twin/source/attempt/admission tests | exit0,69 passed in150.80s |
| Twin/source/attempt/admission tests alone | exit0,31 passed in131.95s |
| Current ordinary and no-ignore Ruff default checks, src/tests | exit0 |
| Current ordinary and no-ignore C901/PLR0911/PLR0912/PLR0915, src/tests | exit0 |
| Ruff show-files ordinary/no-ignore vs actual filesystem `.py` inventory | 109/109/109, no missing or extra file |
| `uv run --locked --offline mypy src` | exit0,67 source files |
| `uv lock --check --offline` | exit0,46 packages |
| Frozen spec / frozen plan / accepted ADR-0005 SHA-256 | exact expected values |
| `git diff --check` on technical candidate range | exit0 |

Historical negative execution retained: an overlapping in-progress selected
run reported `1 failed,30 passed in128.98s` at
`test_current_stage_revalidates_after_clock_advance`, with an uncaught
`ApprovalError: approval rejected`. Its precise transient cause was not
established. A later isolated test passed, followed by the exact committed
31/69/1007-case runs above. None is a formal experiment or a replacement for
an unfavorable benchmark result. The earlier979 full-suite count belongs to
the Task4A repair, not to a Task4B full-suite run.

Independent review: REQUEST CHANGES for M5-4B-R1/R2; see the separate report.
No production or test repair is applied after that verdict without approval.
