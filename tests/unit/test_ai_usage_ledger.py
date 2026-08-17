from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).parents[2]
LEDGER = ROOT / "research/ai-usage-ledger.jsonl"
PLAN = (
    ROOT
    / "docs/superpowers/plans/2026-07-30-contract-capsule-fse-2027-execution-plan.md"
)
REQUIRED_FIELDS = frozenset(
    {
        "timestamp",
        "module",
        "agent",
        "model_id",
        "prompt_sha256",
        "inputs",
        "outputs",
        "research_role",
        "human_validation",
        "commit",
    }
)
PROMPT_DIGEST = re.compile(r"^[0-9a-f]{64}$")

# Rows created before enum enforcement are research history and are not rewritten.
# Exact raw-line digests prevent these exceptions from admitting any new invalid row.
LEGACY_NON_ENUM_ROW_DIGESTS = frozenset(
    {
        "06db04ac7549a563f86f0578bca4f35fba8e79c0cdece15e792043e7807bb240",
        "2925a2969bc4ff1ae248bc982e2feded454967d7bf6ffada74df435db2fee53f",
        "fc1463131bffc9e0a5a097bf184836ce7180bfa69286d29acd1f954246684eef",
        "0596ba0ff68037433abc4f8ffe10eb57f562a518f382cb35d7ce98c80147739d",
        "2e08ead16330bf3881f67ba67a68a93ac926152bcd0d84456cbd69a6dc0374fb",
        "7f5103c4919cbd29987ec3863fd5e5e1b2545e7d0b150fef852ceea7635aaf7c",
        "5533044bbb468ed5798dbb67a7794e1784140c5d3c17f31b3eae7489bac305a1",
        "5dd40951e829c110ab8d9860e9c6bd27026b5d1f8a7954ef5e17f5eee091e844",
        "0cd0e9f5a60312c8e36afa43e017701c90fa5f3f22144e85c85fc81fb1a01480",
        "5883f82d40ca846a3fd2a4f41ca4e0c01ea78a1a9151dc6b82c58dff02931c99",
        "39fe58944cd03f93a1b0678842ed7cccf976ace810c33191a27426cf1378319f",
    }
)


def _frozen_enums() -> tuple[frozenset[str], frozenset[str]]:
    text = PLAN.read_text(encoding="utf-8")
    role_match = re.search(r'"research_role": "([a-z|]+)"', text)
    validation_match = re.search(r'"human_validation": "([a-z|]+)"', text)
    assert role_match is not None
    assert validation_match is not None
    return (
        frozenset(role_match.group(1).split("|")),
        frozenset(validation_match.group(1).split("|")),
    )


def test_ai_usage_ledger_is_jsonl_with_required_fields_and_frozen_enums() -> None:
    roles, validations = _frozen_enums()
    assert roles == {"implementation", "dataset", "experiment", "analysis", "writing"}
    assert validations == {"pending", "approved", "rejected"}

    seen_legacy: set[str] = set()
    for line_number, line in enumerate(
        LEDGER.read_text(encoding="utf-8").splitlines(), start=1
    ):
        record = json.loads(line)
        assert isinstance(record, dict), f"ledger row {line_number} is not an object"
        assert not REQUIRED_FIELDS - record.keys(), (
            f"ledger row {line_number} lacks required fields"
        )
        prompt_digest = record["prompt_sha256"]
        assert PROMPT_DIGEST.fullmatch(prompt_digest) or prompt_digest == (
            "unavailable:not-exposed-by-session-metadata"
        ), f"ledger row {line_number} has an invalid prompt digest declaration"
        assert isinstance(record["inputs"], list) and record["inputs"]
        assert isinstance(record["outputs"], list) and record["outputs"]

        if (
            record["research_role"] not in roles
            or record["human_validation"] not in validations
        ):
            row_digest = hashlib.sha256(line.encode("utf-8")).hexdigest()
            assert row_digest in LEGACY_NON_ENUM_ROW_DIGESTS, (
                f"ledger row {line_number} violates frozen enums"
            )
            seen_legacy.add(row_digest)

    assert seen_legacy == LEGACY_NON_ENUM_ROW_DIGESTS
