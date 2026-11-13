"""Single-master control contract. Camera authority has exactly four fields."""
from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class RegisterRequest(Contract):
    worker_id: str = Field(min_length=1, max_length=128)


class CameraClaim(Contract):
    camera_id: str = Field(min_length=1)
    assignment_epoch: int = Field(ge=1)


class HeartbeatRequest(RegisterRequest):
    ready: bool
    cameras: list[CameraClaim] = Field(default_factory=list, max_length=10000)
