"""Load a bounded camera catalog; no network/database access."""
import json
from pathlib import Path
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


SERVICE_ROOT = Path(__file__).resolve().parents[1]


def service_path(value):
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (SERVICE_ROOT / path).resolve()


class Region(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    name: str = Field(min_length=1, max_length=128)
    x1: float
    y1: float
    x2: float
    y2: float

    @model_validator(mode="after")
    def rectangle(self):
        if not self.name.strip() or self.x1 >= self.x2 or self.y1 >= self.y2:
            raise ValueError("ROI needs a name and non-empty rectangle")
        return self


class Camera(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    camera_id: str = Field(min_length=1, max_length=128, validation_alias=AliasChoices("camera_id", "_id"))
    camera_path: str = Field(min_length=1)
    camera_name: str = ""
    enabled: bool = True
    config_version: int = Field(default=1, ge=1)
    group_id: Any = 0
    roi: list[Region] = Field(min_length=1)


def load_camera_catalog(path, max_cameras=1000, max_rois=256, max_bytes=8 * 1024 * 1024):
    target = service_path(path)
    with target.open("rb") as source:
        raw = source.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError("Camera config exceeds configured file size limit")
    data = json.loads(raw.decode("utf-8-sig"))
    if isinstance(data, dict):
        if set(data) != {"schema_version", "cameras"} or data["schema_version"] != 1:
            raise ValueError("Expected schema_version=1 and cameras array")
        data = data["cameras"]
    if not isinstance(data, list) or len(data) > max_cameras:
        raise ValueError("Camera config must be an array within the camera count limit")
    cameras, identities, positions = [], set(), set()
    for item in data:
        # Do not include validation input in logs: RTSP URLs may contain secrets.
        try:
            camera = Camera.model_validate(item)
        except Exception:
            raise ValueError("Invalid camera configuration; check IDs, path and ROI fields") from None
        cid = camera.camera_id
        if not cid.strip() or not camera.camera_path.strip() or cid in identities:
            raise ValueError("Camera IDs and paths must be nonempty; IDs must be unique")
        identities.add(cid)
        if len(camera.roi) > max_rois:
            raise ValueError("Camera exceeds configured ROI count limit")
        if not camera.enabled:
            continue
        names = {roi.name for roi in camera.roi}
        if len(names) != len(camera.roi) or positions.intersection(names):
            raise ValueError("Enabled cameras must have globally unique ROI position names")
        positions.update(names)
        value = camera.model_dump(exclude={"camera_id"})
        value["_id"] = cid
        cameras.append(value)
    return cameras
