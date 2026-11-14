# Phân tích code phân chia camera

Phần quản lý camera đã được tách khỏi logic_service sang folder camera_cluster.

- [Kiến trúc, sơ đồ và triển khai](../camera_cluster/README.md)
- [Phân tích từng file/hàm điều phối](../camera_cluster/docs/code-walkthrough.md)
- [AI đọc camera và gửi dữ liệu](../ai_service/README.md)
- [Contract ai_data tới logic_service](contract-ai-to-logic.md)

camera_cluster chỉ xử lý control API, không nhận/chuyển ai_data và không có POS/robot. AI gửi heartbeat tới CLUSTER_URL, gửi map điểm trực tiếp tới logic_service qua AI_DATA_URL. Logic nghiệp vụ và lệnh robot giữ nguyên.

Các thiết kế/session/revision/ingest cũ được ghi trong [nhật ký thay đổi](logic-service-change-log.md), không phải luồng hiện hành.
