from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


UpdateTone = Literal["success", "muted", "warning"]
UpdateTaskState = Literal["idle", "queued", "running", "succeeded", "failed"]
UpdateTaskStage = Literal[
    "idle",
    "queued",
    "checking",
    "downloading",
    "verifying",
    "installing",
    "syncing",
    "restarting",
    "completed",
    "failed",
]
UpdateTaskTone = Literal["info", "success", "warning", "danger"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class UpdateStatusView(_StrictModel):
    current_tag: str = Field(min_length=1)
    latest_tag: str = ""
    update_available: bool
    release_url: str = Field(min_length=1)
    status_label: str = Field(min_length=1)
    status_message: str = Field(min_length=1)
    tone: UpdateTone
    changelog: str = ""
    can_update: bool = False

    @model_validator(mode="after")
    def validate_status(self) -> "UpdateStatusView":
        if self.update_available and not self.latest_tag:
            raise ValueError("available updates require the latest release")
        if self.can_update and not self.update_available:
            raise ValueError("update capability requires an available update")
        return self


class UpdateTaskEventView(_StrictModel):
    id: str = Field(min_length=1)
    timestamp: str = Field(min_length=1)
    label: str = Field(min_length=1)
    message: str = Field(min_length=1)
    tone: UpdateTaskTone = "info"


class UpdateTaskView(_StrictModel):
    task_id: str = ""
    state: UpdateTaskState = "idle"
    stage: UpdateTaskStage = "idle"
    current: int = Field(default=0, ge=0)
    total: int = Field(default=6, ge=1)
    status_label: str = Field(min_length=1)
    message: str = Field(min_length=1)
    tone: UpdateTaskTone = "info"
    busy: bool = False
    current_tag: str = Field(min_length=1)
    latest_tag: str = ""
    error: str = ""
    updated_at: str = Field(min_length=1)
    events: tuple[UpdateTaskEventView, ...] = ()

    @model_validator(mode="after")
    def validate_task(self) -> "UpdateTaskView":
        if self.current > self.total:
            raise ValueError("update progress cannot exceed its total")
        if self.busy != (self.state in {"queued", "running"}):
            raise ValueError("update busy state must match task state")
        if self.state == "idle" and self.task_id:
            raise ValueError("idle update task cannot have an id")
        if self.state != "idle" and not self.task_id:
            raise ValueError("active or terminal update task requires an id")
        if self.state == "failed" and not self.error:
            raise ValueError("failed update task requires an error")
        return self
