# M6 Independent Read-Only Audit

Date: 2026-09-20 (Asia/Shanghai)

## Scope

The reviewer audited exact implementation commit
`4396115abb5d909d3ed6001bca07908f706f93fa` in an isolated read-only copy.
The governance-only follow-up commit is `0667ed4`; it changes only the AI-use
ledger timestamp and does not change the audited code.

## Verdict

**PASS** for the M6 implementation boundary. No unresolved code, security, or
correctness finding remains.

The review verified the six MCP methods, trusted Registry revalidation, public
projection redaction, adapter environment isolation, malformed-output handling,
high-risk receipt checks, and the real `RuntimeStore`/`SwapController` path in
the vertical fixture. It also checked that frozen files and the eight A-zone
schemas were unchanged.

## Findings and closure

1. **F1 — bounded subprocess output (重要):** the initial candidate used
   unbounded `capture_output`. It was replaced by bounded stdout/stderr reader
   threads, child termination on overflow, stable `ADAPTER_OUTPUT_LIMIT`, and
   two regressions covering both streams. The behavior-preserving split in
   `4396115` passes ordinary and no-ignore complexity rules.
2. **F2 — real swap path coverage:** the initial vertical test used a spy. It
   now creates a real M5 `RuntimeStore`, signs and consumes a boundary ticket,
   invokes `SwapController.activate`, reserves a rollback ticket, invokes
   `SwapController.rollback`, and asserts generation-two restoration.
3. **F3/G1 — real-provider run:** no code defect was found, but the frozen G1
   gate remains open. Fake executables are used for deterministic tests; a real
   Codex/Claude old/new task and approved `agents.yaml` model/version freeze
   have not been performed. Installed `--version` strings alone are not a
   model/version freeze. This is not reported as an experiment result.

## Reverification

- Frozen M6 command: 12 passed.
- Adapter and vertical tests: 14 passed.
- Full repository: 1073 passed.
- Ruff, complexity (C901/PLR0911/PLR0912/PLR0915), and Mypy: passed in both
  ordinary and `--no-respect-gitignore` modes where applicable.
- Frozen hashes, schema parity, lock check, wheel build, and `git diff --check`:
  passed.

No files were modified by the independent reviewer. M7 and formal experiments
remain unstarted pending the G1/author exit decision.
