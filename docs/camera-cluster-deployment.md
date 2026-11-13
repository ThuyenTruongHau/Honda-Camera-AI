# Triển khai camera cluster

Hướng dẫn cài đặt, cấu hình và chuyển boot state đã chuyển về [camera_cluster/README.md](../camera_cluster/README.md).

| Máy | Folder/service | Port mẫu |
|---|---|---|
| Master | camera_cluster — quản lý/chia camera | 8002 |
| Master | logic_service — nghiệp vụ/robot hiện có | 8001 |
| Mỗi AI | ai_service — capture/detect, gửi map điểm | 8000 |

Trên AI đặt CLUSTER_URL trỏ coordinator và AI_DATA_URL trỏ endpoint /ai-data của logic_service. Không dùng một URL cho cả hai vai trò. Trước khi chuyển controller, dừng nguồn cũ, bảo toàn catalog thật và generation trong cluster_boot.json, chờ lease cũ hết; không reset epoch.

Máy AI offline: [hướng dẫn wheelhouse](ai-service-offline-deployment.md). Không thay nghiệp vụ robot để triển khai việc chia camera.
