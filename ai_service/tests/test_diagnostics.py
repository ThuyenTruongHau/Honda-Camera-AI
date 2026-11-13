import asyncio
import json
import logging
import multiprocessing as mp
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from services.cluster_capture import capture_camera, capture_process
from services.cluster_detector import detector_process, labels_for_rois, publish_result
from core.roi_geometry import roi_overlap_ratio
from services.cluster_runtime import ClusterAIService
from shared.diagnostics import DetectionEvidence, camera_summary
from shared.logger import RedactStreams, setup_logger


ROI = {"name": "start_123", "x1": 10, "y1": 20, "x2": 100, "y2": 120}


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.records = [{"camera_id": "cam1", "camera_path": "rtsp://secret", "assignment_epoch": 2, "roi": [ROI]}]
        self.capture = {("cam1", 2): {"status": "STREAMING", "last_frame_at": 99}}
        self.results = {("cam1", 2): {"captured_at": 99, "points": {"123": {"label": "hang"}}}}

    def test_fresh_and_stale_are_distinct(self):
        fresh = camera_summary(self.records, self.capture, self.results, 3, now=100)
        self.assertTrue(fresh["all_connected"])
        self.assertTrue(fresh["all_detecting"])
        stale = camera_summary(self.records, self.capture, self.results, 3, now=105)
        self.assertFalse(stale["all_connected"])
        self.assertFalse(stale["all_detecting"])
        self.assertNotIn("camera_path", json.dumps(fresh))

    def test_open_without_frame_is_not_connected(self):
        self.capture[("cam1", 2)] = {"status": "CONNECTING"}
        self.assertFalse(camera_summary(self.records, self.capture, self.results, 3, now=100)["all_connected"])

    def test_read_failure_invalidates_fresh_frame(self):
        self.capture[("cam1", 2)]["status"] = "READ_FAILED"
        self.assertFalse(camera_summary(self.records, self.capture, self.results, 3, now=100)["all_detecting"])

    def test_new_epoch_cannot_reuse_previous_connection(self):
        self.records[0]["assignment_epoch"] = 3
        self.assertFalse(camera_summary(self.records, self.capture, self.results, 3, now=100)["all_connected"])

    def test_empty_assignment_does_not_claim_success(self):
        summary = camera_summary([], {}, {}, 3)
        self.assertFalse(summary["all_connected"])
        self.assertFalse(summary["all_detecting"])

    def test_expired_authority_cannot_claim_connection(self):
        service = ClusterAIService(SimpleNamespace(worker_id="test", cluster_max_frame_age=3))
        service.assignments = {"cam1": self.records[0]}
        service.camera_health = self.capture
        service.results = self.results
        service.authority = {"cam1": {"epoch": 2, "deadline": 0}}
        with patch.object(service, "ready", return_value=True):
            report = service.diagnostics()
        self.assertFalse(report["all_connected"])
        self.assertEqual(report["cameras"][0]["status"], "STOPPING")


