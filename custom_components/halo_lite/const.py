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
# struct <BBBBBBI4sBBBBBBB (company id already stripped by HA):
#   DeviceType, DeviceVersion, DeviceProtocol, DeviceProtocolRevision,
#   DeviceStatus, reserved, DeviceUniqueId(uint32 LE), ByteAccessCode(4),
#   FwMajor, FwMinor, BootMajor, BootMinor, HwLo, HwHi, TimeAlive
ADV_UNIQUE_ID_OFFSET = 6      # 4-byte uint32 LE serial number
ADV_ACCESS_CODE_OFFSET = 10   # 4-byte ASCII access code
ADV_ACCESS_CODE_LEN = 4

# --- Protocol opcodes / command types --------------------------------------
OPCODE_RESPONSE = 1
OPCODE_READ = 2
OPCODE_ACTION = 3

CMD_LIGHT_STATE = 300      # read -> [mode, 0,0,0, effect, ...]
CMD_LIGHT_ACTIONS = 501    # action -> light control

# LightAppActions (payload[0]) for cmd 501
LIGHT_ACTION_ON = 0x01
LIGHT_ACTION_OFF = 0x03
LIGHT_ACTION_SET_EFFECT = 0x05

# LightState modes (payload[0] of a cmd 300 response)
MODE_OFF = 0
MODE_AUTO = 1
MODE_ON = 2

FRAME_LEN = 20

# Default effect names (indices are device presets; refine once fully mapped).
EFFECT_NAMES: dict[int, str] = {
    0: "effect_0",
    1: "effect_1",
    2: "effect_2",
    3: "effect_3",
    4: "effect_4",
    5: "effect_5",
    6: "effect_6",
}
