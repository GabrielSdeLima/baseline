"""BLE scanner for the HC900 smart scale.

Passively scans for HC900 BLE advertisements (company ID 0xA0AC), collects
weight and impedance packets, and returns the raw manufacturer bytes once a
stable reading is captured.

This module knows only enough to collect the right packets — it does NOT
decode the XOR-encrypted values or compute body composition.  Decoding is
the responsibility of the Pulso decode_scale.dart CLI.

Usage as a module:
    from scan_scale import scan_for_reading
    result = asyncio.run(scan_for_reading())

Usage as a standalone script (for debugging):
    python scripts/scan_scale.py [--mac A0:91:5C:92:CF:17] [--timeout 90]
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import UTC, datetime

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

logger = logging.getLogger(__name__)

HC900_COMPANY_ID = 0xA0AC  # little-endian: AC A0

# Manufacturer data layout received from bleak (12 bytes, i.e. mfr[2..13]):
#   [0-5]  Device MAC (reversed)
#   [6]    Flags: bit 7 set = scale is measuring, clear = stable
#   [7-9]  Weight bytes (XOR-encrypted — not decoded here)
#   [10]   Packet type: 0x0D = weight, 0x06 = impedance
#   [11]   Checksum
_PKT_WEIGHT = 0x0D
_PKT_IMPEDANCE = 0x06
_STABLE_FLAG_MASK = 0x80   # mfr[6] bit 7 clear → scale reports stable weight
_STABLE_CONSEC = 5         # consecutive identical weight-byte triples → stable
_IMPEDANCE_GRACE_S = 15.0  # wait this long after stable weight for impedance packet


class IncompleteMeasurementError(Exception):
    """Stable weight captured but the impedance packet never arrived.

    HC900 emits impedance only after the user stands still long enough for the
    bioimpedance sweep to complete.  Stepping off early produces a weight-only
    reading that is not usable for body composition, so we fail the scan and
    ask the user to step back on instead of silently saving a partial record.
    """


class ScaleScanResult:
    """Raw bytes from a completed HC900 measurement session."""

    def __init__(
        self,
        device_mac: str,
        mfr_weight: list[int],
        mfr_impedance: list[int] | None,
        captured_at: datetime,
    ) -> None:
        self.device_mac = device_mac
        # Full 14-byte arrays (company ID prepended) as expected by the Dart CLI
        self.mfr_weight = mfr_weight
        self.mfr_impedance = mfr_impedance
        self.captured_at = captured_at


async def scan_for_reading(
    mac_filter: str | None = None,
    timeout: float = 90.0,
) -> ScaleScanResult:
    """Scan BLE until a complete HC900 measurement is captured.

    Args:
        mac_filter: If given, only accept advertisements from this MAC address
                    (case-insensitive, e.g. "A0:91:5C:92:CF:17").
        timeout:    Maximum scan duration in seconds.  Raises TimeoutError if
                    no stable reading is captured within this window.

    Returns:
        ScaleScanResult with raw manufacturer bytes ready for the Dart decoder.
    """
    mac_upper = mac_filter.upper() if mac_filter else None
    loop = asyncio.get_running_loop()

    result_future: asyncio.Future[ScaleScanResult] = loop.create_future()
    stable_weight_bytes: list[int] | None = None
    impedance_bytes: list[int] | None = None
    last_weight_triple: bytes | None = None
    stable_count = 0
    impedance_timer_handle = None
    detected_mac: str | None = None

    def _emit_now() -> None:
        if result_future.done():
            return
        assert stable_weight_bytes is not None
        assert detected_mac is not None
        result_future.set_result(
            ScaleScanResult(
                device_mac=detected_mac,
                mfr_weight=stable_weight_bytes,
                mfr_impedance=impedance_bytes,
                captured_at=datetime.now(UTC),
            )
        )
        logger.debug("[scan] result emitted for %s", detected_mac)

    def _fail_incomplete() -> None:
        if result_future.done():
            return
        logger.info("[scan] impedance timeout — incomplete measurement")
        result_future.set_exception(
            IncompleteMeasurementError(
                "Saiu da balança antes da leitura de impedância. "
                "Suba de novo e fique parado até o display travar."
            )
        )

    def _schedule_impedance_timeout() -> None:
        nonlocal impedance_timer_handle
        if impedance_timer_handle is None:
            # Require impedance for a complete reading; if it doesn't arrive
            # within the grace window, fail the scan so the user knows to
            # step back on rather than accepting a weight-only record.
            impedance_timer_handle = loop.call_later(_IMPEDANCE_GRACE_S, _fail_incomplete)

    def _callback(device: BLEDevice, adv: AdvertisementData) -> None:
        nonlocal stable_weight_bytes, impedance_bytes, last_weight_triple
        nonlocal stable_count, detected_mac

        if result_future.done():
            return

        mfr_data = adv.manufacturer_data.get(HC900_COMPANY_ID)
        if mfr_data is None or len(mfr_data) < 12:
            return

        if mac_upper and device.address.upper() != mac_upper:
            return

        if detected_mac is None:
            detected_mac = device.address
            logger.info("[scan] HC900 found: %s", detected_mac)

        # Reconstruct the 14-byte mfr array expected by the Dart decoder
        full_mfr: list[int] = [0xAC, 0xA0, *mfr_data]
        packet_type = full_mfr[12]

        if packet_type == _PKT_WEIGHT:
            weight_triple = bytes(full_mfr[9:12])
            is_stable_flag = (full_mfr[8] & _STABLE_FLAG_MASK) == 0

            if weight_triple == last_weight_triple:
                stable_count += 1
            else:
                stable_count = 1
            last_weight_triple = weight_triple

            is_stable = is_stable_flag or stable_count >= _STABLE_CONSEC

            if is_stable and stable_weight_bytes is None:
                stable_weight_bytes = full_mfr
                logger.info(
                    "[scan] stable weight captured (stable_flag=%s, consec=%d)",
                    is_stable_flag,
                    stable_count,
                )
                if impedance_bytes is not None:
                    loop.call_soon(_emit_now)
                else:
                    loop.call_soon(_schedule_impedance_timeout)

        elif packet_type == _PKT_IMPEDANCE:
            if impedance_bytes is None:
                impedance_bytes = full_mfr
                logger.info("[scan] impedance packet captured")
                if stable_weight_bytes is not None:
                    if impedance_timer_handle is not None:
                        impedance_timer_handle.cancel()
                    loop.call_soon(_emit_now)

    scanner = BleakScanner(detection_callback=_callback)
    await scanner.start()
    try:
        await asyncio.wait_for(result_future, timeout=timeout)
    except TimeoutError:
        raise TimeoutError(
            f"No stable HC900 reading captured within {timeout:.0f}s. "
            "Make sure the scale is powered on and within BLE range."
        )
    finally:
        await scanner.stop()

    return result_future.result()


# ── CLI entry-point (for debugging / standalone use) ──────────────────────────

def _cli() -> None:
    parser = argparse.ArgumentParser(description="Scan for HC900 BLE scale reading")
    parser.add_argument("--mac", help="Filter by device MAC (e.g. A0:91:5C:92:CF:17)")
    parser.add_argument("--timeout", type=float, default=90.0, help="Scan timeout in seconds")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    try:
        result = asyncio.run(scan_for_reading(mac_filter=args.mac, timeout=args.timeout))
    except TimeoutError as e:
        print(f"TIMEOUT: {e}", file=sys.stderr)
        sys.exit(1)
    except IncompleteMeasurementError as e:
        print(f"INCOMPLETE: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        sys.exit(1)

    print(
        json.dumps(
            {
                "device_mac": result.device_mac,
                "captured_at": result.captured_at.isoformat(),
                "mfr_weight": result.mfr_weight,
                "mfr_impedance": result.mfr_impedance,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    _cli()