class EvidenceTests(unittest.TestCase):
    def test_snapshot_has_normalized_label_and_matching_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = DetectionEvidence({"debug_save_snapshots": True, "debug_snapshot_dir": directory})
            frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            evidence.record("../cam1", frame, [[20, 30, 90, 110, .9, 0], [10, 20, 100, 120, .4, 0]], {0: "hang"},
                            [ROI], {"123": "hang"}, 99, normalize_roi_names=True, camera_name="cam02")
            files = list(Path(directory).glob("*.json"))
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].name, "cam02_000001.json")
            data = json.loads(files[0].read_text(encoding="utf-8"))
            self.assertEqual(data["camera_name"], "cam02")
            self.assertEqual(data["labels"], {"123": "hang"})
            self.assertNotIn("omitted_roi_names", data)
            self.assertAlmostEqual(data["roi_hang_overlap_ratio"]["123"], 5600 / 9000)
            self.assertEqual(data["roi_overlap_threshold"], .5)
            self.assertNotIn("roi_without_box_center", data)
            image = cv2.imread(str(files[0].with_suffix(".jpg")))
            self.assertEqual(image.shape, frame.shape)
            np.testing.assert_array_equal(frame, np.zeros_like(frame))
            self.assertGreater(int(image[20, 10, 2]), 150)  # red ROI for hang
            with patch("cv2.imencode") as encode:
                evidence.record("../cam1", frame, [], {}, [ROI], {}, 100)
                encode.assert_not_called()

    def test_snapshot_sequence_preserves_previous_images_across_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            config = {"debug_save_snapshots": True, "debug_snapshot_dir": directory, "debug_snapshot_interval": 1}
            frame = np.zeros((20, 20, 3), dtype=np.uint8)
            evidence = DetectionEvidence(config)
            for observed_at in (1, 2, 3):
                if observed_at == 3:
                    evidence = DetectionEvidence(config)
                with patch("shared.diagnostics.time.monotonic", return_value=observed_at):
                    evidence.record("camera-id", frame, [], {}, [], {}, observed_at, camera_name="cam02")
            root = Path(directory)
            self.assertEqual(sorted(p.name for p in root.glob("*.jpg")),
                             ["cam02_000001.jpg", "cam02_000002.jpg", "cam02_000003.jpg"])
            for index in (1, 2, 3):
                data = json.loads((root / f"cam02_{index:06d}.json").read_text(encoding="utf-8"))
                self.assertEqual(data["captured_at"], index)
                self.assertEqual(data["image"], f"cam02_{index:06d}.jpg")
            self.assertEqual(list(root.glob("*.tmp")), [])

    def test_snapshot_name_cannot_escape_output_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = DetectionEvidence({"debug_save_snapshots": True, "debug_snapshot_dir": directory})
            evidence.record("camera-id", np.zeros((20, 20, 3), dtype=np.uint8), [], {}, [], {}, 1,
                            camera_name="../cam02/../../")
            self.assertEqual(sorted(p.name for p in Path(directory).iterdir()),
                             ["cam02_000001.jpg", "cam02_000001.json"])

    def test_snapshot_sequence_respects_metadata_without_image(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing = root / "cam02_000010.json"
            existing.write_text("{}", encoding="utf-8")
            evidence = DetectionEvidence({"debug_save_snapshots": True, "debug_snapshot_dir": directory})
            evidence.record("camera-id", np.zeros((20, 20, 3), dtype=np.uint8), [], {}, [], {}, 1, camera_name="cam02")
            self.assertTrue((root / "cam02_000011.jpg").is_file())
            self.assertEqual(existing.read_text(encoding="utf-8"), "{}")

    def test_failed_snapshot_does_not_break_detection(self):
        evidence = DetectionEvidence({"debug_save_snapshots": True})
        with patch("shared.diagnostics.Path.mkdir", side_effect=PermissionError):
            evidence.record("cam1", np.zeros((720, 1280, 3), dtype=np.uint8), [], {}, [ROI], {"123": "trong"}, 99)
        self.assertIn("cam1", evidence.last_image)

    def test_weak_or_unknown_boxes_default_to_empty_and_reserved_roi_excluded(self):
        reserved = {**ROI, "name": "10001546"}
        names = {0: "hang", 1: "unknown"}
        self.assertEqual(labels_for_rois([], names, [ROI, reserved]), {"123": "trong"})
        self.assertEqual(labels_for_rois([[20, 30, 90, 110, .9, 0]], names, [ROI, reserved]), {"123": "hang"})
        self.assertEqual(labels_for_rois([[20, 30, 90, 110, .6, 0]], names, [ROI]), {"123": "trong"})
        self.assertEqual(labels_for_rois([[20, 30, 90, 110, .9, 1]], names, [ROI]), {"123": "trong"})

    def test_confident_hang_survives_other_boxes_in_any_order(self):
        from itertools import permutations
        names = {0: "hang", 1: "trong", 2: "unknown"}
        strong = [20, 30, 90, 110, .95, 0]
        for extra in ([20, 30, 90, 110, .4, 0],
                      [20, 30, 90, 110, .4, 1],
                      [20, 30, 90, 110, .95, 1],
                      [20, 30, 90, 110, .95, 2]):
            for boxes in permutations([strong, extra]):
                with self.subTest(extra=extra, boxes=boxes):
                    self.assertEqual(labels_for_rois(boxes, names, [ROI]), {"123": "hang"})

    def test_small_box_with_center_inside_roi_is_empty(self):
        self.assertEqual(labels_for_rois([[20, 30, 60, 90, .95, 0]], {0: "hang"}, [ROI]), {"123": "trong"})

    def test_roi_overlap_threshold_is_strictly_above_half(self):
        roi = {"name": "123", "x1": 0, "y1": 0, "x2": 100, "y2": 100}
        for right, expected in ((49.99, "trong"), (50, "trong"), (50.01, "hang")):
            with self.subTest(right=right):
                boxes = [[0, 0, right, 100, .95, 0]]
                self.assertEqual(labels_for_rois(boxes, {0: "hang"}, [roi]), {"123": expected})

    def test_center_outside_roi_can_still_cover_majority(self):
        roi = {"name": "123", "x1": 0, "y1": 0, "x2": 100, "y2": 100}
        self.assertEqual(labels_for_rois([[-100, 0, 60, 100, .95, 0]], {0: "hang"}, [roi]), {"123": "hang"})

    def test_overlap_uses_roi_area_rather_than_iou_or_entire_box_area(self):
        roi = {"name": "123", "x1": 0, "y1": 0, "x2": 100, "y2": 100}
        for box, expected in (([-100, -100, 200, 200, .95, 0], "hang"),
                              ([80, 0, 200, 100, .95, 0], "trong"),
                              ([100, 0, 200, 100, .95, 0], "trong"),
                              ([110, 0, 200, 100, .95, 0], "trong")):
            with self.subTest(box=box):
                self.assertEqual(labels_for_rois([box], {0: "hang"}, [roi]), {"123": expected})

    def test_separate_small_boxes_do_not_add_up_to_majority(self):
        roi = {"name": "123", "x1": 0, "y1": 0, "x2": 100, "y2": 100}
        boxes = [[0, 0, 30, 100, .95, 0], [70, 0, 100, 100, .95, 0]]
        self.assertEqual(labels_for_rois(boxes, {0: "hang"}, [roi]), {"123": "trong"})

    def test_overlap_handles_invalid_rectangles_without_dividing_by_zero(self):
        for roi in ({**ROI, "x2": ROI["x1"]}, {**ROI, "y2": ROI["y1"]},
                    {**ROI, "x2": 0, "y2": 0}):
            with self.subTest(roi=roi):
                self.assertEqual(roi_overlap_ratio([0, 0, 200, 200], roi), 0)

    def test_single_class_model_loads_without_class_warning(self):
        model = Mock(names={0: "hang"})
        logger = Mock()
        health = {}
        stop = Mock()
        stop.is_set.return_value = True
        modules = {
            "ultralytics": SimpleNamespace(YOLO=Mock(return_value=model), __version__="test"),
            "torch": SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False), __version__="test"),
        }
        with patch.dict(sys.modules, modules), patch("services.cluster_detector.setup_logger", return_value=logger):
            detector_process({}, {}, {}, health, stop, {"weight_path": "unused-test-model.pt"})
        model.to.assert_called_once_with("cpu")
        logger.warning.assert_not_called()
        logger.error.assert_not_called()
        self.assertFalse(health["error"])

    def test_detector_passes_catalog_camera_name_to_snapshot_writer(self):
        model = Mock(names={0: "hang"})
        model.return_value = [SimpleNamespace(boxes=None, names={0: "hang"})]
        writer = Mock()
        stop = Mock()
        stop.is_set.side_effect = [False, True]
        item = {"camera_id": "camera-id", "camera_name": "cam02", "assignment_epoch": 1,
                "group_id": "AF", "captured_at": time.time(), "roi": [ROI],
                "frame": np.zeros((20, 20, 3), dtype=np.uint8)}
        modules = {
            "ultralytics": SimpleNamespace(YOLO=Mock(return_value=model), __version__="test"),
            "torch": SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False), __version__="test"),
        }
        authority = {"camera-id": {"epoch": 1, "deadline": time.monotonic() + 10}}
        with patch.dict(sys.modules, modules), \
                patch("services.cluster_detector.setup_logger"), \
                patch("services.cluster_detector.select_batch", return_value=[item]), \
                patch("services.cluster_detector.DetectionEvidence", return_value=writer):
            detector_process(authority, {}, {}, {}, stop, {"weight_path": "unused-test-model.pt"})
        writer.record.assert_called_once()
        self.assertEqual(writer.record.call_args.kwargs["camera_name"], "cam02")

    def test_business_payload_keeps_both_occupied_and_weak_only_rois(self):
        from schemas.detection import build_logic_payload
        other = {"name": "end_456", "x1": 200, "y1": 20, "x2": 300, "y2": 120}
        boxes = [[20, 30, 90, 110, .95, 0], [20, 30, 90, 110, .4, 0], [220, 30, 290, 110, .4, 0]]
        labels = labels_for_rois(boxes, {0: "hang"}, [ROI, other])
        item = {"camera_id": "cam1", "assignment_epoch": 2, "captured_at": time.time(), "group_id": "AF"}
        results = {}
        publish_result(item, labels, {"cam1": {"epoch": 2, "deadline": time.monotonic() + 10}}, results)
        self.assertEqual(build_logic_payload("worker", list(results.values())),
                         {"123": {"label": "hang", "group_id": "AF"},
                          "456": {"label": "trong", "group_id": "AF"}})

    def test_snapshot_does_not_draw_labels_for_excluded_points(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = DetectionEvidence({"debug_save_snapshots": True, "debug_snapshot_dir": directory})
            reserved = {**ROI, "name": "10001546"}
            with patch("cv2.putText", wraps=cv2.putText) as put_text:
                evidence.record("cam1", np.zeros((720, 1280, 3), dtype=np.uint8), [], {},
                                [ROI, reserved], {"123": "trong"}, 99, normalize_roi_names=True)
            self.assertEqual([call.args[1] for call in put_text.call_args_list], ["start_123: trong"])

    def test_observation_metadata_does_not_change_business_payload(self):
        from schemas.detection import build_logic_payload
        item = {"camera_id": "cam1", "assignment_epoch": 2, "captured_at": time.time(), "group_id": "AF"}
        results = {}
        publish_result(item, {"123": "hang"}, {"cam1": {"epoch": 2, "deadline": time.monotonic() + 10}}, results)
        self.assertEqual(build_logic_payload("worker", list(results.values())), {"123": {"label": "hang", "group_id": "AF"}})


class CaptureTests(unittest.TestCase):
    def exercise(self, cap, captured_frames=None):
        statuses = []
        class Health(dict):
            def __setitem__(self, key, value):
                statuses.append(value["status"])
                super().__setitem__(key, value)
        class Frames(dict):
            def __setitem__(self, key, value):
                if captured_frames is not None:
                    captured_frames.append(value)
                super().__setitem__(key, value)
        stop = threading.Event()
        stop.wait = lambda delay: stop.set()
        health = Health()
        assignment = {"camera_id": "cam1", "camera_name": "cam02", "assignment_epoch": 2, "camera_path": "rtsp://user:secret@camera", "roi": []}
        config = {"target_fps": 5, "cluster_capture_open_timeout_ms": 100,
                  "cluster_capture_read_timeout_ms": 100, "cluster_source_retry_delay": .01}
        with patch("cv2.VideoCapture", return_value=cap):
            capture_camera(assignment, {"cam1": {"epoch": 2, "deadline": time.monotonic() + 20}}, Frames(),
                           stop, config, threading.Semaphore(1), health)
        cap.release.assert_called()
        return statuses

    def test_open_failure_is_distinguished_from_streaming(self):
        cap = Mock()
        cap.isOpened.return_value = False
        self.assertEqual(self.exercise(cap), ["CONNECTING", "OPEN_FAILED", "STOPPED"])

    def test_first_frame_then_read_failure(self):
        cap = Mock()
        cap.isOpened.return_value = True
        cap.read.side_effect = [(True, np.zeros((50, 50, 3), dtype=np.uint8)), (False, None)]
        self.assertEqual(self.exercise(cap), ["CONNECTING", "STREAMING", "READ_FAILED", "STOPPED"])

    def test_capture_keeps_catalog_camera_name_on_frame(self):
        cap = Mock()
        cap.isOpened.return_value = True
        cap.read.side_effect = [(True, np.zeros((50, 50, 3), dtype=np.uint8)), (False, None)]
        captured = []
        self.exercise(cap, captured)
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["camera_name"], "cam02")

    def test_capture_exception_is_visible(self):
        cap = Mock()
        cap.isOpened.side_effect = RuntimeError("rtsp://user:secret@camera")
        self.assertEqual(self.exercise(cap), ["CONNECTING", "ERROR", "STOPPED"])


