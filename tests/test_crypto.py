"""Crypto/framing tests.

The implementation was validated byte-for-byte against a real btsnoop
capture. The vectors below are derived from that capture, with the
device identifiers replaced by dummy values and every frame re-encrypted
under the dummy session key. They are not from a real device:
  session key = a1b2c3d4e5f60718293a4b5c6d7e8f90   (dummy; read from char ...001)
  access code = "XY34" (0x58593334)                (dummy; from the advertisement)
  auth value  = 53d03c479fa36818cd2fab80987f83c9   (derived; written to char ...002)
  serial      = 1234567                            (dummy)
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

SESSION = bytes.fromhex("a1b2c3d4e5f60718293a4b5c6d7e8f90")
ACCESS = b"XY34"
AUTH = bytes.fromhex("53d03c479fa36818cd2fab80987f83c9")

# (name, encrypted-on-wire, decrypted-plaintext) frames, derived from a capture.
FRAMES = [
    ("read_dev_info", "3f8d668e1b247f7ee232aabdba5b8bc9b57cd833",
     "0201000000000000000000000000000000000000"),
    ("dev_info_resp", "5ad4a8cb1fca3e25815eb7f5d14acf66faab3167",
     "01010003000001010101000087d61200000000bd"),
    ("read_light_state", "867c9e0fb17509d71c03c976e45c5ca09664727c",
     "022c010000000000000000000000000000000008"),
    ("turn_on", "f12a998bd69c964b6cadd6ce37d0fe8d9e0e8804",
     "03f501010000000000000000000000000000000d"),
    ("set_colour_3", "849b86eee3958751cdf4f0f6776ff5233436520c",
     "03f5010500030000000000000000000000000012"),
    ("turn_off", "15c97ba95c26760d3d73886d906296cfabdec64c",
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
    assert serial == 1234567


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
