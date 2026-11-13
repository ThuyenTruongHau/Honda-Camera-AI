import cv2
import time
import threading
from core.config import settings
from shared.logger import get_logger

logger = get_logger("camera_ai_service")


class CameraThread(threading.Thread):
    def __init__(self, camera_info, shared_dict, max_retries, target_fps, camera_health=None):
        super().__init__()
        self.camera_info = camera_info
        self.shared_dict = shared_dict
        self.camera_health = camera_health
        self.max_retries = max_retries
        self.frame_interval = 1.0 / target_fps
        self.running = True
        self.retry_count = 0
        self.attempts = 0
        self.frames_received = 0
        self.last_frame_at = None

    def _status(self, status, **details):
        if self.camera_health is not None:
            self.camera_health[self.camera_info['camera_name']] = {
                'status': status, 'attempts': self.attempts, 'retry_count': self.retry_count,
                'frames_received': self.frames_received, 'last_frame_at': self.last_frame_at, **details}

    def _connect_camera(self):
        self.attempts += 1
        self._status('CONNECTING')
        logger.info('RTSP_CONNECTING camera_id=%s attempt=%s', self.camera_info['camera_name'], self.attempts)
        cap = cv2.VideoCapture(self.camera_info['cam_path'], cv2.CAP_FFMPEG, [
            cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, settings.cluster_capture_open_timeout_ms,
            cv2.CAP_PROP_READ_TIMEOUT_MSEC, settings.cluster_capture_read_timeout_ms])
        if cap.isOpened():
            return cap
        cap.release()
        self._status('OPEN_FAILED', error_type='OpenFailed')
        logger.warning('RTSP_OPEN_FAILED camera_id=%s attempt=%s', self.camera_info['camera_name'], self.attempts)
        return None

    def run(self):
        cid = self.camera_info['camera_name']
        while self.running and self.retry_count < self.max_retries:
            cap = None
            try:
                cap = self._connect_camera()
                if cap is not None:
                    last_frame, last_status, first_frame = 0.0, 0.0, True
                    while self.running:
                        ok, frame = cap.read()
                        if not ok or frame is None:
                            self._status('READ_FAILED', error_type='ReadFailed')
                            logger.warning('RTSP_READ_FAILED camera_id=%s frames_received=%s', cid, self.frames_received)
                            break
                        now = time.monotonic()
                        if now - last_frame < self.frame_interval:
                            continue
                        last_frame = now
                        self.last_frame_at = time.time()
                        self.frames_received += 1
                        self.retry_count = 0
                        self.shared_dict[cid] = {
                            'frame': cv2.resize(frame, (1280, 720)), 'ts': self.last_frame_at,
                            'status': 'success', 'retry_count': 0, 'rois': self.camera_info['roi'],
                            'group_id': self.camera_info['group_id']}
                        if first_frame or now - last_status >= 1:
                            self._status('STREAMING')
                            last_status = now
                        if first_frame:
                            logger.info('RTSP_STREAMING camera_id=%s source_size=%sx%s output_size=1280x720', cid, frame.shape[1], frame.shape[0])
                            first_frame = False
            except Exception as exc:
                self._status('ERROR', error_type=type(exc).__name__)
                logger.error('RTSP_ERROR camera_id=%s error_type=%s', cid, type(exc).__name__)
            finally:
                if cap is not None:
                    cap.release()
            self.retry_count += 1
            # Invalidate the previous frame as soon as the connection fails.
            self.shared_dict[cid] = {'frame': None, 'ts': time.time(), 'status': 'failed', 'retry_count': self.retry_count}
            if self.running and self.retry_count < self.max_retries:
                logger.info('RTSP_RETRY camera_id=%s retry=%s max_retries=%s delay_seconds=5', cid, self.retry_count, self.max_retries)
                time.sleep(5)
        if self.running:
            self._status('RETRY_EXHAUSTED')
            logger.error('RTSP_RETRY_EXHAUSTED camera_id=%s max_retries=%s', cid, self.max_retries)
        else:
            self._status('STOPPED')

    def stop(self):
        self.running = False
