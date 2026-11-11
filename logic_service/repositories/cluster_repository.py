"""Four-field camera ownership in RAM; the runtime serializes every operation."""
import copy
from collections import deque
from core.local_master_session import EPOCH_STRIDE


OWNERSHIP_FIELDS = {"camera_id", "owner_worker_id", "assignment_epoch", "lease_expires_at"}


class RamClusterRepository:
    def __init__(self, cameras=(), *, epoch_base=0, history_limit=1000):
        self.catalog = copy.deepcopy(list(cameras))
        self.rows = {}
        self.epoch_base = epoch_base
        self.events = deque(maxlen=history_limit)

    async def load_catalog(self):
        return copy.deepcopy(self.catalog)

    async def list_cameras(self):
        return copy.deepcopy(list(self.rows.values()))

    async def get_camera(self, camera_id):
        return copy.deepcopy(self.rows.get(camera_id))

    async def save_camera(self, row):
        if set(row) != OWNERSHIP_FIELDS:
            raise ValueError("Camera ownership must contain exactly four fields")
        if not self.epoch_base <= row["assignment_epoch"] < self.epoch_base + EPOCH_STRIDE:
            raise RuntimeError("Camera epoch range exhausted; restart master for a new generation")
        self.rows[row["camera_id"]] = copy.deepcopy(row)

    async def event(self, event):
        self.events.append(copy.deepcopy(event))

    async def close(self):
        pass
