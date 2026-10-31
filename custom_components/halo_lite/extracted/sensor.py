"""Diagnostic sensors for the Astral Pool Halo Lite."""

from __future__ import annotations

from datetime import date

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import CONF_ADDRESS, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HaloConfigEntry
from .const import CONF_SERIAL, DOMAIN
from .coordinator import HaloLiteCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HaloConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the diagnostic sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        [HaloRunHoursSensor(coordinator, entry), HaloDeviceDateSensor(coordinator, entry)]
    )


class _HaloSensorBase(SensorEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: HaloLiteCoordinator, entry: HaloConfigEntry) -> None:
        self.coordinator = coordinator
        serial = entry.data.get(CONF_SERIAL)
        self._attr_device_info = DeviceInfo(
            connections={(dr.CONNECTION_BLUETOOTH, coordinator.address)},
            identifiers={(DOMAIN, coordinator.address)},
            manufacturer="Astral Pool / Fabtronics",
            model="Halo Lite 2",
            name=entry.title,
            serial_number=str(serial) if serial else None,
        )
        self._base_unique = entry.data[CONF_ADDRESS]

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.coordinator.async_add_listener(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return self.coordinator.has_access_code


class HaloRunHoursSensor(_HaloSensorBase):
    """Lifetime light run hours (zone 1)."""

    _attr_translation_key = "run_hours"
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator: HaloLiteCoordinator, entry: HaloConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._base_unique}_run_hours"

    @property
    def native_value(self) -> int | None:
        return self.coordinator.run_hours


class HaloDeviceDateSensor(_HaloSensorBase):
    """The device's own calendar date (the clock the timers run on)."""

    _attr_translation_key = "device_date"
    _attr_device_class = SensorDeviceClass.DATE

    def __init__(self, coordinator: HaloLiteCoordinator, entry: HaloConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self._base_unique}_device_date"

    @property
    def native_value(self) -> date | None:
        return self.coordinator.device_date
