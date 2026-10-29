"""Connection/command coordinator for a Halo Lite device.

The device auto-disconnects after ~15-20s of idle, so rather than hold a
persistent link this connects on demand: establish -> authenticate -> run the
command -> read state -> disconnect, serialized behind a lock. State is cached
between operations and pushed to entities via listeners.

The access code the device accepts is only advertised during the ~10s window
after power-on (outside that window it advertises a placeholder). So the code
is *not* read live on every connect; instead a valid code is captured from
advertisements whenever one appears (``async_update_access_code``) and reused.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import logging

from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant, callback

from .const import CHAR_TX_NOTIFY
from .protocol import (
    HaloAuthError,
    HaloLightState,
    HaloLiteClient,
    HaloProtocolError,
    is_valid_access_code,
)

_LOGGER = logging.getLogger(__name__)

# How long to wait after a command for the device to push its new state.
_STATE_SETTLE = 1.5
_CONNECT_TIMEOUT = 20.0
# The device/BLE link is flaky (the official app sees this too): a connect,
# the auth handshake, or a command write can fail transiently. Retry the whole
# sequence a few times before giving up.
_MAX_ATTEMPTS = 3
_RETRY_BACKOFF = 1.0


class HaloLiteCoordinator:
    """Owns the on-demand connection, the captured access code and the state."""

    def __init__(
        self,
        hass: HomeAssistant,
        address: str,
        access_code: bytes | None,
        persist_access_code: Callable[[bytes], None] | None = None,
    ) -> None:
        self.hass = hass
        self.address = address
        self.access_code = access_code if is_valid_access_code(access_code) else None
        self._persist = persist_access_code
        self.state = HaloLightState()
        self._lock = asyncio.Lock()
        self._listeners: list[Callable[[], None]] = []

    @property
    def has_access_code(self) -> bool:
        return is_valid_access_code(self.access_code)

    @callback
    def async_add_listener(self, update_callback: Callable[[], None]) -> Callable[[], None]:
        """Register an entity update callback; returns an unsubscribe fn."""
        self._listeners.append(update_callback)

        def _remove() -> None:
            self._listeners.remove(update_callback)

        return _remove

    @callback
    def _async_notify_listeners(self) -> None:
        for update_callback in list(self._listeners):
            update_callback()

    @callback
    def async_update_access_code(self, code: bytes) -> None:
        """Capture a freshly advertised access code (ignores the placeholder)."""
        if not is_valid_access_code(code) or code == self.access_code:
            return
        _LOGGER.debug("captured new access code for %s", self.address)
        self.access_code = code
        if self._persist is not None:
            self._persist(code)
        self._async_notify_listeners()

    # -- high-level operations ---------------------------------------------
    async def async_turn_on(self) -> None:
        await self._run(lambda c: c.turn_on())

    async def async_turn_off(self) -> None:
        await self._run(lambda c: c.turn_off())

    async def async_set_effect(self, effect: int) -> None:
        await self._run(lambda c: c.set_effect(effect))

    async def async_refresh(self) -> None:
        await self._run(None)

    # -- connection plumbing -----------------------------------------------
    async def _run(
        self, action: Callable[[HaloLiteClient], Awaitable[None]] | None
    ) -> None:
        if not self.has_access_code:
            raise HaloAuthError(
                "no pairing code captured yet - power-cycle the Halo Lite so it "
                "advertises its access code (the ~10s window after power-on)"
            )
        async with self._lock:
            last_err: Exception | None = None
            for attempt in range(1, _MAX_ATTEMPTS + 1):
                try:
                    await self._attempt(action)
                    break
                except (
                    BleakError,
                    HaloProtocolError,
                    HaloConnectionError,
                    TimeoutError,
                    OSError,
                ) as err:
                    last_err = err
                    _LOGGER.debug(
                        "Halo command attempt %s/%s failed: %s",
                        attempt,
                        _MAX_ATTEMPTS,
                        err,
                    )
                    if attempt < _MAX_ATTEMPTS:
                        await asyncio.sleep(_RETRY_BACKOFF * attempt)
            else:
                assert last_err is not None
                raise last_err
        self._async_notify_listeners()

    async def _attempt(
        self, action: Callable[[HaloLiteClient], Awaitable[None]] | None
    ) -> None:
        """One connect -> authenticate -> command -> read-state cycle."""
        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if ble_device is None:
            raise HaloConnectionError(
                f"{self.address} not currently seen by any adapter"
            )

        client = await establish_connection(
            BleakClientWithServiceCache,
            ble_device,
            self.address,
            timeout=_CONNECT_TIMEOUT,
        )
        try:
            halo = HaloLiteClient(client, self.access_code)
            await halo.authenticate()
            if action is not None:
                await action(halo)
            await halo.request_light_state()
            await asyncio.sleep(_STATE_SETTLE)
            self.state = halo.state
        finally:
            try:
                await client.stop_notify(CHAR_TX_NOTIFY)
            except Exception:  # noqa: BLE001 - best effort on teardown
                pass
            await client.disconnect()


class HaloConnectionError(Exception):
    """Raised when the device cannot be reached."""
