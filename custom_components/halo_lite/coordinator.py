"""Connection/command coordinator for a Halo Lite device.

The device auto-disconnects after ~15-20s of idle, so rather than hold a
persistent link this connects on demand: establish -> authenticate -> run the
command -> read state -> disconnect, serialized behind a lock. State is cached
between operations and pushed to entities via listeners.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import logging

from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant, callback

from .const import CHAR_TX_NOTIFY, MANUFACTURER_ID
from .protocol import HaloLightState, HaloLiteClient, parse_manufacturer_data

_LOGGER = logging.getLogger(__name__)

# How long to wait after a command for the device to push its new state.
_STATE_SETTLE = 1.5
_CONNECT_TIMEOUT = 20.0


class HaloLiteCoordinator:
    """Owns the on-demand connection and the cached light state."""

    def __init__(self, hass: HomeAssistant, address: str, access_code: bytes) -> None:
        self.hass = hass
        self.address = address
        self.access_code = access_code
        self.state = HaloLightState()
        self._lock = asyncio.Lock()
        self._listeners: list[Callable[[], None]] = []

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
    def _async_current_access_code(self) -> bytes:
        """Return the access code from the latest advertisement.

        The code changes on power-cycle, so prefer the live advertised value
        and fall back to the one stored at setup.
        """
        info = bluetooth.async_last_service_info(
            self.hass, self.address, connectable=True
        )
        if info is not None:
            raw = info.manufacturer_data.get(MANUFACTURER_ID)
            if raw is not None:
                adv = parse_manufacturer_data(raw)
                if adv is not None and adv.is_pairable:
                    self.access_code = adv.access_code  # keep the fallback fresh
                    return adv.access_code
        return self.access_code

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
        async with self._lock:
            ble_device = bluetooth.async_ble_device_from_address(
                self.hass, self.address, connectable=True
            )
            if ble_device is None:
                raise HaloConnectionError(f"{self.address} not currently seen by any adapter")

            client = await establish_connection(
                BleakClientWithServiceCache,
                ble_device,
                self.address,
                timeout=_CONNECT_TIMEOUT,
            )
            try:
                halo = HaloLiteClient(client, self._async_current_access_code())
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
        self._async_notify_listeners()


class HaloConnectionError(Exception):
    """Raised when the device cannot be reached."""
