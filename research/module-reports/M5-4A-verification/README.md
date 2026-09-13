# M5-4A retained verification evidence

These are engineering tests and independent review diagnostics, not benchmark
experiments. The two independent reports in the parent directory retain their
original bytes and original temporary artifact paths.

`independent-base-regression-red.log.gz` stores the exact base-regression log
losslessly with deterministic gzip headers. Pytest prints trailing whitespace
in tracebacks; the first archive commit603196e therefore failed its staged
whitespace check even though the shell sequence proceeded to commit. That
failure is not a passing gate. Lossless compression preserves the raw bytes
while allowing the branch diff check to evaluate source and documentation
normally. No whitespace-check exception or threshold change is introduced.

All other `.log` files are plain text. `.py.txt` files preserve independent
diagnostic code without adding it to the committed pytest collection. The
original review/copy directories remain untouched. The full regression log
summarizes main's979-test run; it is not an independent full-suite claim.
