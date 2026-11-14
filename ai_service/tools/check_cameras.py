"""Bounded RTSP probe of an entire cluster catalog; no AI data is posted.

Run from ai_service: python tools/check_cameras.py --catalog ../camera_cluster/config/cameras.json
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import socket
import sys
import threading
import time
from urllib.parse import urlsplit


def load_cameras(path):
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    cameras = data["cameras"] if isinstance(data, dict) else data
    if not isinstance(cameras, list):
        raise ValueError("Camera catalog must contain a list")
    seen = set()
    for camera in cameras:
        if not isinstance(camera, dict) or not isinstance(camera.get("enabled", True), bool):
            raise ValueError("Invalid camera record")
        cid = camera.get("camera_id")
        if not isinstance(cid, str) or not cid.strip() or cid in seen:
            raise ValueError("Camera IDs must be nonempty and unique")
        seen.add(cid)
        if not isinstance(camera.get("camera_path"), str) or not camera["camera_path"].strip():
            raise ValueError("Camera path must be nonempty")
    return [camera for camera in cameras if camera.get("enabled", True)]


def probe(camera, args):
    # Native FFmpeg errors bypass Python logging. Parent captures and discards
    # child stderr so credentials cannot appear in the operator's console/report.
    os.environ["OPENCV_FFMPEG_LOGLEVEL"] = "-8"
    import cv2
    started = time.monotonic()
    cap = None
    result = {"connected": False, "frames_read": 0}
    try:
        source = urlsplit(camera["camera_path"])
        if args.tcp_check and source.scheme.lower() in ("rtsp", "rtsps"):
            try:
                with socket.create_connection((source.hostname, source.port or 554), timeout=args.open_timeout_ms / 1000):
                    result["tcp_connected"] = True
            except OSError as exc:
                result.update(tcp_connected=False, error_type="TcpConnectFailed", tcp_error_type=type(exc).__name__,
                              tcp_error_code=getattr(exc, "winerror", None) or exc.errno)
                return result
        cap = cv2.VideoCapture(camera["camera_path"], cv2.CAP_FFMPEG, [
            cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, args.open_timeout_ms,
            cv2.CAP_PROP_READ_TIMEOUT_MSEC, args.read_timeout_ms])
        if not cap.isOpened():
            result["error_type"] = "OpenFailed"
            return result
        for _ in range(args.frames):
            ok, frame = cap.read()
            if not ok or frame is None:
                result["error_type"] = "ReadFailed"
                return result
            result["frames_read"] += 1
            result["source_size"] = [frame.shape[1], frame.shape[0]]
        result["connected"] = True
        return result
    except Exception as exc:
        result["error_type"] = type(exc).__name__
        return result
    finally:
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        if cap is not None:
            cap.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--output", default="logs/camera_probe.json")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--camera-id", action="append", default=[], help="Check only this camera ID; repeat for more IDs")
    parser.add_argument("--tcp-check", action="store_true", help="Check RTSP TCP port first and report OS network errors")
    parser.add_argument("--frames", type=int, default=3)
    parser.add_argument("--open-timeout-ms", type=int, default=4000)
    parser.add_argument("--read-timeout-ms", type=int, default=4000)
    parser.add_argument("--timeout", type=float, default=25, help="Hard deadline per camera, including Python startup")
    parser.add_argument("--_index", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if min(args.workers, args.frames, args.open_timeout_ms, args.read_timeout_ms, args.timeout) <= 0:
        parser.error("All limits must be positive")
    try:
        cameras = load_cameras(args.catalog)
        if not cameras:
            raise ValueError("Empty catalog")
    except Exception as exc:
        print(f"CATALOG_FAILED error_type={type(exc).__name__}")
        return 2
    if args._index is not None:
        print(json.dumps(probe(cameras[args._index], args)))
        return 0

    indices = [index for index, camera in enumerate(cameras) if not args.camera_id or camera["camera_id"] in args.camera_id]
    if args.camera_id and set(args.camera_id) - {cameras[i]["camera_id"] for i in indices}:
        parser.error("Requested camera ID is not enabled or absent from the catalog")
    output_lock = threading.Lock()

    def check(index):
        camera = cameras[index]
        result = {"camera_id": camera["camera_id"], "camera_name": camera.get("camera_name", ""),
                  "roi_count": len(camera.get("roi", []))}
        command = [sys.executable, str(Path(__file__).resolve()), "--catalog", str(Path(args.catalog).resolve()),
                   "--_index", str(index), "--frames", str(args.frames),
                   "--open-timeout-ms", str(args.open_timeout_ms), "--read-timeout-ms", str(args.read_timeout_ms)]
        if args.tcp_check:
            command.append("--tcp-check")
        try:
            child = subprocess.run(command, capture_output=True, text=True, timeout=args.timeout)
            if child.returncode:
                result.update(connected=False, error_type="ProbeProcessFailed")
            else:
                result.update(json.loads(child.stdout.strip().splitlines()[-1]))
        except subprocess.TimeoutExpired:
            result.update(connected=False, error_type="HardTimeout")
        except Exception as exc:
            result.update(connected=False, error_type=type(exc).__name__)
        with output_lock:
            print(f"{result['camera_id']}: {'STREAMING' if result['connected'] else result.get('error_type', 'FAILED')}", flush=True)
        return result

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(check, indices))
    connected = sum(result["connected"] for result in results)
    report = {"checked_at": time.time(), "scope": "selected_cameras" if args.camera_id else "enabled_catalog_cameras", "expected": len(results),
              "connected": connected, "all_connected": connected == len(results), "cameras": results}
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Connected {connected}/{len(results)}; report: {destination}")
    return 0 if report["all_connected"] else 1


if __name__ == "__main__":
    sys.exit(main())
