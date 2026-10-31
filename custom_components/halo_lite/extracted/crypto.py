"""Pure crypto + frame encode/decode for the Halo Lite Gen2 BLE protocol.

No Home Assistant or Bluetooth dependencies here so this module can be unit
tested in isolation (and reused standalone). Reverse engineered from the
official app's ``libapp.so`` and validated byte-for-byte against a real
``btsnoop`` capture.

The scheme is the same one used by the ``pychlorinator`` project for the
sibling Halo chlorinator: a fixed, public AES-128 key (the FIPS-197 test
vector), with the per-connection 16-byte session key used as an XOR mask.
It is obfuscation, not real encryption.
"""

from __future__ import annotations

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .const import FRAME_LEN

# FIPS-197 / SP 800-38A AES-128 test-vector key (public, not a secret).
SECRET_KEY = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")


def _aes_ecb_encrypt(data: bytes) -> bytes:
    enc = Cipher(algorithms.AES(SECRET_KEY), modes.ECB()).encryptor()  # noqa: S305
    return enc.update(data) + enc.finalize()


def _aes_ecb_decrypt(data: bytes) -> bytes:
    dec = Cipher(algorithms.AES(SECRET_KEY), modes.ECB()).decryptor()  # noqa: S305
    return dec.update(data) + dec.finalize()


def xor_bytes(array1: bytes, array2: bytes) -> bytes:
    """XOR two byte strings, zero-padding the shorter on the right."""
    short, long = sorted((array1, array2), key=len)
    short = short.ljust(len(long), b"\x00")
    return bytes(a ^ b for a, b in zip(short, long))


def compute_auth(session_key: bytes, access_code: bytes) -> bytes:
    """Return the 16-byte value to write to the master-auth characteristic.

    ``auth = AES_ECB(SECRET_KEY, session_key XOR access_code.pad16)``
    where ``access_code`` is the 4 ASCII bytes from the advertisement.
    """
    if len(session_key) != 16:
        raise ValueError("session_key must be 16 bytes")
    return _aes_ecb_encrypt(xor_bytes(session_key, access_code))


def encrypt_characteristic(data: bytes, session_key: bytes) -> bytes:
    """Encrypt a 20-byte command frame for the RX (command) characteristic."""
    if len(data) != FRAME_LEN:
        raise ValueError("frame must be 20 bytes")
    masked = xor_bytes(data, session_key)
    block1 = _aes_ecb_encrypt(masked[0:16])
    intermediate = block1 + masked[16:FRAME_LEN]
    block2 = _aes_ecb_encrypt(intermediate[4:FRAME_LEN])
    return intermediate[0:4] + block2


def decrypt_characteristic(data: bytes, session_key: bytes) -> bytes:
    """Decrypt a 20-byte notification frame from the TX characteristic."""
    if len(data) != FRAME_LEN:
        raise ValueError("frame must be 20 bytes")
    block2 = _aes_ecb_decrypt(bytes(data[4:FRAME_LEN]))
    intermediate = bytes(data[0:4]) + block2
    block1 = _aes_ecb_decrypt(intermediate[0:16])
    masked = block1 + intermediate[16:FRAME_LEN]
    return xor_bytes(masked, session_key)


def build_frame(opcode: int, cmd_type: int, payload: bytes, counter: int) -> bytes:
    """Assemble a 20-byte plaintext frame.

    Layout: ``[opcode][cmd_type uint16 LE][payload...][counter]`` padded to 20,
    with ``counter`` occupying the final byte.
    """
    head = bytes([opcode]) + int(cmd_type).to_bytes(2, "little") + payload
    if len(head) > FRAME_LEN - 1:
        raise ValueError("payload too long for a 20-byte frame")
    return head.ljust(FRAME_LEN - 1, b"\x00") + bytes([counter & 0xFF])


def parse_frame(plaintext: bytes) -> tuple[int, int, bytes, int]:
    """Return (opcode, cmd_type, payload, counter) from a decrypted frame."""
    opcode = plaintext[0]
    cmd_type = int.from_bytes(plaintext[1:3], "little")
    payload = plaintext[3 : FRAME_LEN - 1]
    counter = plaintext[FRAME_LEN - 1]
    return opcode, cmd_type, payload, counter
