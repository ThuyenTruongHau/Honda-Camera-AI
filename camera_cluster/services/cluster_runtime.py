"""One master, one control lock, four fields per camera and lease-only handover."""
import asyncio
import hmac
import logging
import time
from collections import Counter
from repositories.cluster_repository import RamClusterRepository
from core.camera_catalog import load_camera_catalog, service_path
from core.local_master_session import LocalMasterSession


class ClusterError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message
        super().__init__(message)


class ClusterRuntime:
    def __init__(self, repository, settings, clock=time.time, startup_delay=0):
        self.repo, self.config, self.clock = repository, settings, clock
        self.catalog, self.workers = {}, {}
        self.control = asyncio.Lock()
        self.master_until = 0.0
        self.healthy = False
        self.task = None
        self.failure_reason = None
        self.startup_delay = startup_delay
        self.recovery_until = 0.0
        self.local_session = None

    def authenticate(self, worker_id, token):
        expected = self.config.cluster_worker_tokens.get(worker_id)
        if not expected or not hmac.compare_digest(expected, token or ""):
            raise ClusterError(401, "Invalid worker credentials")

    def require_ready(self):
        if not self.healthy or self.clock() >= self.master_until:
            raise ClusterError(503, "Cluster controller unavailable")

    async def _save_camera(self, row, reason=None):
        await self.repo.save_camera(row)
        if reason:
            await self.repo.event(dict(row, at=self.clock(), reason=reason))

    async def _revoke(self, row, reason):
        # Keep the old expiry as the handover barrier. Never issue an overlapping lease.
        row["owner_worker_id"] = None
        await self._save_camera(row, reason)

    async def start(self, background=True):
        now = self.clock()
        self.recovery_until = now + self.startup_delay
        for raw in await self.repo.load_catalog():
            cid = str(raw["_id"])
            if cid in self.catalog:
                raise ValueError("Camera IDs must be unique")
            self.catalog[cid] = {k: v for k, v in raw.items() if k not in ("_id", "enabled")}
            self.catalog[cid]["camera_id"] = cid
            await self._save_camera({
                "camera_id": cid, "owner_worker_id": None,
                "assignment_epoch": self.repo.epoch_base,
                "lease_expires_at": self.recovery_until,
            }, "master_start")
        self.master_until = self.clock() + 30
        self.healthy = True
        if background:
            self.task = asyncio.create_task(self._loop())

    async def stop(self):
        self.healthy = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        try:
            await self.repo.close()
        finally:
            if self.local_session:
                self.local_session.close()
                self.local_session = None

    async def _loop(self):
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.healthy = False
                self.failure_reason = type(exc).__name__
                logging.getLogger("camera_cluster").error("Cluster controller stopped: %s", self.failure_reason)
                return
            await asyncio.sleep(self.config.cluster_tick_seconds)

    def _worker(self, worker_id):
        worker = self.workers.get(worker_id)
        if worker is None:
            raise ClusterError(409, "Register this worker before sending data")
        return worker

    async def register(self, data):
        async with self.control:
            self.require_ready()
            # Register always means empty local state. Also safe when a lost reply is retried.
            for row in await self.repo.list_cameras():
                if row["owner_worker_id"] == data.worker_id:
                    await self._revoke(row, "worker_register")
            self.workers[data.worker_id] = {
                "worker_id": data.worker_id, "last_seen": self.clock(),
                "ready": False, "ready_since": None,
            }
            return await self._response(data.worker_id)

    async def heartbeat(self, data):
        async with self.control:
            self.require_ready()
            worker = self._worker(data.worker_id)
            now = self.clock()
            previous_ready = worker["ready_since"] if worker["last_seen"] + self.config.cluster_lease_seconds > now else None
            worker.update(last_seen=now, ready=data.ready,
                          ready_since=(previous_ready if previous_ready is not None else now) if data.ready else None)
            claims = {(c.camera_id, c.assignment_epoch) for c in data.cameras}
            for row in await self.repo.list_cameras():
                if (data.ready and row["owner_worker_id"] == data.worker_id
                        and row["lease_expires_at"] > now
                        and (row["camera_id"], row["assignment_epoch"]) in claims):
                    row["lease_expires_at"] = now + self.config.cluster_lease_seconds
                    await self._save_camera(row)
            return await self._response(data.worker_id)

    async def _response(self, worker_id):
        now = self.clock()
        assignments = [dict(self.catalog[row["camera_id"]], **row)
                       for row in await self.repo.list_cameras()
                       if row["owner_worker_id"] == worker_id and row["lease_expires_at"] > now]
        return {"worker_id": worker_id, "server_time": self.clock(),
                "heartbeat_interval": self.config.cluster_heartbeat_interval, "assignments": assignments}

    async def tick(self):
        async with self.control:
            self.require_ready()
            now = self.clock()
            self.master_until = now + 30
            eligible = sorted(wid for wid, w in self.workers.items()
                              if w["ready"] and w["last_seen"] + self.config.cluster_lease_seconds > now
                              and w["ready_since"] is not None
                              and now - w["ready_since"] >= self.config.cluster_recovery_delay)
            rows = await self.repo.list_cameras()
            for row in rows:
                if row["owner_worker_id"] is not None and row["lease_expires_at"] <= now:
                    await self._revoke(row, "lease_expired")
            if not eligible:
                return
            counts = Counter(r["owner_worker_id"] for r in rows if r["owner_worker_id"] is not None)
            targets = {w: len(rows) // len(eligible) + (i < len(rows) % len(eligible))
                       for i, w in enumerate(eligible)}
            for row in sorted(rows, key=lambda r: r["camera_id"]):
                if row["owner_worker_id"] is not None or row["lease_expires_at"] > now:
                    continue
                candidates = [w for w in eligible if counts[w] < targets[w]]
                if not candidates:
                    break
                target = min(candidates, key=lambda w: (counts[w], w))
                row.update(owner_worker_id=target, assignment_epoch=row["assignment_epoch"] + 1,
                           lease_expires_at=now + self.config.cluster_lease_seconds)
                await self._save_camera(row, "assigned")
                counts[target] += 1
            budget = self.config.cluster_rebalance_batch
            for row in sorted(rows, key=lambda r: r["camera_id"], reverse=True):
                owner = row["owner_worker_id"]
                if not budget or owner is None or counts[owner] <= targets.get(owner, 0):
                    continue
                await self._revoke(row, "rebalance")
                counts[owner] -= 1
                budget -= 1


    async def state(self):
        async with self.control:
            self.require_ready()
            return {"healthy": self.healthy, "storage": "ram",
                    "startup_recovery_until": self.recovery_until,
                    "history_size": len(self.repo.events), "history_limit": self.repo.events.maxlen,
                    "workers": list(self.workers.values()), "cameras": await self.repo.list_cameras()}


_runtime = None


def get_runtime():
    if _runtime is None:
        raise ClusterError(503, "Cluster mode is not running")
    return _runtime


async def start_runtime(settings, *, clock=time.time, background=True):
    global _runtime
    if service_path(settings.cluster_camera_config_path) == service_path(settings.cluster_boot_state_path):
        raise ValueError("Camera config and boot state must use different files")
    cameras = await asyncio.to_thread(load_camera_catalog, settings.cluster_camera_config_path,
                                     settings.cluster_max_cameras, settings.cluster_max_rois_per_camera)
    session = LocalMasterSession(settings.cluster_boot_state_path)
    session.open()
    runtime = ClusterRuntime(RamClusterRepository(cameras, epoch_base=session.epoch_base,
                                                 history_limit=settings.cluster_history_limit),
                             settings, clock=clock, startup_delay=settings.cluster_lease_seconds)
    runtime.local_session = session
    try:
        await runtime.start(background=background)
    except BaseException:
        try:
            await runtime.repo.close()
        finally:
            session.close()
        raise
    _runtime = runtime
    return runtime
