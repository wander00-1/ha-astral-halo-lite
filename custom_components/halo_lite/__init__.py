"""The Astral Pool Halo Lite integration."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothCallbackMatcher,
    BluetoothChange,
    BluetoothServiceInfoBleak,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant, callback

from .const import CONF_ACCESS_CODE, MANUFACTURER_ID
from .coordinator import HaloLiteCoordinator
from .protocol import is_valid_access_code, parse_manufacturer_data

PLATFORMS: list[Platform] = [
    Platform.LIGHT,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TIME,
]

type HaloConfigEntry = ConfigEntry[HaloLiteCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: HaloConfigEntry) -> bool:
    """Set up Halo Lite from a config entry."""
    address: str = entry.data[CONF_ADDRESS]
    stored = entry.data.get(CONF_ACCESS_CODE)
    access_code = bytes.fromhex(stored) if stored else None

    @callback
    def _persist(code: bytes) -> None:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_ACCESS_CODE: code.hex()}
        )

    coordinator = HaloLiteCoordinator(hass, address, access_code, _persist)
    entry.runtime_data = coordinator

    # The access code is fixed per unit, so we only need to catch it once (in
    # the ~10s power-on advertising window). If we don't have it yet, listen
    # for an advertisement that carries it, then stop listening. If we already
    # have one, don't listen at all - nothing to capture.
    if not coordinator.has_access_code:
        cancel: list[Callable[[], None]] = []

        @callback
        def _stop_listening() -> None:
            while cancel:
                cancel.pop()()

        @callback
        def _on_advertisement(
            service_info: BluetoothServiceInfoBleak, change: BluetoothChange
        ) -> None:
            raw = service_info.manufacturer_data.get(MANUFACTURER_ID)
            if raw is None:
                return
            adv = parse_manufacturer_data(raw)
            if adv is not None and is_valid_access_code(adv.access_code):
                coordinator.async_update_access_code(adv.access_code)
                # Captured once; the code never changes, so stop listening.
                _stop_listening()

        cancel.append(
            bluetooth.async_register_callback(
                hass,
                _on_advertisement,
                BluetoothCallbackMatcher(address=address),
                bluetooth.BluetoothScanningMode.ACTIVE,
            )
        )
        entry.async_on_unload(_stop_listening)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Read the timer schedule once in the background so the timer entities
    # populate without blocking setup.
    if coordinator.has_access_code:

        async def _initial_timer_read() -> None:
            try:
                await coordinator.async_read_timers()
            except Exception:  # noqa: BLE001 - device may be out of range
                pass

        entry.async_create_background_task(
            hass, _initial_timer_read(), "halo_lite_timer_init"
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: HaloConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
