"""Protocol-layer tests: advertisement parsing and the connected client."""

from __future__ import annotations

import asyncio

import pytest

from halo_lite import const
from halo_lite.crypto import encrypt_characteristic
from halo_lite.protocol import (
    HaloLiteClient,
    HaloLightState,
    parse_manufacturer_data,
)

SESSION = bytes.fromhex("17825ad7af1e5e6a336035dacfe0853b")
ACCESS = b"TT84"

# Real advertisement manufacturer-specific payload (company id 0x0447 stripped),
# captured from HLITE2: serial 2813710 (0e ef 2a 00), access code 01 01 01 00.
#   03 00 00 01 00 00 | 0e ef 2a 00 | 01 01 01 00 | 01 00 3c 00 00 00 00 00 00
ADV = bytes.fromhex("0300000100000eef2a000101010001003c000000000000")


def test_parse_manufacturer_data():
    adv = parse_manufacturer_data(ADV)
    assert adv is not None
    assert adv.serial_number == 2813710
    assert adv.access_code == bytes.fromhex("01010100")
    assert adv.is_pairable is True


def test_parse_manufacturer_data_not_pairable():
    data = bytearray(ADV)
    data[const.ADV_ACCESS_CODE_OFFSET : const.ADV_ACCESS_CODE_OFFSET + 4] = b"\x00\x00\x00\x00"
    adv = parse_manufacturer_data(bytes(data))
    assert adv is not None
    assert adv.is_pairable is False


def test_parse_manufacturer_data_too_short():
    assert parse_manufacturer_data(b"\x00\x01\x02") is None


class FakeClient:
    """Minimal bleak-like client that records writes and replays notifies."""

    def __init__(self, session_key: bytes) -> None:
        self._session = session_key
        self.writes: list[tuple[str, bytes]] = []
        self.notify_cb = None

    async def read_gatt_char(self, _uuid):
        return bytearray(self._session)

    async def write_gatt_char(self, uuid, data, response=True):
        self.writes.append((uuid, bytes(data)))

    async def start_notify(self, _uuid, cb):
        self.notify_cb = cb


def _client(counter: int = 0) -> HaloLiteClient:
    c = HaloLiteClient(FakeClient(SESSION), ACCESS)
    c._session_key = SESSION  # noqa: SLF001 - test shortcut, skip the live handshake
    c._counter = counter  # noqa: SLF001
    return c


def test_turn_on_bytes_match_capture():
    c = _client(counter=0x0D)
    asyncio.run(c.turn_on())
    uuid, data = c._client.writes[-1]  # noqa: SLF001
    assert uuid == const.CHAR_RX_WRITE
    assert data.hex() == "38e718c96a917d32cca444bab54d0a39d0757653"


def test_turn_off_bytes_match_capture():
    c = _client(counter=0x14)
    asyncio.run(c.turn_off())
    assert c._client.writes[-1][1].hex() == "4f0c9292defb72d120470b798c9e337975f80b49"  # noqa: SLF001


def test_set_effect_bytes_match_capture():
    c = _client(counter=0x12)
    asyncio.run(c.set_effect(3))
    assert c._client.writes[-1][1].hex() == "7c7b61360763ebba4553f17735871159b43a2499"  # noqa: SLF001


def test_request_state_bytes_match_capture():
    c = _client(counter=0x08)
    asyncio.run(c.request_light_state())
    assert c._client.writes[-1][1].hex() == "d71e8840684e2ed5bee04aba640173909e69eaa6"  # noqa: SLF001


def test_counter_increments():
    c = _client(counter=0x00)
    asyncio.run(c.turn_on())
    asyncio.run(c.turn_on())
    assert c._counter == 0x02  # noqa: SLF001


def test_notify_updates_state_and_auth():
    c = HaloLiteClient(FakeClient(SESSION), ACCESS)
    c._session_key = SESSION  # noqa: SLF001
    updates: list[HaloLightState] = []
    c.add_listener(updates.append)

    # Device LightState response: mode=On(2) at payload[0], effect=4 at payload[4].
    pt = bytes.fromhex("012c0102000000040000000100000000000000ca")
    enc = encrypt_characteristic(pt, SESSION)
    c._handle_notify(None, bytearray(enc))  # noqa: SLF001

    assert c.is_authenticated is True
    assert c.state.mode == const.MODE_ON
    assert c.state.effect == 4
    assert c.state.is_on is True
    assert updates and updates[-1].effect == 4


def test_notify_ignores_bad_frame():
    c = HaloLiteClient(FakeClient(SESSION), ACCESS)
    c._session_key = SESSION  # noqa: SLF001
    c._handle_notify(None, bytearray(b"\x00" * 5))  # wrong length -> ignored
    assert c.state.mode is None


def test_send_without_session_raises():
    c = HaloLiteClient(FakeClient(SESSION), ACCESS)
    with pytest.raises(Exception):
        asyncio.run(c.turn_on())


def test_light_state_is_on_off():
    assert HaloLightState(mode=const.MODE_OFF).is_on is False
    assert HaloLightState(mode=const.MODE_ON).is_on is True
    assert HaloLightState(mode=None).is_on is None
