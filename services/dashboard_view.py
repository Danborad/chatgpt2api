from __future__ import annotations

from services.account_service import account_service
from services.config import config
from services.dashboard_metrics_service import (
    DASHBOARD_TIME_RANGES,
    dashboard_metrics_service,
)
from services.realtime_monitor_service import realtime_monitor_service
from services.runtime_environment_service import snapshot as runtime_environment_snapshot
from utils.timezone import beijing_now


DASHBOARD_VIEW_SCHEMA_VERSION = 5


def _image_storage_view() -> dict[str, object]:
    settings = config.get_image_storage_settings()
    return {
        "enabled": bool(settings.get("enabled")),
        "mode": str(settings.get("mode") or "local"),
        "status": "not_checked",
        "available": None,
        "image_count": None,
        "image_size_bytes": None,
    }


def build_dashboard_view(*, app_version: str) -> dict:
    account_stats = account_service.get_stats()
    account_healthy = bool(account_stats.get("active")) or bool(
        account_stats.get("unlimited_quota_count")
    )
    snapshot = dashboard_metrics_service.snapshot_many()
    metrics = snapshot["metrics"]
    ranges = snapshot["ranges"]
    application_database = config.get_storage_backend().get_backend_info()
    image_storage = _image_storage_view()
    overall_healthy = account_healthy and bool(metrics.get("ready"))
    runtime = runtime_environment_snapshot()
    operations = realtime_monitor_service.operations_snapshot()
    return {
        "status": "ok" if overall_healthy else "degraded",
        "healthy": overall_healthy,
        "version": app_version,
        "meta": {
            "schema_version": DASHBOARD_VIEW_SCHEMA_VERSION,
            "generated_at": beijing_now().isoformat(timespec="seconds"),
            "available_ranges": list(DASHBOARD_TIME_RANGES),
        },
        "metrics": metrics,
        "runtime": runtime,
        "operations": operations,
        "accounts": {
            **account_stats,
            "healthy": account_healthy,
        },
        "storage": {
            "application_database": application_database,
            "image_storage": image_storage,
        },
        "ranges": ranges,
    }
