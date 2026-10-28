"""The Astral Pool Halo Lite integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant

from .const import CONF_ACCESS_CODE
from .coordinator import HaloLiteCoordinator

PLATFORMS: list[Platform] = [Platform.LIGHT]

type HaloConfigEntry = ConfigEntry[HaloLiteCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: HaloConfigEntry) -> bool:
    """Set up Halo Lite from a config entry."""
    address: str = entry.data[CONF_ADDRESS]
    access_code = bytes.fromhex(entry.data[CONF_ACCESS_CODE])

    coordinator = HaloLiteCoordinator(hass, address, access_code)
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HaloConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
