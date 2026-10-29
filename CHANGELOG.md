# Changelog

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
