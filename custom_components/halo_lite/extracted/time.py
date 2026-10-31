"""Timer start/stop time entities for the Astral Pool Halo Lite."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
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
    """Set up start/stop time entities for each timer."""
    coordinator = entry.runtime_data
    entities: list[TimeEntity] = []
    for i in range(DEFAULT_TIMER_COUNT):
        entities.append(HaloTimerTime(coordinator, entry, i, is_start=True))
        entities.append(HaloTimerTime(coordinator, entry, i, is_start=False))
    async_add_entities(entities)


class HaloTimerTime(TimeEntity):
    """Start or stop time of one Halo Lite timer."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HaloLiteCoordinator,
        entry: HaloConfigEntry,
        index: int,
        *,
        is_start: bool,
    ) -> None:
        self.coordinator = coordinator
        self._index = index
        self._is_start = is_start
        kind = "start" if is_start else "stop"
        self._attr_translation_key = f"timer_{kind}"
        self._attr_translation_placeholders = {"number": str(index + 1)}
        self._attr_unique_id = f"{entry.data[CONF_ADDRESS]}_timer{index}_{kind}"
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
    def native_value(self) -> time | None:
        timer = self.coordinator.timers.get(self._index)
        if timer is None:
            return None
        if self._is_start:
            return time(hour=timer.start_hour, minute=timer.start_min)
        return time(hour=timer.stop_hour, minute=timer.stop_min)

    async def async_set_value(self, value: time) -> None:
        if self._is_start:
            await self.coordinator.async_set_timer(
                self._index, start=(value.hour, value.minute)
            )
        else:
            await self.coordinator.async_set_timer(
                self._index, stop=(value.hour, value.minute)
            )
