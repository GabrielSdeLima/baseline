"""Unit tests for app.integrations.hc900.decode_hc900.

Covers the public decode contract — not the DB.  The live HC900 hex
fixture (same bytes used in tests/test_scale_integration.py) is treated
as a black-box input; we verify the *shape* of the decoded reading, not
numeric correctness (that belongs in test_hc900_body_composition.py).

Ensures the decoder preserves the "no inventing data" invariant:
  - weight-only → body-comp stays None (never fabricated)
  - impedance without profile → ValueError (no silent garbage)
  - bmi/bmr only populated when the profile is complete
"""

import pytest

from app.integrations.hc900 import decode_hc900
from app.integrations.hc900.decoder import DECODER_VERSION, DecodedReading
from app.integrations.hc900.protocol import hex_to_bytes

# Real btsnoop capture — same values as the scale integration fixture
_WEIGHT_HEX = "aca017cf925c91a0202d88e00da2"
_IMPEDANCE_HEX = "aca017cf925c91a0a2afa0a206b9"


# ── All impedance-dependent slugs — used to assert None-when-absent ────────────

_BODY_COMP_FIELDS = (
    "body_fat_pct",
    "fat_free_mass_kg",
    "fat_mass_kg",
    "skeletal_muscle_mass_kg",
    "skeletal_muscle_pct",
    "muscle_mass_kg",
    "muscle_pct",
    "water_mass_kg",
    "water_pct",
    "protein_mass_kg",
    "protein_pct",
    "bone_mass_kg",
    "ffmi",
    "fmi",
)


# ── Weight-only paths ─────────────────────────────────────────────────────────


class TestWeightOnly:
    def test_weight_only_no_profile_leaves_bmi_bmr_none(self):
        """No profile → only weight_kg populated; bmi/bmr/body-comp are None."""
        r = decode_hc900(hex_to_bytes(_WEIGHT_HEX))
        assert r.weight_kg == 75.84
        assert r.impedance_adc is None
        assert r.bmi is None
        assert r.bmr is None
        for f in _BODY_COMP_FIELDS:
            assert getattr(r, f) is None, f"{f} must be None without impedance"

    def test_weight_only_with_profile_populates_bmi_bmr_only(self):
        """Profile present → bmi/bmr filled, body-comp still None (no impedance)."""
        r = decode_hc900(
            hex_to_bytes(_WEIGHT_HEX),
            height_cm=180, age=34, sex=1,
        )
        assert r.weight_kg == 75.84
        assert r.impedance_adc is None
        assert r.bmi is not None
        assert r.bmr is not None
        # Invariant: body-comp must stay None with no impedance, even with profile.
        for f in _BODY_COMP_FIELDS:
            assert getattr(r, f) is None, f"{f} must be None without impedance"

    def test_has_impedance_false_when_impedance_absent(self):
        r = decode_hc900(hex_to_bytes(_WEIGHT_HEX), height_cm=180, age=34, sex=1)
        assert r.has_impedance is False


# ── Full readings ─────────────────────────────────────────────────────────────


class TestFullReading:
    def test_full_reading_populates_all_18_fields(self):
        """Weight + impedance + profile → every metric field is populated."""
        r = decode_hc900(
            hex_to_bytes(_WEIGHT_HEX),
            hex_to_bytes(_IMPEDANCE_HEX),
            height_cm=180, age=34, sex=1,
        )
        assert r.weight_kg == 75.84
        assert r.impedance_adc == 527
        assert r.bmi is not None
        assert r.bmr is not None
        for f in _BODY_COMP_FIELDS:
            assert getattr(r, f) is not None, f"{f} must be populated on full reading"

    def test_has_impedance_true_on_full_reading(self):
        r = decode_hc900(
            hex_to_bytes(_WEIGHT_HEX),
            hex_to_bytes(_IMPEDANCE_HEX),
            height_cm=180, age=34, sex=1,
        )
        assert r.has_impedance is True

    def test_decoder_version_stamped(self):
        r = decode_hc900(
            hex_to_bytes(_WEIGHT_HEX),
            hex_to_bytes(_IMPEDANCE_HEX),
            height_cm=180, age=34, sex=1,
        )
        assert r.decoder_version == DECODER_VERSION
        assert r.decoder_version == "hc900_ble_v2"


