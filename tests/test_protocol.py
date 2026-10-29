"""Protocol-layer tests: advertisement parsing and the connected client."""

from __future__ import annotations

import asyncio

import pytest

from halo_lite import const
from halo_lite.crypto import decrypt_characteristic, encrypt_characteristic, parse_frame
from halo_lite.protocol import (
    HaloLiteClient,
    HaloLightState,
    HaloTimer,
    build_timer_config,
    is_valid_access_code,
    parse_device_date,
    parse_manufacturer_data,
    parse_run_hours,
    parse_timer_config,
)

SESSION = bytes.fromhex("17825ad7af1e5e6a336035dacfe0853b")
ACCESS = b"TT84"

# Real advertisement manufacturer-specific payloads (company id 0x0447
# stripped), captured from HLITE2 serial 2813710 (0e ef 2a 00). The real
# access code lives at offset 17, NOT in the fixed 01 01 01 00 field at 10-13.
#   steady:  ...2a 00 | 01 01 01 00 | 01 00 3c | 00 00 00 00 | 00 00   (zeros @17)
#   pairing: ...2a 00 | 01 01 01 00 | 01 00 00 | 54 54 38 34 | 00 00   ("TT84" @17)
ADV = bytes.fromhex("0300000100000eef2a000101010001003c000000000000")
ADV_PAIRING = bytes.fromhex("0300000100000eef2a0001010100010000545438340000")


def test_parse_manufacturer_data_steady_state_not_pairable():
    # At offset 17 the code field is all zeros when not in the pairing window.
    adv = parse_manufacturer_data(ADV)
    assert adv is not None
    assert adv.serial_number == 2813710
    assert adv.access_code == bytes.fromhex("00000000")
    assert adv.is_pairable is False


def test_parse_manufacturer_data_pairing_window_real_code():
    # The real code TT84 appears at offset 17 during the power-on window.
    adv = parse_manufacturer_data(ADV_PAIRING)
    assert adv is not None
    assert adv.serial_number == 2813710
    assert adv.access_code == b"TT84"
    assert adv.is_pairable is True


def test_parse_ignores_fixed_01010100_field():
    # Bytes 10-13 are always 01 01 01 00 and must NOT be read as the code.
    assert ADV[10:14] == bytes.fromhex("01010100")
    assert ADV_PAIRING[10:14] == bytes.fromhex("01010100")
    assert parse_manufacturer_data(ADV).access_code != bytes.fromhex("01010100")


def test_is_valid_access_code():
    assert is_valid_access_code(b"TT84") is True
    assert is_valid_access_code(b"AB12") is True
    assert is_valid_access_code(bytes.fromhex("01010100")) is False  # fixed field
    assert is_valid_access_code(b"\x00\x00\x00\x00") is False
    assert is_valid_access_code(b"TT8") is False  # wrong length
    assert is_valid_access_code(None) is False


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


def test_set_auto_frame_uses_action_2():
    # No capture of Auto exists, so assert the decoded frame rather than bytes:
    # op=3 (action), cmd=501 (LightAppActions), payload[0]=2 (SetZoneModeToAuto).
    c = _client(counter=0x20)
    asyncio.run(c.set_auto())
    enc = c._client.writes[-1][1]  # noqa: SLF001
    op, cmd, payload, counter = parse_frame(decrypt_characteristic(enc, SESSION))
    assert op == const.OPCODE_ACTION
    assert cmd == const.CMD_LIGHT_ACTIONS
    assert payload[0] == const.LIGHT_ACTION_AUTO == 0x02
    assert counter == 0x20


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


def test_parse_timer_config_from_capture():
    # Real cmd-403 response for timer idx0: enabled, start 18:00, stop 21:00.
    payload = bytes.fromhex("01000001000000120000150000000000")
    t = parse_timer_config(payload)
    assert t is not None
    assert t.index == 0 and t.timer_type == 1 and t.season == 0
    assert t.enabled is True
    assert (t.start_hour, t.start_min) == (18, 0)
    assert (t.stop_hour, t.stop_min) == (21, 0)


def test_build_timer_config_matches_capture_write():
    # The captured edit: timer 0 enabled, start 18:05, stop 21:05 (op-3 write).
    captured = bytes.fromhex("010000010f0000120500150500000000")
    t = HaloTimer(
        index=0, enabled=True, start_hour=18, start_min=5, stop_hour=21, stop_min=5
    )
    built = build_timer_config(t)
    assert built == captured[: len(built)]
    assert built[4] == 0x0F  # write field-mask


def test_timer_config_round_trip():
    t = HaloTimer(
        index=1, enabled=False, start_hour=6, start_min=30, stop_hour=9, stop_min=45
    )
    back = parse_timer_config(build_timer_config(t))
    assert back is not None
    assert (back.index, back.enabled) == (1, False)
    assert (back.start_hour, back.start_min) == (6, 30)
    assert (back.stop_hour, back.stop_min) == (9, 45)


def test_parse_timer_config_too_short():
    assert parse_timer_config(b"\x01\x00\x00") is None


def test_parse_run_hours_from_capture():
    # cmd-602 StatisticsLightRunHours: 59 02 00 00 (LE) = 601 hours.
    assert parse_run_hours(bytes.fromhex("59020000000000000000000000000000")) == 601
    assert parse_run_hours(b"\x00\x00") is None


def test_parse_device_date_from_capture():
    # cmd-3 DeviceDate: 1e 0a 1a 05 -> day 30, month 10, year 2026.
    assert parse_device_date(bytes.fromhex("1e0a1a05000000000000000000000000")) == (
        2026,
        10,
        30,
    )
    assert parse_device_date(b"\x00\x00\x1a") is None  # month 0 invalid


def test_light_state_is_on_off():
    assert HaloLightState(mode=const.MODE_OFF).is_on is False
    assert HaloLightState(mode=const.MODE_ON).is_on is True
    assert HaloLightState(mode=None).is_on is None


def test_output_flag_drives_is_on_in_auto():
    # In Auto the schedule decides on/off; the output flag (payload byte 8)
    # is what should drive is_on, overriding the mode-based fallback.
    assert HaloLightState(mode=const.MODE_AUTO, output_on=True).is_on is True
    assert HaloLightState(mode=const.MODE_AUTO, output_on=False).is_on is False
    # Fallback to mode when the flag isn't known.
    assert HaloLightState(mode=const.MODE_AUTO, output_on=None).is_on is True


def test_notify_parses_output_flag():
    c = HaloLiteClient(FakeClient(SESSION), ACCESS)
    c._session_key = SESSION  # noqa: SLF001
    # LightState: mode=Auto(1) at [0], effect=0 at [4], output-on=0 at [8].
    pt = bytes.fromhex("012c0101000000000000000000000000000000ca")
    c._handle_notify(None, bytearray(encrypt_characteristic(pt, SESSION)))  # noqa: SLF001
    assert c.state.mode == const.MODE_AUTO
    assert c.state.output_on is False
    assert c.state.is_on is False  # Auto but currently off per the schedule
