"""YOLO prediction options shared by both runtimes, matching test_model_engine.py."""

FRAME_SIZE = (640, 480)  # OpenCV uses (width, height).
EXPECTED_CLASS_NAMES = {0: "hang"}

INFERENCE_CONFIG = {
    "conf": 0.4,
    "iou": 0.45,
    "imgsz": [480, 640],
    "classes": [0],
    "verbose": False,
}
