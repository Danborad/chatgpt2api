from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Mapping

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    delete,
    inspect,
    select,
    text,
)
from sqlalchemy.orm import sessionmaker

from services.application_database import (
    DatabaseBase,
    initialize_application_database,
    resolve_database_url,
)
from services.storage.call_record_repository import CallRecordStateModel


_COUNT_FIELDS = (
    "total",
    "success",
    "final_failed",
    "switch_requests",
    "switch_count",
    "switch_recovered",
)


class DashboardMetricStateModel(DatabaseBase):
    __tablename__ = "dashboard_metric_state"

    id = Column(Integer, primary_key=True)
    call_record_generation = Column(String(64), nullable=False, default="")
    last_sequence = Column(BigInteger, nullable=False, default=0)
    status = Column(String(16), nullable=False, default="degraded")
    failure_reason = Column(String(255), nullable=True)
    last_event_id = Column(String(64), nullable=True)
    last_event_at = Column(String(40), nullable=True)
    checkpoint_at = Column(String(40), nullable=True)
    retention_cutoff = Column(String(13), nullable=False, default="")
    revision = Column(Integer, nullable=False, default=1)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class DashboardMetricHourlyModel(DatabaseBase):
    __tablename__ = "dashboard_metric_hourly"

    bucket_start = Column(String(13), primary_key=True)
    total = Column(BigInteger, nullable=False, default=0)
    success = Column(BigInteger, nullable=False, default=0)
    final_failed = Column(BigInteger, nullable=False, default=0)
    switch_requests = Column(BigInteger, nullable=False, default=0)
    switch_count = Column(BigInteger, nullable=False, default=0)
    switch_recovered = Column(BigInteger, nullable=False, default=0)
    success_duration_total_ms = Column(Float, nullable=False, default=0.0)
    success_duration_count = Column(BigInteger, nullable=False, default=0)


class DashboardMetricModelHourlyModel(DatabaseBase):
    __tablename__ = "dashboard_metric_model_hourly"

    bucket_start = Column(
        String(13),
        ForeignKey("dashboard_metric_hourly.bucket_start", ondelete="CASCADE"),
        primary_key=True,
    )
    model = Column(String(255), primary_key=True)
    success = Column(BigInteger, nullable=False, default=0)
    success_duration_total_ms = Column(Float, nullable=False, default=0.0)
    success_duration_count = Column(BigInteger, nullable=False, default=0)

    __table_args__ = (
        Index("ix_dashboard_metric_model_hourly_model", "model", "bucket_start"),
    )


@dataclass(frozen=True, slots=True)
class DashboardMetricsState:
    call_record_generation: str = ""
    last_sequence: int = 0
    status: str = "degraded"
    failure_reason: str | None = None
    last_event_id: str | None = None
    last_event_at: str | None = None
    checkpoint_at: str | None = None
    retention_cutoff: str = ""
    revision: int = 0

    @property
    def cursor(self) -> dict[str, Any] | None:
        if not self.call_record_generation:
            return None
        return {
            "generation": self.call_record_generation,
            "sequence": self.last_sequence,
        }

    @property
    def ready(self) -> bool:
        return self.status == "ready" and self.cursor is not None


@dataclass(frozen=True, slots=True)
class DashboardMetricsSnapshot:
    state: DashboardMetricsState | None
    hourly: dict[str, dict[str, Any]]


@dataclass(frozen=True, slots=True)
class DashboardMetricsWriteResult:
    state: DashboardMetricsState
    changed: bool


@dataclass(frozen=True, slots=True)
class DashboardMetricsSchemaReset:
    state_recreated: bool = False
    hourly_recreated: bool = False
    model_hourly_recreated: bool = False

    @property
    def projection_recreated(self) -> bool:
        return self.hourly_recreated or self.model_hourly_recreated

    @property
    def changed(self) -> bool:
        return self.state_recreated or self.projection_recreated


class DashboardMetricsWriteConflict(RuntimeError):
    pass


class DashboardMetricsSourceChanged(RuntimeError):
    pass


