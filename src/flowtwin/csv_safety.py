from __future__ import annotations

from typing import Any


_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")


def safe_csv_value(value: Any) -> Any:
    """Prefix untrusted text that spreadsheet programs may interpret as a formula."""
    if not isinstance(value, str):
        return value
    probe = value.lstrip(" \t\r\n")
    if probe.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value
