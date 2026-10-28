"""Crypto/framing tests validated against real btsnoop-captured frames.

Ground truth from a live Halo Lite 2 session (serial 2813710):
  session key = 17825ad7af1e5e6a336035dacfe0853b   (read from char ...001)
  access code = "TT84" (0x54543834)                (from the advertisement)
  auth value  = 6457cdfe8dfcfb4796d5df663d53ce9f   (written to char ...002)
"""

from __future__ import annotations

import pytest

from halo_lite import const
from halo_lite.crypto import (
    build_frame,
    compute_auth,
    decrypt_characteristic,
    encrypt_characteristic,
    parse_frame,
)

SESSION = bytes.fromhex("17825ad7af1e5e6a336035dacfe0853b")
ACCESS = b"TT84"
AUTH = bytes.fromhex("6457cdfe8dfcfb4796d5df663d53ce9f")

# (name, encrypted-on-wire, decrypted-plaintext) captured frames.
FRAMES = [
    ("read_dev_info", "a724982db699778c0088ebef03f5c3e90ac290a0",
     "0201000000000000000000000000000000000000"),
    ("dev_info_resp", "f4874e347205e34460950c3f58feb4ed6182bc65",
     "0101000300000101010100000eef2a00000000bd"),
    ("read_light_state", "d71e8840684e2ed5bee04aba640173909e69eaa6",
     "022c010000000000000000000000000000000008"),
    ("turn_on", "38e718c96a917d32cca444bab54d0a39d0757653",
     "03f501010000000000000000000000000000000d"),
    ("set_colour_3", "7c7b61360763ebba4553f17735871159b43a2499",
     "03f5010500030000000000000000000000000012"),
    ("turn_off", "4f0c9292defb72d120470b798c9e337975f80b49",
     "03f5010300000000000000000000000000000014"),
]


def test_compute_auth_matches_capture():
    assert compute_auth(SESSION, ACCESS) == AUTH


def test_compute_auth_rejects_bad_session_length():
    with pytest.raises(ValueError):
        compute_auth(b"\x00" * 15, ACCESS)


@pytest.mark.parametrize("name,enc,pt", FRAMES, ids=[f[0] for f in FRAMES])
def test_decrypt_matches_capture(name, enc, pt):
    assert decrypt_characteristic(bytes.fromhex(enc), SESSION).hex() == pt


@pytest.mark.parametrize("name,enc,pt", FRAMES, ids=[f[0] for f in FRAMES])
def test_encrypt_matches_capture(name, enc, pt):
    assert encrypt_characteristic(bytes.fromhex(pt), SESSION).hex() == enc


@pytest.mark.parametrize("name,enc,pt", FRAMES, ids=[f[0] for f in FRAMES])
def test_round_trip(name, enc, pt):
    data = bytes.fromhex(pt)
    assert decrypt_characteristic(encrypt_characteristic(data, SESSION), SESSION) == data


def test_dev_info_contains_serial():
    # The decoded device-info response embeds the serial number as uint32 LE.
    pt = decrypt_characteristic(bytes.fromhex(FRAMES[1][1]), SESSION)
    _op, _cmd, payload, _cnt = parse_frame(pt)
    serial = int.from_bytes(payload[9:13], "little")
    assert serial == 2813710


def test_build_frame_turn_on():
    frame = build_frame(
        const.OPCODE_ACTION,
        const.CMD_LIGHT_ACTIONS,
        bytes([const.LIGHT_ACTION_ON, 0, 0]),
        0x0D,
    )
    assert frame.hex() == "03f501010000000000000000000000000000000d"
    assert encrypt_characteristic(frame, SESSION).hex() == FRAMES[3][1]


def test_build_frame_set_colour():
    frame = build_frame(
        const.OPCODE_ACTION,
        const.CMD_LIGHT_ACTIONS,
        bytes([const.LIGHT_ACTION_SET_EFFECT, 0, 3]),
        0x12,
    )
    assert encrypt_characteristic(frame, SESSION).hex() == FRAMES[4][1]


def test_build_frame_turn_off():
    frame = build_frame(
        const.OPCODE_ACTION,
        const.CMD_LIGHT_ACTIONS,
        bytes([const.LIGHT_ACTION_OFF, 0, 0]),
        0x14,
    )
    assert encrypt_characteristic(frame, SESSION).hex() == FRAMES[5][1]


def test_build_frame_read_state():
    frame = build_frame(const.OPCODE_READ, const.CMD_LIGHT_STATE, b"", 0x08)
    assert encrypt_characteristic(frame, SESSION).hex() == FRAMES[2][1]


def test_parse_frame():
    op, cmd, payload, counter = parse_frame(bytes.fromhex(FRAMES[4][2]))
    assert op == const.OPCODE_ACTION
    assert cmd == const.CMD_LIGHT_ACTIONS
    assert payload[0] == const.LIGHT_ACTION_SET_EFFECT
    assert payload[2] == 3
    assert counter == 0x12


def test_build_frame_rejects_oversized_payload():
    with pytest.raises(ValueError):
        build_frame(const.OPCODE_ACTION, const.CMD_LIGHT_ACTIONS, b"\x00" * 17, 0)
