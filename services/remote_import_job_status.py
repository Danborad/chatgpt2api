"""Canonical status semantics for remote account-import jobs."""

from __future__ import annotations


REMOTE_IMPORT_ACTIVE_STATUSES = frozenset({"pending", "running"})


def import_job_is_active(raw: object) -> bool:
    if not isinstance(raw, dict):
        return False
    status = str(raw.get("status") or "").strip().lower()
    return status in REMOTE_IMPORT_ACTIVE_STATUSES
