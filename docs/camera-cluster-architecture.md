# Kiến trúc camera cluster hiện hành

Kiến trúc và sơ đồ hiện nằm tại [camera_cluster/README.md](../camera_cluster/README.md), cùng code control plane.

```text
Camera RTSP → ai_service trên bốn AI → ai_data → logic_service trên master → Robot
                         ↕ heartbeat / assignment
                   camera_cluster trên master
```

camera_cluster chỉ quản lý/chia camera; không nhận, xử lý hoặc chuyển detect. AI lấy phân công từ CLUSTER_URL (port mẫu 8002), gửi map điểm tới AI_DATA_URL của logic_service (port mẫu 8001). Không có phụ thuộc runtime giữa hai service trên master.

Xem [phân tích code](../camera_cluster/docs/code-walkthrough.md), [contract](contract-ai-to-logic.md), [lịch sử](logic-service-change-log.md).
