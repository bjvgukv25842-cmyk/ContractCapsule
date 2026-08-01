# ContractCapsule

ContractCapsule is a research prototype for verifiable context replacement in
coding agents. The only normative design baseline is `CCS-2.1`; the frozen
execution plan controls module order, evidence requirements, and human gates.

The project is currently at M0: research governance, repository bootstrap, and
paper charter. No M1 system implementation or experiment has started.

## Frozen Baselines

- Specification: `docs/spec/CCS-2.1.md`
- Execution plan:
  `docs/superpowers/plans/2026-07-30-contract-capsule-fse-2027-execution-plan.md`

Both files are copied byte-for-byte from the retained root-level source files
and protected by `tests/unit/test_spec_lock.py`.

## Development

The project requires Python 3.12 and `uv`.

```bash
uv sync --locked
uv run pytest tests/unit/test_spec_lock.py -v
uv run ruff check .
```

Licensing and citation metadata remain pending author decisions.
