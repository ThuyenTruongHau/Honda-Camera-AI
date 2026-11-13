"""Inference process. GPU imports stay out of the controller and CPU-only tests."""
import time
from services.cluster_capture import owns
from core.point_contract import END_POINT_EMPTY, normalize_point_id
from core.roi_geometry import DETECTION_CONFIDENCE_THRESHOLD, ROI_OVERLAP_THRESHOLD, roi_overlap_ratio
from shared.logger import setup_logger
from shared.diagnostics import DetectionEvidence


def labels_for_rois(boxes, names, rois):
    regions = [(normalize_point_id(roi["name"]), roi) for roi in rois]
    regions = [(name, roi) for name, roi in regions if name != END_POINT_EMPTY]
    labels = {name: "trong" for name, roi in regions}
    for x1, y1, x2, y2, confidence, class_id in boxes:
        # Only confident hang boxes mark a region occupied. Other boxes cannot
        # cancel an existing hang result or remove a region from the payload.
        if not confidence > DETECTION_CONFIDENCE_THRESHOLD or names[int(class_id)] != "hang":
            continue
        for name, roi in regions:
            if roi_overlap_ratio((x1, y1, x2, y2), roi) > ROI_OVERLAP_THRESHOLD:
                labels[name] = "hang"
    return labels


def publish_result(item, labels, authority, results):
    key = (item["camera_id"], item["assignment_epoch"])
    if not owns(authority, *key):
        return False
    # captured_at is local scheduling state, never part of the HTTP payload.
    snapshot = {k: item[k] for k in ("camera_id", "assignment_epoch", "captured_at")}
    points = {normalize_point_id(name): {"label": label, "group_id": str(item.get("group_id", ""))}
              for name, label in labels.items()
              if normalize_point_id(name) != END_POINT_EMPTY and label in ("hang", "trong")}
    snapshot.update(points=points)
    results[key] = snapshot
    return True


def select_batch(frames, authority, processed, last_selected, config):
    candidates = []
    now = time.time()
    for key in list(frames.keys()):
        item = frames.get(key)
        if item and owns(authority, *key) and item["captured_at"] > processed.get(key, 0) and now - item["captured_at"] <= config["cluster_max_frame_age"]:
            candidates.append(item)
    # A busy source can replace its latest frame on every pass. Scheduling by
    # observation age alone could starve it forever behind slower sources.
    candidates.sort(key=lambda item: (last_selected.get((item["camera_id"], item["assignment_epoch"]), 0), item["camera_id"]))
    return candidates[:config["cluster_inference_batch_size"]]


def detector_process(authority, frames, results, health, stop, config):
    logger = setup_logger("camera_ai_service", config.get("log_level"), log_dir=config.get("log_dir"))
    evidence = DetectionEvidence(config)
    health.update(ready=False, busy_since=0.0, error=False)
    try:
        from ultralytics import YOLO
        import ultralytics
        import torch
        import cv2
        device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info("MODEL_ENV torch=%s ultralytics=%s opencv=%s cuda_available=%s", torch.__version__, ultralytics.__version__, cv2.__version__, torch.cuda.is_available())
        logger.info("MODEL_LOADING weights=%s device=%s", config["weight_path"], device)
        model = YOLO(config["weight_path"])
        model.to(device)
        logger.info("MODEL_READY device=%s classes=%s", device, model.names)
        if set(model.names.values()) != {"hang"}:
            logger.warning("MODEL_CLASSES_UNEXPECTED expected=hang actual=%s; verify custom weights", model.names)
        health["ready"] = True
        processed, last_selected = {}, {}
        selection_round = 0
        while not stop.is_set():
            batch = select_batch(frames, authority, processed, last_selected, config)
            if not batch:
                time.sleep(0.02)
                continue
            health["busy_since"] = time.monotonic()
            selection_round += 1
            predictions = model([item["frame"] for item in batch], device=device, verbose=False)
            for item, prediction in zip(batch, predictions):
                key = (item["camera_id"], item["assignment_epoch"])
                boxes = prediction.boxes.data.tolist() if prediction.boxes is not None else []
                labels = labels_for_rois(boxes, prediction.names, item["roi"])
                if publish_result(item, labels, authority, results):
                    evidence.record(item["camera_id"], item["frame"], boxes, prediction.names,
                                    item["roi"], labels, item["captured_at"],
                                    assignment_epoch=item["assignment_epoch"], group_id=item.get("group_id"),
                                    camera_name=item.get("camera_name") or item["camera_id"],
                                    normalize_roi_names=True,
                                    mapping_policy="intersection_over_roi_gt_0.5_conf_gt_0.6_default_trong")
                processed[key] = item["captured_at"]
                last_selected[key] = selection_round
            health.update(busy_since=0.0, last_progress=time.monotonic())
            for key in list(processed):
                if not owns(authority, *key):
                    processed.pop(key, None)
                    last_selected.pop(key, None)
            evidence.prune({key[0] for key in processed})
    except Exception as exc:
        logger.error("MODEL_FAILED error_type=%s reason=%s", type(exc).__name__, exc)
        health.update(error=True, ready=False, busy_since=0.0, error_type=type(exc).__name__)
    finally:
        health["ready"] = False
