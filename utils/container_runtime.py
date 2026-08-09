from __future__ import annotations

from pathlib import Path


_CONTAINER_MARKERS = (Path("/.dockerenv"), Path("/run/.containerenv"))


def is_containerized() -> bool:
    """Return whether the current process is running in a supported container runtime."""
    return any(marker.is_file() for marker in _CONTAINER_MARKERS)
