# ContractCapsule Research Protocol

Status: M0 governance baseline, 2026-08-01. M1 will formalize and preregister
the research questions and analysis protocol; this file does not preempt M1.

## Normative Inputs

- `docs/spec/CCS-2.1.md`
  - SHA-256: `aaddaa8def8df1ef2efbe4f9487de0ba86a60ae5aed8955ca76f5e070fa01e5c`
- `docs/superpowers/plans/2026-07-30-contract-capsule-fse-2027-execution-plan.md`
  - SHA-256: `7c1feebb36776c09de5c0ba5462540072374b9902d8e04d405585a8efb8659c0`
- `AGENTS.md` governs daily execution beneath those two frozen baselines.

Execution status belongs in `research/decision-log.md` and
`research/module-reports/`; the frozen files are never edited in place.

## Submission Constraints

The confirmed target is FSE 2027 Research Papers. Per the frozen plan's
official-source lock dated 2026-07-30:

- initial submissions allow at most 18 pages of text and figures plus 4 pages
  of references;
- the paper uses `\documentclass[acmsmall,screen,review,anonymous]{acmart}`;
- review is heavy double-anonymous;
- a Data Availability statement appears after the conclusion;
- an anonymized replication package is expected when possible; and
- AI use affecting research design, implementation, datasets, experiments,
  analysis, validation, or research artifacts is disclosed in Methods.

No claim, citation, run, datum, or author identity may be invented to satisfy a
submission requirement.

## Research Contribution and Question IDs

- C1: formal context-capsule and replacement model.
- C2: working CCS-2.1 research prototype.
- C3: CapsuleBench replacement benchmark.
- C4: empirical comparison against context baselines.
- C5: open and reproducible research artifacts.
- RQ1: task effectiveness and efficiency.
- RQ2: explainability and evidence fidelity.
- RQ3: replacement correctness and safety.
- RQ4: generality and component necessity.

TER, PIP, and BSR are reported separately. Mandatory dependency closure,
evidence traceability, atomic activation, and recovery of the prior version are
independent replacement requirements. RCS may only be secondary and cannot hide
a failed component.

## Integrity and Execution Controls

- Modules execute strictly from M0 through M11, one authorized module at a
  time, with human approval at each exit gate.
- The current authorization covers M0 only.
- Tests precede behavioral implementation.
- Valid unfavorable results and negative cases are retained.
- Infrastructure retries never replace valid unfavorable runs.
- Benchmark ground truth requires human source review; at least 25 percent of
  tasks require a second independent reviewer.
- Raw experimental data become read-only after freezing; revisions create a
  new version and retain the prior digest.
- Safety, permission, evidence, dependency, integrity, and behavior-contract
  failures are fail-closed.
- Codex is a research tool and is not a paper author.

## M0 Environment Lock

- `uv`: 0.12.1 (`329541a50`, 2026-07-31, aarch64-apple-darwin).
- Python: CPython 3.12.13.
- Interpreter:
  `/Users/litmus/.local/share/uv/python/cpython-3.12-macos-aarch64-none/bin/python3.12`.
- Project interpreter: `.venv/bin/python3`.

The absolute interpreter path is an M0 audit record and must be removed or
normalized before the M11 anonymity freeze.

## M0 Human Decisions

| Decision | Status |
|---|---|
| Target track: FSE 2027 Research Papers | Confirmed by author, 2026-08-01 |
| CCS-2.1 approved digest | Confirmed by author and local verification |
| Final author names and affiliations | Pending |
| Submission conflicts of interest | Pending |
| Human-participant or other ethics review requirement | Pending |
| Repository license and citation metadata | Pending |
