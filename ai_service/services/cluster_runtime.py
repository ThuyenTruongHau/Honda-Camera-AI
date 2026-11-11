"""AI cluster lifecycle; only current assignments may publish camera snapshots."""
import asyncio
import multiprocessing as mp
import queue
import time
import logging
import httpx
from core.worker_lock import WorkerLock
from schemas.cluster import AssignmentResponse
from schemas.detection import build_payload
from services.cluster_capture import capture_process, owns
from services.cluster_detector import detector_process


def lease_deadline(request_started, server_time, expires_at, margin):
    # Request start, not response receipt: delayed replies cannot extend a lease.
    return request_started + max(0.0, expires_at - server_time - margin)


class ClusterAIService:
    def __init__(self, settings):
        self.settings = settings
        self.worker_id = settings.worker_id
        self.worker_lock = WorkerLock(self.worker_id)
        self.http_lock = asyncio.Lock()
        self.ctx = mp.get_context("spawn")
        self.manager = None
        self.processes, self.commands = [], []
        self.assignments, self.stopping, self.rejected = {}, {}, {}
        self.sent, self.tasks = {}, []
        self.running = False
        self.registered = False
        self.client = None
        self.detector = None

    async def start(self):
        self.worker_lock.open()
        try:
            await self._start()
        except BaseException:
            await self.stop()
            raise

    async def _start(self):
        self.manager = self.ctx.Manager()
        self.authority, self.frames, self.results = [self.manager.dict() for _ in range(3)]
        self.health = self.manager.dict()
        self.events = self.ctx.Queue()
        self.stop_detector = self.ctx.Event()
        self.config = self.settings.model_dump(exclude={"mongo_url", "worker_token"})
        self.client = httpx.AsyncClient(base_url=self.settings.master_url.rstrip("/"),
                                      headers={"Authorization": f"Bearer {self.settings.worker_token}"},
                                      timeout=self.settings.cluster_http_timeout)
        self.running = True
        for _ in range(self.settings.num_process):
            self._spawn_capture()
        self._spawn_detector()
        self.tasks = [asyncio.create_task(self._control_loop()), asyncio.create_task(self._report_loop()),
                      asyncio.create_task(self._watchdog_loop())]

    def _spawn_capture(self, index=None):
        commands = self.ctx.Queue()
        process = self.ctx.Process(target=capture_process,
                                   args=(commands, self.events, self.authority, self.frames, self.config), daemon=True)
        process.start()
        if index is None:
            self.processes.append(process)
            self.commands.append(commands)
        else:
            old_queue = self.commands[index]
            old_queue.cancel_join_thread()
            old_queue.close()
            self.processes[index], self.commands[index] = process, commands

    def _spawn_detector(self):
        self.health.update(ready=False, error=False, busy_since=0.0)
        self.model_started = time.monotonic()
        self.detector = self.ctx.Process(target=detector_process,
                                         args=(self.authority, self.frames, self.results, self.health, self.stop_detector, self.config), daemon=True)
        self.detector.start()

    def ready(self):
        busy = self.health.get("busy_since", 0) if self.running else 0
        progressing = not busy or time.monotonic() - busy <= self.settings.cluster_inference_timeout
        return bool(self.running and self.detector and self.detector.is_alive() and self.health.get("ready") and
                    progressing and all(p.is_alive() for p in self.processes) and all(not task.done() for task in self.tasks))

    def _stop_camera(self, cid):
        record = self.assignments.get(cid)
        self.authority.pop(cid, None)
        if not record:
            return
        key = (cid, record["assignment_epoch"])
        self.frames.pop(key, None)
        self.results.pop(key, None)
        if cid not in self.stopping:
            self.stopping[cid] = time.monotonic()
            self.commands[record["process"]].put({"action": "STOP", "assignment": record})

    async def reconcile(self, response, started):
        if response.worker_id != self.worker_id or any(a.owner_worker_id != self.worker_id for a in response.assignments):
            raise ValueError("Assignments belong to another worker")
        desired = {a.camera_id: a for a in response.assignments}
        for cid, current in list(self.assignments.items()):
            new = desired.get(cid)
            if not new or new.assignment_epoch != current["assignment_epoch"]:
                self._stop_camera(cid)
        for cid, assignment in desired.items():
            if self.rejected.get(cid, 0) >= assignment.assignment_epoch:
                continue
            deadline = lease_deadline(started, response.server_time, assignment.lease_expires_at, self.settings.cluster_lease_margin)
            if deadline <= time.monotonic() or cid in self.stopping:
                continue
            self.authority[cid] = {"epoch": assignment.assignment_epoch, "deadline": deadline}
            if cid not in self.assignments:
                counts = [sum(r["process"] == i for r in self.assignments.values()) for i in range(len(self.processes))]
                index = min(range(len(counts)), key=lambda i: counts[i])
                record = assignment.model_dump()
                record["process"] = index
                self.assignments[cid] = record
                self.commands[index].put({"action": "START", "assignment": record})

    async def _control_loop(self):
        interval = self.settings.cluster_heartbeat_interval
        while self.running:
            try:
                # One HTTP request at a time, with its response applied before the next.
                async with self.http_lock:
                    if not self.registered:
                        for cid in list(self.assignments):
                            self._stop_camera(cid)
                        reply = await self.client.post("/cluster/register", json={"worker_id": self.worker_id})
                        reply.raise_for_status()
                        self.registered = True
                    claims = [{"camera_id": cid, "assignment_epoch": record["assignment_epoch"]}
                              for cid, record in self.assignments.items()
                              if owns(self.authority, cid, record["assignment_epoch"]) and cid not in self.stopping]
                    started = time.monotonic()
                    reply = await self.client.post("/cluster/heartbeat", json={
                        "worker_id": self.worker_id, "ready": self.ready(), "cameras": claims})
                    if reply.status_code == 409:
                        self.registered = False
                    reply.raise_for_status()
                    response = AssignmentResponse.model_validate(reply.json())
                    await self.reconcile(response, started)
                    interval = response.heartbeat_interval
            except asyncio.CancelledError:
                raise
            except Exception:
                # Watchdog expires permissions independently of HTTP completion.
                pass
            await asyncio.sleep(interval)

    async def _report_loop(self):
        while self.running:
            try:
                items = []
                for key, result in list(self.results.items()):
                    if not owns(self.authority, *key) or time.time() - result["captured_at"] > self.settings.cluster_max_frame_age:
                        self.results.pop(key, None)
                        continue
                    if self.sent.get(key, 0) < result["captured_at"]:
                        items.append(result)
                for offset in range(0, len(items), self.settings.cluster_report_batch_size):
                    async with self.http_lock:
                        if not self.registered:
                            continue
                        batch = [item for item in items[offset:offset + self.settings.cluster_report_batch_size]
                                 if owns(self.authority, item["camera_id"], item["assignment_epoch"])
                                 and time.time() - item["captured_at"] <= self.settings.cluster_max_frame_age]
                        if not batch:
                            continue
                        pending = {(item["camera_id"], item["assignment_epoch"]): item["captured_at"]
                                   for item in batch}
                        reply = await self.client.post("/ai-data", json=build_payload(self.worker_id, batch))
                        if reply.status_code == 409:
                            self.registered = False
                        reply.raise_for_status()
                        response = reply.json()
                        acknowledgements = response.get("results")
                        if acknowledgements is None:
                            if response.get("status") != "success":
                                raise ValueError("Unexpected AI data acknowledgement")
                            # Also support the simple success response in the point contract.
                            acknowledgements = [dict(camera_id=item["camera_id"],
                                                     assignment_epoch=item["assignment_epoch"],
                                                     status="accepted")
                                                for item in batch]
                        for result in acknowledgements:
                            key = (result["camera_id"], result["assignment_epoch"])
                            if key not in pending:
                                raise ValueError("Acknowledgement does not match the submitted cameras")
                            if result["status"] in ("wrong_assignment", "expired", "invalid_config"):
                                current = self.assignments.get(key[0])
                                if current and current["assignment_epoch"] == key[1]:
                                    self._stop_camera(key[0])
                            elif owns(self.authority, *key):
                                self.sent[key] = max(self.sent.get(key, 0), pending[key])
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logging.getLogger("camera_ai_service").warning(
                    "AI data delivery failed: %s; waiting for the next report cycle", type(exc).__name__)
            await asyncio.sleep(self.settings.cluster_report_interval)

    async def _watchdog_loop(self):
        while self.running:
            now = time.monotonic()
            for cid, record in list(self.assignments.items()):
                if not owns(self.authority, cid, record["assignment_epoch"]):
                    self._stop_camera(cid)
            while True:
                try:
                    event = self.events.get_nowait()
                except queue.Empty:
                    break
                cid, epoch = event["camera_id"], event["assignment_epoch"]
                current = self.assignments.get(cid)
                if current and current["assignment_epoch"] == epoch:
                    self._forget(cid)
                    self.rejected[cid] = max(self.rejected.get(cid, 0), epoch)
            for index, process in enumerate(self.processes):
                stuck = any(now - start > self.settings.cluster_camera_stop_timeout and self.assignments[cid]["process"] == index
                            for cid, start in self.stopping.items() if cid in self.assignments)
                if not process.is_alive() or stuck:
                    if process.is_alive():
                        process.terminate()
                    await asyncio.to_thread(process.join, 3)
                    for cid, record in list(self.assignments.items()):
                        if record["process"] == index:
                            epoch = record["assignment_epoch"]
                            self.rejected[cid] = max(self.rejected.get(cid, 0), epoch)
                            self._forget(cid)
                    self._spawn_capture(index)
            busy = self.health.get("busy_since", 0)
            model_timeout = not self.health.get("ready") and now - self.model_started > self.settings.cluster_model_start_timeout
            if not self.detector.is_alive() or model_timeout or (busy and now - busy > self.settings.cluster_inference_timeout):
                self.health["ready"] = False
                for cid in list(self.assignments):
                    self._stop_camera(cid)
                if self.detector.is_alive():
                    self.detector.terminate()
                await asyncio.to_thread(self.detector.join, 3)
                await asyncio.sleep(self.settings.cluster_process_restart_delay)
                self._spawn_detector()
            await asyncio.sleep(0.1)

    def _forget(self, cid):
        self.authority.pop(cid, None)
        record = self.assignments.pop(cid, None)
        self.stopping.pop(cid, None)
        if record:
            key = (cid, record["assignment_epoch"])
            self.frames.pop(key, None)
            self.results.pop(key, None)
            self.sent.pop(key, None)

    async def stop(self):
        try:
            await self._stop()
        finally:
            self.worker_lock.close()

    async def _stop(self):
        self.running = False
        for task in self.tasks:
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        if self.manager:
            self.authority.clear()
            self.stop_detector.set()
            for commands in self.commands:
                commands.put({"action": "SHUTDOWN"})
            for process in self.processes + ([self.detector] if self.detector else []):
                await asyncio.to_thread(process.join, 2)
                if process.is_alive():
                    process.terminate()
                    await asyncio.to_thread(process.join, 3)
            for commands in self.commands + [self.events]:
                commands.cancel_join_thread()
                commands.close()
            self.manager.shutdown()
            self.manager = None
        if self.client:
            await self.client.aclose()
            self.client = None
        self.tasks.clear()
