from core.database import get_collection
from multiprocessing import Manager, Process
import math
import time
from shared.logger import get_logger
from typing import List, Dict, Any
from core.database import get_collection
from services.camera_process_worker import start_camera_threads
from services.yolo_detector import YoloDetector
from core.config import settings
import asyncio
import httpx
import json
from shared.diagnostics import camera_summary


logger = get_logger("camera_ai_service")

class CameraOrchestratorService:
    def __init__(self, group_id=0, num_processes=4, max_retry_attempts=3, model_path="weights/ModelHN_170926.engine", target_fps=5.0):
        self.group_id = group_id
        self.num_processes = num_processes
        self.max_retry_attempts = max_retry_attempts
        self.model_path = model_path
        self.target_fps = target_fps
        self.manager = Manager()
        self.shared_dict = self.manager.dict()
        self.target_dict = self.manager.dict()
        self.camera_health = self.manager.dict()
        self.camera_detections = self.manager.dict()
        self.tasks = []
        self.last_delivery_ok = None
        self.delivery_error = None
        self.last_delivery_log = 0.0
        self.processes = []
        self.cameras = []
        self.logic_path = settings.logic_path
        self._is_running = True

    def diagnostics(self):
        records = [{"camera_id": c["camera_name"], "camera_name": c["camera_name"],
                    "group_id": c["group_id"], "roi": c["roi"]} for c in self.cameras]
        return {"scope": "configured_mongo_groups", "group_ids": self.group_id,
                "runtime_ready": bool(self.processes) and all(p.is_alive() for p in self.processes),
                "last_delivery_ok": self.last_delivery_ok, "delivery_error": self.delivery_error,
                **camera_summary(records, self.camera_health, self.camera_detections, settings.cluster_max_frame_age)}

    async def _diagnostics_loop(self):
        while self._is_running:
            summary = self.diagnostics()
            cameras = summary.pop("cameras")
            summary["problem_cameras"] = [{"camera_id": c["camera_id"], "status": c.get("status", "WAITING")}
                                          for c in cameras if not c["connected"] or not c["detecting"]]
            logger.info("CAMERA_SUMMARY %s", json.dumps(summary))
            await asyncio.sleep(settings.camera_summary_interval)

    def _devide_camera_urls(self):
        total_cameras = len(self.cameras)
        if total_cameras == 0:
                return [], 0

        cameras_per_process = math.ceil(total_cameras / self.num_processes)
        
        camera_groups = []
        for i in range(0, total_cameras, cameras_per_process):
            group = self.cameras[i:i + cameras_per_process]
            camera_groups.append(group)

        return camera_groups, total_cameras

    async def _report_to_logic_service(self):
        logger.info("Background reporting task started.")
        
        async with httpx.AsyncClient() as client:
            while self._is_running:
                try:
                    # Chuyển đổi Manager.dict sang dict thường để serialize JSON
                    data_to_send = dict(self.target_dict)
                    if data_to_send:
                        # Gửi POST request
                        response = await client.post(
                            self.logic_path, 
                            json=data_to_send,
                            timeout=3.0
                        )
                        
                        if response.status_code != 200:
                            self.delivery_error = {"http_status": response.status_code}
                            logger.warning("AI_DATA_DELIVERY_FAILED http_status=%s points=%s", response.status_code, len(data_to_send))
                        else:
                            self.last_delivery_ok = time.time()
                            self.delivery_error = None
                            if time.monotonic() - self.last_delivery_log >= settings.detection_log_interval:
                                logger.info("AI_DATA_DELIVERED http_status=200 points=%s", len(data_to_send))
                                self.last_delivery_log = time.monotonic()
                    
                except Exception as e:
                    self.delivery_error = {"error_type": type(e).__name__}
                    logger.error("AI_DATA_DELIVERY_FAILED error_type=%s", type(e).__name__)

                # Chờ 1 giây cho chu kỳ tiếp theo
                await asyncio.sleep(0.5)

    async def start(self):
        logger.info(f"Starting Camera Orchestrator Service for group id: {self.group_id}, with {self.num_processes} processes")

        cursor = get_collection("cameras").find({"group_id": {"$in": self.group_id}})
        raw_cameras = await cursor.to_list(length=None)

        #Chuyển dữ liệu về đúng định dạng
        for c in raw_cameras:
            self.cameras.append({
                'camera_name': c['camera_name'],
                'cam_path': c['camera_path'], # Map 'camera_path' từ DB sang 'cam_path' cho Thread
                'id': str(c['_id']),
                'roi': c.get('roi', []), # Lưu lại ROI để dùng cho logic AI sau này
                'group_id': c.get('group_id', 0) # Lưu lại group_id để dùng cho monitor
            })

        #Tìm cách hold cho xong config mới chạy
        # time.sleep(5)

        camera_groups, total = self._devide_camera_urls()

        logger.info(f"Divided {total} cameras into {len(camera_groups)} groups")
        logger.info(f"Starting {len(camera_groups)} camera processes with {self.max_retry_attempts} max retry attempts and {self.target_fps} FPS")

        # Tạo và spawn các process camera
        for i, camera_group in enumerate(camera_groups):
            process = Process(
                target=start_camera_threads,
                args=(i, camera_group, self.shared_dict, self.max_retry_attempts, self.target_fps, self.camera_health)
            )
            self.processes.append(process)
            process.start()

        ai_process = YoloDetector(
            shared_dict=self.shared_dict, 
            target_dict=self.target_dict, 
            model_path=self.model_path, 
            target_fps=self.target_fps,
            draw=True,
            camera_detections=self.camera_detections
        )
        self.processes.append(ai_process)
        ai_process.start()

        # Kích hoạt task gửi data định kỳ (không dùng await ở đây để nó chạy nền)
        self.tasks = [asyncio.create_task(self._report_to_logic_service()),
                      asyncio.create_task(self._diagnostics_loop())]
        logger.info("Sending data to logic service ....")

    async def stop(self):
        """Dừng tất cả process"""
        self._is_running = False
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

        for process in self.processes:
            process.terminate()
        
        for process in self.processes:
            process.join(timeout=5.0)
        
        logger.info("All processes stopped")



        
        
