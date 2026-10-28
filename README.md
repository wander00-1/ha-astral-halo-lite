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
- Select a **preset effect / colour**
- Reads the light's current **on/off + effect** state back from the device
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

> If setup reports the device is "not pairable", power-cycle the Halo Lite to refresh the
> access code it advertises, then retry while it is advertising.

## Development / tests

The crypto and framing have no Home Assistant dependency and are covered by tests that
assert against **real captured frames** (including the known `session key → auth value`
pair and decoded on/off/colour commands):

```bash
pip install -r requirements_test.txt
pytest tests/ -q
```

## Known limitations / TODO

- **Effect names** are placeholders (`effect_0…`); the real preset names/palette still
  need mapping from more captures.
- **Access-code source at runtime** is assumed to be the live advertisement. If a unit
  instead keeps a code fixed at pairing, this may need a stored/override value.
- Full RGB (beyond preset effects) is not yet implemented.
- State is refreshed on connect and after each command (the device drops idle links after
  ~15–20 s, so the integration connects on demand rather than holding a link).

## Credits

Built on prior work by the Halo/Viron community: [`pychlorinator`](https://github.com/pbutterworth/pychlorinator)
and [`pychlorinator-cloud`](https://github.com/robmarkoski/pychlorinator-cloud) for the
sibling chlorinator protocol, NVISO's Flutter TLS bypass research, and
[Blutter](https://github.com/worawit/blutter) for Dart/Flutter decompilation.

## License

MIT
