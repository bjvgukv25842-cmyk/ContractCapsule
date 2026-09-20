# M6 Agent Adapters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Expose the existing CCS-2.1 compiler, validator, twin runner, and swap controller through a narrow Skill/MCP/adapter boundary without moving capsule facts or authorization into the adapter layer.

**Architecture:** The MCP gateway is a dependency-free JSON-RPC/stdio facade over explicitly injected core services. `AgentAdapter` implementations own only process invocation, preflight metadata, and usage-event parsing; they receive a compiled view and never receive publication authority. A pre-tool hook is a fail-closed gate that accepts a signed view/receipt envelope and blocks configured high-risk tools unless the envelope is current and valid.

**Tech Stack:** Python 3.12, Pydantic 2, existing CCS-2.1 models/services, `subprocess`, JSONL, pytest, Ruff, Mypy, SQLite/CAS through injected core services. No new network plugin, search provider, or automatic package download.

**Spec:** `docs/spec/CCS-2.1.md`, frozen execution plan M6 section, accepted `docs/adr/0005-m5-executable-contracts-and-swap.md`.

## Global Constraints

- Capsule payloads, permissions, compilation, activation, and rollback remain in core/MCP services; adapters and the Skill contain no live capsule data.
- Adapter subprocesses are non-interactive, bounded, and fail closed on missing binaries, malformed JSON, non-zero exits, timeouts, or missing version metadata.
- MCP methods return stable structured error codes and never expose raw subprocess stderr, secrets, or internal tracebacks.
- Hook decisions are deny-by-default for configured high-risk tool classes and never perform activation or irreversible effects.
- Codex and Claude calls are integration seams only; no external agent run or formal experiment is claimed by M6 unit/integration tests.
- The frozen CCS-2.1 and execution-plan files, eight core schemas, dependency lock, and M5 source remain unchanged.

## Dependency Graph

`adapter models/protocol` -> `Codex/Claude process adapters` -> `MCP facade` ->
`pre-tool hook` -> `vertical-slice contract tests` -> `M6 audit/report`.

## Task List

### Task 1: Adapter Contract and Safe Process Runner

**Files:**
- Create: `src/contractcapsule/adapters/base.py`
- Create: `tests/unit/test_agent_adapters.py`

**Interfaces:**
- `AgentMetadata(agent: str, version: str, model: str, capabilities: tuple[str, ...])`.
- `AgentTask(task_id: str, prompt: str, cwd: Path, timeout_seconds: float)`.
- `UsageRecord(input_tokens: int | None, output_tokens: int | None, raw_digest: str)`.
- `AgentRun(metadata: AgentMetadata, exit_code: int, stdout: bytes, stderr_digest: str, usage: UsageRecord | None)`.
- `AgentAdapter.preflight() -> AgentMetadata`.
- `AgentAdapter.run(task: AgentTask, view: CompiledView, workspace: Path) -> AgentRun`.
- `AgentAdapter.parse_usage(raw_events: Path) -> UsageRecord`.

- [ ] Write failing tests for strict metadata, bounded subprocess execution, malformed JSON, non-zero exit, missing binary, and secret-free error projection.
- [ ] Implement a private `run_bounded` helper using `subprocess.run` with an explicit argv list, timeout, captured output, and normalized errors.
- [ ] Make models frozen and validate non-negative usage and absolute workspace boundaries.
- [ ] Run `uv run --locked --offline pytest tests/unit/test_agent_adapters.py -v` and commit.

### Task 2: Codex and Claude Adapters

**Files:**
- Create: `src/contractcapsule/adapters/codex.py`
- Create: `src/contractcapsule/adapters/claude.py`
- Modify: `src/contractcapsule/adapters/__init__.py`
- Extend: `tests/unit/test_agent_adapters.py`

**Interfaces:**
- `CodexAdapter(binary: str = "codex", timeout_seconds: float = 300.0)`.
- `ClaudeAdapter(binary: str = "claude", timeout_seconds: float = 300.0)`.
- Codex argv: `codex exec --ephemeral --json -- <prompt>`.
- Claude argv: `claude --bare -p <prompt> --output-format json`.

- [ ] Add RED tests with fake executable scripts for exact argv, preflight version parsing, JSONL usage parsing, output truncation, and failure redaction.
- [ ] Implement adapters by composing Task 1's runner; no shell string interpolation and no inherited environment secrets beyond an explicit allowlist.
- [ ] Reject event streams without a stable agent version/model and reject duplicate or negative usage fields.
- [ ] Run adapter unit tests, Ruff, and Mypy; commit.

