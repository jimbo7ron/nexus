"""Shared utility functions for Nexus."""

from __future__ import annotations
import hashlib


def content_hash(text: str) -> str:
    """Generate a consistent hash for content deduplication."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

