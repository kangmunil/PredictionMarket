from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Tuple

def _ensure_datetime(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None
    return None

def seconds_to_expiry(expires_at) -> Optional[float]:
    dt = _ensure_datetime(expires_at)
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    return (dt - now).total_seconds()

def aggression_profile(seconds_to_expiry_value: Optional[float]) -> Tuple[float, str]:
    if seconds_to_expiry_value is None:
        return 1.0, "UNKNOWN"
    if seconds_to_expiry_value <= 0:
        return 3.5, "FINAL"
    if seconds_to_expiry_value > 300:
        return 1.0, "EARLY"
    if seconds_to_expiry_value > 120:
        return 1.5, "WARMUP"
    if seconds_to_expiry_value > 30:
        return 2.2, "PRE_CLOSE"
    return 3.5, "FINAL"
