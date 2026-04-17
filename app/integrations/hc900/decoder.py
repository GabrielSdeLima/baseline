"""Top-level HC900 decoder — Baseline's replacement for the Pulso CLI.

Call :func:`decode_hc900` with raw 14-byte advertisement packets (plus
profile inputs when impedance is available) and receive a single
:class:`DecodedReading` with every primary and derived metric.  The
output shape is a superset of the Dart CLI's legacy ``hc900_ble_v1``
contract and is tagged ``hc900_ble_v2``.

Design notes:

- Two primary metrics come straight from the sensor: ``weight_kg`` and
  ``impedance_adc``.  Everything else is derived via the formulas in
  :mod:`.body_composition`.
- Derived metrics that depend on impedance are only populated when a
  valid impedance packet is present.  We never fabricate body-comp
  values from weight alone (per the "no inventing data" invariant).
- BMI and BMR *can* be computed from weight + profile alone, so they
  are populated even on impedance-missing readings.
- Returning a dataclass (rather than a plain dict) gives the parser a
  stable typed surface and forces contract breakages to be visible.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from app.integrations.hc900 import body_composition as bc
from app.integrations.hc900.protocol import (
    ImpedancePacket,
    WeightPacket,
    decode_packet,
)

DECODER_VERSION = "hc900_ble_v2"


@dataclass(frozen=True, slots=True)
class DecodedReading:
    """Complete HC900 decoded reading.

    Fields that cannot be derived without impedance are ``None`` on
    weight-only readings; the parser persists only what is present.
    """

    # Primary metrics (sensor values)
    weight_kg: float
    impedance_adc: int | None

    # Impedance-independent derived
    bmi: float | None
    bmr: int | None

    # Impedance-dependent derived (all None together)
    body_fat_pct: float | None
    fat_free_mass_kg: float | None
    fat_mass_kg: float | None
    muscle_mass_kg: float | None
    muscle_pct: float | None
    skeletal_muscle_mass_kg: float | None
    skeletal_muscle_pct: float | None
    water_mass_kg: float | None
    water_pct: float | None
    protein_mass_kg: float | None
    protein_pct: float | None
    bone_mass_kg: float | None
    ffmi: float | None
    fmi: float | None

    # Metadata
    decoder_version: str = DECODER_VERSION

    @property
    def has_impedance(self) -> bool:
        return self.impedance_adc is not None

    def to_dict(self) -> dict:
        """Serializable dict matching the ``payload_json['decoded']`` shape."""
        return asdict(self)


def decode_hc900(
    mfr_weight: bytes | list[int],
    mfr_impedance: bytes | list[int] | None = None,
    *,
    height_cm: int | None = None,
    age: int | None = None,
    sex: int | None = None,
) -> DecodedReading:
    """Decode an HC900 reading into a full body-composition record.

    Args:
        mfr_weight: 14-byte weight advertisement (includes company ID).
        mfr_impedance: 14-byte impedance advertisement, if captured.
        height_cm, age, sex: user profile, required only when impedance
            is provided (needed for the BIA regressions) or when you
            want ``bmi``/``bmr`` in the output.

    Raises:
        ValueError: if ``mfr_weight`` is missing/malformed or if
            impedance is present but the profile is incomplete.
    """
    weight_pkt = decode_packet(mfr_weight)
    if not isinstance(weight_pkt, WeightPacket):
        raise ValueError("mfr_weight is not a valid HC900 weight packet")

    impedance_adc: int | None = None
    if mfr_impedance is not None:
        imp_pkt = decode_packet(mfr_impedance)
        if isinstance(imp_pkt, ImpedancePacket) and imp_pkt.adc is not None:
            impedance_adc = imp_pkt.adc

    # Impedance-independent derived metrics (only when profile given).
    bmi_val: float | None = None
    bmr_val: int | None = None
    if height_cm is not None and age is not None and sex is not None:
        bmi_val = bc.bmi(weight_pkt.weight_kg, height_cm)
        bmr_val = bc.bmr(weight_pkt.weight_kg, height_cm, age, sex)

    # Impedance-dependent metrics — all-or-nothing so downstream code
    # can check a single field to decide whether body comp exists.
    if impedance_adc is None:
        return DecodedReading(
            weight_kg=weight_pkt.weight_kg,
            impedance_adc=None,
            bmi=bmi_val,
            bmr=bmr_val,
            body_fat_pct=None,
            fat_free_mass_kg=None,
            fat_mass_kg=None,
            muscle_mass_kg=None,
            muscle_pct=None,
            skeletal_muscle_mass_kg=None,
            skeletal_muscle_pct=None,
            water_mass_kg=None,
            water_pct=None,
            protein_mass_kg=None,
            protein_pct=None,
            bone_mass_kg=None,
            ffmi=None,
            fmi=None,
        )

    if height_cm is None or age is None or sex is None:
        raise ValueError(
            "Impedance packet present but user profile (height_cm, age, sex) is incomplete"
        )

    comp = bc.calculate_full(
        weight_kg=weight_pkt.weight_kg,
        height_cm=height_cm,
        age=age,
        sex=sex,
        impedance_adc=float(impedance_adc),
    )

    return DecodedReading(
        weight_kg=weight_pkt.weight_kg,
        impedance_adc=impedance_adc,
        bmi=comp.bmi,
        bmr=comp.bmr,
        body_fat_pct=comp.body_fat_pct,
        fat_free_mass_kg=comp.fat_free_mass_kg,
        fat_mass_kg=comp.fat_mass_kg,
        muscle_mass_kg=comp.muscle_mass_kg,
        muscle_pct=comp.muscle_pct,
        skeletal_muscle_mass_kg=comp.skeletal_muscle_mass_kg,
        skeletal_muscle_pct=comp.skeletal_muscle_pct,
        water_mass_kg=comp.water_mass_kg,
        water_pct=comp.water_pct,
        protein_mass_kg=comp.protein_mass_kg,
        protein_pct=comp.protein_pct,
        bone_mass_kg=comp.bone_mass_kg,
        ffmi=comp.ffmi,
        fmi=comp.fmi,
    )
