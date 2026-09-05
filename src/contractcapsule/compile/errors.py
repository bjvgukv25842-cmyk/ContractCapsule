"""Non-disclosing expected compilation failures."""

import re


class CompileError(RuntimeError):
    """Carries only a caller-chosen safe code, never raw operational detail."""

    def __init__(self, code: str) -> None:
        if (
            not isinstance(code, str)
            or re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", code) is None
        ):
            raise ValueError("compile error requires a safe nonempty code")
        self.code = code
        super().__init__(code)
