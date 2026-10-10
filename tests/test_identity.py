"""Core owns authentication; reject ambiguous identity at the header boundary."""

from uuid import UUID

import pytest

from opendefence_integration_mediamtx.identity import DEFAULT_USER_UUID_HEADER, user_id_from_headers
from opendefence_integration_mediamtx.paths import encode_user_id

SUBJECT = UUID("01234567-89ab-cdef-0123-456789abcdef")
OTHER = UUID("01234567-89ab-cdef-0123-456789abcdea")


@pytest.mark.parametrize("value", [str(SUBJECT), encode_user_id(SUBJECT)])
def test_accepts_one_case_insensitive_core_header(value: str) -> None:
    headers = [("authorization", "Basic ignored"), (DEFAULT_USER_UUID_HEADER.lower(), value)]
    assert user_id_from_headers(headers) == SUBJECT


def test_configured_header_replaces_default_without_alias_fallback() -> None:
    headers = [(DEFAULT_USER_UUID_HEADER, str(OTHER)), ("X-Core-Subject", str(SUBJECT))]
    assert user_id_from_headers(headers, header_name="X-Core-Subject") == SUBJECT
    with pytest.raises(ValueError):
        user_id_from_headers(headers[:1], header_name="X-Core-Subject")


@pytest.mark.parametrize(
    "headers",
    [
        [],
        [("X-ClientCert-DN", f"CN={SUBJECT}")],
        [("Authorization", "Basic ignored")],
        [(DEFAULT_USER_UUID_HEADER, str(SUBJECT)), (DEFAULT_USER_UUID_HEADER.lower(), str(OTHER))],
        [(DEFAULT_USER_UUID_HEADER, str(SUBJECT)), (DEFAULT_USER_UUID_HEADER.upper(), str(SUBJECT))],
        [(DEFAULT_USER_UUID_HEADER, f"{SUBJECT},{OTHER}")],
        [(DEFAULT_USER_UUID_HEADER, str(SUBJECT) + " ")],
        [(DEFAULT_USER_UUID_HEADER, " " + str(SUBJECT))],
        [(DEFAULT_USER_UUID_HEADER, str(SUBJECT).upper())],
        [(DEFAULT_USER_UUID_HEADER, "")],
        [(DEFAULT_USER_UUID_HEADER, "ALPHA")],
        [(DEFAULT_USER_UUID_HEADER, encode_user_id(SUBJECT) + "=")],
        [(DEFAULT_USER_UUID_HEADER, "secret-do-not-echo\r\nInjected: value")],
    ],
)
def test_rejects_missing_ambiguous_or_noncanonical_identity(headers: list[tuple[str, str]]) -> None:
    with pytest.raises(ValueError) as error:
        user_id_from_headers(headers)
    assert "secret-do-not-echo" not in str(error.value)


@pytest.mark.parametrize("header_name", ["", "X Subject", "X-Subject:", "X-Subject\n", "X-Üser"])
def test_rejects_invalid_header_configuration(header_name: str) -> None:
    with pytest.raises(ValueError, match="configuration"):
        user_id_from_headers([], header_name=header_name)
