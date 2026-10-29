"""Constants for the Astral Pool Halo Lite integration."""

from __future__ import annotations

DOMAIN = "halo_lite"

# Config entry keys
CONF_ACCESS_CODE = "access_code"
CONF_SERIAL = "serial"

# --- BLE identity -----------------------------------------------------------
# Manufacturer-specific data company id (Fabtronics Australia Pty Ltd).
MANUFACTURER_ID = 0x0447  # 1095

# Primary GATT service. Note: the session-key characteristic shares this UUID.
SERVICE_UUID = "45000001-98b7-4e29-a03f-160174643002"

# Characteristics (value handles seen in the capture given for reference):
CHAR_SESSION_KEY = "45000001-98b7-4e29-a03f-160174643002"  # ...001 READ   (0x0012)
CHAR_MASTER_AUTH = "45000002-98b7-4e29-a03f-160174643002"  # ...002 WRITE  (0x0014)
CHAR_TX_NOTIFY = "45000003-98b7-4e29-a03f-160174643002"    # ...003 NOTIFY (0x000d)
CHAR_RX_WRITE = "45000004-98b7-4e29-a03f-160174643002"     # ...004 WRITE  (0x0010)

LOCAL_NAME = "HLITE2"

# --- Advertisement manufacturer-data layout --------------------------------
# Byte layout verified from live captures (company id 0x0447 already stripped
# by HA), both steady-state and mid-power-cycle:
#   offset: 0  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 16 17 18 19 20 21 22
#   steady: 03 00 00 01 00 00 0e ef 2a 00 01 01 01 00 01 00 3c 00 00 00 00 00 00
#   paired: 03 00 00 01 00 00 0e ef 2a 00 01 01 01 00 01 00 00 54 54 38 34 00 00
#                           |serial 2813710|  |---always 01 01 01 00---|  |"TT84"|
# Bytes 10-13 are a FIXED field (always 01 01 01 00) that earlier work wrongly
# labelled the access code; byte 16 is a jittering counter. The real 4-byte
# printable-ASCII access code is at offset 17, present only in the pairing
# window (zeros otherwise).
ADV_UNIQUE_ID_OFFSET = 6      # 4-byte uint32 LE serial number
ADV_ACCESS_CODE_OFFSET = 17   # 4-byte ASCII access code (pairing window only)
ADV_ACCESS_CODE_LEN = 4

# --- Protocol opcodes / command types --------------------------------------
OPCODE_RESPONSE = 1
OPCODE_READ = 2
OPCODE_ACTION = 3

CMD_LIGHT_STATE = 300      # read -> [mode, 0,0,0, effect, ...]
CMD_LIGHT_ACTIONS = 501    # action -> light control

# Device info / diagnostics (decimal cmd types, decoded from a live capture).
CMD_DEVICE_PROFILE = 1     # deviceType + version numbers
CMD_DEVICE_DATE = 3        # [day, month, year-2000, dow]
CMD_STATS_RUN_HOURS = 602  # zone1 run hours (uint32 LE)

# Timer characteristics (decimal cmd types, decoded from a live capture).
CMD_DEVICE_TIME = 2        # read -> live device clock
CMD_TIMER_CAPS = 400       # read -> capabilities (byte 1 ~ timer count)
CMD_TIMER_SETUP = 401
CMD_TIMER_STATE = 402
CMD_TIMER_CONFIG = 403     # read (select by type/index/season) / write (op 3)

# TimerConfiguration (cmd 403) payload layout:
#   [0]type [1]index [2]season [3]enabledMask [4]writeMask
#   [7]startHour [8]startMin [10]stopHour [11]stopMin
TIMER_TYPE_CLOCK = 1       # time-of-day timer (the default type)
TIMER_WRITE_MASK = 0x0F    # byte 4 on an op-3 write = "apply start/stop fields"
DEFAULT_TIMER_COUNT = 2    # confirmed from capabilities on the reference unit

# LightAppActions (payload[0]) for cmd 501. Full enum (from the app / the
# sibling pychlorinator library, UUIDs + on/off/effect bytes confirmed against
# the BLE capture):
#   0 NoAction  1 SetZoneModeToManual  2 SetZoneModeToAuto  3 TurnOffZone
#   4 TurnOnZone  5 SetZoneColour  6 SynchroniseZoneColour
# We use SetZoneModeToManual (1) for "on" - that is what the app sent and it
# works. Auto (2) puts the light on its internal timer schedule.
LIGHT_ACTION_ON = 0x01
LIGHT_ACTION_AUTO = 0x02
LIGHT_ACTION_OFF = 0x03
LIGHT_ACTION_SET_EFFECT = 0x05

# LightState modes (payload[0] of a cmd 300 response)
MODE_OFF = 0
MODE_AUTO = 1
MODE_ON = 2

FRAME_LEN = 20

# Effect/colour presets for the SLX/FLX light type, as the SetZoneColour byte
# (payload[2] of a cmd-501 action-5 frame). Verified from the official app's
# LightPreset table (ids 0-11) and cross-checked against the BLE capture
# (effect 4->3 == Green->Orange). Indices 7-8 ("Custom …") recall a user-stored
# colour/pattern and may do nothing until one has been set from the app.
EFFECT_NAMES: dict[int, str] = {
    0: "Blue",
    1: "Magenta",
    2: "Red",
    3: "Orange",
    4: "Green",
    5: "Aqua",
    6: "White",
    7: "Custom Colour",
    8: "Custom Pattern",
    9: "Rainbow",
    10: "Ocean",
    11: "Disco",
}
