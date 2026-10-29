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
    LIGHT_ACTION_OFF,
    LIGHT_ACTION_ON,
    LIGHT_ACTION_SET_EFFECT,
    MODE_OFF,
    OPCODE_ACTION,
    OPCODE_READ,
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

    Outside the ~10 s power-on pairing window the device advertises a
    placeholder (``01 01 01 00``) rather than its real code, so a ``!= 0``
    test is not enough. Requiring printable ASCII rejects both the
    placeholder and the all-zero "not pairable" value.
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
    raw: bytes = field(default=b"", repr=False)

    @property
    def is_on(self) -> bool | None:
        if self.mode is None:
            return None
        return self.mode != MODE_OFF


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

    async def set_effect(self, effect: int) -> None:
        await self._action(LIGHT_ACTION_SET_EFFECT, effect)

    async def request_light_state(self) -> None:
        await self._send(OPCODE_READ, CMD_LIGHT_STATE)

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
        if cmd_type == CMD_LIGHT_STATE and len(payload) >= 5:
            self.state = HaloLightState(
                mode=payload[0], effect=payload[4], raw=payload
            )
            for cb in list(self._listeners):
                cb(self.state)


class HaloProtocolError(Exception):
    """Base error for Halo protocol problems."""


class HaloAuthError(HaloProtocolError):
    """Authentication was not acknowledged by the device."""
