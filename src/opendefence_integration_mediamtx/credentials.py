"""Validate Core's proposed public certificate records without reading Secrets."""

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

_FIELDS = {"fingerprintSha256", "serialHex", "issuerId", "notBefore", "notAfter"}
_RFC3339 = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})")


@dataclass(frozen=True, slots=True)
class CertificateCredential:
    fingerprint_sha256: str
    serial_hex: str
    issuer_id: str
    not_before: datetime
    not_after: datetime

    def __post_init__(self) -> None:
        if (
            not isinstance(self.fingerprint_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", self.fingerprint_sha256)
            or not isinstance(self.serial_hex, str)
            or not re.fullmatch(r"[1-9a-f][0-9a-f]*", self.serial_hex)
            or not isinstance(self.issuer_id, str)
            or not self.issuer_id.strip()
            or not isinstance(self.not_before, datetime)
            or self.not_before.utcoffset() is None
            or not isinstance(self.not_after, datetime)
            or self.not_after.utcoffset() is None
            or self.not_before >= self.not_after
        ):
            raise ValueError("Invalid certificate credential")

    def valid_at(self, now: datetime) -> bool:
        return isinstance(now, datetime) and now.utcoffset() is not None and self.not_before <= now < self.not_after


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("Duplicate credential field")
    return result


def _time(value: Any) -> datetime:
    if not isinstance(value, str) or not _RFC3339.fullmatch(value):
        raise ValueError("Invalid credential time")
    return datetime.fromisoformat(value)


def _record(value: Any) -> CertificateCredential:
    if not isinstance(value, dict) or set(value) != _FIELDS:
        raise ValueError("Invalid credential record")
    return CertificateCredential(
        value["fingerprintSha256"],
        value["serialHex"],
        value["issuerId"],
        _time(value["notBefore"]),
        _time(value["notAfter"]),
    )


def parse_credential_annotation(raw: str | None) -> frozenset[CertificateCredential]:
    """Fail closed on missing or malformed version-one User metadata."""
    if not isinstance(raw, str):
        return frozenset()
    try:
        data = json.loads(raw, object_pairs_hook=_unique_object)
        if (
            not isinstance(data, dict)
            or set(data) != {"version", "credentials"}
            or type(data["version"]) is not int
            or data["version"] != 1
            or not isinstance(data["credentials"], list)
        ):
            return frozenset()
        records = frozenset(_record(value) for value in data["credentials"])
        if (
            len(records) != len(data["credentials"])
            or len({record.fingerprint_sha256 for record in records}) != len(records)
            or len({(record.issuer_id, record.serial_hex) for record in records}) != len(records)
        ):
            return frozenset()
        return records
    except TypeError, ValueError, RecursionError:
        return frozenset()
