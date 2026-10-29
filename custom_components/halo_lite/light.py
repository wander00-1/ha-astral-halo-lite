"""Light platform for the Astral Pool Halo Lite."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_EFFECT,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HaloConfigEntry
from .const import CONF_SERIAL, DOMAIN, EFFECT_NAMES
from .coordinator import HaloLiteCoordinator

_EFFECT_BY_NAME = {name: idx for idx, name in EFFECT_NAMES.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HaloConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Halo Lite light."""
    async_add_entities([HaloLiteLight(entry.runtime_data, entry)])


class HaloLiteLight(LightEntity):
    """A single Halo Lite pool light."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_effect_list = list(EFFECT_NAMES.values())

    def __init__(self, coordinator: HaloLiteCoordinator, entry: HaloConfigEntry) -> None:
        self.coordinator = coordinator
        self._attr_unique_id = entry.data[CONF_ADDRESS]
        serial = entry.data.get(CONF_SERIAL)
        self._attr_device_info = DeviceInfo(
            connections={(dr.CONNECTION_BLUETOOTH, coordinator.address)},
            identifiers={(DOMAIN, coordinator.address)},
            manufacturer="Astral Pool / Fabtronics",
            model="Halo Lite 2",
            name=entry.title,
            serial_number=str(serial) if serial else None,
        )

    async def async_added_to_hass(self) -> None:
        """Register for coordinator updates and do a best-effort initial read."""
        self.async_on_remove(self.coordinator.async_add_listener(self._handle_update))
        self.hass.async_create_background_task(
            self._async_initial_refresh(), name="halo_lite_initial_refresh"
        )

    async def _async_initial_refresh(self) -> None:
        if not self.coordinator.has_access_code:
            return  # nothing to do until the access code is captured
        try:
            await self.coordinator.async_refresh()
        except Exception:  # noqa: BLE001 - device may simply be out of range at startup
            pass

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        # Until the pairing code has been captured we cannot control the light.
        return self.coordinator.has_access_code

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.state.is_on

    @property
    def effect(self) -> str | None:
        effect = self.coordinator.state.effect
        return EFFECT_NAMES.get(effect) if effect is not None else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on, optionally selecting an effect."""
        effect_name = kwargs.get(ATTR_EFFECT)
        if effect_name is not None and effect_name in _EFFECT_BY_NAME:
            await self.coordinator.async_set_effect(_EFFECT_BY_NAME[effect_name])
            return
        await self.coordinator.async_turn_on()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off."""
        await self.coordinator.async_turn_off()