### Checkpoint A: Process Boundary

- [ ] Both adapters pass deterministic fake-executable tests.
- [ ] No adapter test contacts a real external agent service.
- [ ] `uv run --locked --offline pytest tests/unit/test_agent_adapters.py -v` passes.

### Task 3: MCP JSON-RPC Gateway

**Files:**
- Create: `src/contractcapsule/mcp/server.py`
- Create: `src/contractcapsule/mcp/__init__.py`
- Create: `tests/integration/test_mcp_tools.py`

**Interfaces:**
- `MCPService(registry, compiler, evidence, swap, authorizer)` with explicit dependencies.
- `handle_request(service, request: Mapping[str, object]) -> dict[str, object]`.
- Methods: `discover_capsules`, `compile_view`, `expand_evidence`, `compare_capsules`, `activate_capsule`, `rollback_capsule`.
- Error shape: `{"jsonrpc":"2.0","id":...,"error":{"code":"...","message":"..."}}`.

- [ ] Write failing integration tests for method schemas, unknown methods, malformed JSON-RPC, permission denial, compile-view replay identity, evidence reauthorization, and activation/rollback delegation.
- [ ] Implement strict request parsing with Pydantic/core validators; return only public projections and stable blocker codes.
- [ ] Ensure live capsule bytes and approval keys never enter adapter/Skill payloads; activation and rollback require the existing `SwapController`.
- [ ] Run MCP integration tests and commit.

### Task 4: Agent Skill and Pre-tool Hook

**Files:**
- Create: `skills/contract-capsule/SKILL.md`
- Create: `.codex/hooks/pre_tool_use.py`
- Create: `tests/integration/test_agent_adapters.py` (hook cases)

**Interfaces:**
- Hook input: one JSON object from stdin containing `tool_name`, `risk_class`, `view_receipt`, and `operation_id`.
- Hook output: `{"decision":"allow"}` or `{"decision":"deny","code":"..."}`.
- High-risk classes: `shell`, `filesystem_write`, `network`, `external_side_effect`.

- [ ] Write RED tests for absent envelope, malformed signature, expired receipt, wrong operation, low-risk allow, and high-risk deny.
- [ ] Implement a pure verifier using injected key/clock and no filesystem mutation; never print raw input back.
- [ ] Keep the Skill metadata concise and instruct it to call MCP methods rather than embedding capsule data.
- [ ] Run hook/adapter integration tests and commit.

### Task 5: M6 Vertical-Slice Wiring and Exit Evidence

**Files:**
- Extend: `tests/integration/test_mcp_tools.py`
- Extend: `tests/integration/test_agent_adapters.py`
- Create: `research/module-reports/M6-2026-09-20-implementation.md`
- Modify: `research/decision-log.md`, `research/claim-evidence-matrix.md`, `research/ai-usage-ledger.jsonl`

- [ ] Exercise one local deterministic fixture through discover -> compile -> expand -> adapter preflight/run using a fake executable -> hook decision -> existing M5 activation/rollback delegation.
- [ ] Verify unauthorized calls never reach the adapter, malformed adapter output is denied, and immutable capsule bytes/digests remain unchanged.
- [ ] Run the frozen M6 command, full regression, formal fixtures, Ruff default/no-ignore, complexity default/no-ignore, Mypy, lock/hash/schema/build/ledger checks, and `git diff --check`.
- [ ] Request a read-only independent audit of the exact committed candidate and preserve any failing mutation or rejected finding.
- [ ] Record engineering evidence only; stop before M7 and before formal experiments.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Real Codex/Claude binaries unavailable | Medium | Fake executable contract tests; preflight fails closed; no experiment claim |
| MCP protocol drift | High | Keep a narrow JSON-RPC method/error contract and test exact projections |
| Adapter receives unauthorized capsule data | High | Inject only `CompiledView`; assert denied calls occur before adapter invocation |
| Hook bypass or malformed receipt | High | Verify signed envelope, expiry, operation and risk class; deny by default |
| New dependency or network access | Medium | Dependency-free gateway and offline lock/build checks |

## Exit Criteria

M6 is technically complete only when both adapters, all six MCP methods, the
Skill metadata, and the high-risk hook pass the frozen integration command and
full regression, with an independent read-only PASS. No M7 implementation or
formal experiment is started in this plan.
