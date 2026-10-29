"""The Astral Pool Halo Lite integration."""

from __future__ import annotations

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

PLATFORMS: list[Platform] = [Platform.LIGHT]

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

    # Capture the real access code whenever it is advertised (power-on window).
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

    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            _on_advertisement,
            BluetoothCallbackMatcher(address=address),
            bluetooth.BluetoothScanningMode.ACTIVE,
        )
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HaloConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