class LoggingTests(unittest.TestCase):
    def test_credentials_redacted_and_format_args_consumed(self):
        record = logging.LogRecord("test", logging.ERROR, __file__, 1,
                                   "failed %s", ("rtsp://user:secret@camera/path?token=private",), None)
        RedactStreams().filter(record)
        self.assertNotIn("secret", record.getMessage())
        self.assertNotIn("private", record.getMessage())

    def test_configured_level_and_pid_file(self):
        with tempfile.TemporaryDirectory() as directory:
            logger = setup_logger("diagnostics_test_logger", "DEBUG", log_dir=directory)
            try:
                self.assertEqual(logger.level, logging.DEBUG)
                logger.debug("check")
                self.assertTrue((Path(directory) / f"ai_{os.getpid()}.log").is_file())
            finally:
                for handler in list(logger.handlers):
                    logger.removeHandler(handler)
                    handler.close()


class ProbeTests(unittest.TestCase):
    def test_tcp_failure_is_visible_without_attempting_rtsp(self):
        from tools.check_cameras import probe
        args = SimpleNamespace(tcp_check=True, open_timeout_ms=100, read_timeout_ms=100, frames=3)
        with patch("tools.check_cameras.socket.create_connection", side_effect=TimeoutError), patch("cv2.VideoCapture") as capture:
            result = probe({"camera_path": "rtsp://user:secret@127.0.0.1:554/stream"}, args)
        self.assertEqual(result["error_type"], "TcpConnectFailed")
        self.assertEqual(result["tcp_error_type"], "TimeoutError")
        self.assertFalse(result["tcp_connected"])
        self.assertIn("elapsed_seconds", result)
        self.assertNotIn("secret", json.dumps(result))
        capture.assert_not_called()

    def test_catalog_probe_reads_frames_and_reports_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = str(root / "sample.avi")
            writer = cv2.VideoWriter(video, cv2.VideoWriter_fourcc(*"MJPG"), 5, (64, 48))
            self.assertTrue(writer.isOpened())
            for _ in range(4):
                writer.write(np.zeros((48, 64, 3), dtype=np.uint8))
            writer.release()
            catalog = root / "catalog.json"
            catalog.write_text(json.dumps({"cameras": [
                {"camera_id": "good", "camera_path": video},
                {"camera_id": "bad", "camera_path": str(root / "missing.avi")},
                {"camera_id": "disabled", "camera_path": "unused", "enabled": False}]}), encoding="utf-8")
            output = root / "report.json"
            process = subprocess.run([sys.executable, "tools/check_cameras.py", "--catalog", str(catalog),
                                      "--output", str(output)], capture_output=True, text=True, timeout=40)
            self.assertEqual(process.returncode, 1, process.stdout + process.stderr)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual((report["expected"], report["connected"]), (2, 1))
            self.assertEqual(report["cameras"][0]["frames_read"], 3)
            self.assertEqual(report["cameras"][1]["error_type"], "OpenFailed")
            self.assertNotIn("camera_path", output.read_text(encoding="utf-8"))


