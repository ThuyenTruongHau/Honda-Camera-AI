"""Exercise exported-model inference without loading a TensorRT engine or cameras."""
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from services.cluster_detector import detector_process
from services.yolo_detector import YoloDetector


# Keep the reference options explicit so changes to service defaults cannot
# silently change the prediction contract established by test_model_engine.py.
REFERENCE_OPTIONS = {
    "device": 0,
    "conf": 0.4,
    "iou": 0.45,
    "imgsz": [480, 640],
    "classes": [0],
    "verbose": False,
}
ROI = {"name": "start_123", "x1": 10, "y1": 20, "x2": 100, "y2": 120}


def prediction(boxes):
    return SimpleNamespace(names={0: "hang"}, boxes=SimpleNamespace(
        data=np.array(boxes, dtype=float).reshape(-1, 6)))


class LegacyInferenceTests(unittest.TestCase):
    def test_exported_model_predicts_batch_with_reference_options(self):
        # An exported model supports predict(), but has no PyTorch .to() or
        # eager .names access. Either operation must fail this regression test.
        model = Mock(spec=["predict"])
        model.predict.return_value = [prediction([[10, 20, 100, 120, .9, 0]]), prediction([])]
        frames = [np.zeros((480, 640, 3), dtype=np.uint8) for _ in range(2)]
        with patch("services.yolo_detector.load_detection_model", return_value=(model, 0)) as load:
            detector = YoloDetector({}, {}, "custom.engine", draw=False)
            detector._load_model()
            results = detector._detect(frames)

        self.assertIs(detector.model, model)
        load.assert_called_once_with("custom.engine")
        model.predict.assert_called_once_with(frames, **REFERENCE_OPTIONS)
        self.assertIs(results, model.predict.return_value)

        detector.evidence = Mock()
        batch = [{"camera_name": f"cam{i}", "group_id": "AF", "captured_at": 99,
                  "rois": [{**ROI, "name": str(123 + i)}]} for i in range(2)]
        detector._process_results(results, batch, frames)
        self.assertEqual(detector.target_dict["123"]["label"], "hang")
        self.assertEqual(detector.target_dict["124"]["label"], "trong")
        self.assertEqual(detector.evidence.record.call_count, 2)

    def test_pytorch_model_keeps_cpu_fallback(self):
        model = Mock(spec=["predict"])
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        with patch("services.yolo_detector.load_detection_model", return_value=(model, "cpu")):
            detector = YoloDetector({}, {}, "custom.pt", draw=False)
            detector._load_model()
            detector._detect(frame)
        model.predict.assert_called_once_with(frame, **{**REFERENCE_OPTIONS, "device": "cpu"})

    def test_failed_load_does_not_leave_a_usable_model(self):
        with patch("services.yolo_detector.load_detection_model", side_effect=RuntimeError("invalid weights")):
            detector = YoloDetector({}, {}, "invalid.engine", draw=False)
            detector._load_model()
        self.assertIsNone(detector.model)


class ClusterInferenceTests(unittest.TestCase):
    def setUp(self):
        self.stop = threading.Event()
        self.health = {}
        self.results = {}
        self.authority = {f"cam{i}": {"epoch": 2, "deadline": time.monotonic() + 30} for i in range(2)}
        self.frames = {
            (f"cam{i}", 2): {"camera_id": f"cam{i}", "assignment_epoch": 2,
                            "captured_at": time.time(), "group_id": "AF",
                            "roi": [{**ROI, "name": f"start_{123 + i}"}],
                            "frame": np.zeros((480, 640, 3), dtype=np.uint8)}
            for i in range(2)
        }
        self.config = {"weight_path": "custom.engine", "cluster_max_frame_age": 3,
                       "cluster_inference_batch_size": 16}
        self.model = Mock(spec=["predict"])

    def run_detector(self):
        with patch("services.cluster_detector.load_detection_model", return_value=(self.model, 0)) as load, \
                patch("services.cluster_detector.setup_logger", return_value=Mock()), \
                patch("services.cluster_detector.DetectionEvidence"):
            detector_process(self.authority, self.frames, self.results, self.health, self.stop, self.config)
        load.assert_called_once_with("custom.engine")

    def test_verified_model_can_start_before_cameras_are_assigned(self):
        self.stop.set()
        self.run_detector()
        self.assertFalse(self.health["error"])
        self.model.predict.assert_not_called()

    def test_batch_uses_reference_options_and_publishes_matching_camera_labels(self):
        def predict(frames, **options):
            self.assertTrue(self.health["ready"])
            self.assertEqual(options, REFERENCE_OPTIONS)
            self.assertIs(frames[0], self.frames[("cam0", 2)]["frame"])
            self.assertIs(frames[1], self.frames[("cam1", 2)]["frame"])
            self.stop.set()
            return [prediction([[10, 20, 100, 120, .9, 0]]), prediction([])]

        self.model.predict.side_effect = predict
        self.run_detector()
        self.model.predict.assert_called_once()
        self.assertFalse(self.health["error"])
        self.assertEqual(self.results[("cam0", 2)]["points"], {"123": {"label": "hang", "group_id": "AF"}})
        self.assertEqual(self.results[("cam1", 2)]["points"], {"124": {"label": "trong", "group_id": "AF"}})

    def test_backend_failure_is_reported_without_publishing_empty_labels(self):
        self.model.predict.side_effect = RuntimeError("engine initialization failed")
        self.run_detector()
        self.assertTrue(self.health["error"])
        self.assertFalse(self.health["ready"])
        self.assertEqual(self.health["error_type"], "RuntimeError")
        self.assertEqual(self.results, {})

    def test_startup_failure_keeps_runtime_unready_and_reports_reason(self):
        from shared.model_runtime import ModelRuntimeUnavailable
        with patch("services.cluster_detector.load_detection_model",
                   side_effect=ModelRuntimeUnavailable("CUDA-enabled PyTorch is required")), \
                patch("services.cluster_detector.setup_logger", return_value=Mock()), \
                patch("services.cluster_detector.DetectionEvidence"):
            detector_process(self.authority, self.frames, self.results, self.health, self.stop, self.config)
        self.assertFalse(self.health["ready"])
        self.assertTrue(self.health["error"])
        self.assertEqual(self.health["error_type"], "ModelRuntimeUnavailable")
        self.assertIn("CUDA-enabled PyTorch", self.health["error_message"])
        self.assertEqual(self.results, {})


if __name__ == "__main__":
    unittest.main()
