from __future__ import annotations

import re
import threading
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, Iterable

from services.call_view import call_outcome, call_switch_count
from services.storage.dashboard_metrics_repository import (
    DashboardMetricsRepository,
    DashboardMetricsSchemaReset,
    DashboardMetricsSourceChanged,
    DashboardMetricsState,
    DashboardMetricsWriteConflict,
)
from utils.log import logger
from utils.timezone import beijing_now, parse_to_beijing_naive


DASHBOARD_METRICS_RETENTION_DAYS = 30
DASHBOARD_TIME_RANGES = ("24h", "7d", "30d")
DASHBOARD_METRICS_REFRESH_INTERVAL_SECS = 10.0

_NON_MODEL_KEYS = {
    "",
    "-",
    "auto",
    "default",
    "unknown",
    "null",
    "none",
    "low",
    "medium",
    "high",
    "standard",
    "hd",
    "portrait",
    "landscape",
    "square",
    "vertical",
    "horizontal",
    "image",
    "images",
    "text",
    "chat",
    "generation",
    "generations",
    "edit",
    "edits",
}


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _detail_value(item: dict[str, Any], key: str, default: object = "") -> object:
    detail = item.get("detail")
    if isinstance(detail, dict):
        value = detail.get(key)
        if value not in (None, ""):
            return value
    value = item.get(key)
    return default if value in (None, "") else value


def _parse_log_time(value: object) -> datetime | None:
    return parse_to_beijing_naive(value)


def _beijing_now_naive() -> datetime:
    return beijing_now().replace(tzinfo=None)


def _call_started_at(item: dict[str, Any]) -> object:
    return _detail_value(item, "started_at", item.get("time"))


def _call_event_at(item: dict[str, Any]) -> object:
    return item.get("time")


def _looks_like_model_label(value: object) -> bool:
    label = _clean_text(value)
    key = label.lower().replace("\u00d7", "x")
    if key in _NON_MODEL_KEYS or key.startswith("/"):
        return False
    if re.fullmatch(r"\d+\s*x\s*\d+", key) or re.fullmatch(r"\d+\s*:\s*\d+", key):
        return False
    return bool(label)


def _increment(counter: dict[str, int], key: object, default: str = "unknown") -> None:
    label = _clean_text(key) or default
    counter[label] = int(counter.get(label, 0) or 0) + 1


def _dashboard_outcome(item: dict[str, Any]) -> str:
    outcome = call_outcome(item)
    if outcome in {"success", "partial_success"}:
        return "success"
    if outcome == "text_review":
        return "excluded"
    return "final_failed"


def _image_switch_count(item: dict[str, Any]) -> int:
    return call_switch_count(item)


def _empty_bucket() -> dict[str, Any]:
    return {
        "total": 0,
        "success": 0,
        "final_failed": 0,
        "switch_requests": 0,
        "switch_count": 0,
        "switch_recovered": 0,
        "success_duration_total_ms": 0.0,
        "success_duration_count": 0,
        "model_success": {},
        "model_success_total_times": {},
        "model_success_time_counts": {},
    }


def _merge_bucket(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key in (
        "total",
        "success",
        "final_failed",
        "switch_requests",
        "switch_count",
        "switch_recovered",
    ):
        target[key] = int(target.get(key, 0) or 0) + int(source.get(key, 0) or 0)
    target["success_duration_total_ms"] = (
        float(target.get("success_duration_total_ms", 0.0) or 0.0)
        + float(source.get("success_duration_total_ms", 0.0) or 0.0)
    )
    target["success_duration_count"] = (
        int(target.get("success_duration_count", 0) or 0)
        + int(source.get("success_duration_count", 0) or 0)
    )
    for key in ("model_success", "model_success_total_times", "model_success_time_counts"):
        target_map = target.setdefault(key, {})
        source_map = source.get(key) if isinstance(source.get(key), dict) else {}
        for name, value in source_map.items():
            try:
                numeric = float(value) if key == "model_success_total_times" else int(value)
            except (TypeError, ValueError):
                numeric = 0.0 if key == "model_success_total_times" else 0
            target_map[str(name)] = target_map.get(str(name), 0) + numeric


def _percentage(numerator: int, denominator: int) -> float | None:
    return round(numerator * 100 / denominator, 2) if denominator > 0 else None


def _bucket_metrics(bucket: dict[str, Any]) -> dict[str, Any]:
    success = int(bucket.get("success", 0) or 0)
    final_failed = int(bucket.get("final_failed", 0) or 0)
    measured = success + final_failed
    duration_total = float(bucket.get("success_duration_total_ms", 0.0) or 0.0)
    duration_count = int(bucket.get("success_duration_count", 0) or 0)
    switch_requests = int(bucket.get("switch_requests", 0) or 0)
    switch_recovered = int(bucket.get("switch_recovered", 0) or 0)
    return {
        "total_calls": int(bucket.get("total", 0) or 0),
        "success_calls": success,
        "final_failed_calls": final_failed,
        "success_rate": _percentage(success, measured),
        "avg_success_duration_ms": (
            round(duration_total / duration_count, 2)
            if duration_count > 0
            else None
        ),
        "switch_requests": switch_requests,
        "switch_count": int(bucket.get("switch_count", 0) or 0),
        "switch_recovered": switch_recovered,
        "switch_recovery_rate": _percentage(switch_recovered, switch_requests),
    }


def _retention_start(now: datetime | None = None) -> datetime:
    current = now or _beijing_now_naive()
    return (current - timedelta(days=DASHBOARD_METRICS_RETENTION_DAYS - 1)).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )


