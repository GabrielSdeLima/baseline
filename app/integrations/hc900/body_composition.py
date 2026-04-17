"""Body composition formulas for HC900 readings.

Pure-function port of
``pulso-app/lib/features/health/ble/body_composition.dart``.  Every
coefficient is preserved byte-for-byte so a Baseline result is
numerically identical to the reference Pulso Dart implementation
(subject to IEEE-754 rounding that matches between Dart and Python).

Sources:
    FFM   — Sun et al., Am J Clin Nutr 77(2):331-340 (2003)
    SMM   — Janssen et al., J Appl Physiol 89(1):81-88 (2000)
    TBW   — Wang et al. (1999), total body water ≈ 73.2% of FFM
    Prot. — Heymsfield et al. (2005), protein ≈ 19.4% of FFM
    Bone  — Heymsfield et al. (2005), 5.63% (M) / 5.92% (F) of FFM
    BMR   — Mifflin-St Jeor, Am J Clin Nutr 51(2):241-247 (1990)
    FFMI  — Kouri et al. (1995); FMI — Kelly et al. (2009)

Every clamp triggers a WARN log so we can audit how often we're
saturating at the safety bounds.  The clamp thresholds themselves are
carried over from the reference code.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BodyComposition:
    # Impedance-independent (computable from weight + profile alone)
    bmi: float
    bmr: int

    # Impedance-dependent
    fat_free_mass_kg: float
    fat_mass_kg: float
    body_fat_pct: float
    skeletal_muscle_mass_kg: float
    skeletal_muscle_pct: float
    muscle_mass_kg: float
    muscle_pct: float
    water_mass_kg: float
    water_pct: float
    protein_mass_kg: float
    protein_pct: float
    bone_mass_kg: float
    ffmi: float
    fmi: float


def _clamp(value: float, lo: float, hi: float, name: str, context: str) -> float:
    """Clamp value to [lo, hi] and log a WARN when the bound is hit."""
    if value < lo:
        logger.warning(
            "[hc900] clamp low: %s=%.3f → %.1f (%s)", name, value, lo, context
        )
        return lo
    if value > hi:
        logger.warning(
            "[hc900] clamp high: %s=%.3f → %.1f (%s)", name, value, hi, context
        )
        return hi
    return value


def _round1(value: float) -> float:
    """Round to 1 decimal matching Dart's (v*10).roundToDouble()/10."""
    return round(value * 10) / 10


def bmi(weight_kg: float, height_cm: int) -> float:
    h_m = height_cm / 100.0
    return _round1(weight_kg / (h_m * h_m))


def bmr(weight_kg: float, height_cm: int, age: int, sex: int) -> int:
    """Mifflin-St Jeor resting metabolic rate in kcal/day (rounded int).

    ``sex``: 1 = male, 2 = female.  Returns an ``int`` to match the Dart
    reference, which uses ``.round()`` on the last step.
    """
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age
    return round(base + 5) if sex == 1 else round(base - 161)


def calculate_full(
    weight_kg: float,
    height_cm: int,
    age: int,
    sex: int,
    impedance_adc: float,
) -> BodyComposition:
    """Full body composition including impedance-dependent metrics.

    Raises ``ValueError`` if ``impedance_adc`` is not positive — the
    caller is expected to have filtered invalid impedances already.
    """
    if impedance_adc <= 0:
        raise ValueError(f"impedance_adc must be positive, got {impedance_adc}")

    is_male = sex == 1
    height_m = height_cm / 100.0
    height_sq = height_m * height_m
    ctx = f"w={weight_kg:.1f}kg h={height_cm}cm age={age} sex={sex} z={impedance_adc:.0f}"

    # BMI — same as the impedance-independent helper; inline to avoid a
    # double log line on _clamp (BMI isn't clamped here anyway).
    bmi_val = weight_kg / height_sq

    # Fat-free mass (Sun 2003). h²/z is the impedance index.
    h2z = (height_cm * height_cm) / impedance_adc
    if is_male:
        ffm = -10.68 + 0.65 * h2z + 0.26 * weight_kg + 0.02 * impedance_adc
    else:
        ffm = -9.53 + 0.69 * h2z + 0.17 * weight_kg + 0.02 * impedance_adc
    ffm_clamped = _clamp(ffm, 0.0, weight_kg, "ffm", ctx)

    # Fat mass derived from FFM; body-fat % clamped to a physiological ceiling.
    fat_mass = weight_kg - ffm_clamped
    fat_pct = _clamp((fat_mass / weight_kg * 100), 0.0, 70.0, "body_fat_pct", ctx)

    # Skeletal muscle mass (Janssen 2000). Clamped to ffm as a physical upper bound.
    smm = (h2z * 0.401) + (3.825 if is_male else 0.0) + (age * -0.071) + 5.102
    smm_clamped = _clamp(smm, 0.0, ffm_clamped, "smm", ctx)
    sm_pct = _clamp(
        (smm_clamped / weight_kg * 100), 0.0, 70.0, "skeletal_muscle_pct", ctx
    )

    # Total muscle (skeletal + smooth + cardiac). Skeletal is ~80% of total.
    total_muscle = smm_clamped / 0.80
    muscle_pct_val = _clamp(
        (total_muscle / weight_kg * 100), 0.0, 85.0, "muscle_pct", ctx
    )

    # Body water (Wang 1999): 73.2% of FFM.
    water_mass = ffm_clamped * 0.732
    water_pct_val = _clamp(
        (water_mass / weight_kg * 100), 0.0, 80.0, "water_pct", ctx
    )

    # Protein (Heymsfield 2005): 19.4% of FFM.
    protein_mass = ffm_clamped * 0.194
    protein_pct_val = _clamp(
        (protein_mass / weight_kg * 100), 0.0, 30.0, "protein_pct", ctx
    )

    # Bone mineral (Heymsfield 2005): sex-dependent fraction of FFM.
    bone_fraction = 0.0563 if is_male else 0.0592
    bone_mass = ffm_clamped * bone_fraction

    # BMR (Mifflin-St Jeor) — integer kcal.
    bmr_val = bmr(weight_kg, height_cm, age, sex)

    # Height-normalised indices.
    ffmi_val = ffm_clamped / height_sq
    fmi_val = fat_mass / height_sq

    return BodyComposition(
        bmi=_round1(bmi_val),
        bmr=bmr_val,
        fat_free_mass_kg=_round1(ffm_clamped),
        fat_mass_kg=_round1(fat_mass),
        body_fat_pct=_round1(fat_pct),
        skeletal_muscle_mass_kg=_round1(smm_clamped),
        skeletal_muscle_pct=_round1(sm_pct),
        muscle_mass_kg=_round1(total_muscle),
        muscle_pct=_round1(muscle_pct_val),
        water_mass_kg=_round1(water_mass),
        water_pct=_round1(water_pct_val),
        protein_mass_kg=_round1(protein_mass),
        protein_pct=_round1(protein_pct_val),
        bone_mass_kg=_round1(bone_mass),
        ffmi=_round1(ffmi_val),
        fmi=_round1(fmi_val),
    )
