# Astral Pool Halo Lite — Home Assistant integration

Local **Bluetooth LE** control of the **Astral Pool / Fabtronics "Halo Lite 2"** pool
light controller (`HLITE2`). No cloud, no account — the device is driven entirely over
BLE, the same way the official app does it.

> **Status: experimental.** The protocol was reverse engineered from the official app
> and validated byte-for-byte against a real device capture (see the unit tests), but it
> has so far been exercised against a single unit. Treat early releases as a work in
> progress.

## Features

- Turn the light **on / off**
- **Mode** select: Off / Auto / On (Auto runs the light on its internal timer schedule)
- **Editable timers**: per-timer start/stop time and enabled switch (Auto follows these)
- Select a **preset effect / colour**
- Reads the light's current **on/off + effect** state back from the device
- **Diagnostics**: lifetime light run hours and the device's own date
- Local push — auto-discovered over Bluetooth, works through ESPHome Bluetooth proxies

## How it works

The Halo Lite uses a "Gen2" BLE scheme on service `45000001-98b7-4e29-a03f-160174643002`:

1. Read a per-connection 16-byte **session key** from char `…001`.
2. Compute `auth = AES-ECB(FIPS_test_vector_key, session_key XOR accessCode·pad16)` and
   write it to char `…002`. `accessCode` is 4 ASCII bytes read from the device's
   advertisement (manufacturer data, company `0x0447`).
3. Enable notifications on char `…003`; the device acknowledges the auth there.
4. Send 20-byte command frames to char `…004`, encrypted with a session-keyed two-pass
   AES (`encrypt_characteristic`); decode notifications the same way.

Frames are `[opcode][cmd_type u16-LE][payload…][counter]`. Light control is
`opcode=3, cmd_type=501`: payload `01`=on, `03`=off, `05 00 NN`=set effect `NN`. State
is read with `opcode=2, cmd_type=300`.

The AES key is the public FIPS-197 test vector — this is obfuscation, not security.

## Installation (HACS custom repository)

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/wander00-1/ha-astral-halo-lite`, category **Integration**.
2. Install **Astral Pool Halo Lite**, then restart Home Assistant.
3. The device should be **auto-discovered** (Settings → Devices & Services). If not, add
   it manually via **Add Integration → Astral Pool Halo Lite**.
4. **Pair it: power-cycle the Halo Lite (off, then on).** The light only advertises its
   real access code for a brief window right after power-on; Home Assistant listens for
   that and captures it automatically. Until a code is captured the light entity stays
   *unavailable*. After a power-cycle the code rotates, and HA captures the new one the
   same way — no re-configuration needed.

## Development / tests

The crypto and framing have no Home Assistant dependency and are covered by tests that
assert against **real captured frames** (including the known `session key → auth value`
pair and decoded on/off/colour commands):

```bash
pip install -r requirements_test.txt
pytest tests/ -q
```

There is also a read-only diagnostic service, `halo_lite.dump`, which connects,
authenticates and reads a sweep of Gen2 characteristics, returning and logging the
decrypted responses (it never writes). Call it from Developer Tools → Actions, optionally
with a Bluetooth `address` to target one device.

## Known limitations / TODO

- **Effect names** cover the SLX/FLX palette (Blue, Magenta, Red, Orange, Green, Aqua,
  White, Custom Colour, Custom Pattern, Rainbow, Ocean, Disco — colour-byte ids 0-11,
  read from the official app). A light configured as a different type (Spa Electrics,
  LumiPower, Single Colour) uses a different name set for the same ids.
- **Access code** is captured from the advertisement during the power-on window and
  stored/reused. If your light is power-cycled while HA is not running or out of range,
  power-cycle it again once HA is back so the new code can be captured.
- Full RGB (beyond preset effects) is not yet implemented.
- State is refreshed on startup, after each command, and on a 2-minute poll (the device
  drops idle links after ~15–20 s, so the integration connects on demand rather than
  holding a link). The poll is what lets Auto/timer-driven on/off show up in HA. It can
  be turned off per device via **Reconfigure** for a device that shares its single
  Bluetooth connection with another controller and can't spare the periodic connection.

## Credits

Built on prior work by the Halo/Viron community: [`pychlorinator`](https://github.com/pbutterworth/pychlorinator)
and [`pychlorinator-cloud`](https://github.com/robmarkoski/pychlorinator-cloud) for the
sibling chlorinator protocol.

## License

MIT
