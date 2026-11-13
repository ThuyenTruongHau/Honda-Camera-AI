"""Point-keyed contract plus a reserved _cluster ownership extension."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from core.point_contract import END_POINT_EMPTY, normalize_point_id


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class PointResult(Contract):
    label: Literal["hang", "trong"]
    group_id: str | None = None


class CameraObservation(Contract):
    camera_id: str = Field(min_length=1)
    assignment_epoch: int = Field(ge=1)


class ClusterMetadata(Contract):
    worker_id: str = Field(min_length=1, max_length=128)
    cameras: list[CameraObservation] = Field(min_length=1, max_length=1000)


class DetectionBatch(BaseModel):
    model_config = ConfigDict(extra="allow", allow_inf_nan=False)
    __pydantic_extra__: dict[str, PointResult] = Field(init=False)
    cluster: ClusterMetadata = Field(alias="_cluster")

    @property
    def worker_id(self):
        return self.cluster.worker_id

    @property
    def points(self):
        return self.__pydantic_extra__

    @model_validator(mode="after")
    def validate_points(self):
        if len(self.points) > 10000:
            raise ValueError("Too many points in one request")
        for point in self.points:
            if normalize_point_id(point) != point or point == END_POINT_EMPTY:
                raise ValueError("Use numeric point IDs and omit END_POINT_EMPTY")
        cameras = set()
        for camera in self.cluster.cameras:
            if camera.camera_id in cameras:
                raise ValueError("A camera may appear only once in a request")
            cameras.add(camera.camera_id)
        return self


def build_payload(worker_id, snapshots):
    points, cameras = {}, []
    for snapshot in snapshots:
        current = snapshot["points"]
        if points.keys() & current.keys():
            raise ValueError("Duplicate point in camera batch")
        points.update(current)
        cameras.append({k: snapshot[k] for k in ("camera_id", "assignment_epoch")})
    payload = {**points, "_cluster": {"worker_id": worker_id, "cameras": cameras}}
    return DetectionBatch.model_validate(payload).model_dump(by_alias=True, exclude_none=True)


def build_logic_payload(worker_id, snapshots):
    """The unchanged business receiver expects only point_id -> label/group_id."""
    payload = build_payload(worker_id, snapshots)
    del payload["_cluster"]
    return payload
