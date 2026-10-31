# Changelog

## 0.1.14

- Give the non-light **Status** sensor a water-pump icon (shown filled when on
  and crossed-out when off), via a local `icons.json`. No functional change.

## 0.1.13

- **Pump/non-light "Status" binary sensor.** A non-light Astral device (e.g. a
  Viron pump) now gets a passive **Status** sensor that reads **On** while the
  device is advertising over BLE and **Off** when it stops. These devices only
  advertise while powered on, so this tracks the pump's on/off without ever
  connecting to it: it listens for advertisements only, so it never competes
  for the device's single Bluetooth connection slot. Off is reported after
  ~2.5 minutes without an advertisement.

## 0.1.12

- **Diagnostic logging** of the per-connection session key and computed auth
  value (and an "acknowledged" line on success), to investigate a device that
  accepts authentication once per power cycle and then rejects re-auth. Lets
  repeated connections be compared to see whether the session key is reused.

## 0.1.11

- **Force-close a stale/zombie link before each connect.** On a device that
  allows a single connection, a half-open link left over from a previous
  session (held by the local adapter or an ESPHome Bluetooth proxy) kept the
  slot busy, so every connect after the first failed until the device was
  power-cycled. We now tear down any lingering connection to the device
  (`close_stale_connections_by_address`) before reconnecting.

## 0.1.10

- **Wait for the device's single connection slot to clear before reconnecting.**
  These devices allow only one BLE connection and need a moment after a link is
  torn down before accepting a new one; `disconnect()` returning doesn't mean
  the slot is free. A minimum gap since the last disconnect is now enforced, so
  a quick second operation (e.g. two `dump` calls back to back) no longer fails
  to connect until the device recovers.

## 0.1.9

- **Detect the device type and only create light entities for a light.** The
  same BLE protocol is spoken by other Astral/Fabtronics devices (e.g. a Viron
  pump). Those are now set up with **no entities** - only the connection and
  the read-only `dump` service, so they can be mapped without pretending to be
  a light. A device is treated as a light when its name contains `HLITE`.
- **Reconfigure can now turn off the 2-minute poll.** Some devices (e.g. a
  pump sharing its single Bluetooth connection with a chlorinator) can't spare
  the periodic connection; disabling it stops the poll from contending for the
  device's one connection slot. The poll defaults to on and only runs for a
  light.

## 0.1.8

- Add a **read-only `halo_lite.dump` diagnostic service**. It connects,
  authenticates and reads a sweep of Gen2 characteristics, then returns and
  logs the decrypted responses. It never writes to the device. Useful for
  inspecting what a device actually exposes (including a non-light Gen2 device
  that speaks the same protocol).

## 0.1.7

- Poll the device every 2 minutes so the light reflects **Auto/timer-driven
  on/off changes** it wasn't told to make. Previously state was only read on
  startup and after a command, so a light switched on by its own schedule kept
  showing **off** in Home Assistant until the next manual command.

## 0.1.6

- Add diagnostic sensors: **Light run time** (lifetime run hours, zone 1) and
  **Device date** (the device's own calendar, which the timers run on), both
  decoded from a live capture. Read alongside the timers, no extra connection.

## 0.1.5

- **Editable timers.** Each timer now has a start time, a stop time and an
  enabled switch; changes are written back to the device. Decoded from a live
  capture of the official app (cmd 403 TimerConfiguration), start/stop in local
  device time. Auto mode runs these timers.

## 0.1.4

- The light now reflects the real on/off output (reported separately from the
  mode), so while Mode is Auto the toggle shows on when the schedule has it on
  and off when it has it off, instead of always showing on.

## 0.1.3

- Add a **Mode** select (Off / Auto / On). Auto puts the light on its internal
  timer schedule (`SetZoneModeToAuto`); the select also reflects the current
  mode read back from the device.

## 0.1.2

- Retry a failed command sequence up to 5 times (was 3) with growing backoff,
  giving a brief Bluetooth dropout - or the light's single connection slot
  being momentarily held - time to clear.
- Always release the BLE link after a command, even if teardown errors, so a
  lingering/half-open connection can't block the next authentication.

## 0.1.1

- Don't fail a command when the device drops the link right after it: once the
  write lands, the state read-back is best-effort and no longer turns a
  successful on/off/effect into an authentication error.
- Reflect the commanded state immediately (optimistic), so the entity is
  correct even if the read-back is skipped.
- Capture the access code only once (it is fixed per unit) and then stop
  listening, instead of re-persisting it on every advertisement. This also
  prevents a spurious advertisement from overwriting a known-good code.

## 0.1.0

First release.

- Local Bluetooth LE control of the Astral Pool / Fabtronics "Halo Lite 2"
  (`HLITE2`) pool light — no cloud, works through ESPHome Bluetooth proxies.
- Turn on/off and select a colour/effect preset; reads on/off + effect state
  back from the device.
- Effect/colour presets named for the SLX/FLX light type (Blue, Magenta, Red,
  Orange, Green, Aqua, White, Custom Colour, Custom Pattern, Rainbow, Ocean,
  Disco — colour-byte ids 0-11).
- Access code captured automatically from the advertisement during the ~10s
  power-on pairing window, or entered manually during setup / via Reconfigure.
- Commands retry the connect + authenticate + write sequence a few times to
  ride out transient Bluetooth failures.
