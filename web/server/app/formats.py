"""Shared representations: RFC 3339 UTC instants, money in minor units, opaque cursors."""

import base64
import binascii
import json
from datetime import UTC, datetime
from typing import Any

from .problems import Problem


def iso(moment: datetime) -> str:
    """Instant as RFC 3339 in UTC with milliseconds: 2035-06-01T16:00:00.000Z."""
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def money(amount_minor: int, currency: str) -> dict[str, Any]:
    return {"amount_minor": amount_minor, "currency": currency}


def encode_cursor(created_at: datetime, row_id: str) -> str:
    """Position after the last row of a page: the sort key (time, id). Opaque for clients."""
    raw = json.dumps({"t": created_at.astimezone(UTC).isoformat(), "i": row_id}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        data = json.loads(raw)
        moment = datetime.fromisoformat(data["t"])
        row_id = data["i"]
        if moment.tzinfo is None or not isinstance(row_id, str) or not row_id:
            raise ValueError("bad cursor")
        return moment, row_id
    except (binascii.Error, ValueError, KeyError, TypeError, UnicodeDecodeError) as exc:
        raise Problem(400, "invalid-cursor", "Cursor is not valid", "Use next_cursor of a previous page as is") from exc
