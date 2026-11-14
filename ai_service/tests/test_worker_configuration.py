import unittest
from unittest.mock import Mock, patch

from core.config import Settings
from services.cluster_runtime import ClusterAIService


class WorkerConfigurationTests(unittest.IsolatedAsyncioTestCase):
    def settings(self, **values):
        return Settings(_env_file=None, cluster_enabled=True, app_debug=False,
                        worker_id="AI-01", **values)

    async def test_cluster_settings_and_http_clients_need_only_worker_id(self):
        settings = self.settings()
        service = ClusterAIService(settings)
        context = Mock()
        manager = context.Manager.return_value
        manager.dict.side_effect = dict
        service.ctx = context
        # Exercise actual HTTP client setup without starting GPU/capture children.
        with patch.object(service, "_spawn_capture"), patch.object(service, "_spawn_detector"):
            try:
                await service._start()
                self.assertEqual(service.config["worker_id"], "AI-01")
                self.assertNotIn("authorization", service.client.headers)
                self.assertNotIn("authorization", service.data_client.headers)
            finally:
                await service._stop()

    async def test_empty_worker_id_still_rejected(self):
        with self.assertRaisesRegex(ValueError, "requires WORKER_ID"):
            Settings(_env_file=None, cluster_enabled=True, app_debug=False, worker_id=" ")


if __name__ == "__main__":
    unittest.main()
