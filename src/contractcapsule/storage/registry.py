"""Immutable SQLite Registry for published CCS-2.1 capsule versions."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from contractcapsule.models import Capsule, Principal
from contractcapsule.models.canonical import (
    canonical_digest,
    canonical_json_bytes,
    capsule_wire_dict,
)
from contractcapsule.storage.cas import (
    BlobAuthorizationError,
    BlobIntegrityError,
    FilesystemCAS,
)


class RegistryError(RuntimeError):
    """Base class for immutable Registry failures."""


class RegistryAuthorizationError(RegistryError):
    """A trusted policy resolver did not authorize publication."""


class RegistryNotFound(RegistryError):
    """Generic non-disclosing result for absent or unreadable versions."""


class VersionConflict(RegistryError):
    """The capsule ID and version already identify a different digest."""


class PublicationConflict(RegistryError):
    """An apparent replay differs in another immutable publication field."""


class PublicationIntegrityError(RegistryError):
    """Stored publication rows no longer form the immutable committed record."""


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    allowed_access_policies: frozenset[str]

    @classmethod
    def deny(cls) -> PolicyDecision:
        return cls(False, frozenset())


class PolicyResolver(Protocol):
    def resolve(
        self,
        principal: Principal,
        action: str,
        authority: str,
        scope: object,
    ) -> PolicyDecision: ...


class DefaultDenyPolicyResolver:
    def resolve(
        self,
        principal: Principal,
        action: str,
        authority: str,
        scope: object,
    ) -> PolicyDecision:
        del principal, action, authority, scope
        return PolicyDecision.deny()


@dataclass(frozen=True, slots=True)
class PublishedCapsule:
    capsule: Capsule
    registry_status: str
    published_at: str


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _timestamp(clock: Callable[[], datetime]) -> str:
    value = clock().astimezone(UTC).isoformat(timespec="microseconds")
    return value.replace("+00:00", "Z")


def _scope_dict(capsule: Capsule) -> dict[str, Any]:
    scope = capsule.control_manifest.scope
    return {
        "repositories": list(scope.repositories),
        "paths": list(scope.paths),
        "environments": list(scope.environments),
    }


def _signature_dict(capsule: Capsule) -> dict[str, Any] | None:
    signature = capsule.detached_signature
    if signature is None:
        return None
    return {
        "algorithm": signature.algorithm,
        "key_id": signature.key_id,
        "value": signature.value,
        "envelope": dict(signature.envelope),
    }


def _publication_core(capsule: Capsule) -> dict[str, Any]:
    wire = capsule_wire_dict(capsule)
    wire.pop("detached_signature", None)
    wire.pop("derived_artifacts", None)
    wire.pop("runtime_sidecar", None)
    return wire


def _jcs_text(value: Any) -> str:
    return canonical_json_bytes(value).decode("utf-8")


class Registry:
    """Append-only publication registry; it exposes no update or delete API."""

    def __init__(
        self,
        database_path: Path,
        cas: FilesystemCAS,
        resolver: PolicyResolver | None = None,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.database_path = database_path
        self._cas = cas
        self._resolver = resolver or DefaultDenyPolicyResolver()
        self._clock = clock
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS publications (
                    publication_id INTEGER PRIMARY KEY,
                    capsule_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    content_digest TEXT NOT NULL,
                    lifecycle TEXT NOT NULL,
                    authority TEXT NOT NULL,
                    scope_jcs TEXT NOT NULL,
                    immutable_record_jcs TEXT NOT NULL,
                    detached_signature_jcs TEXT,
                    published_at TEXT NOT NULL,
                    UNIQUE (capsule_id, version)
                );
                CREATE TABLE IF NOT EXISTS evidence_references (
                    publication_id INTEGER NOT NULL,
                    ordinal INTEGER NOT NULL,
                    evidence_id TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    content_digest TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    access_policy TEXT NOT NULL,
                    immutable_record_jcs TEXT NOT NULL,
                    PRIMARY KEY (publication_id, evidence_id),
                    UNIQUE (publication_id, ordinal),
                    FOREIGN KEY (publication_id) REFERENCES publications(publication_id)
                        ON UPDATE RESTRICT ON DELETE RESTRICT
                );
                CREATE TABLE IF NOT EXISTS digest_grants (
                    publication_id INTEGER NOT NULL,
                    evidence_id TEXT NOT NULL,
                    digest TEXT NOT NULL,
                    access_policy TEXT NOT NULL,
                    PRIMARY KEY (publication_id, evidence_id, digest),
                    FOREIGN KEY (publication_id, evidence_id)
                        REFERENCES evidence_references(publication_id, evidence_id)
                        ON UPDATE RESTRICT ON DELETE RESTRICT
                );
                """
            )

    def _decision(
        self, capsule: Capsule, principal: Principal, action: str
    ) -> PolicyDecision:
        return self._decision_for_claims(
            principal,
            action,
            capsule.control_manifest.authority,
            _scope_dict(capsule),
        )

    def _decision_for_claims(
        self,
        principal: Principal,
        action: str,
        authority: str,
        scope: object,
    ) -> PolicyDecision:
        try:
            decision = self._resolver.resolve(
                principal,
                action,
                authority,
                scope,
            )
        except Exception:  # noqa: BLE001 - policy-resolver failures must deny access.
            return PolicyDecision.deny()
        if (
            not isinstance(decision, PolicyDecision)
            or type(decision.allowed) is not bool
            or type(decision.allowed_access_policies) is not frozenset
            or any(
                type(policy) is not str or not policy
                for policy in decision.allowed_access_policies
            )
        ):
            return PolicyDecision.deny()
        return decision

    @staticmethod
    def _access_policies(capsule: Capsule) -> frozenset[str]:
        return frozenset(record.access_policy for record in capsule.evidence_plane.records)

    def _authorize_publish(self, capsule: Capsule, principal: Principal) -> None:
        decision = self._decision(capsule, principal, "publish")
        if not decision.allowed or not self._access_policies(capsule) <= decision.allowed_access_policies:
            raise RegistryAuthorizationError("publication is not authorized")

    def _authorize_read(self, capsule: Capsule, principal: Principal) -> bool:
        decision = self._decision(capsule, principal, "read")
        return decision.allowed and self._access_policies(capsule) <= decision.allowed_access_policies

    @staticmethod
    def _evidence_records(capsule: Capsule) -> list[dict[str, Any]]:
        wire_records = capsule_wire_dict(capsule)["evidence_plane"]["records"]
        return [dict(record) for record in wire_records]

    def _validate_candidate(self, capsule: Capsule) -> None:
        manifest = capsule.control_manifest
        if manifest.lifecycle != "PUBLISHED":
            raise PublicationIntegrityError("publish requires PUBLISHED lifecycle")
        if canonical_digest(capsule) != manifest.content_digest:
            raise PublicationIntegrityError("candidate content digest does not match core")
        for record in capsule.evidence_plane.records:
            if record.mode == "CAS":
                stored = self._cas._read_verified(record.content_digest)
                if stored.ref.media_type != record.media_type:
                    raise PublicationIntegrityError("CAS evidence media type mismatch")

    @staticmethod
    def _revalidate_candidate(capsule: Capsule) -> Capsule:
        """Re-enter the strict model boundary before trusting a caller's object."""

        if not isinstance(capsule, Capsule):
            raise PublicationIntegrityError("candidate model validation failed")
        try:
            wire = capsule_wire_dict(capsule)
            return Capsule.model_validate_json(
                json.dumps(wire, ensure_ascii=False, allow_nan=False)
            )
        except (AttributeError, TypeError, ValueError) as error:
            raise PublicationIntegrityError(
                "candidate model validation failed"
            ) from error

    def _insert_evidence(
        self, connection: sqlite3.Connection, publication_id: int, capsule: Capsule
    ) -> None:
        for ordinal, record in enumerate(self._evidence_records(capsule)):
            connection.execute(
                """
                INSERT INTO evidence_references (
                    publication_id, ordinal, evidence_id, mode, content_digest,
                    media_type, access_policy, immutable_record_jcs
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    publication_id,
                    ordinal,
                    record["evidence_id"],
                    record["mode"],
                    record["content_digest"],
                    record["media_type"],
                    record["access_policy"],
                    _jcs_text(record),
                ),
            )

    def _insert_grants(
        self, connection: sqlite3.Connection, publication_id: int, capsule: Capsule
    ) -> None:
        for record in capsule.evidence_plane.records:
            if record.mode != "CAS":
                continue
            connection.execute(
                """
                INSERT INTO digest_grants (
                    publication_id, evidence_id, digest, access_policy
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    publication_id,
                    record.evidence_id,
                    record.content_digest,
                    record.access_policy,
                ),
            )

    def _expected_rows(
        self, capsule: Capsule
    ) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
        evidence = []
        grants = []
        for ordinal, record in enumerate(self._evidence_records(capsule)):
            evidence.append(
                (
                    ordinal,
                    record["evidence_id"],
                    record["mode"],
                    record["content_digest"],
                    record["media_type"],
                    record["access_policy"],
                    _jcs_text(record),
                )
            )
            if record["mode"] == "CAS":
                grants.append(
                    (record["evidence_id"], record["content_digest"], record["access_policy"])
                )
        return evidence, grants

    def _verify_existing(
        self, connection: sqlite3.Connection, row: sqlite3.Row, capsule: Capsule
    ) -> None:
        signature = _signature_dict(capsule)
        expected_publication = (
            capsule.control_manifest.content_digest,
            capsule.control_manifest.lifecycle,
            capsule.control_manifest.authority,
            _jcs_text(_scope_dict(capsule)),
            _jcs_text(_publication_core(capsule)),
            _jcs_text(signature) if signature is not None else None,
        )
        stored_publication = (
            row["content_digest"],
            row["lifecycle"],
            row["authority"],
            row["scope_jcs"],
            row["immutable_record_jcs"],
            row["detached_signature_jcs"],
        )
        if stored_publication != expected_publication:
            raise PublicationConflict("immutable publication fields differ")
        publication_id = row["publication_id"]
        evidence_rows = connection.execute(
            """
            SELECT ordinal, evidence_id, mode, content_digest, media_type,
                   access_policy, immutable_record_jcs
            FROM evidence_references WHERE publication_id = ? ORDER BY ordinal
            """,
            (publication_id,),
        ).fetchall()
        grant_rows = connection.execute(
            """
            SELECT evidence_id, digest, access_policy FROM digest_grants
            WHERE publication_id = ? ORDER BY evidence_id, digest
            """,
            (publication_id,),
        ).fetchall()
        expected_evidence, expected_grants = self._expected_rows(capsule)
        if [tuple(item) for item in evidence_rows] != expected_evidence:
            raise PublicationIntegrityError("stored evidence references are incomplete")
        if [tuple(item) for item in grant_rows] != sorted(expected_grants):
            raise PublicationIntegrityError("stored digest grants are incomplete")

    def _row_to_published(self, row: sqlite3.Row) -> PublishedCapsule:
        try:
            wire = json.loads(row["immutable_record_jcs"])
            signature = row["detached_signature_jcs"]
            wire["detached_signature"] = json.loads(signature) if signature else None
            wire["derived_artifacts"] = {}
            wire["runtime_sidecar"] = {}
            capsule = Capsule.model_validate_json(json.dumps(wire))
        except Exception as error:
            raise PublicationIntegrityError("stored Capsule cannot be reconstructed") from error
        if (
            canonical_digest(capsule) != row["content_digest"]
            or capsule.control_manifest.content_digest != row["content_digest"]
            or capsule.control_manifest.lifecycle != row["lifecycle"]
            or capsule.control_manifest.authority != row["authority"]
            or _jcs_text(_scope_dict(capsule)) != row["scope_jcs"]
        ):
            raise PublicationIntegrityError("stored Capsule denormalized fields disagree")
        return PublishedCapsule(capsule, "PUBLISHED", row["published_at"])

    def publish(self, capsule: Capsule, principal: Principal) -> PublishedCapsule:
        capsule = self._revalidate_candidate(capsule)
        self._authorize_publish(capsule, principal)
        manifest = capsule.control_manifest
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            # The private CAS rehash is inside the Registry transaction. A failed
            # check cannot leave publication, reference, or grant rows behind.
            self._validate_candidate(capsule)
            row = connection.execute(
                "SELECT * FROM publications WHERE capsule_id = ? AND version = ?",
                (manifest.capsule_id, manifest.version),
            ).fetchone()
            if row is not None:
                if row["content_digest"] != manifest.content_digest:
                    raise VersionConflict("capsule ID and version already have another digest")
                self._verify_existing(connection, row, capsule)
                return self._row_to_published(row)

            published_at = _timestamp(self._clock)
            signature = _signature_dict(capsule)
            cursor = connection.execute(
                """
                INSERT INTO publications (
                    capsule_id, version, content_digest, lifecycle, authority,
                    scope_jcs, immutable_record_jcs, detached_signature_jcs, published_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    manifest.capsule_id,
                    manifest.version,
                    manifest.content_digest,
                    manifest.lifecycle,
                    manifest.authority,
                    _jcs_text(_scope_dict(capsule)),
                    _jcs_text(_publication_core(capsule)),
                    _jcs_text(signature) if signature is not None else None,
                    published_at,
                ),
            )
            if cursor.lastrowid is None:  # pragma: no cover - SQLite contract guard
                raise PublicationIntegrityError("publication insert returned no identifier")
            publication_id = cursor.lastrowid
            self._insert_evidence(connection, publication_id, capsule)
            self._insert_grants(connection, publication_id, capsule)
            row = connection.execute(
                "SELECT * FROM publications WHERE publication_id = ?", (publication_id,)
            ).fetchone()
            if row is None:  # pragma: no cover - SQLite contract guard
                raise PublicationIntegrityError("publication row disappeared in transaction")
            self._verify_existing(connection, row, capsule)
            return self._row_to_published(row)

    def get(
        self, capsule_id: str, version: str, principal: Principal
    ) -> PublishedCapsule:
        generic = "capsule version is unavailable"
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM publications WHERE capsule_id = ? AND version = ?",
                (capsule_id, version),
            ).fetchone()
            if row is None:
                raise RegistryNotFound(generic)
            try:
                scope = json.loads(row["scope_jcs"])
                policies = frozenset(
                    item[0]
                    for item in connection.execute(
                        """
                        SELECT access_policy FROM evidence_references
                        WHERE publication_id = ?
                        """,
                        (row["publication_id"],),
                    ).fetchall()
                )
                decision = self._decision_for_claims(
                    principal, "read", row["authority"], scope
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                decision = PolicyDecision.deny()
                policies = frozenset()
            if not decision.allowed or not policies <= decision.allowed_access_policies:
                raise RegistryNotFound(generic)
            published = self._row_to_published(row)
            self._verify_existing(connection, row, published.capsule)
            for record in published.capsule.evidence_plane.records:
                if record.mode == "CAS":
                    stored = self._cas._read_verified(record.content_digest)
                    if stored.ref.media_type != record.media_type:
                        raise PublicationIntegrityError(
                            "stored CAS evidence media type disagrees"
                        )
            return published

    def can_read_blob(self, digest: str, principal: Principal) -> bool:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT p.*, g.evidence_id AS grant_evidence_id,
                       g.access_policy AS grant_access_policy
                FROM digest_grants AS g
                JOIN publications AS p ON p.publication_id = g.publication_id
                WHERE g.digest = ?
                """,
                (digest,),
            ).fetchall()
            for row in rows:
                try:
                    published = self._row_to_published(row)
                    self._verify_existing(connection, row, published.capsule)
                    decision = self._decision(published.capsule, principal, "read")
                except (PublicationConflict, PublicationIntegrityError):
                    continue
                if (
                    decision.allowed
                    and row["grant_access_policy"]
                    in decision.allowed_access_policies
                ):
                    record = next(
                        (
                            item
                            for item in published.capsule.evidence_plane.records
                            if item.mode == "CAS"
                            and item.evidence_id == row["grant_evidence_id"]
                            and item.content_digest == digest
                        ),
                        None,
                    )
                    if record is None:
                        continue
                    stored = self._cas._read_verified(digest)
                    if stored.ref.media_type != record.media_type:
                        raise BlobIntegrityError(
                            "published CAS evidence media type disagrees"
                        )
                    return True
        return False

    def get_blob(self, digest: str, principal: Principal) -> bytes:
        if not self.can_read_blob(digest, principal):
            raise BlobAuthorizationError("blob read is not authorized")
        return self._cas._read_verified(digest).data

    def _table_counts(self) -> dict[str, int]:
        with self._connect() as connection:
            return {
                table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in (
                    "publications",
                    "evidence_references",
                    "digest_grants",
                )
            }


def publish(
    capsule: Capsule, principal: Principal, *, registry: Registry
) -> PublishedCapsule:
    """Required functional interface with an injected Registry."""

    return registry.publish(capsule, principal)


def get(
    capsule_id: str,
    version: str,
    principal: Principal,
    *,
    registry: Registry,
) -> PublishedCapsule:
    """Required functional interface with an injected Registry."""

    return registry.get(capsule_id, version, principal)
