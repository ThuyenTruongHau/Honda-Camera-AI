from datetime import datetime, timezone
from shared.logger import get_logger
import asyncio
from typing import Dict, Any, Optional, List, Tuple
import contextlib
import json
import asyncio
import os
import re
import sys
import time
import importlib
from core.config import settings
from services.observation_guard import observations, remember

logger = get_logger("logic_service")

class Position_Manager:
    def __init__(self, time_recognition) -> None:
        self._consumer_task: Optional[asyncio.Task] = None
        self._position_state: Dict[str, Any] = {}
        self.data_configs = {}
        self.mapping = {}
        self._pending_state = {}
        self._registry = {}
        self._last_check_time = {}
        self.time_recognition = time_recognition
        self._camera_epochs = {}
        self._camera_positions = {}
        self._applied = {}
        self._reservations = {}
        self._business_tasks = {}
        self._manual_tasks = set()
        self._decision_lock = asyncio.Lock()

    def _fresh(self, value):
        now = time.time()
        return bool(value and value.get("quality") == "GOOD" and
                    now - value.get("observed_at", 0) <= getattr(settings, "cluster_max_frame_age", 3) and
                    value.get("lease_expires_at", 0) > now and
                    self._camera_epochs.get(value.get("camera_id")) == value.get("epoch"))

    async def invalidate_camera(self, camera_id, epoch):
        if epoch < self._camera_epochs.get(camera_id, 0):
            return
        self._camera_epochs[camera_id] = epoch
        for point in self._camera_positions.get(camera_id, set()):
            value = self._position_state.get(point)
            if value:
                value["quality"] = "UNKNOWN"
            self._pending_state.pop(point, None)

    async def apply_camera_snapshot(self, camera_id, epoch, observed_at, group_id, rois, lease_expires_at):
        if epoch < self._camera_epochs.get(camera_id, 0):
            return
        if self._applied.get(camera_id, (0, 0)) >= (epoch, observed_at):
            return
        now = time.time()
        if now - observed_at > getattr(settings, "cluster_max_frame_age", 3) or lease_expires_at <= now:
            return
        if self._camera_epochs.get(camera_id) != epoch:
            await self.invalidate_camera(camera_id, epoch)
        self._camera_epochs[camera_id] = epoch
        self._camera_positions[camera_id] = {r["roi_id"] for r in rois}
        triggered = []
        for roi in rois:
            point, label = roi["roi_id"], roi["label"]
            old = self._position_state.get(point, {})
            valid_old = self._fresh(old)
            confirmed = old.get("label") if valid_old else "UNKNOWN"
            pending = self._pending_state.get(point)
            if not valid_old and (not pending or observed_at - pending.get("last_observed_at", 0) > getattr(settings, "cluster_max_frame_age", 3)):
                pending = None
                self._pending_state.pop(point, None)
            if label != confirmed:
                if not pending or pending["label"] != label or pending.get("epoch") != epoch:
                    pending = {"label": label, "start_ts": observed_at, "epoch": epoch}
                pending["last_observed_at"] = observed_at
                self._pending_state[point] = pending
                if observed_at - pending["start_ts"] >= self.time_recognition:
                    confirmed = label
                    self._pending_state.pop(point, None)
            else:
                self._pending_state.pop(point, None)
            self._position_state[point] = {
                "label": confirmed, "group_id": group_id, "ts": now,
                "observed_at": observed_at, "quality": "GOOD", "camera_id": camera_id,
                "epoch": epoch, "lease_expires_at": lease_expires_at,
            }
            if confirmed == "hang" and point not in self._reservations and point in self.mapping:
                triggered.append(point)
        self._applied[camera_id] = (epoch, observed_at)
        # Schedule after the whole snapshot is installed; no robot I/O in ingress.
        for point in triggered:
            old_task = self._business_tasks.get(point)
            if old_task is None or old_task.done():
                self._business_tasks[point] = asyncio.create_task(self._run_business(point))

    async def _run_business(self, point):
        try:
            file_name = self.mapping.get(point)
            if file_name:
                await self.execute_logic(self.data_configs[file_name][point], 0, trigger=point)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Business decision failed")

    def schedule_manual(self, coroutine):
        task = asyncio.create_task(coroutine)
        self._manual_tasks.add(task)
        def finished(done):
            self._manual_tasks.discard(done)
            if not done.cancelled() and done.exception():
                logger.error("Manual business task failed: %s", type(done.exception()).__name__)
        task.add_done_callback(finished)
        return task

    def decision_valid(self):
        context = observations.get()
        if not context:
            return False
        for point, token in context.items():
            value = self._position_state.get(point, {})
            if not token or not self._fresh(value) or value.get("label") != token[2] or (value.get("camera_id"), value.get("epoch")) != token[:2]:
                return False
        return True

    async def authorize_task(self, order_id, points):
        points = points if isinstance(points, list) else [points]
        async with self._decision_lock:
            if getattr(settings, "cluster_enabled", False):
                if not getattr(settings, "cluster_robot_enabled", False) or not self.decision_valid():
                    return False
            if any(p in self._reservations and self._reservations[p] != order_id for p in points):
                return False
            for point in points:
                self._reservations[point] = order_id
            return True

    async def send_robot_task(self, payload, ics_url):
        import httpx
        from services.Task_manager import task_service
        task_id = payload["orderId"]
        tracked = task_service.tracking_task.get(task_id, {})
        points = tracked.get("position", [])
        if not points or not await self.authorize_task(task_id, points):
            return False
        # Reservations remain on ambiguous network failure; do not blindly resend.
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.post(f"{ics_url}/ics/taskOrder/addTask", json=payload)
            response.raise_for_status()
        return True

    async def start(self) -> None:
        self.load_configs()
        if self._consumer_task is None:
            self._consumer_task = asyncio.create_task(self._consumer_loop())

    def load_configs(self):
        config_dir = "config/map_config"
        if not os.path.exists(config_dir):
            logger.error(f"The config path does not exist")
            return
            
        for filename in os.listdir(config_dir):
            # Chỉ kiểm tra file có đuôi .json
            if filename.lower().endswith(".json"):
                path = os.path.join(config_dir, filename)
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        content = json.load(f)
                        
                        if content:
                            # Lưu toàn bộ nội dung file vào data
                            self.data_configs[filename] = content
                            
                            # Mapping từng key trong file đó để biết nó thuộc về file nào (logic nào)
                            for key in content.keys():
                                self.mapping[key] = filename

                except Exception as e:
                    print(f"[ERROR] Could not load {filename}: {e}")
            
        logger.info(f"Loaded all config files")

    async def stop(self) -> None:
        jobs = list(self._business_tasks.values()) + list(self._manual_tasks)
        for task in jobs:
            task.cancel()
        if jobs:
            await asyncio.gather(*jobs, return_exceptions=True)
        self._business_tasks.clear()
        self._manual_tasks.clear()
        if self._consumer_task:
            self._consumer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._consumer_task
            self._consumer_task = None

    async def update_state(self, data) -> None:
        now = time.time()

        for pos_id, info in data.items():
            new_label = info.get("label")
            group_id = info.get("group_id")
            current_confirmed = self._position_state.get(pos_id, {})
            
            if current_confirmed.get("label") == "block":
                continue

            if new_label == current_confirmed.get("label"):
                self._position_state[pos_id]["ts"] = now
                self._pending_state.pop(pos_id, None)

                # Kiểm tra có trong config thì thực hiện gửi đến đúng logic
                file_name = self.mapping.get(pos_id)
                if file_name and new_label == "hang":
                    try:
                        await self.request_service_auto(self.data_configs[file_name][pos_id])
                    except Exception as e:
                        logger.warning(f"Error: {e}")
                continue

            pending = self._pending_state.get(pos_id)

            if pending and pending["label"] == new_label:
                elapsed = now - pending["start_ts"]
                if elapsed >= self.time_recognition:
                    # Đã đủ 5 giây liên tục -> Xác nhận trạng thái mới
                    self._position_state[pos_id] = {
                        "label": new_label,
                        "group_id": group_id,
                        "ts": now,
                    }
                    self._pending_state.pop(pos_id, None)

            else:
                self._pending_state[pos_id] = {
                    "label": new_label,
                    "start_ts": now
                }

    async def request_service_auto(self, data):
        await self.execute_logic(data, 0)

    async def execute_logic(self, data, mode, trigger=None):
        token = observations.set({})
        logic_path = data.get('logic_path')
        try:
            if trigger:
                await self.get_state([trigger])
            logic_path = data.get('logic_path')
            if not logic_path:
                return

            # 1. Lấy hàm từ file logic (Tự động hot-reload nếu cần)
            process_func = await self.get_logic_func(logic_path, mode)

            if process_func:
                response = await process_func(data) 
                return response
            else:
                logger.warning(f"Function process_auto not found in {logic_path}")
                return None

        except Exception as e:
            logger.error(f"Failed to execute logic {logic_path}: {e}")
            return None
        finally:
            observations.reset(token)

    async def get_logic_func(self, logic_path, mode):
        file_path = os.path.join(".", "logic", f"{logic_path}_logic.py")
        module_name = f"logic.{logic_path}_logic"
        now = time.time()
        
        last_check = self._last_check_time.get(logic_path, 0)

        # Cơ chế Cooldown (Chỉ check ổ đĩa 1 lần mỗi giây)
        if now - last_check > 1.0: 
            self._last_check_time[logic_path] = now
            
            if os.path.exists(file_path): # Kiểm tra file vật lý
                current_mtime = os.path.getmtime(file_path)
                cached_info = self._registry.get(logic_path)

                if not cached_info or current_mtime > cached_info["mtime"]:
                    try:
                        if module_name in sys.modules:
                            # Nếu module đã từng được nạp, ta reload nó
                            module = importlib.reload(sys.modules[module_name])
                            logger.info(f"--- HOT RELOADED: {logic_path} ---")
                        else:
                            # Nếu chưa từng nạp, ta import mới
                            module = importlib.import_module(module_name)
                            logger.info(f"--- LOADED NEW: {logic_path} ---")

                        self._registry[logic_path] = {
                            "module": module,
                            "mtime": current_mtime
                        }
                    except Exception as e:
                        logger.error(f"Error loading logic {logic_path}: {e}")

        # Đoạn này chạy cực nhanh vì nó chỉ lấy từ Dict trong RAM ra
        if logic_path in self._registry:
            # Lấy object module đã lưu trong registry ra và tìm hàm 
            if mode == 0:
                return getattr(self._registry[logic_path]["module"], "process_auto", None)

            if mode == 1:
                return getattr(self._registry[logic_path]["module"], "active_request", None)

            if mode == 2:
                return getattr(self._registry[logic_path]["module"], "handle_clear_monitor", None)
        
        return None

    async def get_state(self, points):
        states = []
        for point in points:
            pos_data = self._position_state.get(point, {})            
            label = pos_data.get("label", None)
            if getattr(settings, "cluster_enabled", False):
                fresh = self._fresh(pos_data)
                remember(point, (pos_data.get("camera_id"), pos_data.get("epoch"), label) if fresh and label not in (None, "UNKNOWN") else None)
                if not fresh:
                    label = "UNKNOWN"
            if point in self._reservations:
                label = "block"
            states.append(label)
        return states

    async def get_group(self, point):
        pos_data = self._position_state.get(point, {})            
        group = pos_data.get("group_id", None)            
        return group

    async def block_point(self, point, order_id=None):
        points = point if isinstance(point, list) else [point]
        
        for p in points:
            self._reservations.setdefault(p, order_id or "manual")
            pos_data = self._position_state.get(p)
            if pos_data and not getattr(settings, "cluster_enabled", False):
                self._position_state[p]["label"] = "block"

    async def un_block_point(self, point, order_id=None):
        points = point if isinstance(point, list) else [point]
        
        for p in points:
            if order_id and self._reservations.get(p) not in (None, order_id):
                continue
            self._reservations.pop(p, None)
            pos_data = self._position_state.get(p)
            if pos_data:
                self._position_state[p]["label"] = "UNKNOWN" if getattr(settings, "cluster_enabled", False) else "None"
                self._pending_state.pop(p, None)

    async def active_request(self, data):
        key = str(data.get("end"))
        
        file_name = self.mapping.get(key)
        logger.info(f"file_name: {file_name}")
        if file_name:
            group_id = data.get("group_id")
            node_name = data.get("node_name")
            new_data = self.data_configs[file_name][key]
            new_data["group_id"] = group_id
            new_data["node_name"] = node_name
            try:
                response = await self.execute_logic(new_data, 1)
                return response
            except Exception as e:
                logger.warning(f"Error: {e}")
                return None

    async def clear_monitor(self, data):
        key = data.get("position")

        file_name = self.mapping.get(key)
        if file_name:
            try:
                data["logic_path"] = self.data_configs[file_name][key]["logic_path"]
                await self.execute_logic(data, 2)
            except Exception as e:
                logger.warning(f"Error: {e}")

    async def _consumer_loop(self) -> None:
        while True:
            try:
                now = time.time()
                # Dọn dẹp dữ liệu cũ (> 10 phút)
                if getattr(settings, "cluster_enabled", False):
                    for k, value in self._position_state.items():
                        if not self._fresh(value):
                            value["quality"] = "UNKNOWN"
                            self._pending_state.pop(k, None)
                keys_to_del = [k for k, v in self._position_state.items()
                               if now - v.get('ts', 0) > 600 and k not in self._reservations]
                for k in keys_to_del:
                    del self._position_state[k]
                
                await asyncio.sleep(0.5 if getattr(settings, "cluster_enabled", False) else 60)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in manager loop: {e}")
                await asyncio.sleep(1)

pos_manager = Position_Manager(settings.time_recognition)
