from __future__ import annotations

from typing import Mapping


GENBOX_PUSH_STATUS_LABELS = {
    "imported": "已推送到 GenBox",
    "already-imported": "GenBox 已存在",
    "duplicate-local": "GenBox 本地重复",
}
GENBOX_PUSH_TERMINAL_STATUSES = frozenset(GENBOX_PUSH_STATUS_LABELS)


def genbox_push_status_label(status: object) -> str:
    return GENBOX_PUSH_STATUS_LABELS.get(str(status or "").strip(), "")


def genbox_push_state(value: object) -> dict[str, str] | None:
    if not isinstance(value, Mapping):
        return None
    status = str(value.get("status") or "").strip()
    sha256 = str(value.get("sha256") or "").strip().lower()
    updated_at = str(value.get("updated_at") or "").strip()
    label = genbox_push_status_label(status)
    if not label:
        return None
    if len(sha256) != 64 or any(char not in "0123456789abcdef" for char in sha256):
        return None
    if not updated_at:
        return None
    return {
        "status": status,
        "label": label,
        "sha256": sha256,
        "updated_at": updated_at,
    }
