"""Integrations — device/vendor-specific decoders owned by Baseline.

Each subpackage is self-contained: protocol decode, formulas, and any
public entry points live together so the ingestion layer can call a
single function without knowing the wire format.
"""
