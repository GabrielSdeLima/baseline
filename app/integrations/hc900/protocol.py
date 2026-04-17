"""HC900 BLE advertisement decoder.

Pure-function port of the Dart reference in
``pulso-app/lib/features/health/ble/scale_protocol.dart``.  The HC900
broadcasts 14-byte manufacturer-data packets under company ID 0xA0AC.
Each advertisement is either a weight packet (type 0x0D) or an
impedance packet (type 0x06); the three data bytes are XOR-encrypted
with fixed keys (no key exchange, no rotating nonce).

Byte layout (indices into the 14-byte `mfr` array, which *includes* the
2-byte company ID at [0..1]):

    [0-1]   Company ID  : AC A0  (little-endian 0xA0AC) — validation only
    [2-7]   Device MAC  : reversed, unused in decode
    [8]     Flags       : bit 7 clear → stable weight; bit 7 set → measuring
    [9-11]  Data bytes  : XOR-encrypted (keys depend on packet type)
    [12]    Packet type : 0x0D = weight, 0x06 = impedance
    [13]    Checksum    : not validated (scale never emits bad checksums
                          in practice, and the proprietary stack also
                          skips verification)

The decoder is deliberately tolerant: it returns ``None`` for non-HC900
advertisements so a BLE scanner can forward *every* packet without
prefiltering.
"""

from __future__ import annotations

from dataclasses import dataclass

HC900_COMPANY_ID = 0xA0AC  # little-endian bytes: AC A0

_PKT_WEIGHT = 0x0D
_PKT_IMPEDANCE = 0x06

_STABLE_FLAG_MASK = 0x80  # mfr[8] bit 7 clear → stable weight

# XOR keys for the weight packet (type 0x0D), applied to bytes 9, 10, 11.
_WEIGHT_XOR_KEYS = (0x2C, 0xA0, 0xA0)

# XOR key reused for both impedance bytes (9 and 11).
_IMPEDANCE_XOR_KEY = 0xA0


@dataclass(frozen=True, slots=True)
class WeightPacket:
    weight_kg: float
    is_stable: bool


@dataclass(frozen=True, slots=True)
class ImpedancePacket:
    """Impedance advertisement.

    ``adc`` is the raw counter value from the scale — proportional to
    electrical impedance but *not* expressed in ohms.  We keep the
    native unit rather than applying an unverified conversion factor.
    """

    adc: int | None  # None when scale reports 0 (contact not yet established)


def decode_packet(mfr: bytes | list[int]) -> WeightPacket | ImpedancePacket | None:
    """Decode a 14-byte HC900 advertisement.

    Returns ``None`` for malformed inputs or foreign company IDs so the
    caller can forward every BLE packet without prefiltering.
    """
    if len(mfr) < 14:
        return None
    if mfr[0] != 0xAC or mfr[1] != 0xA0:
        return None

    packet_type = mfr[12]

    if packet_type == _PKT_WEIGHT:
        is_stable = (mfr[8] & _STABLE_FLAG_MASK) == 0
        w_hi, w_mid, w_lo = (
            mfr[9] ^ _WEIGHT_XOR_KEYS[0],
            mfr[10] ^ _WEIGHT_XOR_KEYS[1],
            mfr[11] ^ _WEIGHT_XOR_KEYS[2],
        )
        weight_g = (w_hi << 16) | (w_mid << 8) | w_lo
        return WeightPacket(weight_kg=weight_g / 1000.0, is_stable=is_stable)

    if packet_type == _PKT_IMPEDANCE:
        # Byte order is reversed vs weight: high byte comes from mfr[11].
        hi = mfr[11] ^ _IMPEDANCE_XOR_KEY
        lo = mfr[9] ^ _IMPEDANCE_XOR_KEY
        adc = (hi << 8) | lo
        return ImpedancePacket(adc=adc if adc > 0 else None)

    return None


def hex_to_bytes(hex_str: str) -> list[int]:
    """Decode a lowercase hex string (no separators) into a byte list.

    Used by the parser to replay payloads stored as ``raw_mfr_*_hex``
    fields without pulling in a crypto-hex dependency.
    """
    return list(bytes.fromhex(hex_str))
