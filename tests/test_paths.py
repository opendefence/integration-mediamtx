"""Reject path and identity aliases before they can enter authorization."""

import base64
from uuid import UUID

import pytest

from opendefence_integration_mediamtx.paths import (
    StreamPath,
    encode_user_id,
    parse_path,
    parse_stream_id,
    parse_user_id,
)

OWNER = UUID("00000000-0000-4000-8000-000000000001")
COMPACT_OWNER = "AAAAAAAAQACAAAAAAAAAAQ"
PATH = f"live/ipcam/{COMPACT_OWNER}"


def test_core_text_and_compact_ids_have_one_identity() -> None:
    assert encode_user_id(OWNER) == COMPACT_OWNER
    assert parse_user_id(str(OWNER)) == parse_user_id(COMPACT_OWNER) == OWNER


@pytest.mark.parametrize("value", [0, 1, 2**128 - 1])
@pytest.mark.parametrize("tool", ["icu", "gopro", "uas", "ipcam"])
def test_paths_and_stream_ids_round_trip(tool: str, value: int) -> None:
    path = StreamPath(tool=tool, owner_id=UUID(int=value))
    assert parse_path(str(path)) == parse_stream_id(path.stream_id) == path
    assert "=" not in path.stream_id


@pytest.mark.parametrize(
    "value",
    [
        "",
        "ALPHA",
        "{00000000-0000-4000-8000-000000000001}",
        "00000000000040008000000000000001",
        "01234567-89AB-CDEF-0123-456789ABCDEF",
        COMPACT_OWNER + "=",
        COMPACT_OWNER[:-1] + "R",  # Same decoded bytes with nonzero padding bits.
        COMPACT_OWNER[:-1] + "+",
        " " + COMPACT_OWNER,
        COMPACT_OWNER + "\n",
    ],
)
def test_rejects_noncanonical_user_ids(value: str) -> None:
    with pytest.raises(ValueError):
        parse_user_id(value)


@pytest.mark.parametrize(
    "value",
    [
        "",
        PATH + "2",
        PATH + "/",
        PATH + "/channel",
        PATH.replace("live/", "live//"),
        PATH.replace("ipcam", "."),
        PATH.replace("ipcam", ".."),
        PATH.replace("ipcam", "unknown"),
        PATH.replace("ipcam", "IPCAM"),
        PATH.replace("/ipcam/", "%2Fipcam/"),
        PATH.replace("/ipcam/", "%2fipcam/"),
        PATH.replace("/ipcam/", "%252Fipcam/"),
        PATH.replace(COMPACT_OWNER, str(OWNER)),
        PATH.replace(COMPACT_OWNER, COMPACT_OWNER[:-1] + "R"),
        PATH + "?password=secret",
        PATH + "#fragment",
        "/" + PATH,
        "live/ipcam/" + "A" * 193,
    ],
)
def test_rejects_ambiguous_paths(value: str) -> None:
    with pytest.raises(ValueError):
        parse_path(value)


@pytest.mark.parametrize(
    "value",
    [
        "s2_bGl2ZQ",
        "s1_",
        StreamPath(tool="ipcam", owner_id=OWNER).stream_id + "=",
        "s1_A",
        "s1_" + "A" * 257,
        "s1_" + base64.urlsafe_b64encode((PATH + "/channel").encode()).decode().rstrip("="),
        "s1_" + base64.urlsafe_b64encode("live/ipcam/é".encode()).decode().rstrip("="),
    ],
)
def test_stream_id_does_not_hide_an_invalid_path(value: str) -> None:
    with pytest.raises(ValueError):
        parse_stream_id(value)
