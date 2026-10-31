"""Mode select for the Astral Pool Halo Lite (Off / Auto / On)."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HaloConfigEntry
from .const import CONF_SERIAL, DOMAIN, MODE_AUTO, MODE_OFF, MODE_ON
from .coordinator import HaloLiteCoordinator

# Select option <-> device mode value.
_OPTION_TO_MODE = {"off": MODE_OFF, "auto": MODE_AUTO, "on": MODE_ON}
_MODE_TO_OPTION = {v: k for k, v in _OPTION_TO_MODE.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HaloConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Halo Lite mode select."""
    async_add_entities([HaloLiteModeSelect(entry.runtime_data, entry)])


class HaloLiteModeSelect(SelectEntity):
    """Off / Auto / On. Auto runs the light on its internal timer schedule."""

    _attr_has_entity_name = True
    _attr_translation_key = "light_mode"
    _attr_options = list(_OPTION_TO_MODE)

    def __init__(self, coordinator: HaloLiteCoordinator, entry: HaloConfigEntry) -> None:
        self.coordinator = coordinator
        self._attr_unique_id = f"{entry.data[CONF_ADDRESS]}_mode"
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
        return self.coordinator.has_access_code

    @property
    def current_option(self) -> str | None:
        return _MODE_TO_OPTION.get(self.coordinator.state.mode)

    async def async_select_option(self, option: str) -> None:
        if option == "auto":
            await self.coordinator.async_set_auto()
        elif option == "on":
            await self.coordinator.async_turn_on()
        else:
            await self.coordinator.async_turn_off()
