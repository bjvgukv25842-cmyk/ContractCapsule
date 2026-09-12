"""Small append-only reservation store for M5-4 twin attempts."""

from __future__ import annotations

import hashlib
import hmac
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AttemptRow:
    operation_id: str
    binding_digest: str
    state: str
    manifest: bytes | None


class AttemptStore:
    def __init__(self, database_path: Path, key: bytes | None = None) -> None:
        self.database_path = database_path
        self._key = key or hashlib.sha256(b"ccs-m5-twin-attempts/1").digest()
        if type(self._key) is not bytes or len(self._key) < 16:
            raise ValueError("attempt store key is too short")
        with sqlite3.connect(database_path) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS m5_twin_attempts (
                    operation_id TEXT PRIMARY KEY,
                    binding_digest TEXT NOT NULL,
                    state TEXT NOT NULL,
                    manifest BLOB,
                    signature BLOB NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS m5_twin_attempts_transition
                BEFORE UPDATE ON m5_twin_attempts
                WHEN OLD.state != 'RUNNING'
                  OR NEW.operation_id != OLD.operation_id
                  OR NEW.binding_digest != OLD.binding_digest
                  OR NEW.state != 'COMPLETE'
                BEGIN SELECT RAISE(ABORT, 'invalid attempt transition'); END;
            """)

    def reserve(self, operation_id: str, binding_digest: str) -> AttemptRow:
        with sqlite3.connect(self.database_path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT operation_id,binding_digest,state,manifest FROM m5_twin_attempts WHERE operation_id=?", (operation_id,)).fetchone()
            if row is None:
                signature = self._sign(operation_id, binding_digest, "RUNNING", None)
                db.execute("INSERT INTO m5_twin_attempts VALUES (?,?,?,NULL,?)", (operation_id, binding_digest, "RUNNING", signature))
                return AttemptRow(operation_id, binding_digest, "RUNNING", None)
            result = AttemptRow(*row)
            if result.binding_digest != binding_digest:
                raise ValueError("attempt binding mismatch")
            if result.state != "COMPLETE":
                raise ValueError("attempt already reserved")
            return result

    def complete(self, operation_id: str, manifest: bytes) -> None:
        with sqlite3.connect(self.database_path) as db:
            row = db.execute("SELECT binding_digest,state FROM m5_twin_attempts WHERE operation_id=?", (operation_id,)).fetchone()
            if row is None or row[1] != "RUNNING":
                raise ValueError("attempt completion rejected")
            signature = self._sign(operation_id, row[0], "COMPLETE", manifest)
            db.execute("UPDATE m5_twin_attempts SET state='COMPLETE', manifest=?, signature=? WHERE operation_id=? AND state='RUNNING'", (manifest, signature, operation_id))
            if db.total_changes != 1:
                raise ValueError("attempt completion rejected")

    def get(self, operation_id: str) -> AttemptRow | None:
        with sqlite3.connect(self.database_path) as db:
            row = db.execute("SELECT operation_id,binding_digest,state,manifest,signature FROM m5_twin_attempts WHERE operation_id=?", (operation_id,)).fetchone()
        if row is None:
            return None
        expected = self._sign(row[0], row[1], row[2], row[3])
        if type(row[4]) is not bytes or not hmac.compare_digest(expected, row[4]):
            raise ValueError("attempt authentication failed")
        return AttemptRow(*row[:4])

    def _sign(self, operation_id: str, binding_digest: str, state: str, manifest: bytes | None) -> bytes:
        payload = f"{operation_id}\x00{binding_digest}\x00{state}".encode() + b"\0" + (manifest or b"")
        return hmac.digest(self._key, payload, "sha256")