class DashboardMetricsRepository:
    """Atomic persistence for the rebuildable hourly Dashboard projection."""

    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or resolve_database_url()
        self.engine = initialize_application_database(self.database_url)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

    def reset_schema_if_needed(self) -> DashboardMetricsSchemaReset:
        """Recreate only Dashboard tables whose physical schema is incompatible."""
        tables = (
            DashboardMetricStateModel.__table__,
            DashboardMetricHourlyModel.__table__,
            DashboardMetricModelHourlyModel.__table__,
        )
        with self.engine.begin() as connection:
            if self.engine.dialect.name == "postgresql":
                connection.execute(
                    text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                    {"key": "dashboard_metrics_schema"},
                )
            schema = inspect(connection)
            existing_tables = set(schema.get_table_names())

            def incompatible(table: Any) -> bool:
                if table.name not in existing_tables:
                    return True
                return {
                    column["name"] for column in schema.get_columns(table.name)
                } != {column.name for column in table.columns}

            state_recreated = incompatible(DashboardMetricStateModel.__table__)
            hourly_recreated = incompatible(DashboardMetricHourlyModel.__table__)
            model_hourly_recreated = incompatible(DashboardMetricModelHourlyModel.__table__)

            if hourly_recreated or model_hourly_recreated:
                # Aggregates cannot remain internally consistent after either
                # aggregate table changes, so rebuild the complete projection.
                state_recreated = True
                hourly_recreated = True
                model_hourly_recreated = True
                for table in reversed(tables):
                    table.drop(connection, checkfirst=True)
                DatabaseBase.metadata.create_all(connection, tables=list(tables))
            elif state_recreated:
                DashboardMetricStateModel.__table__.drop(connection, checkfirst=True)
                DatabaseBase.metadata.create_all(
                    connection,
                    tables=[DashboardMetricStateModel.__table__],
                )

            return DashboardMetricsSchemaReset(
                state_recreated=state_recreated,
                hourly_recreated=hourly_recreated,
                model_hourly_recreated=model_hourly_recreated,
            )

    def _lock(self, session: Any) -> None:
        if self.engine.dialect.name == "sqlite":
            session.execute(text("BEGIN IMMEDIATE"))
        elif self.engine.dialect.name == "postgresql":
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                {"key": "dashboard_metrics"},
            )

    @staticmethod
    def _integer(value: object) -> int:
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _number(value: object) -> float:
        try:
            return max(0.0, float(value or 0.0))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _clean(value: object) -> str:
        return str(value or "").strip()

    @classmethod
    def _state(cls, row: DashboardMetricStateModel | None) -> DashboardMetricsState | None:
        if row is None:
            return None
        return DashboardMetricsState(
            call_record_generation=cls._clean(row.call_record_generation),
            last_sequence=cls._integer(row.last_sequence),
            status=cls._clean(row.status) or "degraded",
            failure_reason=cls._clean(row.failure_reason) or None,
            last_event_id=cls._clean(row.last_event_id) or None,
            last_event_at=cls._clean(row.last_event_at) or None,
            checkpoint_at=cls._clean(row.checkpoint_at) or None,
            retention_cutoff=cls._clean(row.retention_cutoff),
            revision=cls._integer(row.revision),
        )

    @classmethod
    def _hour_payload(cls, row: DashboardMetricHourlyModel) -> dict[str, Any]:
        payload = {field: cls._integer(getattr(row, field)) for field in _COUNT_FIELDS}
        payload.update({
            "success_duration_total_ms": cls._number(row.success_duration_total_ms),
            "success_duration_count": cls._integer(row.success_duration_count),
            "model_success": {},
            "model_success_total_times": {},
            "model_success_time_counts": {},
        })
        return payload

    def load_state(self) -> DashboardMetricsState | None:
        session = self.Session()
        try:
            return self._state(session.get(DashboardMetricStateModel, 1))
        finally:
            session.close()

    def has_hourly_projection(self) -> bool:
        """Return whether a preserved hourly projection exists without loading it."""
        session = self.Session()
        try:
            return session.scalar(
                select(DashboardMetricHourlyModel.bucket_start).limit(1)
            ) is not None
        finally:
            session.close()

    def load(self, cutoff_bucket: str) -> DashboardMetricsSnapshot:
        """Load one state row and only retained hourly projection rows."""
        session = self.Session()
        try:
            state = self._state(session.get(DashboardMetricStateModel, 1))
            hourly: dict[str, dict[str, Any]] = {}
            hour_rows = session.scalars(
                select(DashboardMetricHourlyModel)
                .where(DashboardMetricHourlyModel.bucket_start >= cutoff_bucket)
                .order_by(DashboardMetricHourlyModel.bucket_start.asc())
            )
            for row in hour_rows:
                hourly[str(row.bucket_start)] = self._hour_payload(row)

            model_rows = session.scalars(
                select(DashboardMetricModelHourlyModel)
                .where(DashboardMetricModelHourlyModel.bucket_start >= cutoff_bucket)
                .order_by(
                    DashboardMetricModelHourlyModel.bucket_start.asc(),
                    DashboardMetricModelHourlyModel.model.asc(),
                )
            )
            for row in model_rows:
                bucket = hourly.get(str(row.bucket_start))
                if bucket is None:
                    continue
                model_name = str(row.model)
                bucket["model_success"][model_name] = self._integer(row.success)
                bucket["model_success_total_times"][model_name] = self._number(
                    row.success_duration_total_ms
                )
                bucket["model_success_time_counts"][model_name] = self._integer(
                    row.success_duration_count
                )
            return DashboardMetricsSnapshot(state=state, hourly=hourly)
        finally:
            session.close()

    @classmethod
    def _split_buckets(
        cls,
        buckets: Mapping[str, Mapping[str, Any]],
    ) -> tuple[
        dict[str, dict[str, Any]],
        dict[tuple[str, str], dict[str, Any]],
    ]:
        hourly: dict[str, dict[str, Any]] = {}
        models: dict[tuple[str, str], dict[str, Any]] = {}
        for raw_bucket_start, raw_bucket in buckets.items():
            bucket_start = cls._clean(raw_bucket_start)
            if len(bucket_start) != 13 or not isinstance(raw_bucket, Mapping):
                continue
            hourly[bucket_start] = {
                **{field: cls._integer(raw_bucket.get(field)) for field in _COUNT_FIELDS},
                "success_duration_total_ms": cls._number(
                    raw_bucket.get("success_duration_total_ms")
                ),
                "success_duration_count": cls._integer(
                    raw_bucket.get("success_duration_count")
                ),
            }
            model_names: set[str] = set()
            for field in (
                "model_success",
                "model_success_total_times",
                "model_success_time_counts",
            ):
                values = raw_bucket.get(field)
                if isinstance(values, Mapping):
                    model_names.update(
                        cls._clean(name) for name in values if cls._clean(name)
                    )
            successes = raw_bucket.get("model_success")
            duration_totals = raw_bucket.get("model_success_total_times")
            duration_counts = raw_bucket.get("model_success_time_counts")
            for model_name in model_names:
                models[(bucket_start, model_name)] = {
                    "success": cls._integer(
                        successes.get(model_name) if isinstance(successes, Mapping) else 0
                    ),
                    "success_duration_total_ms": cls._number(
                        duration_totals.get(model_name)
                        if isinstance(duration_totals, Mapping)
                        else 0
                    ),
                    "success_duration_count": cls._integer(
                        duration_counts.get(model_name)
                        if isinstance(duration_counts, Mapping)
                        else 0
                    ),
                }
        return hourly, models

    @staticmethod
    def _state_values(state: DashboardMetricsState) -> dict[str, Any]:
        return {
            "call_record_generation": state.call_record_generation,
            "last_sequence": state.last_sequence,
            "status": state.status,
            "failure_reason": state.failure_reason,
            "last_event_id": state.last_event_id,
            "last_event_at": state.last_event_at,
            "checkpoint_at": state.checkpoint_at,
            "retention_cutoff": state.retention_cutoff,
        }

    @classmethod
    def _assign(cls, row: Any, payload: Mapping[str, Any]) -> bool:
        changed = False
        for field, value in payload.items():
            if getattr(row, field) != value:
                setattr(row, field, value)
                changed = True
        return changed

    @classmethod
    def _add_values(cls, row: Any, payload: Mapping[str, Any]) -> bool:
        changed = False
        for field, value in payload.items():
            current = getattr(row, field)
            next_value = current + value
            if next_value != current:
                setattr(row, field, next_value)
                changed = True
        return changed

    @staticmethod
    def _verify_expected_state(
        current: DashboardMetricsState | None,
        expected_revision: int,
    ) -> None:
        revision = current.revision if current is not None else 0
        if revision != expected_revision:
            raise DashboardMetricsWriteConflict("dashboard metrics state changed")

    @staticmethod
    def _verify_source(session: Any, source_cursor: Mapping[str, Any] | None) -> None:
        if source_cursor is None:
            return
        generation = session.scalar(
            select(CallRecordStateModel.generation)
            .where(CallRecordStateModel.id == 1)
            .with_for_update()
        )
        if str(generation or "") != str(source_cursor.get("generation") or ""):
            raise DashboardMetricsSourceChanged("call record generation changed")

    def _replace_rows(
        self,
        session: Any,
        hourly: Mapping[str, Mapping[str, Any]],
        models: Mapping[tuple[str, str], Mapping[str, Any]],
    ) -> bool:
        session.execute(delete(DashboardMetricModelHourlyModel))
        session.execute(delete(DashboardMetricHourlyModel))
        for bucket_start, payload in hourly.items():
            session.add(DashboardMetricHourlyModel(bucket_start=bucket_start, **payload))
        session.flush()
        for (bucket_start, model_name), payload in models.items():
            session.add(DashboardMetricModelHourlyModel(
                bucket_start=bucket_start,
                model=model_name,
                **payload,
            ))
        return True

    def _increment_rows(
        self,
        session: Any,
        hourly: Mapping[str, Mapping[str, Any]],
        models: Mapping[tuple[str, str], Mapping[str, Any]],
    ) -> bool:
        changed = False
        for bucket_start, payload in hourly.items():
            row = session.get(DashboardMetricHourlyModel, bucket_start)
            if row is None:
                session.add(DashboardMetricHourlyModel(bucket_start=bucket_start, **payload))
                changed = True
            else:
                changed = self._add_values(row, payload) or changed
        session.flush()
        for (bucket_start, model_name), payload in models.items():
            row = session.get(
                DashboardMetricModelHourlyModel,
                {"bucket_start": bucket_start, "model": model_name},
            )
            if row is None:
                session.add(DashboardMetricModelHourlyModel(
                    bucket_start=bucket_start,
                    model=model_name,
                    **payload,
                ))
                changed = True
            else:
                changed = self._add_values(row, payload) or changed
        return changed

    def _write(
        self,
        *,
        expected_revision: int,
        next_state: DashboardMetricsState,
        buckets: Mapping[str, Mapping[str, Any]],
        cutoff_bucket: str,
        source_cursor: Mapping[str, Any] | None,
        replace_projection: bool,
    ) -> DashboardMetricsWriteResult:
        session = self.Session()
        try:
            self._lock(session)
            state_row = session.get(DashboardMetricStateModel, 1, with_for_update=True)
            current_state = self._state(state_row)
            self._verify_expected_state(current_state, expected_revision)
            self._verify_source(session, source_cursor)

            hourly, models = self._split_buckets(buckets)
            changed = (
                self._replace_rows(session, hourly, models)
                if replace_projection
                else self._increment_rows(session, hourly, models)
            )
            if replace_projection or (
                current_state is None or current_state.retention_cutoff != cutoff_bucket
            ):
                result = session.execute(
                    delete(DashboardMetricHourlyModel).where(
                        DashboardMetricHourlyModel.bucket_start < cutoff_bucket
                    )
                )
                changed = bool(result.rowcount) or changed

            normalized_state = replace(next_state, retention_cutoff=cutoff_bucket)
            state_values = self._state_values(normalized_state)
            if state_row is None:
                state_row = DashboardMetricStateModel(
                    id=1,
                    **state_values,
                    revision=1,
                    updated_at=datetime.now(timezone.utc),
                )
                session.add(state_row)
                changed = True
            else:
                changed = self._assign(state_row, state_values) or changed
                if changed:
                    state_row.revision = max(0, int(state_row.revision or 0)) + 1
                    state_row.updated_at = datetime.now(timezone.utc)

            session.commit()
            state = self._state(state_row)
            if state is None:
                raise RuntimeError("dashboard metrics state was not persisted")
            return DashboardMetricsWriteResult(state=state, changed=changed)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def apply_increment(
        self,
        *,
        expected_revision: int,
        next_state: DashboardMetricsState,
        buckets: Mapping[str, Mapping[str, Any]],
        cutoff_bucket: str,
        source_cursor: Mapping[str, Any],
    ) -> DashboardMetricsWriteResult:
        return self._write(
            expected_revision=expected_revision,
            next_state=next_state,
            buckets=buckets,
            cutoff_bucket=cutoff_bucket,
            source_cursor=source_cursor,
            replace_projection=False,
        )

    def replace_projection(
        self,
        *,
        expected_revision: int,
        next_state: DashboardMetricsState,
        buckets: Mapping[str, Mapping[str, Any]],
        cutoff_bucket: str,
        source_cursor: Mapping[str, Any] | None,
    ) -> DashboardMetricsWriteResult:
        return self._write(
            expected_revision=expected_revision,
            next_state=next_state,
            buckets=buckets,
            cutoff_bucket=cutoff_bucket,
            source_cursor=source_cursor,
            replace_projection=True,
        )

    def mark_degraded(self, reason: str) -> DashboardMetricsState:
        session = self.Session()
        try:
            self._lock(session)
            row = session.get(DashboardMetricStateModel, 1, with_for_update=True)
            current = self._state(row) or DashboardMetricsState()
            next_state = replace(
                current,
                status="degraded",
                failure_reason=self._clean(reason) or "ingest_failed",
            )
            values = self._state_values(next_state)
            if row is None:
                row = DashboardMetricStateModel(
                    id=1,
                    **values,
                    revision=1,
                    updated_at=datetime.now(timezone.utc),
                )
                session.add(row)
            elif self._assign(row, values):
                row.revision = max(0, int(row.revision or 0)) + 1
                row.updated_at = datetime.now(timezone.utc)
            session.commit()
            state = self._state(row)
            if state is None:
                raise RuntimeError("dashboard metrics degraded state was not persisted")
            return state
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
