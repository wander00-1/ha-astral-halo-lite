"""Per-timer enabled switches for the Astral Pool Halo Lite."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HaloConfigEntry
from .const import CONF_SERIAL, DEFAULT_TIMER_COUNT, DOMAIN
from .coordinator import HaloLiteCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HaloConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up an enabled switch for each timer."""
    coordinator = entry.runtime_data
    async_add_entities(
        HaloTimerSwitch(coordinator, entry, i) for i in range(DEFAULT_TIMER_COUNT)
    )


class HaloTimerSwitch(SwitchEntity):
    """Enable/disable one Halo Lite timer."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: HaloLiteCoordinator, entry: HaloConfigEntry, index: int
    ) -> None:
        self.coordinator = coordinator
        self._index = index
        self._attr_translation_key = "timer_enabled"
        self._attr_translation_placeholders = {"number": str(index + 1)}
        self._attr_unique_id = f"{entry.data[CONF_ADDRESS]}_timer{index}_enabled"
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
        self.async_on_remove(self.coordinator.async_add_listener(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return self.coordinator.has_access_code and self._index in self.coordinator.timers

    @property
    def is_on(self) -> bool | None:
        timer = self.coordinator.timers.get(self._index)
        return timer.enabled if timer is not None else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_timer(self._index, enabled=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_timer(self._index, enabled=False)