class SpawnTests(unittest.TestCase):
    def test_spawned_capture_writes_health_and_log_then_stops(self):
        ctx = mp.get_context("spawn")
        with tempfile.TemporaryDirectory() as directory, ctx.Manager() as manager:
            root = Path(directory)
            video = str(root / "sample.avi")
            writer = cv2.VideoWriter(video, cv2.VideoWriter_fourcc(*"MJPG"), 5, (64, 48))
            self.assertTrue(writer.isOpened())
            for _ in range(4):
                writer.write(np.zeros((48, 64, 3), dtype=np.uint8))
            writer.release()
            health, frames = manager.dict(), manager.dict()
            authority = manager.dict({"cam1": {"epoch": 2, "deadline": time.monotonic() + 30}})
            commands, events = ctx.Queue(), ctx.Queue()
            config = {"target_fps": 5, "cluster_capture_open_timeout_ms": 1000,
                      "cluster_capture_read_timeout_ms": 1000, "cluster_source_retry_delay": 1,
                      "cluster_start_concurrency": 1, "log_dir": str(root / "logs")}
            process = ctx.Process(target=capture_process, args=(commands, events, authority, frames, config, health))
            assignment = {"camera_id": "cam1", "assignment_epoch": 2, "camera_path": video, "roi": []}
            process.start()
            try:
                commands.put({"action": "START", "assignment": assignment})
                deadline = time.monotonic() + 10
                while health.get(("cam1", 2), {}).get("frames_received", 0) < 1 and time.monotonic() < deadline:
                    time.sleep(.05)
                self.assertGreaterEqual(health.get(("cam1", 2), {}).get("frames_received", 0), 1)
                authority.clear()
                commands.put({"action": "STOP", "assignment": assignment})
                self.assertEqual(events.get(timeout=5)["status"], "STOPPED")
                commands.put({"action": "SHUTDOWN"})
                process.join(5)
                self.assertFalse(process.is_alive())
                self.assertEqual(process.exitcode, 0)
                self.assertIn("RTSP_STREAMING", (root / "logs" / f"ai_{process.pid}.log").read_text(encoding="utf-8"))
            finally:
                if process.is_alive():
                    process.terminate()
                    process.join(5)
                for channel in (commands, events):
                    channel.close()
                    channel.join_thread()


