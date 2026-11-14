"""Bounding-box intersection measured against the ROI area, in frame pixels."""

DETECTION_CONFIDENCE_THRESHOLD = 0.4
ROI_OVERLAP_THRESHOLD = 0.45


def roi_overlap_ratio(box, roi):
    """Return intersection(box, ROI) / area(ROI), rather than box area or IoU."""
    width = roi["x2"] - roi["x1"]
    height = roi["y2"] - roi["y1"]
    if width <= 0 or height <= 0:
        return 0.0
    overlap_width = max(0.0, min(box[2], roi["x2"]) - max(box[0], roi["x1"]))
    overlap_height = max(0.0, min(box[3], roi["y2"]) - max(box[1], roi["y1"]))
    return overlap_width * overlap_height / (width * height)
