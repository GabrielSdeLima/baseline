"""HC900 BLE scale importer — end-to-end pipeline.

Orchestrates a complete scale measurement import:
  1. Loads user profile (scale_profile.json + optional CLI overrides)
  2. Scans BLE for a stable HC900 reading
  3. Decodes the advertisement bytes natively via app.integrations.hc900
  4. Builds the normalised raw_payload with full audit fields
  5. POSTs to the Baseline ingestion API

The decoder is Python-native (``hc900_ble_v2``); no Dart/Flutter toolchain
is required. The raw advertisement bytes are preserved on the payload so
future decoder revisions can reprocess historical measurements.

Prerequisites:
  - PostgreSQL running and migrations applied:
        docker compose up -d && alembic upgrade head
  - Baseline API running:
        uvicorn app.main:app --reload
  - User profile configured:
        cp scripts/scale_profile.json.example scripts/scale_profile.json
        # edit scale_profile.json with your biometric data

Usage:
    python scripts/import_scale.py --user-id <UUID>
    python scripts/import_scale.py --user-id <UUID> --mac A0:91:5C:92:CF:17
    python scripts/import_scale.py --user-id <UUID> --dry-run
    python scripts/import_scale.py --user-id <UUID> --height-cm 180 --birth-date 1985-03-10 --sex 1
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path

import httpx

from app.integrations.hc900 import decode_hc900

# ── Paths ─────────────────────────────────────────────────────────────────────

_SCRIPTS_DIR = Path(__file__).parent
_PROFILE_PATH = _SCRIPTS_DIR / "scale_profile.json"

_DEFAULT_API_URL = os.environ.get("BASELINE_API_URL", "http://localhost:8000")
_DEFAULT_USER_ID = os.environ.get("BASELINE_USER_ID")

logger = logging.getLogger(__name__)


# ── User profile ──────────────────────────────────────────────────────────────

def load_profile(
    height_cm: int | None = None,
    birth_date: str | None = None,
    sex: int | None = None,
) -> dict:
    """Load user profile from scale_profile.json, then apply CLI overrides.

    CLI arguments take precedence over the file.  Raises ValueError if any
    required field is missing after merging.
    """
    profile: dict = {}

    if _PROFILE_PATH.exists():
        with open(_PROFILE_PATH) as f:
            raw = json.load(f)
        profile = {k: v for k, v in raw.items() if not k.startswith("_")}

    if height_cm is not None:
        profile["height_cm"] = height_cm
    if birth_date is not None:
        profile["birth_date"] = birth_date
    if sex is not None:
        profile["sex"] = sex

    missing = [f for f in ("height_cm", "birth_date", "sex") if f not in profile]
    if missing:
        raise ValueError(
            f"Missing profile fields: {missing}. "
            "Create scripts/scale_profile.json or pass --height-cm / --birth-date / --sex."
        )

    return profile


def calculate_age(birth_date: date, as_of: date) -> int:
    """Derive age in whole years from birth_date as of a given date.

    Uses calendar birthday: age increments on the birthday, not on the exact
    second of birth.
    """
    age = as_of.year - birth_date.year
    if (as_of.month, as_of.day) < (birth_date.month, birth_date.day):
        age -= 1
    return age


# ── In-process decoder ────────────────────────────────────────────────────────

def decode_reading(
    mfr_weight: list[int],
    mfr_impedance: list[int] | None,
    height_cm: int,
    age: int,
    sex: int,
) -> dict:
    """Decode HC900 advertisement bytes into the full v2 measurement dict.

    Thin wrapper around :func:`app.integrations.hc900.decode_hc900` that
    returns the serialisable dict form expected by the raw_payload
    contract (``decoder_version`` + all primary/derived fields).  BMI and
    BMR are populated from the profile even when impedance is absent;
    body-composition fields stay ``None`` until impedance is captured.
    """
    reading = decode_hc900(
        mfr_weight,
        mfr_impedance,
        height_cm=height_cm,
        age=age,
        sex=sex,
    )
    return reading.to_dict()


# ── External ID (deduplication key) ──────────────────────────────────────────

def build_external_id(
    device_mac: str,
    measured_at: datetime,
    weight_kg: float,
    impedance_adc: int | None,
) -> str:
    """Build a deterministic, human-readable deduplication key.

    Format:
        hc900_{mac_no_colon}_{YYYYmmddTHHMM}_{weight_grams}_{impedance_adc|x}

    Example:
        hc900_a0915c92cf17_20260415T0730_74800_47450
        hc900_a0915c92cf17_20260415T0730_74800_x      (weight-only, no impedance)

    Collision resistance:
        - MAC: isolates readings from different physical devices
        - Minute precision: absorbs BLE timestamp jitter between scan sessions
        - weight_grams: distinguishes different weights in the same minute
        - impedance_adc: eliminates residual collision risk (two measurements
          with identical weight AND impedance at the same minute on the same
          device are physically indistinguishable — they are the same event)
    """
    mac = device_mac.replace(":", "").lower()
    ts = measured_at.strftime("%Y%m%dT%H%M")
    weight_g = round(weight_kg * 1000)
    imp = str(impedance_adc) if impedance_adc is not None else "x"
    return f"hc900_{mac}_{ts}_{weight_g}_{imp}"


# ── Raw payload builder ───────────────────────────────────────────────────────

def build_raw_payload(
    scan_result,        # ScaleScanResult
    decoded: dict,
    profile: dict,
    age: int,
) -> dict:
    """Build the complete raw_payload dict for the Baseline ingestion API.

    Temporal semantics (V2):
        captured_at  — when bleak captured the advertisement packets (machine clock, UTC)
        measured_at  — effective timestamp of the measurement
                       V2: equals captured_at (explicit, not implicit)
                       Future: may diverge if user manually sets measurement time

    Audit fields preserved:
        raw_mfr_*_hex          — original advertisement bytes for reprocessing
        decoded                — exact output of the native Python decoder
                                 (decoder_version = 'hc900_ble_v2')
        user_profile_snapshot  — profile values used for body-comp calculation,
                                 frozen at measurement time (age changes — this captures it)
    """
    captured_at_iso = scan_result.captured_at.isoformat()
    measured_at_iso = captured_at_iso  # V2: explicit equality

    def to_hex(b: list[int] | None) -> str | None:
        return "".join(f"{x:02x}" for x in b) if b else None

    return {
        "format_version": "hc900_ble_v2",
        "device_mac": scan_result.device_mac,
        "captured_at": captured_at_iso,
        "measured_at": measured_at_iso,
        "_measured_at_note": (
            "V2: measured_at == captured_at. "
            "Future versions may allow manual time override."
        ),
        "capture_method": "bleak_scan",
        "raw_mfr_weight_hex": to_hex(scan_result.mfr_weight),
        "raw_mfr_impedance_hex": to_hex(scan_result.mfr_impedance),
        "decoded": decoded,
        "user_profile_snapshot": {
            "height_cm": profile["height_cm"],
            "birth_date": profile["birth_date"],
            "age": age,
            "sex": profile["sex"],
        },
    }


# ── Ingestion API call ────────────────────────────────────────────────────────

async def ingest(
    api_url: str,
    user_id: str,
    external_id: str,
    payload_json: dict,
    *,
    ingestion_run_id: str | None = None,
    user_device_id: str | None = None,
    agent_instance_id: str | None = None,
) -> dict:
    """POST the normalised payload to the Baseline ingestion API."""
    body = {
        "user_id": user_id,
        "source_slug": "hc900_ble",
        "external_id": external_id,
        "payload_type": "hc900_scale",
        "payload_json": payload_json,
    }
    if ingestion_run_id is not None:
        body["ingestion_run_id"] = ingestion_run_id
    if user_device_id is not None:
        body["user_device_id"] = user_device_id
    if agent_instance_id is not None:
        body["agent_instance_id"] = agent_instance_id
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(f"{api_url}/api/v1/raw-payloads/ingest", json=body)
        response.raise_for_status()
        return response.json()


# ── Main pipeline ─────────────────────────────────────────────────────────────

async def run(args: argparse.Namespace) -> None:
    # 1. User profile
    try:
        profile = load_profile(
            height_cm=args.height_cm,
            birth_date=args.birth_date,
            sex=args.sex,
        )
    except ValueError as e:
        logger.error("%s", e)
        sys.exit(1)

    # 2. BLE scan — import deferred to avoid loading bleak before --help is shown
    logger.info("Starting BLE scan (timeout=%ds) …", int(args.timeout))
    logger.info("Step on the scale and stand still until the display locks.")

    # scan_scale.py is in the same scripts/ directory — import by name
    sys.path.insert(0, str(_SCRIPTS_DIR))
    from scan_scale import IncompleteMeasurementError, scan_for_reading  # noqa: PLC0415

    try:
        scan_result = await scan_for_reading(
            mac_filter=args.mac,
            timeout=args.timeout,
        )
    except TimeoutError as e:
        logger.error("%s", e)
        sys.exit(1)
    except IncompleteMeasurementError as e:
        logger.error("%s", e)
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Interrupted.")
        sys.exit(0)

    logger.info(
        "Scale reading captured from %s at %s",
        scan_result.device_mac,
        scan_result.captured_at.isoformat(),
    )

    # 3. Age at measurement time (derived from birth_date + captured_at)
    birth = date.fromisoformat(profile["birth_date"])
    age = calculate_age(birth, scan_result.captured_at.date())

    # 4. Decode (native Python decoder — app.integrations.hc900, v2 contract)
    logger.info("Decoding advertisement bytes …")
    try:
        decoded = decode_reading(
            mfr_weight=scan_result.mfr_weight,
            mfr_impedance=scan_result.mfr_impedance,
            height_cm=int(profile["height_cm"]),
            age=age,
            sex=int(profile["sex"]),
        )
    except ValueError as e:
        logger.error("Decoder error: %s", e)
        sys.exit(1)

    logger.info(
        "Decoded: weight=%.1f kg  body_fat=%s%%  impedance=%s",
        decoded["weight_kg"],
        decoded.get("body_fat_pct", "n/a"),
        decoded.get("impedance_adc", "n/a"),
    )

    # 5. Build raw payload
    payload_json = build_raw_payload(scan_result, decoded, profile, age)
    measured_at = datetime.fromisoformat(payload_json["measured_at"])
    external_id = build_external_id(
        device_mac=scan_result.device_mac,
        measured_at=measured_at,
        weight_kg=decoded["weight_kg"],
        impedance_adc=decoded.get("impedance_adc"),
    )
    logger.info("external_id: %s", external_id)

    if args.dry_run:
        print("\n── DRY RUN — payload that would be submitted ──────────────────────")
        print(json.dumps({"external_id": external_id, "payload_json": payload_json}, indent=2))
        logger.info("Dry run complete — nothing submitted.")
        return

    # 6. Ingest via API
    logger.info("Submitting to Baseline API (%s) …", args.api_url)
    try:
        result = await ingest(
            api_url=args.api_url,
            user_id=args.user_id,
            external_id=external_id,
            payload_json=payload_json,
            ingestion_run_id=getattr(args, "ingestion_run_id", None),
            user_device_id=getattr(args, "user_device_id", None),
            agent_instance_id=getattr(args, "agent_instance_id", None),
        )
    except httpx.HTTPStatusError as e:
        logger.error("API error %d: %s", e.response.status_code, e.response.text)
        sys.exit(1)

    status = result.get("processing_status", "unknown")
    logger.info(
        "Done — raw_payload id=%s  status=%s",
        result.get("id"),
        status,
    )

    if status == "failed":
        logger.error("Parser failed: %s", result.get("error_message"))
        sys.exit(1)

    # User-facing completion line on stdout — the scan API returns stdout as
    # the message shown in the UI, so this is what the user actually sees.
    summary = f"Pesagem concluída: {decoded['weight_kg']:.1f} kg"
    body_fat = decoded.get("body_fat_pct")
    if body_fat is not None:
        summary += f" • gordura {body_fat:.1f}%"
    print(summary)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Import a real HC900 BLE scale reading into Baseline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--user-id",
        default=_DEFAULT_USER_ID,
        required=_DEFAULT_USER_ID is None,
        metavar="UUID",
        help=(
            "Baseline user UUID to associate the measurement with "
            "(falls back to BASELINE_USER_ID env var)"
        ),
    )
    p.add_argument(
        "--mac",
        default=None,
        metavar="MAC",
        help="BLE MAC address filter (e.g. A0:91:5C:92:CF:17). "
             "If omitted, uses the first HC900 found.",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=90.0,
        metavar="SEC",
        help="BLE scan timeout in seconds (default: 90)",
    )
    p.add_argument(
        "--api-url",
        default=_DEFAULT_API_URL,
        metavar="URL",
        help=f"Baseline API base URL (default: {_DEFAULT_API_URL})",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan and decode, but print the payload instead of submitting it",
    )
    g = p.add_argument_group("profile overrides (take precedence over scale_profile.json)")
    g.add_argument("--height-cm", type=int, metavar="CM")
    g.add_argument(
        "--birth-date",
        metavar="YYYY-MM-DD",
        help="Birth date for age-at-measurement derivation",
    )
    g.add_argument("--sex", type=int, choices=[1, 2], metavar="1|2", help="1=male 2=female")
    p.add_argument(
        "--ingestion-run-id",
        default=None,
        metavar="UUID",
        help="Link ingested payload to this IngestionRun UUID (set by scan_scale endpoint)",
    )
    p.add_argument(
        "--user-device-id",
        default=None,
        metavar="UUID",
        help="UserDevice UUID to attach to the raw_payload (set by scan_scale endpoint)",
    )
    p.add_argument(
        "--agent-instance-id",
        default=None,
        metavar="UUID",
        help="AgentInstance UUID to attach to the raw_payload (set by scan_scale endpoint)",
    )
    p.add_argument("--debug", action="store_true", help="Enable debug logging")
    return p


if __name__ == "__main__":
    _args = _build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if _args.debug else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    asyncio.run(run(_args))
