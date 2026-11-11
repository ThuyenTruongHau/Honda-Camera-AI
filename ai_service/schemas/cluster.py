"""Camera authority received through sequential heartbeats to one master."""
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class Assignment(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    camera_id: str = Field(min_length=1)
    owner_worker_id: str = Field(min_length=1)
    assignment_epoch: int = Field(ge=1)
    lease_expires_at: float
    # Static camera configuration, not ownership state.
    config_version: int = Field(ge=1)
    camera_path: str = Field(min_length=1)
    camera_name: str = ""
    group_id: Any = 0
    roi: list[dict[str, Any]] = Field(default_factory=list)


class AssignmentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    worker_id: str
    server_time: float
    heartbeat_interval: float = Field(default=3.0, gt=0)
    assignments: list[Assignment] = Field(default_factory=list)
