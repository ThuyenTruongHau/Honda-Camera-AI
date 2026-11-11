"""Detection timestamps/ROI data are separate from camera ownership."""
from typing import Literal
from pydantic import Field
from schemas.cluster import Contract, RegisterRequest


class RoiResult(Contract):
    roi_id: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=128)


class DetectionItem(Contract):
    camera_id: str = Field(min_length=1)
    assignment_epoch: int = Field(ge=1)
    config_version: int = Field(ge=1)
    frame_observed_at: float
    inferred_at: float
    rois: list[RoiResult] = Field(min_length=1, max_length=10000)


class DetectionBatch(RegisterRequest):
    schema_version: Literal[3]
    items: list[DetectionItem] = Field(min_length=1, max_length=1000)
