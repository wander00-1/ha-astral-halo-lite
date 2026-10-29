"""Halo Lite Gen2 BLE protocol: advertisement parsing + connected client.

The :class:`HaloLiteClient` operates on an already-connected bleak client
(Home Assistant establishes it via ``bleak_retry_connector``; a standalone
caller can pass a plain ``BleakClient``). All framing/crypto lives in
:mod:`.crypto`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
import logging

from .const import (
    ADV_ACCESS_CODE_LEN,
    ADV_ACCESS_CODE_OFFSET,
    ADV_UNIQUE_ID_OFFSET,
    CHAR_MASTER_AUTH,
    CHAR_RX_WRITE,
    CHAR_SESSION_KEY,
    CHAR_TX_NOTIFY,
    CMD_LIGHT_ACTIONS,
    CMD_LIGHT_STATE,
    CMD_TIMER_CAPS,
    CMD_TIMER_CONFIG,
    LIGHT_ACTION_AUTO,
    LIGHT_ACTION_OFF,
    LIGHT_ACTION_ON,
    LIGHT_ACTION_SET_EFFECT,
    MODE_OFF,
    OPCODE_ACTION,
    OPCODE_READ,
    TIMER_WRITE_MASK,
)
from .crypto import (
    build_frame,
    compute_auth,
    decrypt_characteristic,
    encrypt_characteristic,
    parse_frame,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class HaloAdvertisement:
    """Parsed manufacturer-specific advertisement data."""

    serial_number: int
    access_code: bytes

    @property
    def is_pairable(self) -> bool:
        """True only while the device advertises a real (usable) access code."""
        return is_valid_access_code(self.access_code)


def is_valid_access_code(code: bytes | None) -> bool:
    """A usable access code is 4 printable-ASCII bytes (e.g. ``b"TT84"``).

    The access-code field (advert offset 17) is all zeros outside the ~10 s
    power-on pairing window, so a ``!= 0`` test is not enough on its own.
    Requiring printable ASCII rejects the all-zero "not pairable" value.
    """
    return code is not None and len(code) == 4 and all(0x21 <= b <= 0x7E for b in code)


def parse_manufacturer_data(data: bytes) -> HaloAdvertisement | None:
    """Parse the Halo manufacturer-specific payload (company id stripped by HA)."""
    if len(data) < ADV_ACCESS_CODE_OFFSET + ADV_ACCESS_CODE_LEN:
        return None
    serial = int.from_bytes(
        data[ADV_UNIQUE_ID_OFFSET : ADV_UNIQUE_ID_OFFSET + 4], "little"
    )
    access_code = bytes(
        data[ADV_ACCESS_CODE_OFFSET : ADV_ACCESS_CODE_OFFSET + ADV_ACCESS_CODE_LEN]
    )
    return HaloAdvertisement(serial_number=serial, access_code=access_code)


@dataclass
class HaloLightState:
    """Current light state as reported by the device."""

    mode: int | None = None
    effect: int | None = None
    # Whether the light output is actually lit right now, reported separately
    # from mode (payload byte 8). This is what tells on-vs-off while in Auto.
    output_on: bool | None = None
    raw: bytes = field(default=b"", repr=False)

    @property
    def is_on(self) -> bool | None:
        # Prefer the real output flag so Auto reflects the schedule's current
        # on/off; fall back to the mode when the flag isn't known.
        if self.output_on is not None:
            return self.output_on
        if self.mode is None:
            return None
        return self.mode != MODE_OFF


@dataclass
class HaloTimer:
    """One light timer (a daily on/off schedule the device runs in Auto)."""

    index: int
    enabled: bool
    start_hour: int
    start_min: int
    stop_hour: int
    stop_min: int
    timer_type: int = 1
    season: int = 0


def parse_timer_config(payload: bytes) -> HaloTimer | None:
    """Parse a cmd-403 TimerConfiguration response payload."""
    if len(payload) < 12:
        return None
    return HaloTimer(
        timer_type=payload[0],
        index=payload[1],
        season=payload[2],
        enabled=bool(payload[3]),
        start_hour=payload[7],
        start_min=payload[8],
        stop_hour=payload[10],
        stop_min=payload[11],
    )


def build_timer_config(timer: HaloTimer) -> bytes:
    """Build the cmd-403 payload for an op-3 write (sets start/stop + enabled)."""
    p = bytearray(12)
    p[0] = timer.timer_type & 0xFF
    p[1] = timer.index & 0xFF
    p[2] = timer.season & 0xFF
    p[3] = 1 if timer.enabled else 0
    p[4] = TIMER_WRITE_MASK
    p[7] = timer.start_hour & 0xFF
    p[8] = timer.start_min & 0xFF
    p[10] = timer.stop_hour & 0xFF
    p[11] = timer.stop_min & 0xFF
    return bytes(p)


def parse_run_hours(payload: bytes) -> int | None:
    """Zone-1 light run hours from a cmd-602 StatisticsLightRunHours payload."""
    if len(payload) < 4:
        return None
    return int.from_bytes(payload[0:4], "little")


def parse_device_date(payload: bytes) -> tuple[int, int, int] | None:
    """Return (year, month, day) from a cmd-3 DeviceDate payload.

    Layout (from capture): [0]=day, [1]=month, [2]=year-2000, [3]=day-of-week.
    """
    if len(payload) < 3:
        return None
    day, month, year = payload[0], payload[1], payload[2] + 2000
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return year, month, day


class HaloLiteClient:
    """Drives the authenticated session and command/notify flow over an open client."""

    def __init__(self, client, access_code: bytes) -> None:
        self._client = client
        self._access_code = access_code
        self._session_key: bytes | None = None
        self._counter = 0
        self._authenticated = asyncio.Event()
        self.state = HaloLightState()
        self._listeners: list[Callable[[HaloLightState], None]] = []
        # Pending reads awaiting their response notify, keyed by cmd type.
        self._waiters: dict[int, asyncio.Future[bytes]] = {}

    # -- lifecycle ----------------------------------------------------------
    async def authenticate(self, timeout: float = 10.0) -> None:
        """Read the session key, enable notifications, write the auth value."""
        self._authenticated.clear()
        self._session_key = bytes(await self._client.read_gatt_char(CHAR_SESSION_KEY))
        if len(self._session_key) != 16:
            raise HaloProtocolError("unexpected session key length")
        await self._client.start_notify(CHAR_TX_NOTIFY, self._handle_notify)
        auth = compute_auth(self._session_key, self._access_code)
        await self._client.write_gatt_char(CHAR_MASTER_AUTH, auth, response=True)
        try:
            await asyncio.wait_for(self._authenticated.wait(), timeout)
        except TimeoutError as err:
            raise HaloAuthError(
                "device did not acknowledge authentication (check access code)"
            ) from err

    @property
    def is_authenticated(self) -> bool:
        return self._authenticated.is_set()

    def add_listener(self, cb: Callable[[HaloLightState], None]) -> Callable[[], None]:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb)

    # -- commands -----------------------------------------------------------
    async def turn_on(self) -> None:
        await self._action(LIGHT_ACTION_ON)

    async def turn_off(self) -> None:
        await self._action(LIGHT_ACTION_OFF)

    async def set_auto(self) -> None:
        await self._action(LIGHT_ACTION_AUTO)

    async def set_effect(self, effect: int) -> None:
        await self._action(LIGHT_ACTION_SET_EFFECT, effect)

    async def request_light_state(self) -> None:
        await self._send(OPCODE_READ, CMD_LIGHT_STATE)

    # -- timers -------------------------------------------------------------
    async def _request(
        self, opcode: int, cmd_type: int, payload: bytes = b"", timeout: float = 6.0
    ) -> bytes:
        """Send a read and wait for the matching response notify's payload."""
        if self._session_key is None:
            raise HaloProtocolError("not authenticated")
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[bytes] = loop.create_future()
        self._waiters[cmd_type] = fut
        try:
            await self._send(opcode, cmd_type, payload)
            return await asyncio.wait_for(fut, timeout)
        except TimeoutError as err:
            raise HaloProtocolError(f"no response for cmd {cmd_type}") from err
        finally:
            self._waiters.pop(cmd_type, None)

    async def read_characteristic(self, cmd_type: int) -> bytes:
        """Read a simple (no-parameter) characteristic and return its payload."""
        return await self._request(OPCODE_READ, cmd_type)

    async def read_timer_capabilities(self) -> bytes:
        return await self._request(OPCODE_READ, CMD_TIMER_CAPS)

    async def read_timer_config(
        self, timer_type: int, index: int, season: int
    ) -> bytes:
        req = bytes([timer_type & 0xFF, index & 0xFF, season & 0xFF])
        return await self._request(OPCODE_READ, CMD_TIMER_CONFIG, req)

    async def write_timer_config(self, payload: bytes) -> None:
        await self._send(OPCODE_ACTION, CMD_TIMER_CONFIG, payload)

    async def _action(self, action: int, param: int = 0) -> None:
        await self._send(
            OPCODE_ACTION, CMD_LIGHT_ACTIONS, bytes([action, 0x00, param & 0xFF])
        )

    async def _send(self, opcode: int, cmd_type: int, payload: bytes = b"") -> None:
        if self._session_key is None:
            raise HaloProtocolError("not authenticated")
        frame = build_frame(opcode, cmd_type, payload, self._counter)
        self._counter = (self._counter + 1) & 0xFF
        enc = encrypt_characteristic(frame, self._session_key)
        await self._client.write_gatt_char(CHAR_RX_WRITE, enc, response=True)

    # -- notifications ------------------------------------------------------
    def _handle_notify(self, _char, data: bytearray) -> None:
        if self._session_key is None or len(data) != 20:
            return
        try:
            plaintext = decrypt_characteristic(bytes(data), self._session_key)
        except Exception:  # noqa: BLE001 - never let a bad frame break the stream
            _LOGGER.debug("dropped inbound frame that failed to decrypt")
            return
        opcode, cmd_type, payload, _counter = parse_frame(plaintext)
        # First notify after the auth write means the device accepted us.
        if not self._authenticated.is_set():
            self._authenticated.set()
        # Hand the payload to any read awaiting this cmd type (timers, etc).
        waiter = self._waiters.get(cmd_type)
        if waiter is not None and not waiter.done():
            waiter.set_result(payload)
        if cmd_type == CMD_LIGHT_STATE and len(payload) >= 5:
            output_on = bool(payload[8]) if len(payload) > 8 else None
            self.state = HaloLightState(
                mode=payload[0],
                effect=payload[4],
                output_on=output_on,
                raw=payload,
            )
            for cb in list(self._listeners):
                cb(self.state)


class HaloProtocolError(Exception):
    """Base error for Halo protocol problems."""


class HaloAuthError(HaloProtocolError):
    """Authentication was not acknowledged by the device."""
