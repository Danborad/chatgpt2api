from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


DashboardTimeRange = Literal["24h", "7d", "30d"]


class DashboardMetaView(BaseModel):
    schema_version: int
    generated_at: str
    available_ranges: list[DashboardTimeRange]


class DashboardMetricsView(BaseModel):
    status: Literal["ready", "degraded"]
    ready: bool
    stale: bool
    source: str
    source_revision: str | None
    last_ingested_at: str | None
    freshness_ms: int | None
    checkpoint_at: str | None
    failure_reason: str | None
    retention_days: int


class DashboardRuntimeView(BaseModel):
    runtime_mode: Literal["docker", "native"]
    instance_name: str
    distribution: str
    kernel_version: str
    architecture: str
    python_version: str
    cpu_capacity: float = Field(gt=0)
    service_started_at: str
    service_uptime_seconds: int = Field(ge=0)
    process_cpu_percent: float | None = Field(default=None, ge=0, le=100)
    process_memory_bytes: int | None = Field(default=None, ge=0)
    process_memory_percent: float | None = Field(default=None, ge=0, le=100)
    memory_scope: Literal["container", "system", "visible"]
    memory_percent: float | None = Field(default=None, ge=0, le=100)
    storage_percent: float | None = Field(default=None, ge=0, le=100)
    network_rx_bytes_per_sec: float | None = Field(default=None, ge=0)
    network_tx_bytes_per_sec: float | None = Field(default=None, ge=0)


class DashboardOperationsView(BaseModel):
    active_requests: int = Field(ge=0)


class DashboardAccountView(BaseModel):
    model_config = ConfigDict(extra="ignore")

    total: int = 0
    cumulative_total: int = 0
    active: int = 0
    limited: int = 0
    abnormal: int = 0
    disabled: int = 0
    total_quota: int = 0
    unlimited_quota_count: int = 0
    unknown_quota_count: int = 0
    total_success: int = 0
    total_fail: int = 0
    by_type: dict[str, int] = Field(default_factory=dict)
    healthy: bool = False


class DashboardTotalsView(BaseModel):
    total: int
    success: int
    final_failed: int
    success_rate: float | None
    avg_success_duration_ms: float | None


class DashboardBucketView(BaseModel):
    label: str
    start_at: str
    end_at: str
    total_calls: int
    success_calls: int
    final_failed_calls: int
    success_rate: float | None
    avg_success_duration_ms: float | None
    switch_count: int
    switch_recovered: int
    switch_recovery_rate: float | None


class DashboardSwitchingView(BaseModel):
    requests: int
    count: int
    recovered: int
    recovery_rate: float | None


class DashboardTrendView(BaseModel):
    labels: list[str]
    success_requests: list[int]
    final_failed_requests: list[int]
    success_rate: list[float | None]
    switch_count: list[int]
    model_success_requests: dict[str, list[int]]
    model_avg_success_duration_ms: dict[str, list[float | None]]


class DashboardWindowView(BaseModel):
    requested: DashboardTimeRange
    start_at: str
    end_at: str
    bucket_unit: Literal["hour", "day"]
    bucket_count: int


class DashboardRangeView(BaseModel):
    time_range: DashboardTimeRange
    window: DashboardWindowView
    totals: DashboardTotalsView
    switching: DashboardSwitchingView
    buckets: list[DashboardBucketView]
    trend: DashboardTrendView


class DashboardImageStorageView(BaseModel):
    enabled: bool
    mode: Literal["local", "webdav", "both"]
    status: Literal["not_checked"]
    available: bool | None
    image_count: int | None
    image_size_bytes: int | None


class DashboardStorageView(BaseModel):
    application_database: dict
    image_storage: DashboardImageStorageView


class DashboardResponseView(BaseModel):
    status: Literal["ok", "degraded"]
    healthy: bool
    version: str
    meta: DashboardMetaView
    metrics: DashboardMetricsView
    runtime: DashboardRuntimeView
    operations: DashboardOperationsView
    accounts: DashboardAccountView
    storage: DashboardStorageView
    ranges: dict[DashboardTimeRange, DashboardRangeView]
