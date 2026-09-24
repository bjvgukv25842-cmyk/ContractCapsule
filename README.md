# ContractCapsule

ContractCapsule is a research prototype for verifiable context replacement in
coding agents. The only normative design baseline is `CCS-2.1`; the frozen
execution plan controls module order, evidence requirements, and human gates.

The M7 engineering substrate and the M8 fail-closed readiness gate are
implemented. The CapsuleBench records remain screening candidates pending
human source and ground-truth review; no pilot observation, TER/PIP/BSR result,
or empirical RQ conclusion exists.

## Canonical Source Repository

- Repository: `https://github.com/bjvgukv25842-cmyk/ContractCapsule.git`
- Default branch: `main`
- Baseline tag (convenience pointer): `source-baseline-m8-readiness-v1`
- Frozen baseline commit:
  `e3944cb0df21b55ef9b2c1fd62896538198e2536`
- Machine-readable lock: `research/source-repository-lock.json`

The canonical project repository is distinct from the public repositories used
as CapsuleBench task sources. Each benchmark source requires its own immutable
commit, license provenance, content digest, gold checks, and human approval.

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
uv run pytest tests/unit/test_source_repository_lock.py -v
uv run ruff check .
```

Licensing and citation metadata remain pending author decisions.
