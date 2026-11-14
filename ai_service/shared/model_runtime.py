"""Load and verify the detection backend before either runtime accepts cameras."""
import hashlib
import importlib
import logging
from pathlib import Path

from core.inference_config import EXPECTED_CLASS_NAMES, FRAME_SIZE, INFERENCE_CONFIG


SERVICE_ROOT = Path(__file__).resolve().parents[1]
logger = logging.getLogger("camera_ai_service")


class ModelRuntimeUnavailable(RuntimeError):
    """The configured backend cannot run in this Python environment."""


class ModelConfigurationError(RuntimeError):
    """The configured weights do not match the application's detection classes."""


def resolve_model_path(weight_path):
    path = Path(weight_path).expanduser()
    return (path if path.is_absolute() else SERVICE_ROOT / path).resolve()


def load_detection_model(weight_path):
    import numpy as np
    import torch

    path = resolve_model_path(weight_path)
    if not path.is_file():
        raise FileNotFoundError(f"AI model not found: {path}; check WEIGHT_PATH")

    cuda_available = torch.cuda.is_available()
    device = 0 if cuda_available else "cpu"
    if path.suffix.lower() == ".engine":
        if not cuda_available:
            raise ModelRuntimeUnavailable(
                "TensorRT .engine requires CUDA-enabled PyTorch and an available NVIDIA GPU; "
                f"this interpreter has torch={torch.__version__}, cuda_available=False. "
                "Install the GPU runtime; the service will not fall back to another model."
            )
        try:
            importlib.import_module("tensorrt")
        except (ImportError, OSError) as exc:
            raise ModelRuntimeUnavailable(
                "TensorRT is unavailable in this Python environment; install a TensorRT runtime "
                "compatible with the configured .engine and its CUDA dependencies."
            ) from exc

    checksum = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            checksum.update(block)
    logger.info("MODEL_LOADING weights=%s sha256=%s device=%s options=%s",
                path, checksum.hexdigest(), device, INFERENCE_CONFIG)
    from ultralytics import YOLO

    model = YOLO(str(path), task="detect")
    # Initialize exported backends with the actual prediction device/options.
    # Reading model.names before predict() can initialize an engine too early.
    frame = np.zeros((FRAME_SIZE[1], FRAME_SIZE[0], 3), dtype=np.uint8)
    predictions = model.predict([frame], device=device, **INFERENCE_CONFIG)
    if len(predictions) != 1:
        raise ModelConfigurationError("Model warmup must return one result for one frame")
    names = predictions[0].names
    if names != EXPECTED_CLASS_NAMES:
        raise ModelConfigurationError(
            f"Unexpected model classes: expected={EXPECTED_CLASS_NAMES}, actual={names}; "
            "check WEIGHT_PATH. The reference ModelHN_170926 has only class 0='hang'."
        )
    logger.info("MODEL_READY weights=%s device=%s classes=%s", path, device, names)
    return model, device
