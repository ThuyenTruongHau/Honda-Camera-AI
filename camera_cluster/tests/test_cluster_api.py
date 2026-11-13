"""Control API works without credentials; ownership still follows leases."""
import unittest
from unittest.mock import patch

import httpx
from core.config import Settings
from main import app
from repositories.cluster_repository import RamClusterRepository
from services.cluster_runtime import ClusterRuntime


class ClusterAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.now = 1000.0
        self.settings = Settings(_env_file=None, cluster_recovery_delay=0)
        repository = RamClusterRepository([{
            "_id": "cam1", "camera_name": "Offline test camera", "camera_path": "rtsp://offline.test/stream",
            "config_version": 1, "group_id": "AF", "roi": [],
        }])
        self.runtime = ClusterRuntime(repository, self.settings, clock=lambda: self.now)
        await self.runtime.start(background=False)
        self.runtime_patch = patch("api.cluster.get_runtime", return_value=self.runtime)
        self.runtime_patch.start()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()
        self.runtime_patch.stop()
        await self.runtime.stop()

    async def test_register_and_heartbeat_without_authorization(self):
        registered = await self.client.post("/cluster/register", json={"worker_id": "NEW-AI"})
        self.assertEqual(registered.status_code, 200)
        self.assertEqual(registered.json()["worker_id"], "NEW-AI")
        heartbeat = await self.client.post("/cluster/heartbeat", json={"worker_id": "NEW-AI", "ready": True, "cameras": []})
        self.assertEqual(heartbeat.status_code, 200)
        await self.runtime.tick()
        assigned = await self.client.post("/cluster/heartbeat", json={"worker_id": "NEW-AI", "ready": True, "cameras": []})
        self.assertEqual(assigned.json()["assignments"][0]["camera_id"], "cam1")

    async def test_state_needs_no_worker_query_or_authorization(self):
        response = await self.client.get("/cluster/state")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["cameras"][0]["camera_id"], "cam1")

    async def test_unregistered_heartbeat_still_rejected(self):
        response = await self.client.post("/cluster/heartbeat", json={"worker_id": "unknown", "ready": True})
        self.assertEqual(response.status_code, 409)

    async def test_worker_id_still_required(self):
        for payload in ({}, {"worker_id": ""}):
            response = await self.client.post("/cluster/register", json=payload)
            self.assertEqual(response.status_code, 422)

    async def test_wrong_epoch_cannot_extend_lease(self):
        await self.client.post("/cluster/register", json={"worker_id": "AI-01"})
        await self.client.post("/cluster/heartbeat", json={"worker_id": "AI-01", "ready": True})
        await self.runtime.tick()
        row = await self.runtime.repo.get_camera("cam1")
        self.now += 1
        response = await self.client.post("/cluster/heartbeat", json={
            "worker_id": "AI-01", "ready": True,
            "cameras": [{"camera_id": "cam1", "assignment_epoch": row["assignment_epoch"] + 1}],
        })
        self.assertEqual(response.status_code, 200)
        unchanged = await self.runtime.repo.get_camera("cam1")
        self.assertEqual(unchanged["lease_expires_at"], row["lease_expires_at"])
        response = await self.client.post("/cluster/heartbeat", json={
            "worker_id": "AI-01", "ready": True,
            "cameras": [{"camera_id": "cam1", "assignment_epoch": row["assignment_epoch"]}],
        })
        self.assertEqual(response.status_code, 200)
        renewed = await self.runtime.repo.get_camera("cam1")
        self.assertEqual(renewed["lease_expires_at"], self.now + self.settings.cluster_lease_seconds)

    async def test_runtime_unavailable_still_returns_503(self):
        self.runtime.healthy = False
        response = await self.client.post("/cluster/register", json={"worker_id": "AI-01"})
        self.assertEqual(response.status_code, 503)


if __name__ == "__main__":
    unittest.main()
