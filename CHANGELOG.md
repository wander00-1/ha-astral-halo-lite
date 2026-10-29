# Changelog

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
