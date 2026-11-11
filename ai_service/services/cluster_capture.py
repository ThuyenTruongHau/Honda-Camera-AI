"""Dynamic RTSP threads; stop events are local to the AI controller."""
import queue
import threading
import time


def owns(authority, camera_id, epoch):
    current = authority.get(camera_id)
    return bool(current and current["epoch"] == epoch and current["deadline"] > time.monotonic())


def capture_camera(assignment, authority, frames, stop, config, opening):
    import cv2
    cid, epoch = assignment["camera_id"], assignment["assignment_epoch"]
    key = (cid, epoch)
    cap = None
    try:
        while not stop.is_set() and owns(authority, cid, epoch):
            try:
                with opening:
                    if stop.is_set() or not owns(authority, cid, epoch):
                        break
                    cap = cv2.VideoCapture(assignment["camera_path"], cv2.CAP_FFMPEG, [
                        cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, config["cluster_capture_open_timeout_ms"],
                        cv2.CAP_PROP_READ_TIMEOUT_MSEC, config["cluster_capture_read_timeout_ms"],
                    ])
                if not cap.isOpened():
                    cap.release()
                    cap = None
                    stop.wait(config["cluster_source_retry_delay"])
                    continue
                last_frame = 0.0
                while not stop.is_set() and owns(authority, cid, epoch):
                    ok, frame = cap.read()
                    if not ok:
                        break
                    now = time.monotonic()
                    if now - last_frame < 1.0 / config["target_fps"]:
                        continue
                    last_frame = now
                    item = {"camera_id": cid, "assignment_epoch": epoch,
                            "group_id": str(assignment.get("group_id", "")),
                            "captured_at": time.time(), "roi": assignment["roi"],
                            "frame": cv2.resize(frame, (1280, 720))}
                    if owns(authority, cid, epoch) and not stop.is_set():
                        frames[key] = item
                cap.release()
                cap = None
                if not stop.is_set():
                    stop.wait(config["cluster_source_retry_delay"])
            except Exception:
                # Never put a stream URL or credentials in diagnostic messages.
                stop.wait(config["cluster_source_retry_delay"])
    finally:
        if cap is not None:
            cap.release()
        frames.pop(key, None)


def capture_process(commands, events, authority, frames, config):
    running = {}
    opening = threading.BoundedSemaphore(config["cluster_start_concurrency"])
    while True:
        for key, (thread, stop) in list(running.items()):
            if not thread.is_alive():
                events.put({"camera_id": key[0], "assignment_epoch": key[1], "status": "STOPPED"})
                running.pop(key)
        try:
            command = commands.get(timeout=0.1)
        except queue.Empty:
            continue
        action = command["action"]
        if action == "SHUTDOWN":
            for thread, stop in running.values():
                stop.set()
            for thread, stop in running.values():
                thread.join(timeout=0.1)
            return
        assignment = command["assignment"]
        key = (assignment["camera_id"], assignment["assignment_epoch"])
        if action == "STOP":
            if key in running:
                running[key][1].set()
            else:
                events.put({"camera_id": key[0], "assignment_epoch": key[1], "status": "STOPPED"})
        elif action == "START" and key not in running:
            # Never allow a second generation for the same camera in this process.
            if any(k[0] == key[0] for k in running):
                events.put({"camera_id": key[0], "assignment_epoch": key[1], "status": "FAILED"})
                continue
            stop = threading.Event()
            thread = threading.Thread(target=capture_camera,
                                      args=(assignment, authority, frames, stop, config, opening), daemon=True)
            running[key] = (thread, stop)
            thread.start()
