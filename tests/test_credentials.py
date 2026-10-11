"""Keep proposed public certificate metadata strict and fail closed."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from opendefence_integration_mediamtx.credentials import parse_credential_annotation

NOW = datetime(2026, 10, 11, 12, tzinfo=UTC)
RECORD = {
    "fingerprintSha256": "a" * 64,
    "serialHex": "1a",
    "issuerId": "ca-key-1",
    "notBefore": "2026-10-11T11:00:00Z",
    "notAfter": "2026-10-11T13:00:00Z",
}


def annotation(*records: object) -> str:
    return json.dumps({"version": 1, "credentials": records})


def test_current_and_replacement_credentials_are_distinct_and_time_bounded() -> None:
    replacement = RECORD | {"fingerprintSha256": "b" * 64, "serialHex": "2b"}
    records = parse_credential_annotation(annotation(RECORD, replacement))
    assert {(record.fingerprint_sha256, record.serial_hex, record.issuer_id) for record in records} == {
        ("a" * 64, "1a", "ca-key-1"),
        ("b" * 64, "2b", "ca-key-1"),
    }
    assert all(record.valid_at(NOW) for record in records)
    assert all(not record.valid_at(NOW + timedelta(hours=1)) for record in records)
    assert all(not record.valid_at(NOW.replace(tzinfo=None)) for record in records)


def test_same_serial_from_different_issuers_identifies_distinct_credentials() -> None:
    other_issuer = RECORD | {"fingerprintSha256": "b" * 64, "issuerId": "ca-key-2"}
    assert len(parse_credential_annotation(annotation(RECORD, other_issuer))) == 2


def test_rfc3339_offsets_use_the_same_validity_instant() -> None:
    offset_record = RECORD | {"notBefore": "2026-10-11T14:00:00+03:00", "notAfter": "2026-10-11T16:00:00+03:00"}
    (record,) = parse_credential_annotation(annotation(offset_record))
    assert record.valid_at(NOW)


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "not JSON",
        json.dumps({"version": True, "credentials": [RECORD]}),
        json.dumps({"version": 2, "credentials": [RECORD]}),
        json.dumps({"version": 1, "credentials": [RECORD], "cn": "not-authority"}),
        '{"version":1,"version":1,"credentials":[]}',
        annotation(RECORD, RECORD | {"fingerprintSha256": "b" * 64}),
        annotation(RECORD, RECORD | {"serialHex": "2b"}),
        annotation(RECORD, RECORD | {"serialHex": "1a", "issuerId": "ca-key-1"}),
        annotation(RECORD, RECORD | {"serialHex": "00"}),
        annotation(RECORD, RECORD | {"fingerprintSha256": "A" * 64}),
        annotation(RECORD, RECORD | {"issuerId": " "}),
        annotation(RECORD, RECORD | {"notBefore": "2026-10-11T11:00:00"}),
        annotation(RECORD, RECORD | {"notAfter": "2026-10-11T10:00:00Z"}),
    ],
)
def test_missing_or_malformed_metadata_grants_no_credential_access(raw: str | None) -> None:
    assert parse_credential_annotation(raw) == frozenset()
