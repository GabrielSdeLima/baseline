"""HC900 BLE scale — protocol decode + body composition.

Replaces the previous Pulso dart CLI dependency.  The public surface is
:func:`decode_hc900`, which turns raw manufacturer bytes (plus user
profile) into a :class:`DecodedReading` containing every primary and
derived metric the scale can produce.
"""

from app.integrations.hc900.decoder import DecodedReading, decode_hc900
from app.integrations.hc900.protocol import (
    HC900_COMPANY_ID,
    ImpedancePacket,
    WeightPacket,
    decode_packet,
)

__all__ = [
    "DecodedReading",
    "decode_hc900",
    "HC900_COMPANY_ID",
    "ImpedancePacket",
    "WeightPacket",
    "decode_packet",
]
