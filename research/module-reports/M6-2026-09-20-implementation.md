# M6 Agent Adapters and Boundary Implementation

Date: 2026-09-20 (Asia/Shanghai)

## Scope and status

This report records the M6 implementation candidate on branch
`codex/m6-agent-adapters`. The work exposes the existing CCS-2.1 compiler,
evidence resolver, and M5 swap boundary through narrow MCP and agent seams. It
does not move capsule authority into an adapter, add live capsule data to the
Skill, or start a benchmark experiment.

The exact technical candidate is `4396115abb5d909d3ed6001bca07908f706f93fa`.
The independent read-only audit of that exact commit is **PASS**. The frozen
G1 real-agent run remains outstanding: installed CLI version strings are not a
model/version freeze, and no approved real-agent execution or
`experiments/configs/agents.yaml` record exists.

## Delivered modules

- `src/contractcapsule/adapters/base.py` defines frozen metadata/task/usage
  models, a bounded non-interactive process runner, JSONL event validation,
  output truncation, environment allowlisting, and stable non-disclosing
  errors.
- `src/contractcapsule/adapters/codex.py` and `claude.py` implement the exact
  frozen argv forms and preflight/version/usage checks.
- `src/contractcapsule/mcp/server.py` and `mcp/__init__.py` provide a
  dependency-free JSON-RPC/stdio facade for `discover_capsules`, `compile_view`,
  `expand_evidence`, `compare_capsules`, `activate_capsule`, and
  `rollback_capsule`. Registry references are revalidated before compilation.
- `src/contractcapsule/adapters/hook.py` and `.codex/hooks/pre_tool_use.py`
  implement a fail-closed signed view/contract receipt check for high-risk
  tools. `skills/contract-capsule/SKILL.md` contains only invocation guidance;
  it contains no capsule payload or approval key.
- `tests/integration/test_m6_vertical_slice.py` drives a local published
  fixture through discovery, compilation, evidence expansion, a fake Codex
  process, the pre-tool hook, and a real M5 `RuntimeStore`/`SwapController`
  ticket activation and rollback. The old binding is verified after rollback.

## Security and correctness evidence

- Adapter stdout and stderr are drained through bounded readers. Exceeding
  `MAX_EVENT_BYTES` terminates the child and returns `ADAPTER_OUTPUT_LIMIT`;
  both streams have regression coverage. Errors never include raw stderr,
  prompts, executable paths, or environment values.
- Unauthorized MCP requests are rejected before compiler delegation. Only
  validated `PublishedCapsule` references enter `CompileRequest`; public
  projections exclude approval keys and capsule payload internals.
- High-risk Hook requests deny missing, malformed, expired, tampered, or
  operation-mismatched receipts. Low-risk reads remain receipt-free.
- The vertical slice uses the actual M5 ticket signature, generation check,
  durable activation receipt, rollback ticket, and restored generation; no
  adapter can set the active pointer directly.

## Verification

| Check | Result |
|---|---|
| Frozen M6 command (`test_mcp_tools.py` + `test_agent_adapters.py`) | 12 passed |
| Adapter unit tests plus vertical slice | 14 passed |
| Full repository regression | 1073 passed |
| Formal fixtures | 30 passed |
| Frozen/schema parity checks | 47 passed |
| Ruff ordinary and `--no-respect-gitignore` | passed |
| C901/PLR0911/PLR0912/PLR0915 ordinary and no-ignore | passed |
| Mypy | 78 source files, passed |
| `uv lock --check --offline` | passed, 46 packages |
| View Manifest schema rebuild | passed |
| Offline wheel build and required resource presence | passed |
| Frozen CCS-2.1 SHA-256 | `aaddaa8def8df1ef2efbe4f9487de0ba86a60ae5aed8955ca76f5e070fa01e5c` |
| Frozen execution-plan SHA-256 | `7c1feebb36776c09de5c0ba5462540072374b9902d8e04d405585a8efb8659c0` |
| `git diff --check` and clean worktree | passed |

The two date-sensitive M5 fixtures that had expired under the current date
were made explicit-clock tests; production expiry behavior was not changed.

## Independent audit

The read-only reviewer audited exact commit `4396115` in a separate copy and
returned **PASS**. The review specifically rechecked the prior output-limit
finding (bounded stdout/stderr reads), the real SwapController vertical path,
MCP error projections, adapter secret isolation, complexity scans, and frozen
file identity. No unresolved code finding remains.

## Research boundary and remaining gate

These are engineering and safety-boundary results only. No TER/PIP/BSR,
cross-agent superiority, token-cost comparison, or formal RQ result is
claimed. G1 is not passed: real Codex and Claude executions and an approved
model/version freeze in `experiments/configs/agents.yaml` have not been run.
The author M6 exit decision remains separate from this technical PASS.

M7 has not started.

## Commit map

- `b636044` — bounded Codex/Claude adapters and contract tests.
- `e8b57fb` — strict dependency-free MCP JSON-RPC facade.
- `2cf3728` — deterministic vertical slice and date-stable regressions.
- `3381e27` — bounded output enforcement and real SwapController path.
- `4396115` — behavior-preserving bounded-runner complexity split.
