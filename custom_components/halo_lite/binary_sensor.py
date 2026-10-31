"""Advertisement-presence binary sensor for Astral Pool Halo Lite devices."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components import bluetooth
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.components.bluetooth import (
    BluetoothCallbackMatcher,
    BluetoothChange,
    BluetoothServiceInfoBleak,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from . import HaloConfigEntry
from .const import CONF_SERIAL, DOMAIN

# These devices only advertise over BLE while powered on (a Viron pump is
# powered by, and advertises through, the chlorinator), so "no advertisement
# for a while" means off. Flag off after this long without an advertisement,
# checked on a shorter cadence so the off edge lands within CHECK_INTERVAL of
# that point. The gap absorbs a few missed advertisements without flapping.
OFF_AFTER = timedelta(seconds=150)
CHECK_INTERVAL = timedelta(seconds=30)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HaloConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the advertisement-presence binary sensor."""
    async_add_entities([HaloAdvertisingBinarySensor(entry)])


class HaloAdvertisingBinarySensor(BinarySensorEntity):
    """On while the device is advertising over BLE.

    A device like the Viron pump only advertises while it is powered on, so the
    presence of its advertisement is a reliable "running" signal. This is
    entirely passive: it listens for advertisements and never connects to the
    device, so it never contends for the device's single connection slot.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "status"
    _attr_device_class = BinarySensorDeviceClass.POWER
    _attr_should_poll = False

    def __init__(self, entry: HaloConfigEntry) -> None:
        self._address: str = entry.data[CONF_ADDRESS]
        self._attr_unique_id = f"{self._address}_advertising"
        self._last_seen: datetime | None = None
        serial = entry.data.get(CONF_SERIAL)
        self._attr_device_info = DeviceInfo(
            connections={(dr.CONNECTION_BLUETOOTH, self._address)},
            identifiers={(DOMAIN, self._address)},
            manufacturer="Astral Pool / Fabtronics",
            name=entry.title,
            serial_number=str(serial) if serial else None,
        )

    async def async_added_to_hass(self) -> None:
        # Seed from the last cached advertisement so the state is right at
        # startup instead of unknown. If that cache is stale (the device is
        # actually off), the periodic check flips it off within OFF_AFTER.
        if (
            bluetooth.async_last_service_info(
                self.hass, self._address, connectable=False
            )
            is not None
        ):
            self._last_seen = dt_util.utcnow()
            self._attr_is_on = True
        else:
            self._attr_is_on = False

        self.async_on_remove(
            bluetooth.async_register_callback(
                self.hass,
                self._advertisement_seen,
                BluetoothCallbackMatcher(address=self._address, connectable=False),
                bluetooth.BluetoothScanningMode.PASSIVE,
            )
        )
        self.async_on_remove(
            async_track_time_interval(self.hass, self._check_stale, CHECK_INTERVAL)
        )

    @callback
    def _advertisement_seen(
        self, service_info: BluetoothServiceInfoBleak, change: BluetoothChange
    ) -> None:
        self._last_seen = dt_util.utcnow()
        if not self._attr_is_on:
            self._attr_is_on = True
            self.async_write_ha_state()

    @callback
    def _check_stale(self, now: datetime) -> None:
        if (
            self._attr_is_on
            and self._last_seen is not None
            and now - self._last_seen > OFF_AFTER
        ):
            self._attr_is_on = False
            self.async_write_ha_state()
