# Vận hành camera cluster

Runbook hiện hành nằm tại [camera_cluster/README.md](../camera_cluster/README.md). Camera config và runtime/cluster_boot.json thuộc coordinator; logic_service không giữ/tranh quyền chia camera nữa.

- Health coordinator: http://master:8002/health; xem /cluster/state trực tiếp, không cần token.
- Health logic: http://master:8001/health; ai_data đi thẳng tới /ai-data ở service này.
- Health AI: http://ai:8000/health; mỗi WORKER_ID một instance.
- Đổi RTSP/ROI trên catalog coordinator, bảo toàn boot counter và restart trong đợt bảo trì; AI nhận cấu hình/epoch mới qua heartbeat.
- Giữ generation qua rollback; không khởi động đồng thời controller cũ và mới.

Không có /ai-data hoặc lệnh robot trên coordinator. Các reservation, callback và quyết định nghiệp vụ vẫn thuộc logic_service có sẵn. Xem [contract](contract-ai-to-logic.md) và [nhật ký](logic-service-change-log.md).
