"""Check model identity, engine prerequisites and readiness using a fake backend."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from shared.model_runtime import (ModelConfigurationError, ModelRuntimeUnavailable,
                                  SERVICE_ROOT, load_detection_model, resolve_model_path)


class ModelRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.engine = self.root / "reference.engine"
        self.engine.write_bytes(b"fake engine; never deserialized by these tests")
        self.checkpoint = self.root / "reference.pt"
        self.checkpoint.write_bytes(b"fake checkpoint")
        # No .to(), .names or __call__: exported models must use predict().
        self.model = Mock(spec=["predict"])
        self.model.predict.return_value = [SimpleNamespace(names={0: "hang"})]
        self.cuda = self.enter_patch(patch("torch.cuda.is_available", return_value=True))
        self.load = self.enter_patch(patch("ultralytics.YOLO", return_value=self.model))
        self.tensor_rt = self.enter_patch(patch("shared.model_runtime.importlib.import_module", return_value=Mock()))

    def enter_patch(self, context):
        value = context.start()
        self.addCleanup(context.stop)
        return value

    def test_engine_initializes_on_gpu_with_reference_prediction_options(self):
        model, device = load_detection_model(self.engine)
        self.assertIs(model, self.model)
        self.assertEqual(device, 0)
        self.load.assert_called_once_with(str(self.engine.resolve()), task="detect")
        self.tensor_rt.assert_called_once_with("tensorrt")
        args, options = self.model.predict.call_args
        self.assertEqual(options, {"device": 0, "conf": 0.4, "iou": 0.45,
                                   "imgsz": [480, 640], "classes": [0], "verbose": False})
        self.assertEqual(len(args[0]), 1)
        self.assertEqual(args[0][0].shape, (480, 640, 3))
        self.assertEqual(args[0][0].dtype, np.uint8)

    def test_engine_rejects_cpu_environment_before_loading_any_weights(self):
        self.cuda.return_value = False
        with self.assertRaisesRegex(ModelRuntimeUnavailable, "CUDA-enabled PyTorch"):
            load_detection_model(self.engine)
        self.load.assert_not_called()
        self.model.predict.assert_not_called()

    def test_engine_rejects_missing_tensorrt_without_installing_or_falling_back(self):
        self.tensor_rt.side_effect = ImportError("No module named tensorrt")
        with self.assertRaisesRegex(ModelRuntimeUnavailable, "TensorRT is unavailable"):
            load_detection_model(self.engine)
        self.load.assert_not_called()

    def test_correct_checkpoint_can_run_on_cpu(self):
        self.cuda.return_value = False
        model, device = load_detection_model(self.checkpoint)
        self.assertIs(model, self.model)
        self.assertEqual(device, "cpu")
        self.assertEqual(self.model.predict.call_args.kwargs["device"], "cpu")
        self.tensor_rt.assert_not_called()

    def test_old_two_class_checkpoint_cannot_be_accepted_as_reference_model(self):
        self.model.predict.return_value = [SimpleNamespace(names={0: "hang", 1: "qr"})]
        with self.assertRaisesRegex(ModelConfigurationError, "Unexpected model classes"):
            load_detection_model(self.checkpoint)

    def test_invalid_engine_fails_during_startup_warmup(self):
        self.model.predict.side_effect = RuntimeError("engine deserialization failed")
        with self.assertRaisesRegex(RuntimeError, "deserialization failed"):
            load_detection_model(self.engine)

    def test_missing_weights_never_trigger_a_download(self):
        with self.assertRaises(FileNotFoundError):
            load_detection_model(self.root / "missing.engine")
        self.load.assert_not_called()

    def test_relative_weights_are_resolved_against_ai_service(self):
        self.assertEqual(resolve_model_path("weights/ModelHN_170926.engine"),
                         (SERVICE_ROOT / "weights/ModelHN_170926.engine").resolve())


class ModelHealthTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_exposes_startup_failure_reason(self):
        from fastapi import HTTPException
        import main

        service = SimpleNamespace(manager=True, ready=lambda: False,
                                  health={"error_type": "ModelRuntimeUnavailable",
                                          "error_message": "CUDA-enabled PyTorch is required"})
        with patch.object(main.app.state, "ai_service", service, create=True), \
                patch.object(main, "settings", SimpleNamespace(cluster_enabled=True)):
            with self.assertRaises(HTTPException) as raised:
                await main.health_check()
        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.detail, "CUDA-enabled PyTorch is required")


if __name__ == "__main__":
    unittest.main()
