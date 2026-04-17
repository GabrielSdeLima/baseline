"""seed hc900 body composition metric types

Revision ID: e4f5a6b7c8d9
Revises: d1e2f3a4b5c6
Create Date: 2026-04-16 22:00:00.000000

Adds the 16 new metric_types needed to persist the full HC900 V2 decoded
reading (weight + body_fat_pct already existed from the initial schema).

Primary (is_derived=false at measurement time):
  - impedance_adc             raw ADC from the BIA sensor

Derived, impedance-independent (is_derived=true):
  - bmi                       weight / height²
  - bmr                       Mifflin-St Jeor kcal/day

Derived, impedance-dependent (is_derived=true, all from FFM via Sun 2003):
  - fat_free_mass_kg
  - fat_mass_kg
  - skeletal_muscle_mass_kg   Janssen 2000
  - skeletal_muscle_pct
  - muscle_mass_kg            smm / 0.80
  - muscle_pct
  - water_mass_kg             Wang 1999 (73.2% of FFM)
  - water_pct
  - protein_mass_kg           Heymsfield 2005 (19.4% of FFM)
  - protein_pct
  - bone_mass_kg              Heymsfield 2005 (5.63% M / 5.92% F)
  - ffmi                      Kouri 1995 (FFM / h²)
  - fmi                       Kelly 2009 (fat_mass / h²)

`is_derived` lives on the `measurements` row, not on `metric_types`, so
it's set by the parser at persistence time, not declared here.

Also updates the `hc900_ble` data_sources description to reflect that
Baseline now owns the decode (hc900_ble_v2) and no longer shells out to
the Pulso Dart CLI.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e4f5a6b7c8d9"
down_revision: Union[str, None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (slug, name, default_unit, precision, description)
# category is 'body_composition' for all.
_NEW_METRIC_TYPES: list[tuple[str, str, str, int, str]] = [
    (
        "impedance_adc",
        "Bioimpedance (ADC)",
        "adc",
        0,
        "Raw bioelectrical impedance ADC counter from the HC900 scale. "
        "Proportional to impedance but not expressed in ohms; useful for "
        "longitudinal tracking on the same device and as a key for "
        "re-deriving body composition if formulas evolve.",
    ),
    (
        "bmi",
        "Body Mass Index",
        "kg/m²",
        1,
        "Body mass index: weight_kg / (height_m)². Computed from weight + "
        "user profile, no impedance required.",
    ),
    (
        "bmr",
        "Basal Metabolic Rate",
        "kcal",
        0,
        "Resting energy expenditure (Mifflin-St Jeor 1990). "
        "Computed from weight, height, age, and sex.",
    ),
    (
        "fat_free_mass_kg",
        "Fat-Free Mass",
        "kg",
        1,
        "Fat-free mass from bioimpedance (Sun et al. 2003 regression). "
        "Validated against 4-compartment model on 1095 subjects.",
    ),
    (
        "fat_mass_kg",
        "Fat Mass",
        "kg",
        1,
        "Absolute fat mass derived as weight_kg − fat_free_mass_kg.",
    ),
    (
        "skeletal_muscle_mass_kg",
        "Skeletal Muscle Mass",
        "kg",
        1,
        "Skeletal muscle mass (Janssen et al. 2000 regression). "
        "Distinct from total muscle, which also includes smooth and cardiac.",
    ),
    (
        "skeletal_muscle_pct",
        "Skeletal Muscle %",
        "%",
        1,
        "Skeletal muscle mass as a percentage of body weight.",
    ),
    (
        "muscle_mass_kg",
        "Total Muscle Mass",
        "kg",
        1,
        "Total muscle mass (skeletal + smooth + cardiac). "
        "Approximated as skeletal_muscle_mass / 0.80.",
    ),
    (
        "muscle_pct",
        "Total Muscle %",
        "%",
        1,
        "Total muscle mass as a percentage of body weight.",
    ),
    (
        "water_mass_kg",
        "Total Body Water",
        "kg",
        1,
        "Total body water (Wang et al. 1999: ~73.2% of fat-free mass).",
    ),
    (
        "water_pct",
        "Body Water %",
        "%",
        1,
        "Total body water as a percentage of body weight.",
    ),
    (
        "protein_mass_kg",
        "Protein Mass",
        "kg",
        2,
        "Protein mass (Heymsfield et al. 2005: ~19.4% of fat-free mass).",
    ),
    (
        "protein_pct",
        "Protein %",
        "%",
        1,
        "Protein mass as a percentage of body weight.",
    ),
    (
        "bone_mass_kg",
        "Bone Mineral Mass",
        "kg",
        2,
        "Bone mineral mass (Heymsfield et al. 2005: 5.63% male / 5.92% "
        "female of fat-free mass).",
    ),
    (
        "ffmi",
        "Fat-Free Mass Index",
        "kg/m²",
        1,
        "Fat-free mass normalised by height² (Kouri et al. 1995).",
    ),
    (
        "fmi",
        "Fat Mass Index",
        "kg/m²",
        1,
        "Fat mass normalised by height² (Kelly et al. 2009).",
    ),
]

_INSERT_SQL = sa.text(
    """
    INSERT INTO metric_types
        (slug, name, category, default_unit, value_precision, description, created_at)
    VALUES
        (:slug, :name, 'body_composition', :unit, :precision, :description, NOW())
    ON CONFLICT (slug) DO NOTHING
    """
)


def upgrade() -> None:
    bind = op.get_bind()
    for slug, name, unit, precision, description in _NEW_METRIC_TYPES:
        bind.execute(
            _INSERT_SQL,
            {
                "slug": slug,
                "name": name,
                "unit": unit,
                "precision": precision,
                "description": description,
            },
        )

    # Refresh the data_sources description now that Baseline owns the decode.
    op.execute(
        """
        UPDATE data_sources
        SET description = 'HC900/FG260RB BLE smart scale — passive advertisement '
                          'scan via bleak. Decoded natively by Baseline '
                          '(app.integrations.hc900, format hc900_ble_v2).'
        WHERE slug = 'hc900_ble'
        """
    )


def downgrade() -> None:
    slugs = ", ".join(f"'{m[0]}'" for m in _NEW_METRIC_TYPES)
    op.execute(f"DELETE FROM metric_types WHERE slug IN ({slugs})")
    op.execute(
        """
        UPDATE data_sources
        SET description = 'HC900/FG260RB BLE smart scale — passive advertisement '
                          'scan via bleak. Decoded by Pulso decode_scale.dart '
                          '(hc900_ble_v1).'
        WHERE slug = 'hc900_ble'
        """
    )
