"""
Data access layer for web frontend.

Ground truth from disk (ADR 001: Think Data First).
All data functions read filesystem state, return dicts.
No caching, no state management - files are reality.
"""
