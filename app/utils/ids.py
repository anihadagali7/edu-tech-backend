"""ULID/UUID helpers.

Maps to Section 2.5 of the design: ID strategy and uniqueness guarantees.
"""

from __future__ import annotations

from uuid import uuid4, UUID


def new_ulid() -> str:
    """Generate a monotonic ULID as string for request IDs and external refs."""
    return uuid4().hex


def to_bytes(ulid_str: str) -> bytes:
    """Convert a ULID string to 16-byte representation."""
    return UUID(hex=ulid_str).bytes
