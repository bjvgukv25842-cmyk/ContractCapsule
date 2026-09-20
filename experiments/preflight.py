"""Fail-closed adapter preflight and receipt handling."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from experiments.models import (
    ExperimentConfig,
    PreflightReceipt,
    load_config,
)


class PreflightError(ValueError):
    """The adapter/config preflight could not produce a trusted receipt."""


def _metadata(
    adapter: object | None, expected_agent: str
) -> tuple[str | None, str | None, tuple[str, ...], str | None, bool]:
    if adapter is None:
        return None, None, (), "ADAPTER_NOT_PROBED", False
    try:
        observed = adapter.preflight()  # type: ignore[attr-defined]
    except Exception as error:  # noqa: BLE001 - adapter errors are normalized
        code = getattr(error, "code", None)
        return None, None, (), str(code) if isinstance(code, str) else "ADAPTER_PREFLIGHT_FAILED", False
    version = getattr(observed, "version", None)
    model = getattr(observed, "model", None)
    agent = getattr(observed, "agent", None)
    capabilities = getattr(observed, "capabilities", ())
    if not isinstance(version, str) or not version:
        return None, None, (), "ADAPTER_METADATA_INVALID", False
    if not isinstance(model, str) or not model:
        return None, None, (), "ADAPTER_METADATA_INVALID", False
    if agent != expected_agent:
        return None, None, (), "ADAPTER_METADATA_INVALID", False
    if not isinstance(capabilities, (tuple, list)) or any(
        not isinstance(item, str) or not item for item in capabilities
    ):
        return None, None, (), "ADAPTER_METADATA_INVALID", False
    return version, model, tuple(capabilities), None, True


def _write_receipt(path: Path, receipt: PreflightReceipt) -> None:
    if path.is_symlink():
        raise PreflightError("preflight receipt must be a regular file")
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(receipt.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
    if path.exists():
        try:
            existing = PreflightReceipt.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as error:
            raise PreflightError("existing preflight receipt is invalid") from error
        if existing != receipt:
            raise PreflightError("preflight receipt cannot be overwritten")
        return
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        fd = os.open(path, flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as error:
        raise PreflightError("preflight receipt cannot be overwritten") from error
    except OSError as error:
        raise PreflightError("unable to write preflight receipt") from error


def preflight_config(
    config: Path | str | Mapping[str, Any] | ExperimentConfig,
    *,
    output_path: Path | str | None = None,
    adapter: object | None = None,
    binary: str | None = None,
    signing_key: bytes | None = None,
) -> PreflightReceipt:
    """Capture observed adapter metadata without inventing unavailable values.

    A missing adapter is a valid *failed* preflight receipt.  It is useful for
    dry-run planning, but ``run_once`` will refuse live execution unless the
    receipt is available and valid.
    """

    try:
        parsed = load_config(config)
    except Exception as error:
        raise PreflightError("invalid experiment config") from error
    version, model, capabilities, error_code, available = _metadata(adapter, parsed.agent)
    if available and (
        (parsed.model is not None and model != parsed.model)
        or (parsed.version is not None and version != parsed.version)
    ):
        version, model, capabilities = None, None, ()
        error_code, available = "PREFLIGHT_CONFIG_MISMATCH", False
    if available and (type(signing_key) is not bytes or len(signing_key) < 32):
        version, model, capabilities = None, None, ()
        error_code, available = "PREFLIGHT_SIGNING_KEY_REQUIRED", False
    receipt = PreflightReceipt(
        config_digest=parsed.digest,
        agent=parsed.agent,
        version=version,
        model=model,
        binary=binary or parsed.binary,
        capabilities=capabilities,
        available=available,
        error_code=error_code,
    )
    receipt = receipt.model_copy(update={"digest": receipt.computed_digest()})
    if signing_key is not None:
        receipt = receipt.model_copy(update={"signature": receipt.computed_signature(signing_key)})
    target = Path(output_path) if output_path is not None else parsed.preflight_receipt
    if target is not None:
        _write_receipt(target, receipt)
    return receipt


def load_receipt(path: Path | str) -> PreflightReceipt:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise PreflightError("preflight receipt must be a regular file")
    try:
        receipt = PreflightReceipt.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as error:
        raise PreflightError("invalid preflight receipt") from error
    if receipt.digest is None or receipt.digest != receipt.computed_digest():
        raise PreflightError("preflight receipt digest mismatch")
    return receipt


def validate_receipt(
    receipt: PreflightReceipt | Path | str | None,
    config: ExperimentConfig | Path | str | Mapping[str, Any],
    *,
    require_available: bool = True,
    signing_key: bytes | None = None,
) -> PreflightReceipt:
    parsed = load_config(config)
    if receipt is None:
        raise PreflightError("preflight receipt is required")
    loaded = load_receipt(receipt) if isinstance(receipt, (Path, str)) else receipt
    if loaded.digest is None or loaded.digest != loaded.computed_digest():
        raise PreflightError("preflight receipt digest mismatch")
    if loaded.config_digest != parsed.digest:
        raise PreflightError("preflight receipt config mismatch")
    if loaded.agent != parsed.agent:
        raise PreflightError("preflight receipt agent mismatch")
    if parsed.model is not None and loaded.model != parsed.model:
        raise PreflightError("preflight receipt model mismatch")
    if parsed.version is not None and loaded.version != parsed.version:
        raise PreflightError("preflight receipt version mismatch")
    if parsed.binary is not None and loaded.binary != parsed.binary:
        raise PreflightError("preflight receipt binary mismatch")
    if require_available and not loaded.available:
        raise PreflightError("adapter preflight is unavailable")
    if loaded.available:
        if type(signing_key) is not bytes or len(signing_key) < 32:
            raise PreflightError("preflight signing key is required")
        if not loaded.verify_signature(signing_key):
            raise PreflightError("preflight receipt signature mismatch")
    return loaded


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture M7 adapter preflight metadata")
    parser.add_argument("--config", default="experiments/configs/pilot.yaml")
    parser.add_argument("--output", default=None)
    args = parser.parse_args(argv)
    try:
        receipt = preflight_config(args.config, output_path=args.output)
    except PreflightError as error:
        parser.error(str(error))
    print(json.dumps(receipt.model_dump(mode="json"), sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["PreflightError", "load_receipt", "preflight_config", "validate_receipt"]