class HTTPDiagnosticTests(unittest.IsolatedAsyncioTestCase):
    def service(self):
        settings = SimpleNamespace(worker_id="test", cluster_report_interval=1, cluster_max_frame_age=3,
                                   cluster_report_batch_size=32, ai_data_url="http://logic/ai-data",
                                   detection_log_interval=10, cluster_heartbeat_interval=3)
        service = ClusterAIService(settings)
        service.running = service.registered = True
        service.authority = {"cam1": {"epoch": 2, "deadline": time.monotonic() + 30}}
        service.results = {("cam1", 2): {"camera_id": "cam1", "assignment_epoch": 2,
                                        "captured_at": time.time(), "points": {"123": {"label": "hang", "group_id": "AF"}}}}
        return service

    async def run_report_once(self, service, response):
        import httpx
        async def finish(_):
            service.running = False
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response)) as client:
            service.data_client = client
            with patch("services.cluster_runtime.asyncio.sleep", side_effect=finish):
                await service._report_loop()

    async def test_delivery_http_failure_retains_status_and_unsent_frame(self):
        import httpx
        service = self.service()
        await self.run_report_once(service, httpx.Response(503))
        self.assertEqual(service.delivery_error["http_status"], 503)
        self.assertIsNone(service.last_delivery_ok)
        self.assertEqual(service.sent, {})

    async def test_delivery_success_marks_frame_and_clears_error(self):
        import httpx
        service = self.service()
        service.delivery_error = {"http_status": 503}
        await self.run_report_once(service, httpx.Response(200, json={"status": "success"}))
        self.assertIsNone(service.delivery_error)
        self.assertIsNotNone(service.last_delivery_ok)
        self.assertIn(("cam1", 2), service.sent)

    async def test_register_failure_is_visible(self):
        import httpx
        service = self.service()
        service.registered = False
        async def finish(_):
            service.running = False
        async with httpx.AsyncClient(base_url="http://cluster", transport=httpx.MockTransport(lambda request: httpx.Response(401))) as client:
            service.client = client
            with patch("services.cluster_runtime.asyncio.sleep", side_effect=finish):
                await service._control_loop()
        self.assertEqual(service.control_error["http_status"], 401)
        self.assertIsNone(service.last_control_ok)


class APITests(unittest.IsolatedAsyncioTestCase):
    async def test_endpoint_returns_current_worker_diagnostics(self):
        import httpx
        import main
        service = Mock()
        service.diagnostics.return_value = {"expected": 2, "connected": 1, "all_connected": False}
        with patch.object(main.app.state, "ai_service", service, create=True):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
                response = await client.get("/diagnostics/cameras")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["all_connected"])

    async def test_endpoint_returns_503_before_startup(self):
        import httpx
        import main
        with patch.object(main.app.state, "ai_service", None, create=True):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
                response = await client.get("/diagnostics/cameras")
        self.assertEqual(response.status_code, 503)


if __name__ == "__main__":
    unittest.main()
