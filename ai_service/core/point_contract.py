"""Point identifiers shared by the camera catalog and detection wire contract."""
import re

END_POINT_EMPTY = "10001546"


def normalize_point_id(value):
    name = str(value)
    for prefix in ("start_", "end_"):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    if not re.fullmatch(r"[0-9]+", name):
        raise ValueError("Point IDs must contain ASCII digits only")
    return name
