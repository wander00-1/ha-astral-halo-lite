# Changelog

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
