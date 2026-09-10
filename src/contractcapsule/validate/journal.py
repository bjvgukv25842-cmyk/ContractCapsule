"""Host-owned append-only authenticated records, separate from approval authority.

Only trusted composition receives RecordJournal. Subjects receive references;
consumers receive the read-only verifier. HMAC assumes an uncompromised host.
"""

import hashlib
import hmac
import sqlite3
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from contractcapsule.models.base import Digest, NonEmptyString, StrictFrozenModel
from contractcapsule.models.canonical import canonical_json_bytes
from contractcapsule.storage.registry import Registry


class RecordError(ValueError):
    """Unknown, foreign, damaged or unauthenticated record; no private details."""


class RecordRef(StrictFrozenModel):
    record_id: NonEmptyString
    digest: Digest


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _signed_bytes(
    record_id: str, kind: str, scope: str, subject: str, payload: bytes
) -> bytes:
    return canonical_json_bytes(
        {
            "domain": "ccs-m5-record/1",
            "record_id": record_id,
            "kind": kind,
            "scope": scope,
            "subject": subject,
            "payload_sha256": _digest(payload),
        }
    )


@dataclass(frozen=True)
class RecordVerifier:
    database_path: Path
    _key: bytes = field(repr=False)

    def verify(
        self, reference: object, *, kind: str, scope: str, subject: str
    ) -> bytes:
        try:
            if type(reference) is not RecordRef:
                raise ValueError
            with sqlite3.connect(self.database_path) as connection:
                row = connection.execute(
                    "SELECT kind, scope, subject, payload, signature FROM m5_records WHERE record_id=?",
                    (reference.record_id,),
                ).fetchone()
            if row is None or row[:3] != (kind, scope, subject):
                raise ValueError
            payload, signature = row[3:]
            if type(payload) is not bytes or _digest(payload) != reference.digest:
                raise ValueError
            expected = hmac.digest(
                self._key,
                _signed_bytes(reference.record_id, kind, scope, subject, payload),
                "sha256",
            )
            if type(signature) is not bytes or not hmac.compare_digest(
                expected, signature
            ):
                raise ValueError
            return payload
        except (ValueError, TypeError, AttributeError, sqlite3.Error):
            raise RecordError("record rejected") from None


@dataclass(frozen=True)
class RecordJournal:
    registry: Registry = field(repr=False)
    _key: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.registry) is not Registry
            or type(self._key) is not bytes
            or len(self._key) < 32
        ):
            raise RecordError("record rejected")
        with sqlite3.connect(self.registry.database_path) as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS m5_records (
                    record_id TEXT PRIMARY KEY, kind TEXT NOT NULL,
                    scope TEXT NOT NULL, subject TEXT NOT NULL,
                    payload BLOB NOT NULL, signature BLOB NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS m5_records_no_update BEFORE UPDATE ON m5_records
                BEGIN SELECT RAISE(ABORT, 'immutable record'); END;
                CREATE TRIGGER IF NOT EXISTS m5_records_no_delete BEFORE DELETE ON m5_records
                BEGIN SELECT RAISE(ABORT, 'immutable record'); END;
            """)

    def verifier(self) -> RecordVerifier:
        return RecordVerifier(self.registry.database_path, self._key)

    def append(
        self, *, kind: str, scope: str, subject: str, payload: bytes
    ) -> RecordRef:
        """Trusted host writer only; possession is signing authority, not a remote API."""
        try:
            if type(payload) is not bytes or not all(
                type(v) is str and v for v in (kind, scope, subject)
            ):
                raise ValueError
            record_id = str(uuid.uuid4())
            signature = hmac.digest(
                self._key,
                _signed_bytes(record_id, kind, scope, subject, payload),
                "sha256",
            )
            with sqlite3.connect(self.registry.database_path) as connection:
                connection.execute(
                    "INSERT INTO m5_records VALUES (?, ?, ?, ?, ?, ?)",
                    (record_id, kind, scope, subject, payload, signature),
                )
            return RecordRef(record_id=record_id, digest=_digest(payload))
        except (ValueError, TypeError, sqlite3.Error):
            raise RecordError("record rejected") from None
