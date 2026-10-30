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
    CONF_POLLING,
    CONF_SERIAL,
    DEFAULT_POLLING,
    DOMAIN,
    MANUFACTURER_ID,
)
from .protocol import is_valid_access_code, parse_manufacturer_data


def _parse(discovery_info: BluetoothServiceInfoBleak):
    """Return the parsed Halo advertisement, or None if not a Halo payload."""
    raw = discovery_info.manufacturer_data.get(MANUFACTURER_ID)
    if raw is None:
        return None
    return parse_manufacturer_data(raw)


def _code_to_hex(code: str) -> str | None:
    """Validate a user-entered 4-char access code; return its hex, or None."""
    code = code.strip()
    try:
        raw = code.encode("ascii")
    except UnicodeEncodeError:
        return None
    return raw.hex() if is_valid_access_code(raw) else None


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
        """Confirm a discovered device (optionally entering the access code)."""
        assert self._discovery is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            code = user_input.get(CONF_ACCESS_CODE, "")
            if code and _code_to_hex(code) is None:
                errors["base"] = "invalid_access_code"
            else:
                return self._create_entry(self._discovery, code)
        return self.async_show_form(
            step_id="bluetooth_confirm",
            data_schema=vol.Schema(
                {vol.Optional(CONF_ACCESS_CODE, default=""): str}
            ),
            description_placeholders={"name": self._discovery.name},
            errors=errors,
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
                    self._discovery = info
                    return await self.async_step_bluetooth_confirm()
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

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user enter/update the 4-character access code."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            code_hex = _code_to_hex(user_input[CONF_ACCESS_CODE])
            if code_hex is None:
                errors["base"] = "invalid_access_code"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data={
                        **entry.data,
                        CONF_ACCESS_CODE: code_hex,
                        CONF_POLLING: user_input.get(CONF_POLLING, DEFAULT_POLLING),
                    },
                )

        current = entry.data.get(CONF_ACCESS_CODE) or ""
        suggested = ""
        if current:
            try:
                suggested = bytes.fromhex(current).decode("ascii")
            except (ValueError, UnicodeDecodeError):
                suggested = ""

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ACCESS_CODE, default=suggested): str,
                    vol.Required(
                        CONF_POLLING,
                        default=entry.data.get(CONF_POLLING, DEFAULT_POLLING),
                    ): bool,
                }
            ),
            errors=errors,
        )

    def _create_entry(
        self, info: BluetoothServiceInfoBleak, code: str = ""
    ) -> ConfigFlowResult:
        adv = _parse(info)
        assert adv is not None
        # Prefer a code the user typed; else a valid advertised code (only
        # present during the ~10s power-on window); else empty and we capture
        # it later from an advertisement.
        access_code = _code_to_hex(code) if code else None
        if access_code is None:
            access_code = adv.access_code.hex() if adv.is_pairable else ""
        return self.async_create_entry(
            title=info.name or f"Halo Lite {adv.serial_number}",
            data={
                CONF_ADDRESS: info.address,
                CONF_ACCESS_CODE: access_code,
                CONF_SERIAL: adv.serial_number,
            },
        )
