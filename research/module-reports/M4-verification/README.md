# M4 Controller Verification Evidence

Exact technical candidate: `2ce16535ece97733404e91715bb2b7586b54de20`.
These checks were run by the coordinating/authoring agent, not an independent
exit reviewer. See the main M4 report and pending independent-audit handoff.

`commands.jsonl` preserves exact command arguments, physical working directory,
exit status and final output lines. Repeated labels are chronological retries;
they are not extra tests. `identity.json` locks the tested source/test/schema
bytes. It does not include later documentation-only changes.

Initial tokenizer-path failures remain under `initial-path-failure/`. The
initial P1 mutation's setup failure is also retained there; only its later
targeted actual-overflow assertion is counted among the six detected faults.

Some pytest failure logs contain trailing spaces. Their `.log.gz` files are
lossless `gzip -n` archives, not edited transcripts. Read them with
`gzip -cd <exact-file.log.gz>`. Other logs are plain UTF-8. The original
uncompressed files also remain in `/private/tmp/cc-m4-final-verification.4l5I1p`.
The initial whitespace-check exit2 is an artifact-formatting issue; preserving
raw logs as gzip avoids modifying evidence or relaxing repository checks.

The `*.py.txt` files preserve actual disposable verification/probe code, not
installed project modules. They contain this run's explicit workspace paths;
a reviewer should create a new temporary archive and adjust its harness paths,
not execute against mutable source or confuse /tmp aliases with physical paths.

The frozen four-file command was additionally run exactly as specified from
the worktree (without `--no-sync`):235 passed in16.44s, exit0. The recorded
`frozen-exact-uv` log is the separate no-sync equivalent (235 passed16.27s);
the clean-archive log uses the locked interpreter directly (235 passed16.54s).
These are overlapping verification runs, not separate experimental samples.

Offline `uv build --offline --out-dir /private/tmp/cc-m4-final-verification.4l5I1p/dist`
produced both sdist and wheel with exit0. `wheel-smoke.log` records the subsequent
package import and local tokenizer check. No online model billing equivalence,
formal research result, M4 author approval or M5 work is implied.
