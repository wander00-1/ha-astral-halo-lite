"""The Astral Pool Halo Lite integration."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothCallbackMatcher,
    BluetoothChange,
    BluetoothServiceInfoBleak,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    CONF_ACCESS_CODE,
    CONF_POLLING,
    DEFAULT_POLLING,
    DEFAULT_PROBE_CMDS,
    DOMAIN,
    MANUFACTURER_ID,
)
from .coordinator import HaloLiteCoordinator
from .protocol import is_valid_access_code, parse_manufacturer_data

PLATFORMS: list[Platform] = [
    Platform.LIGHT,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TIME,
]

type HaloConfigEntry = ConfigEntry[HaloLiteCoordinator]

# The light's Auto mode runs it on its internal timer schedule, so state can
# change without HA commanding it. Poll the device periodically so the entity
# reflects those schedule-driven on/off changes instead of showing a stale
# value until the next manual command.
SCAN_INTERVAL = timedelta(minutes=2)


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

    # This integration's entities model a Halo Lite *light*. The same BLE
    # protocol is also spoken by other Astral/Fabtronics devices (e.g. a Viron
    # pump), which this integration can connect to and probe with the `dump`
    # service, but which have none of the light's entities. Detect the device
    # type from its advertised name. A light gets the full set of platforms; a
    # non-light (e.g. a pump) gets only a passive "advertising" binary sensor -
    # the pump advertises only while powered on, so that tracks on/off without
    # ever connecting or contending for the device's single connection slot.
    service_info = bluetooth.async_last_service_info(hass, address)
    name = (service_info.name if service_info else None) or entry.title or ""
    is_light = "HLITE" in name.upper()
    platforms = PLATFORMS if is_light else [Platform.BINARY_SENSOR]
    coordinator.platforms = platforms

    # The access code is fixed per unit, so we only need to catch it once (in
    # the ~10s power-on advertising window). If we don't have it yet, listen
    # for an advertisement that carries it, then stop listening. If we already
    # have one, don't listen at all - nothing to capture.
    if not coordinator.has_access_code:
        cancel: list[Callable[[], None]] = []

        @callback
        def _stop_listening() -> None:
            while cancel:
                cancel.pop()()

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
                # Captured once; the code never changes, so stop listening.
                _stop_listening()

        cancel.append(
            bluetooth.async_register_callback(
                hass,
                _on_advertisement,
                BluetoothCallbackMatcher(address=address),
                bluetooth.BluetoothScanningMode.ACTIVE,
            )
        )
        entry.async_on_unload(_stop_listening)

    await hass.config_entries.async_forward_entry_setups(entry, platforms)

    # Read the timer schedule once in the background so the timer entities
    # populate without blocking setup.
    if is_light and coordinator.has_access_code:

        async def _initial_timer_read() -> None:
            try:
                await coordinator.async_read_timers()
            except Exception:  # noqa: BLE001 - device may be out of range
                pass

        entry.async_create_background_task(
            hass, _initial_timer_read(), "halo_lite_timer_init"
        )

    # Poll the device so Auto/timer-driven on/off changes are reflected even
    # when HA didn't issue the command itself. No-op until a code is captured.
    # Only lights have pollable state; can also be turned off per entry
    # (Reconfigure) for a device whose single connection slot is being shared
    # with another BLE client.
    if is_light and entry.data.get(CONF_POLLING, DEFAULT_POLLING):

        async def _async_poll(now) -> None:
            if not coordinator.has_access_code:
                return
            try:
                await coordinator.async_refresh()
            except Exception:  # noqa: BLE001 - device may simply be out of range
                pass

        entry.async_on_unload(
            async_track_time_interval(hass, _async_poll, SCAN_INTERVAL)
        )

    _async_register_dump_service(hass)

    return True


@callback
def _async_register_dump_service(hass: HomeAssistant) -> None:
    """Register the read-only diagnostic sweep service (once per domain).

    ``halo_lite.dump`` connects to each Halo device, authenticates, reads a
    sweep of Gen2 cmd types and returns/logs the decrypted responses. It never
    writes to the device. Useful for mapping a non-light device (e.g. a Viron
    pump) by what characteristics it answers.
    """
    if hass.services.has_service(DOMAIN, "dump"):
        return

    async def _handle_dump(call: ServiceCall) -> ServiceResponse:
        address = call.data.get("address")
        cmds = call.data.get("cmds") or list(DEFAULT_PROBE_CMDS)
        out: dict[str, dict[str, str]] = {}
        for entry in hass.config_entries.async_entries(DOMAIN):
            coordinator = getattr(entry, "runtime_data", None)
            if coordinator is None:
                continue
            if address and coordinator.address.lower() != str(address).lower():
                continue
            try:
                res = await coordinator.async_probe(cmds)
                out[coordinator.address] = {str(k): v for k, v in res.items()}
            except Exception as err:  # noqa: BLE001 - report, don't raise
                out[coordinator.address] = {"error": str(err)}
        return {"results": out}

    hass.services.async_register(
        DOMAIN, "dump", _handle_dump, supports_response=SupportsResponse.ONLY
    )


async def async_unload_entry(hass: HomeAssistant, entry: HaloConfigEntry) -> bool:
    """Unload a config entry."""
    platforms = getattr(entry.runtime_data, "platforms", PLATFORMS)
    if not platforms:
        return True
    return await hass.config_entries.async_unload_platforms(entry, platforms)
