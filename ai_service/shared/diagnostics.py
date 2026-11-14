"""Local evidence for operators; never added to the business HTTP payload."""
import re
import time
from pathlib import Path

from shared.logger import get_logger


def camera_summary(records, capture, detections, max_age, now=None):
    now = time.time() if now is None else now
    cameras = []
    for record in records:
        cid = record["camera_id"]
        key = (cid, record["assignment_epoch"]) if "assignment_epoch" in record else cid
        source = dict(capture.get(key, {}))
        result = dict(detections.get(key, {}))
        frame_at = source.get("last_frame_at")
        inferred_at = result.get("captured_at")
        frame_age = max(0, now - frame_at) if frame_at else None
        detection_age = max(0, now - inferred_at) if inferred_at else None
        connected = bool(source.get("status") == "STREAMING" and frame_age is not None and frame_age <= max_age)
        cameras.append({
            "camera_id": cid, "camera_name": record.get("camera_name", cid),
            "assignment_epoch": record.get("assignment_epoch"),
            "group_id": record.get("group_id"), "roi_count": len(record.get("roi", [])),
            **source, "connected": connected, "frame_age_seconds": frame_age,
            "detection_age_seconds": detection_age,
            "detecting": bool(connected and detection_age is not None and detection_age <= max_age),
            "points": result.get("points", {}),
        })
    connected = sum(c["connected"] for c in cameras)
    detecting = sum(c["detecting"] for c in cameras)
    return {"expected": len(cameras), "connected": connected, "detecting": detecting,
            "all_connected": bool(cameras) and connected == len(cameras),
            "all_detecting": bool(cameras) and detecting == len(cameras), "cameras": cameras}


class DetectionEvidence:
    def __init__(self, config):
        self.config = config
        self.last_image = {}
        self.image_sequence = {}

    def _reserve_image(self, directory, camera_name):
        # Use the same safe camera name for its folder and image filenames.
        prefix = re.sub(r"[^\w-]+", "_", str(camera_name)).strip("_")[:120] or "camera"
        directory = directory / prefix
        directory.mkdir(parents=True, exist_ok=True)
        key = (str(directory.resolve()), prefix)
        if key not in self.image_sequence:
            previous = [path.stem[len(prefix) + 1:] for path in directory.glob(f"{prefix}_*")]
            self.image_sequence[key] = max((int(number) for number in previous if number.isascii() and number.isdigit()), default=0)
        while True:
            self.image_sequence[key] += 1
            image_path = directory / f"{prefix}_{self.image_sequence[key]:06d}.jpg"
            temporary = image_path.with_suffix(".tmp")
            if image_path.exists() or image_path.with_suffix(".json").exists():
                continue
            try:
                # Reserve the name so another writer cannot choose the same image.
                with temporary.open("xb"):
                    pass
                if image_path.exists() or image_path.with_suffix(".json").exists():
                    temporary.unlink()
                    continue
                return image_path, temporary
            except FileExistsError:
                continue

    def record(self, camera_id, frame, boxes, names, rois, labels, captured_at, normalize_roi_names=False, camera_name=None, **context):
        camera_name = camera_name or camera_id
        now = time.monotonic()
        image_due = (self.config.get("debug_save_snapshots", False) and
                     now - self.last_image.get(camera_id, float("-inf")) >= self.config.get("debug_snapshot_interval", 30))
        if not image_due:
            return
        details = []
        for x1, y1, x2, y2, confidence, class_id in boxes:
            details.append({"xyxy": [x1, y1, x2, y2], "confidence": round(confidence, 4),
                            "class_id": int(class_id), "label": names[int(class_id)]})
        if normalize_roi_names:
            from core.point_contract import normalize_point_id
            roi_keys = {str(r["name"]): normalize_point_id(r["name"]) for r in rois}
        else:
            roi_keys = {str(r["name"]): str(r["name"]) for r in rois}
        logger = get_logger("camera_ai_service")
        if image_due:
            self.last_image[camera_id] = now
            temporary = None
            try:
                import cv2
                directory = Path(self.config.get("debug_snapshot_dir", "logs/snapshots"))
                canvas = frame.copy()
                for box in details:
                    x1, y1, x2, y2 = map(int, box["xyxy"])
                    cv2.rectangle(canvas, (x1, y1), (x2, y2), (255, 180, 0), 2)
                    cv2.putText(canvas, f'{box["label"]} {box["confidence"]:.2f}',
                                (x1, max(15, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, .5, (255, 180, 0), 1)
                for roi in rois:
                    name = str(roi["name"])
                    label = labels.get(roi_keys[name])
                    if label not in ("hang", "trong"):
                        continue
                    color = (0, 0, 255) if label == "hang" else (0, 255, 0)
                    x1, y1, x2, y2 = (int(roi[k]) for k in ("x1", "y1", "x2", "y2"))
                    cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)
                    cv2.putText(canvas, f"{name}: {label}", (x1, max(15, y1 - 8)),
                                cv2.FONT_HERSHEY_SIMPLEX, .5, color, 1)
                ok, encoded = cv2.imencode(".jpg", canvas)
                if not ok:
                    raise OSError("JPEG encoding failed")
                image_path, temporary = self._reserve_image(directory, camera_name)
                temporary.write_bytes(encoded.tobytes())
                temporary.replace(image_path)
                logger.info("SNAPSHOT camera_id=%s camera_name=%s file=%s", camera_id, camera_name, image_path)
            except Exception as exc:
                if temporary is not None:
                    try:
                        temporary.unlink(missing_ok=True)
                    except OSError:
                        pass
                logger.warning("SNAPSHOT_FAILED camera_id=%s error_type=%s", camera_id, type(exc).__name__)

    def prune(self, active_ids):
        for cid in list(self.last_image):
            if cid not in active_ids:
                self.last_image.pop(cid, None)
