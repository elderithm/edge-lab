"""Venue-agnostic Edge Lab core.

This package must not import from any specific venue (Polymarket or DreamDEX).
It defines shared types and the probability -> edge -> risk -> signal pipeline
that both venues feed. All monetary/price/probability values are ``Decimal``.
"""