# ── Contract enforcement ──────────────────────────────────────────────────────


class TestContractEnforcement:
    def test_impedance_present_without_profile_raises(self):
        """Impedance bytes but no profile → ValueError, never silent body-comp garbage."""
        with pytest.raises(ValueError, match="profile"):
            decode_hc900(
                hex_to_bytes(_WEIGHT_HEX),
                hex_to_bytes(_IMPEDANCE_HEX),
                # height_cm/age/sex intentionally omitted
            )

    def test_impedance_with_partial_profile_raises(self):
        """Incomplete profile (missing sex) with impedance → ValueError."""
        with pytest.raises(ValueError, match="profile"):
            decode_hc900(
                hex_to_bytes(_WEIGHT_HEX),
                hex_to_bytes(_IMPEDANCE_HEX),
                height_cm=180, age=34,  # sex omitted
            )

    def test_invalid_weight_packet_raises(self):
        """Garbage bytes → ValueError rather than a nonsense DecodedReading."""
        with pytest.raises(ValueError, match="weight packet"):
            decode_hc900(bytes([0] * 14))

    def test_wrong_length_weight_packet_raises(self):
        with pytest.raises(ValueError, match="weight packet"):
            decode_hc900(bytes([0xAC, 0xA0]))  # too short

    def test_impedance_zero_falls_back_to_weight_only(self):
        """ADC=0 means 'feet not yet in contact'; treat the packet as absent.

        The protocol decoder returns ImpedancePacket(adc=None) for zero, and
        decode_hc900 must honour that by producing a weight-only reading (not
        fabricating body comp from a zero impedance).
        """
        # Craft a valid impedance packet with ADC=0 (both bytes XOR'd equal 0xA0)
        zero_imp = bytes([
            0xAC, 0xA0,  # company id
            0x17, 0xCF, 0x92, 0x5C, 0x91, 0xA0,  # mac + filler
            0xA2,        # flags
            0xA0,        # low byte XOR → 0
            0xAF,        # filler
            0xA0,        # high byte XOR → 0
            0x06,        # packet type = impedance
            0x00,        # checksum (unused)
        ])
        r = decode_hc900(
            hex_to_bytes(_WEIGHT_HEX),
            zero_imp,
            height_cm=180, age=34, sex=1,
        )
        assert r.impedance_adc is None
        assert r.has_impedance is False
        for f in _BODY_COMP_FIELDS:
            assert getattr(r, f) is None


# ── Serialisation ─────────────────────────────────────────────────────────────


class TestToDict:
    def test_to_dict_full_shape(self):
        """to_dict() contains every field from the dataclass + decoder_version."""
        r = decode_hc900(
            hex_to_bytes(_WEIGHT_HEX),
            hex_to_bytes(_IMPEDANCE_HEX),
            height_cm=180, age=34, sex=1,
        )
        d = r.to_dict()
        expected_keys = {
            "weight_kg", "impedance_adc",
            "bmi", "bmr",
            *_BODY_COMP_FIELDS,
            "decoder_version",
        }
        assert set(d.keys()) == expected_keys
        assert d["decoder_version"] == "hc900_ble_v2"

    def test_to_dict_weight_only_keeps_none_fields(self):
        """Serialisation preserves None entries — round-trip shape is stable."""
        r = decode_hc900(hex_to_bytes(_WEIGHT_HEX))
        d = r.to_dict()
        assert d["weight_kg"] == 75.84
        assert d["impedance_adc"] is None
        assert d["bmi"] is None
        for f in _BODY_COMP_FIELDS:
            assert d[f] is None


# ── Return type ───────────────────────────────────────────────────────────────


def test_decode_returns_decodedreading_instance():
    """Frozen-dataclass contract is preserved (callers pattern-match on it)."""
    r = decode_hc900(hex_to_bytes(_WEIGHT_HEX))
    assert isinstance(r, DecodedReading)
    # Frozen: assignment must fail
    with pytest.raises(AttributeError):
        r.weight_kg = 100.0  # type: ignore[misc]
