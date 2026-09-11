"""Bounded binary subprocess streams, including daemon/control operations."""

import os
import selectors
import subprocess
import time
from dataclasses import dataclass

from contractcapsule.swap.trees import RunnerError


@dataclass(frozen=True)
class Output:
    stdout: bytes
    stderr: bytes
    exit_code: int | None
    timed_out: bool
    limited: bool


def bounded(argv: list[str], *, timeout: float = 10, out_limit: int = 65536,
            err_limit: int = 65536, env: dict[str, str] | None = None) -> Output:
    with subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, env=env, close_fds=True) as process:
        return _collect(process, timeout, out_limit, err_limit)


def _collect(process, timeout, out_limit, err_limit) -> Output:
    streams = [bytearray(), bytearray()]
    limits = (out_limit, err_limit)
    deadline = time.monotonic() + timeout
    timed_out = limited = False
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ, 0)
        selector.register(process.stderr, selectors.EVENT_READ, 1)
        while selector.get_map():
            if time.monotonic() >= deadline:
                timed_out = True
                break
            for key, _ in selector.select(min(0.05, max(0, deadline - time.monotonic()))):
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                index = key.data
                remaining = limits[index] - len(streams[index])
                streams[index].extend(chunk[:remaining])
                limited |= len(chunk) > remaining
            if limited:
                break
        if timed_out or limited:
            process.kill()
        try:
            code = process.wait(timeout=max(0.01, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            code = process.wait(timeout=2)
    return Output(bytes(streams[0]), bytes(streams[1]), code, timed_out, limited)


def checked(argv: list[str], **kwargs) -> bytes:
    output = bounded(argv, **kwargs)
    if output.exit_code != 0 or output.timed_out or output.limited:
        raise RunnerError("bounded command failed")
    return output.stdout
