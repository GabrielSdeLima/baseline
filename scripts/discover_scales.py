"""BLE discovery for HC900 smart scales.

Scans for any HC900 advertisement (company ID 0xA0AC) and emits one JSON
line to stdout the first time each unique MAC is observed.  Intended to be
called as a subprocess by the Baseline API, which streams the stdout
incrementally to the UI so devices show up as they are found.

Output format (NDJSON, one per line):
    {"mac": "A0:91:5C:92:CF:17", "name": "HC900", "rssi": -52}

Usage:
    python scripts/discover_scales.py [--timeout 15]
"""

import argparse
import asyncio
import json
import logging
import sys

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

HC900_COMPANY_ID = 0xA0AC

logger = logging.getLogger(__name__)


async def discover(timeout: float) -> None:
    seen: set[str] = set()

    def _callback(device: BLEDevice, adv: AdvertisementData) -> None:
        if HC900_COMPANY_ID not in adv.manufacturer_data:
            return
        mac = device.address
        if mac in seen:
            return
        seen.add(mac)
        record = {
            "mac": mac,
            "name": device.name or adv.local_name or "HC900",
            "rssi": adv.rssi,
        }
        # Single JSON line per device, flushed immediately so the API can
        # forward it to the client without buffering.
        print(json.dumps(record), flush=True)

    scanner = BleakScanner(detection_callback=_callback)
    await scanner.start()
    try:
        await asyncio.sleep(timeout)
    finally:
        await scanner.stop()


def main() -> None:
    p = argparse.ArgumentParser(description="Discover HC900 BLE scales")
    p.add_argument("--timeout", type=float, default=15.0, help="Scan duration in seconds")
    p.add_argument("--debug", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    try:
        asyncio.run(discover(args.timeout))
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
