import asyncio
import json
from typing import Dict, Set, Any
from fastapi import Request
from fastapi.responses import StreamingResponse
from fastapi import HTTPException
from core.config import settings

class RawSSEManager:
    def __init__(self):
        self.active_queues: Dict[asyncio.Queue, dict] = {} # Lưu queue và metadata

    async def subscribe(self, metadata: dict):
        clustered = settings.cluster_enabled
        if clustered and len(self.active_queues) >= settings.cluster_sse_max_clients:
            raise HTTPException(503, "SSE client limit reached")
        queue = asyncio.Queue(maxsize=settings.cluster_sse_queue_size if clustered else 0)
        self.active_queues[queue] = metadata
        return queue

    def unsubscribe(self, queue: asyncio.Queue):
        if queue in self.active_queues:
            del self.active_queues[queue]

    async def broadcast(self, data: Any, event: str = None, group_id: int = None):
        # Định dạng chuẩn SSE: "event: ...\ndata: ...\n\n"
        msg = f"data: {json.dumps(data)}\n\n"
        if event:
            msg = f"event: {event}\n{msg}"

        for queue, meta in list(self.active_queues.items()):
            # Check lọc theo group_id nếu cần
            if group_id is not None and meta.get("group_id") != group_id:
                continue
            try:
                queue.put_nowait(msg)
            except asyncio.QueueFull:
                # A slow monitor reconnects instead of accumulating messages.
                self.unsubscribe(queue)
                self._close_queue(queue)

    @staticmethod
    def _close_queue(queue):
        while not queue.empty():
            queue.get_nowait()
        queue.put_nowait(None)

    async def disconnect_all(self):
        """Gửi tín hiệu None để đóng tất cả các stream đang chạy"""
        if not self.active_queues:
            return
        
        # Tạo danh sách các queue để tránh lỗi 'dictionary changed size during iteration'
        queues = list(self.active_queues.keys())
        for queue in queues:
            try:
                # Gửi None làm tín hiệu dừng
                self._close_queue(queue)
            except Exception:
                pass
        self.active_queues.clear()

sse_manager = RawSSEManager()
