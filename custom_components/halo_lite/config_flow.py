"""Config flow for the Astral Pool Halo Lite integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS

from .const import (
    CONF_ACCESS_CODE,
    CONF_SERIAL,
    DOMAIN,
    MANUFACTURER_ID,
)
from .protocol import parse_manufacturer_data


def _parse(discovery_info: BluetoothServiceInfoBleak):
    """Return the parsed Halo advertisement, or None if not a Halo payload."""
    raw = discovery_info.manufacturer_data.get(MANUFACTURER_ID)
    if raw is None:
        return None
    return parse_manufacturer_data(raw)


class HaloLiteConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Halo Lite."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery: BluetoothServiceInfoBleak | None = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a Bluetooth discovery."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        if _parse(discovery_info) is None:
            return self.async_abort(reason="not_supported")
        self._discovery = discovery_info
        self.context["title_placeholders"] = {"name": discovery_info.name}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm a discovered device."""
        assert self._discovery is not None
        if user_input is not None:
            return self._create_entry(self._discovery)
        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": self._discovery.name},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick a device discovered over Bluetooth."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            for info in async_discovered_service_info(self.hass):
                if info.address == address:
                    return self._create_entry(info)
            return self.async_abort(reason="cannot_connect")

        devices: dict[str, str] = {}
        current = self._async_current_ids()
        for info in async_discovered_service_info(self.hass):
            if info.address in current or _parse(info) is None:
                continue
            devices[info.address] = f"{info.name} ({info.address})"

        if not devices:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In(devices)}),
        )

    def _create_entry(self, info: BluetoothServiceInfoBleak) -> ConfigFlowResult:
        adv = _parse(info)
        assert adv is not None
        # The usable access code is only advertised during the ~10s power-on
        # window. Store it if it happens to be valid right now; otherwise the
        # integration captures it from a later advertisement (power-cycle).
        access_code = adv.access_code.hex() if adv.is_pairable else ""
        return self.async_create_entry(
            title=info.name or f"Halo Lite {adv.serial_number}",
            data={
                CONF_ADDRESS: info.address,
                CONF_ACCESS_CODE: access_code,
                CONF_SERIAL: adv.serial_number,
            },
        )