def _retention_cutoff(now: datetime | None = None) -> str:
    return _retention_start(now).strftime("%Y-%m-%dT%H")


class DashboardMetricsService:
    """Own the incremental hourly projection derived from canonical Call Records."""

    def __init__(
        self,
        repository: DashboardMetricsRepository | None = None,
        *,
        database_url: str | None = None,
    ) -> None:
        if repository is not None and database_url is not None:
            raise ValueError("provide repository or database_url, not both")
        self.repository = repository or DashboardMetricsRepository(database_url)
        self._lock = threading.RLock()
        self._ingest_failed = False
        self._stale_reason: str | None = None

    def reset_projection_schema_if_needed(self) -> DashboardMetricsSchemaReset:
        """Reset stale physical projection tables without touching Call Records."""
        with self._lock:
            reset = self.repository.reset_schema_if_needed()
            if reset.projection_recreated:
                self._ingest_failed = True
                self._stale_reason = "projection_schema_reset"
            return reset

    @staticmethod
    def _normalize_log_cursor(value: object) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        generation = _clean_text(value.get("generation"))
        try:
            sequence = int(value.get("sequence"))
        except (TypeError, ValueError):
            return None
        if not generation or sequence < 0:
            return None
        return {"generation": generation, "sequence": sequence}

    @staticmethod
    def _apply_call(bucket: dict[str, Any], item: dict[str, Any]) -> None:
        model = _clean_text(_detail_value(item, "model"))
        outcome = _dashboard_outcome(item)
        duration_ms: float | None = None
        duration_raw = _detail_value(item, "duration_ms", None)
        if outcome == "success" and duration_raw not in (None, ""):
            try:
                duration_ms = max(0.0, float(duration_raw))
            except (TypeError, ValueError):
                duration_ms = None

        bucket["total"] = int(bucket.get("total", 0) or 0) + 1
        if outcome != "excluded":
            bucket[outcome] = int(bucket.get(outcome, 0) or 0) + 1

        switch_count = _image_switch_count(item)
        if switch_count > 0:
            bucket["switch_requests"] = int(bucket.get("switch_requests", 0) or 0) + 1
            bucket["switch_count"] = int(bucket.get("switch_count", 0) or 0) + switch_count
            if outcome == "success":
                bucket["switch_recovered"] = int(bucket.get("switch_recovered", 0) or 0) + 1

        if duration_ms is not None:
            bucket["success_duration_total_ms"] = (
                float(bucket.get("success_duration_total_ms", 0.0) or 0.0)
                + duration_ms
            )
            bucket["success_duration_count"] = (
                int(bucket.get("success_duration_count", 0) or 0) + 1
            )

        if outcome == "success" and _looks_like_model_label(model):
            _increment(bucket.setdefault("model_success", {}), model)
            if duration_ms is not None:
                totals = bucket.setdefault("model_success_total_times", {})
                counts = bucket.setdefault("model_success_time_counts", {})
                totals[model] = float(totals.get(model, 0.0) or 0.0) + duration_ms
                counts[model] = int(counts.get(model, 0) or 0) + 1

    @classmethod
    def _aggregate_items(
        cls,
        items: Iterable[dict[str, Any]],
        *,
        now: datetime,
    ) -> tuple[dict[str, dict[str, Any]], int, str | None, str | None]:
        buckets: dict[str, dict[str, Any]] = {}
        cutoff = _retention_start(now)
        last_event_id: str | None = None
        last_event_at: str | None = None
        record_count = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            call_id = _clean_text(item.get("id"))
            if call_id:
                last_event_id = call_id
            event_dt = _parse_log_time(_call_event_at(item))
            if event_dt is not None:
                last_event_at = event_dt.isoformat(timespec="seconds")
            bucket_dt = _parse_log_time(_call_started_at(item))
            if bucket_dt is None or bucket_dt < cutoff or bucket_dt > now:
                continue
            bucket_start = bucket_dt.strftime("%Y-%m-%dT%H")
            cls._apply_call(buckets.setdefault(bucket_start, _empty_bucket()), item)
            record_count += 1
        return buckets, record_count, last_event_id, last_event_at

    @staticmethod
    def _next_state(
        current: DashboardMetricsState | None,
        *,
        end_cursor: dict[str, Any],
        last_event_id: str | None,
        last_event_at: str | None,
        checkpoint_at: str,
        full_rebuild: bool,
    ) -> DashboardMetricsState:
        previous = current or DashboardMetricsState()
        return DashboardMetricsState(
            call_record_generation=str(end_cursor["generation"]),
            last_sequence=int(end_cursor["sequence"]),
            status="ready",
            failure_reason=None,
            last_event_id=(
                last_event_id
                if full_rebuild or last_event_id is not None
                else previous.last_event_id
            ),
            last_event_at=(
                last_event_at
                if full_rebuild or last_event_at is not None
                else previous.last_event_at
            ),
            checkpoint_at=checkpoint_at,
            retention_cutoff=previous.retention_cutoff,
            revision=previous.revision,
        )

    def _reset_runtime_ingest_locked(self) -> None:
        self._ingest_failed = False
        self._stale_reason = None

    def sync_from_log_service(self, log_source: Any) -> bool:
        """Process only new Call Records, rebuilding after destructive changes."""
        from services.log_service import LogCursorMismatch

        with self._lock:
            force_rebuild = False
            try:
                for attempt in range(3):
                    state = self.repository.load_state()
                    expected_revision = state.revision if state is not None else 0
                    checkpoint_ready = (
                        not force_rebuild
                        and state is not None
                        and state.ready
                        and not state.failure_reason
                        and not self._ingest_failed
                    )
                    checkpoint_required = (
                        not force_rebuild
                        and state is None
                        and not self._ingest_failed
                        and self.repository.has_hourly_projection()
                    )
                    now = _beijing_now_naive()
                    cutoff_bucket = _retention_cutoff(now)
                    try:
                        if checkpoint_required:
                            raw_end_cursor = log_source.current_call_cursor()
                            end_cursor = self._normalize_log_cursor(raw_end_cursor)
                            if end_cursor is None:
                                raise LogCursorMismatch("call record cursor is invalid")
                            next_state = DashboardMetricsState(
                                call_record_generation=str(end_cursor["generation"]),
                                last_sequence=int(end_cursor["sequence"]),
                                status="ready",
                                checkpoint_at=beijing_now().isoformat(timespec="seconds"),
                            )
                            self.repository.apply_increment(
                                expected_revision=expected_revision,
                                next_state=next_state,
                                buckets={},
                                cutoff_bucket=cutoff_bucket,
                                source_cursor=end_cursor,
                            )
                            rebuilt = False
                            record_count = 0
                            mode = "checkpoint"
                        elif checkpoint_ready:
                            cursor = state.cursor
                            if cursor is None:
                                force_rebuild = True
                                continue
                            with log_source.open_call_window(cursor) as (items, raw_end_cursor):
                                end_cursor = self._normalize_log_cursor(raw_end_cursor)
                                if end_cursor is None:
                                    raise LogCursorMismatch("call record cursor is invalid")
                                unchanged = end_cursor == cursor
                                if unchanged:
                                    buckets: dict[str, dict[str, Any]] = {}
                                    record_count = 0
                                    next_state = state
                                else:
                                    (
                                        buckets,
                                        record_count,
                                        last_event_id,
                                        last_event_at,
                                    ) = self._aggregate_items(items, now=now)
                                    next_state = self._next_state(
                                        state,
                                        end_cursor=end_cursor,
                                        last_event_id=last_event_id,
                                        last_event_at=last_event_at,
                                        checkpoint_at=beijing_now().isoformat(timespec="seconds"),
                                        full_rebuild=False,
                                    )
                            self.repository.apply_increment(
                                expected_revision=expected_revision,
                                next_state=next_state,
                                buckets=buckets,
                                cutoff_bucket=cutoff_bucket,
                                source_cursor=end_cursor,
                            )
                            rebuilt = False
                            mode = "incremental"
                        else:
                            with log_source.open_call_window(None) as (items, raw_end_cursor):
                                end_cursor = self._normalize_log_cursor(raw_end_cursor)
                                if end_cursor is None:
                                    raise LogCursorMismatch("call record cursor is invalid")
                                (
                                    buckets,
                                    record_count,
                                    last_event_id,
                                    last_event_at,
                                ) = self._aggregate_items(items, now=now)
                            next_state = self._next_state(
                                state,
                                end_cursor=end_cursor,
                                last_event_id=last_event_id,
                                last_event_at=last_event_at,
                                checkpoint_at=beijing_now().isoformat(timespec="seconds"),
                                full_rebuild=True,
                            )
                            self.repository.replace_projection(
                                expected_revision=expected_revision,
                                next_state=next_state,
                                buckets=buckets,
                                cutoff_bucket=cutoff_bucket,
                                source_cursor=end_cursor,
                            )
                            rebuilt = True
                            mode = "rebuild"

                        self._reset_runtime_ingest_locked()
                        logger.info({
                            "event": "dashboard_metrics_log_cursor_synced",
                            "mode": mode,
                            "records": record_count,
                        })
                        return rebuilt
                    except DashboardMetricsWriteConflict:
                        if attempt >= 2:
                            raise
                    except (LogCursorMismatch, DashboardMetricsSourceChanged):
                        force_rebuild = True
                        if attempt >= 2:
                            raise
                raise RuntimeError("dashboard metrics synchronization did not converge")
            except Exception:
                self._ingest_failed = True
                self._stale_reason = "log_cursor_sync_failed"
                try:
                    self.repository.mark_degraded(self._stale_reason)
                except Exception:
                    pass
                raise

    def sync_from_logs(self, items: Iterable[dict[str, Any]]) -> bool:
        """Replace the projection from an explicit deterministic Call Record set."""
        with self._lock:
            now = _beijing_now_naive()
            buckets, record_count, last_event_id, last_event_at = self._aggregate_items(
                items,
                now=now,
            )
            state = self.repository.load_state()
            expected_revision = state.revision if state is not None else 0
            checkpoint_at = beijing_now().isoformat(timespec="seconds")
            next_state = DashboardMetricsState(
                call_record_generation="explicit_snapshot",
                last_sequence=0,
                status="ready",
                last_event_id=last_event_id,
                last_event_at=last_event_at,
                checkpoint_at=checkpoint_at,
                revision=expected_revision,
            )
            self.repository.replace_projection(
                expected_revision=expected_revision,
                next_state=next_state,
                buckets=buckets,
                cutoff_bucket=_retention_cutoff(now),
                source_cursor=None,
            )
            self._reset_runtime_ingest_locked()
            logger.info({"event": "dashboard_metrics_synced", "records": record_count})
            return True

    def mark_ingest_failed(self, reason: str = "ingest_failed") -> None:
        """Persist a stale marker so the next synchronization performs a rebuild."""
        with self._lock:
            self._ingest_failed = True
            self._stale_reason = _clean_text(reason) or "ingest_failed"
            try:
                self.repository.mark_degraded(self._stale_reason)
            except Exception as exc:
                logger.error({
                    "event": "dashboard_metrics_ingest_marker_failed",
                    "error": str(exc),
                })

    def refresh_worker(
        self,
        log_source: Any,
        stop_event: threading.Event,
        *,
        interval_seconds: float = DASHBOARD_METRICS_REFRESH_INTERVAL_SECS,
    ) -> None:
        """Incrementally refresh the projection until application shutdown."""
        interval = max(0.1, float(interval_seconds))
        while not stop_event.wait(interval):
            try:
                self.sync_from_log_service(log_source)
            except Exception as exc:
                logger.error({
                    "event": "dashboard_metrics_refresh_failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                })

    def start_refresh_scheduler(
        self,
        log_source: Any,
        stop_event: threading.Event,
    ) -> threading.Thread:
        thread = threading.Thread(
            target=self.refresh_worker,
            args=(log_source, stop_event),
            daemon=True,
            name="dashboard-metrics-refresh",
        )
        thread.start()
        return thread

    def _snapshot_data(self) -> tuple[DashboardMetricsState | None, dict[str, Any]]:
        with self._lock:
            now = _beijing_now_naive()
            snapshot = self.repository.load(_retention_cutoff(now))
            days: dict[str, Any] = {}
            for bucket_start, bucket in snapshot.hourly.items():
                day_key, hour_key = bucket_start.split("T", 1)
                days.setdefault(day_key, {"hours": {}})["hours"][hour_key] = bucket
            return snapshot.state, days

    def _metrics_view(
        self,
        state: DashboardMetricsState | None,
        *,
        now: datetime,
    ) -> dict[str, Any]:
        ready = bool(state and state.ready and not self._ingest_failed)
        last_ingested_at = state.last_event_at if state is not None else None
        last_ingested_dt = _parse_log_time(last_ingested_at)
        freshness_ms = (
            max(0, int((now - last_ingested_dt).total_seconds() * 1000))
            if last_ingested_dt is not None
            else None
        )
        failure_reason = (
            self._stale_reason
            if self._ingest_failed
            else (state.failure_reason if state is not None else "uninitialized")
        )
        return {
            "status": "ready" if ready else "degraded",
            "ready": ready,
            "stale": not ready,
            "source": "call_record_sequence",
            "source_revision": state.last_event_id if state is not None else None,
            "last_ingested_at": last_ingested_at,
            "freshness_ms": freshness_ms,
            "checkpoint_at": state.checkpoint_at if state is not None else None,
            "failure_reason": failure_reason,
            "retention_days": DASHBOARD_METRICS_RETENTION_DAYS,
        }

    @staticmethod
    def _range_view(
        days: dict[str, Any],
        time_range: str,
        *,
        now: datetime,
    ) -> dict[str, Any]:
        bucket_count = {"24h": 24, "7d": 7, "30d": 30}.get(time_range)
        if bucket_count is None:
            raise ValueError(f"Unsupported dashboard time range: {time_range}")
        bucket_delta = timedelta(hours=1) if time_range == "24h" else timedelta(days=1)
        bucket_format = "%H:00" if time_range == "24h" else "%m-%d"
        current_bucket_start = (
            now.replace(minute=0, second=0, microsecond=0)
            if time_range == "24h"
            else now.replace(hour=0, minute=0, second=0, microsecond=0)
        )
        starts = [
            current_bucket_start - bucket_delta * (bucket_count - 1 - index)
            for index in range(bucket_count)
        ]
        labels = [start.strftime(bucket_format) for start in starts]
        window = {
            "requested": time_range,
            "start_at": starts[0].isoformat(timespec="seconds"),
            "end_at": now.isoformat(timespec="seconds"),
            "bucket_unit": "hour" if time_range == "24h" else "day",
            "bucket_count": bucket_count,
        }

        def bucket_for(start: datetime) -> dict[str, Any]:
            day = days.get(start.strftime("%Y-%m-%d"), {})
            hours = (
                day.get("hours")
                if isinstance(day, dict) and isinstance(day.get("hours"), dict)
                else {}
            )
            if time_range == "24h":
                bucket = hours.get(start.strftime("%H"), {}) if isinstance(hours, dict) else {}
                return bucket if isinstance(bucket, dict) else {}
            bucket = _empty_bucket()
            for hour in hours.values() if isinstance(hours, dict) else ():
                if isinstance(hour, dict):
                    _merge_bucket(bucket, hour)
            return bucket

        series_buckets = [bucket_for(start) for start in starts]
        total_bucket = _empty_bucket()
        for bucket in series_buckets:
            _merge_bucket(total_bucket, bucket)

        def integer_series(key: str) -> list[int]:
            return [int(bucket.get(key, 0) or 0) for bucket in series_buckets]

        success_requests = integer_series("success")
        final_failed_requests = integer_series("final_failed")
        measured_requests = [
            success_requests[index] + final_failed_requests[index]
            for index in range(bucket_count)
        ]
        success_rate = [
            round(success_requests[index] * 100 / measured, 2) if measured > 0 else None
            for index, measured in enumerate(measured_requests)
        ]

        model_success_requests: dict[str, list[int]] = {}
        model_duration_totals: dict[str, list[float]] = {}
        model_duration_counts: dict[str, list[int]] = {}
        for index, bucket in enumerate(series_buckets):
            successes = (
                bucket.get("model_success")
                if isinstance(bucket.get("model_success"), dict)
                else {}
            )
            for model, count in successes.items():
                model_success_requests.setdefault(str(model), [0] * bucket_count)[index] += int(
                    count or 0
                )
            totals = (
                bucket.get("model_success_total_times")
                if isinstance(bucket.get("model_success_total_times"), dict)
                else {}
            )
            counts = (
                bucket.get("model_success_time_counts")
                if isinstance(bucket.get("model_success_time_counts"), dict)
                else {}
            )
            for model, total in totals.items():
                model_duration_totals.setdefault(str(model), [0.0] * bucket_count)[index] += float(
                    total or 0.0
                )
            for model, count in counts.items():
                model_duration_counts.setdefault(str(model), [0] * bucket_count)[index] += int(
                    count or 0
                )

        model_names = sorted(
            set(model_success_requests) | set(model_duration_totals) | set(model_duration_counts),
            key=lambda model: (-sum(model_success_requests.get(model, [])), model.lower()),
        )
        model_avg_success_duration_ms: dict[str, list[float | None]] = {}
        for model in model_names:
            duration_totals = model_duration_totals.get(model, [0.0] * bucket_count)
            duration_counts = model_duration_counts.get(model, [0] * bucket_count)
            model_avg_success_duration_ms[model] = [
                round(duration_totals[index] / duration_counts[index], 2)
                if duration_counts[index] > 0
                else None
                for index in range(bucket_count)
            ]

        current_metrics = _bucket_metrics(total_bucket)
        totals = {
            "total": current_metrics["total_calls"],
            "success": current_metrics["success_calls"],
            "final_failed": current_metrics["final_failed_calls"],
            "success_rate": current_metrics["success_rate"],
            "avg_success_duration_ms": current_metrics["avg_success_duration_ms"],
        }
        switching = {
            "requests": current_metrics["switch_requests"],
            "count": current_metrics["switch_count"],
            "recovered": current_metrics["switch_recovered"],
            "recovery_rate": current_metrics["switch_recovery_rate"],
        }
        buckets = []
        for start, current_bucket in zip(starts, series_buckets):
            metrics = _bucket_metrics(current_bucket)
            buckets.append({
                "label": start.strftime(bucket_format),
                "start_at": start.isoformat(timespec="seconds"),
                "end_at": (start + bucket_delta).isoformat(timespec="seconds"),
                "total_calls": metrics["total_calls"],
                "success_calls": metrics["success_calls"],
                "final_failed_calls": metrics["final_failed_calls"],
                "success_rate": metrics["success_rate"],
                "avg_success_duration_ms": metrics["avg_success_duration_ms"],
                "switch_count": metrics["switch_count"],
                "switch_recovered": metrics["switch_recovered"],
                "switch_recovery_rate": metrics["switch_recovery_rate"],
            })
        trend = {
            "labels": labels,
            "success_requests": success_requests,
            "final_failed_requests": final_failed_requests,
            "success_rate": success_rate,
            "switch_count": integer_series("switch_count"),
            "model_success_requests": model_success_requests,
            "model_avg_success_duration_ms": model_avg_success_duration_ms,
        }
        return {
            "time_range": time_range,
            "window": window,
            "totals": totals,
            "switching": switching,
            "buckets": buckets,
            "trend": trend,
        }

    def snapshot_many(
        self,
        time_ranges: Iterable[str] = DASHBOARD_TIME_RANGES,
    ) -> dict[str, Any]:
        requested = tuple(dict.fromkeys(str(item or "").strip() for item in time_ranges))
        invalid = [item for item in requested if item not in DASHBOARD_TIME_RANGES]
        if invalid:
            raise ValueError(f"Unsupported dashboard time ranges: {', '.join(invalid)}")
        state, days = self._snapshot_data()
        now = _beijing_now_naive()
        return {
            "metrics": self._metrics_view(state, now=now),
            "ranges": {
                time_range: self._range_view(days, time_range, now=now)
                for time_range in requested
            },
        }

    def summary_many(
        self,
        time_ranges: Iterable[str] = DASHBOARD_TIME_RANGES,
    ) -> dict[str, dict[str, Any]]:
        return self.snapshot_many(time_ranges)["ranges"]

    def summary(self, time_range: str = "24h") -> dict[str, Any]:
        return self.snapshot_many((time_range,))["ranges"][time_range]


dashboard_metrics_service = DashboardMetricsService()
