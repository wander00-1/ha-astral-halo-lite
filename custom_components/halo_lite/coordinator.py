"""Connection/command coordinator for a Halo Lite device.

The device auto-disconnects after ~15-20s of idle, so rather than hold a
persistent link this connects on demand: establish -> authenticate -> run the
command -> read state -> disconnect, serialized behind a lock. State is cached
between operations and pushed to entities via listeners.

The access code the device accepts is only advertised during the ~10s window
after power-on (outside that window it advertises a placeholder). So the code
is *not* read live on every connect; instead a valid code is captured from
advertisements whenever one appears (``async_update_access_code``) and reused.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import logging

from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant, callback

from dataclasses import replace

from datetime import date

from .const import (
    CHAR_TX_NOTIFY,
    CMD_DEVICE_DATE,
    CMD_STATS_RUN_HOURS,
    DEFAULT_TIMER_COUNT,
    MODE_AUTO,
    MODE_OFF,
    MODE_ON,
    TIMER_TYPE_CLOCK,
)
from .protocol import (
    HaloAuthError,
    HaloLightState,
    HaloLiteClient,
    HaloProtocolError,
    HaloTimer,
    build_timer_config,
    is_valid_access_code,
    parse_device_date,
    parse_run_hours,
    parse_timer_config,
)

_LOGGER = logging.getLogger(__name__)

# How long to wait after a command for the device to push its new state.
_STATE_SETTLE = 1.5
_CONNECT_TIMEOUT = 20.0
# The device/BLE link is flaky (the official app sees this too): a connect,
# the auth handshake, or a command write can fail transiently. Retry the whole
# sequence several times with growing backoff before giving up, so a brief
# dropout - or the light's single connection slot being momentarily held - has
# time to clear.
_MAX_ATTEMPTS = 5
_RETRY_BACKOFF = 1.0
# These devices allow a single BLE connection and need a moment after a link is
# torn down before the radio will accept a new one. `client.disconnect()`
# returning does not mean the slot is free yet, so enforce a minimum gap since
# our last disconnect before opening the next connection. Without this, a quick
# second operation (e.g. two dumps back to back) hits a slot that has not
# cleared and fails to connect/authenticate until the device recovers.
_SLOT_COOLDOWN = 5.0


class HaloLiteCoordinator:
    """Owns the on-demand connection, the captured access code and the state."""

    def __init__(
        self,
        hass: HomeAssistant,
        address: str,
        access_code: bytes | None,
        persist_access_code: Callable[[bytes], None] | None = None,
    ) -> None:
        self.hass = hass
        self.address = address
        self.access_code = access_code if is_valid_access_code(access_code) else None
        self._persist = persist_access_code
        self.state = HaloLightState()
        self.timers: dict[int, HaloTimer] = {}
        self.run_hours: int | None = None
        self.device_date: date | None = None
        self._lock = asyncio.Lock()
        self._listeners: list[Callable[[], None]] = []
        # Monotonic time of the last BLE disconnect, so the next connect can
        # wait out _SLOT_COOLDOWN and let the device's single slot clear.
        self._last_disconnect: float = 0.0
        # Platforms set up for this entry (empty for a non-light device); set
        # by __init__.py after device-type detection, read back on unload.
        self.platforms: list = []

    @property
    def has_access_code(self) -> bool:
        return is_valid_access_code(self.access_code)

    @callback
    def async_add_listener(self, update_callback: Callable[[], None]) -> Callable[[], None]:
        """Register an entity update callback; returns an unsubscribe fn."""
        self._listeners.append(update_callback)

        def _remove() -> None:
            self._listeners.remove(update_callback)

        return _remove

    @callback
    def _async_notify_listeners(self) -> None:
        for update_callback in list(self._listeners):
            update_callback()

    @callback
    def async_update_access_code(self, code: bytes) -> None:
        """Capture the advertised access code, but only if we don't have one.

        The code is fixed per unit, so once a valid code is stored we keep it
        rather than let a later (possibly spurious/partial) advertisement
        overwrite a known-good value and break authentication. Use the
        Reconfigure step to change the code deliberately.
        """
        if not is_valid_access_code(code) or self.has_access_code:
            return
        _LOGGER.debug("captured access code for %s", self.address)
        self.access_code = code
        if self._persist is not None:
            self._persist(code)
        self._async_notify_listeners()

    # -- high-level operations ---------------------------------------------
    # Each command reads the real state back when it can (which carries the true
    # output-on flag, important for Auto). Only if that read-back failed do we
    # fall back to an optimistic guess.
    async def async_turn_on(self) -> None:
        if not await self._run(lambda c: c.turn_on()):
            self._set_optimistic(MODE_ON, output_on=True)

    async def async_turn_off(self) -> None:
        if not await self._run(lambda c: c.turn_off()):
            self._set_optimistic(MODE_OFF, output_on=False)

    async def async_set_auto(self) -> None:
        # In Auto the schedule decides on/off, so don't guess the output here.
        if not await self._run(lambda c: c.set_auto()):
            self._set_optimistic(MODE_AUTO, output_on=None)

    async def async_set_effect(self, effect: int) -> None:
        if not await self._run(lambda c: c.set_effect(effect)):
            self._set_optimistic(MODE_ON, effect, output_on=True)

    async def async_refresh(self) -> None:
        await self._run(None)

    # -- timers -------------------------------------------------------------
    async def async_read_timers(self) -> None:
        """Read every timer's configuration from the device."""
        await self._run(self._op_read_timers, readback=False)

    async def async_set_timer(
        self,
        index: int,
        *,
        enabled: bool | None = None,
        start: tuple[int, int] | None = None,
        stop: tuple[int, int] | None = None,
    ) -> None:
        """Change one timer and write it back to the device."""
        cur = self.timers.get(index)
        if cur is None:
            raise HaloProtocolError(f"timer {index} not loaded yet")
        changes: dict = {}
        if enabled is not None:
            changes["enabled"] = enabled
        if start is not None:
            changes["start_hour"], changes["start_min"] = start
        if stop is not None:
            changes["stop_hour"], changes["stop_min"] = stop
        new = replace(cur, **changes)
        await self._run(
            lambda c: self._op_write_timer(c, new), readback=False
        )

    async def _op_read_timers(self, client: HaloLiteClient) -> None:
        try:
            caps = await client.read_timer_capabilities()
            count = caps[1] if len(caps) > 1 and 1 <= caps[1] <= 8 else DEFAULT_TIMER_COUNT
        except HaloProtocolError:
            count = DEFAULT_TIMER_COUNT
        timers: dict[int, HaloTimer] = {}
        for i in range(count):
            try:
                payload = await client.read_timer_config(TIMER_TYPE_CLOCK, i, 0)
            except HaloProtocolError:
                continue
            timer = parse_timer_config(payload)
            if timer is not None:
                timers[timer.index] = timer
        if timers:
            self.timers = timers

        # Diagnostics (best effort - don't fail the whole read over these).
        try:
            hours = parse_run_hours(
                await client.read_characteristic(CMD_STATS_RUN_HOURS)
            )
            if hours is not None:
                self.run_hours = hours
        except HaloProtocolError:
            pass
        try:
            ymd = parse_device_date(
                await client.read_characteristic(CMD_DEVICE_DATE)
            )
            if ymd is not None:
                self.device_date = date(*ymd)
        except (HaloProtocolError, ValueError):
            pass

    # -- diagnostics / probe ------------------------------------------------
    async def async_probe(
        self, cmd_types, timeout: float = 3.0
    ) -> dict[int, str]:
        """Read-only sweep: connect, auth, read each cmd type, return hex.

        A missing/unsupported cmd simply times out and is recorded as such.
        Nothing is ever written to the device.
        """
        results: dict[int, str] = {}
        await self._run(
            lambda c: self._op_probe(c, cmd_types, results, timeout),
            readback=False,
        )
        return results

    async def _op_probe(
        self, client: HaloLiteClient, cmd_types, results: dict[int, str], timeout: float
    ) -> None:
        for cmd in cmd_types:
            try:
                payload = await client.read_characteristic(cmd, timeout=timeout)
                hexstr = payload.hex()
                results[cmd] = hexstr
                _LOGGER.warning("halo probe %s: cmd %s -> %s", self.address, cmd, hexstr)
            except HaloProtocolError:
                results[cmd] = "(no response)"
                _LOGGER.warning("halo probe %s: cmd %s -> no response", self.address, cmd)
            except Exception as err:  # noqa: BLE001 - keep sweeping past any error
                results[cmd] = f"(error: {err})"
                _LOGGER.warning("halo probe %s: cmd %s -> error %s", self.address, cmd, err)

    async def _op_write_timer(self, client: HaloLiteClient, timer: HaloTimer) -> None:
        await client.write_timer_config(build_timer_config(timer))
        # Read the timer back so the stored value reflects what the device kept.
        payload = await client.read_timer_config(
            timer.timer_type, timer.index, timer.season
        )
        confirmed = parse_timer_config(payload)
        self.timers[timer.index] = confirmed if confirmed is not None else timer

    @callback
    def _set_optimistic(
        self, mode: int, effect: int | None = None, output_on: bool | None = None
    ) -> None:
        """Reflect the commanded state immediately (read-back failed)."""
        self.state = HaloLightState(
            mode=mode,
            effect=effect if effect is not None else self.state.effect,
            output_on=output_on,
            raw=self.state.raw,
        )
        self._async_notify_listeners()

    # -- connection plumbing -----------------------------------------------
    async def _run(
        self,
        action: Callable[[HaloLiteClient], Awaitable[None]] | None,
        *,
        readback: bool = True,
    ) -> bool:
        """Run a command/refresh; return True if fresh device state was read."""
        if not self.has_access_code:
            raise HaloAuthError(
                "no pairing code captured yet - power-cycle the Halo Lite so it "
                "advertises its access code (the ~10s window after power-on)"
            )
        got_state = False
        async with self._lock:
            last_err: Exception | None = None
            for attempt in range(1, _MAX_ATTEMPTS + 1):
                try:
                    got_state = await self._attempt(action, readback)
                    break
                except (
                    BleakError,
                    HaloProtocolError,
                    HaloConnectionError,
                    TimeoutError,
                    OSError,
                ) as err:
                    last_err = err
                    _LOGGER.debug(
                        "Halo command attempt %s/%s failed: %s",
                        attempt,
                        _MAX_ATTEMPTS,
                        err,
                    )
                    if attempt < _MAX_ATTEMPTS:
                        await asyncio.sleep(_RETRY_BACKOFF * attempt)
            else:
                assert last_err is not None
                raise last_err
        self._async_notify_listeners()
        return got_state

    async def _attempt(
        self,
        action: Callable[[HaloLiteClient], Awaitable[None]] | None,
        readback: bool = True,
    ) -> bool:
        """One connect -> authenticate -> command -> read-state cycle.

        Returns True if the light state was read back from the device. When
        ``readback`` is False (e.g. timer ops that do their own reads), the
        light-state read is skipped.
        """
        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if ble_device is None:
            raise HaloConnectionError(
                f"{self.address} not currently seen by any adapter"
            )

        # Let the device's single connection slot clear from our previous link
        # before opening a new one.
        gap = _SLOT_COOLDOWN - (asyncio.get_running_loop().time() - self._last_disconnect)
        if gap > 0:
            await asyncio.sleep(gap)

        client = await establish_connection(
            BleakClientWithServiceCache,
            ble_device,
            self.address,
            timeout=_CONNECT_TIMEOUT,
        )
        got_state = False
        try:
            halo = HaloLiteClient(client, self.access_code)
            await halo.authenticate()
            if action is not None and not readback:
                # Self-contained op (e.g. timers): it does its own reads.
                await action(halo)
            elif action is None:
                # A pure refresh: reading the state back IS the operation.
                await halo.request_light_state()
                await asyncio.sleep(_STATE_SETTLE)
                self.state = halo.state
                got_state = True
            else:
                # A command (on/off/effect). Once the write lands the action
                # has succeeded; the device often drops the link right after,
                # so read the new state back only on a best-effort basis and
                # never fail (or retry) the command because of the read-back.
                await action(halo)
                try:
                    await halo.request_light_state()
                    await asyncio.sleep(_STATE_SETTLE)
                    self.state = halo.state
                    got_state = True
                except (BleakError, HaloProtocolError, TimeoutError, OSError):
                    _LOGGER.debug(
                        "post-command state read-back failed (best effort)"
                    )
        finally:
            # Always release the link: this light allows only one connection,
            # so a lingering/half-open link blocks the next authentication.
            try:
                await client.stop_notify(CHAR_TX_NOTIFY)
            except Exception:  # noqa: BLE001 - best effort on teardown
                pass
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001 - best effort on teardown
                pass
            self._last_disconnect = asyncio.get_running_loop().time()
        return got_state


class HaloConnectionError(Exception):
    """Raised when the device cannot be reached."""
