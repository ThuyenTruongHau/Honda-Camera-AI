# ai_service — Máy xử lý camera theo quyền từ master

Bản hiện hành dùng map điểm theo contract và metadata rút gọn gồm worker_id cùng các cặp camera_id/assignment_epoch. AI chỉ đọc camera master giao và còn lease, không tự phân camera hoặc gọi robot.

Phạm vi đợt đổi format chỉ tới phần gửi HTTP từ AI. Bộ nhận logic_service vẫn dùng v3, chưa được sửa để nhận map điểm mới và sẽ trả 422 cho payload rút gọn. Không triển khai ghép hai format để chạy nghiệp vụ trước khi phần nhận được tích hợp riêng. POS và logic robot không đổi.

## Luồng hoạt động

1. Giữ khóa cục bộ theo WORKER_ID để ngăn instance thứ hai trong cùng bản cài. Khởi động với danh sách camera rỗng; không có session_id.
2. Load model/capture process, đăng ký worker_id với master rồi gửi heartbeat ready.
3. Nhận assignment gồm bốn trường camera_id, owner_worker_id, assignment_epoch, lease_expires_at cùng cấu hình RTSP/ROI.
4. Reconcile mở camera mới, gia hạn quyền camera còn giữ hoặc dừng camera bị bỏ khỏi danh sách/đổi epoch.
5. Capture đọc RTSP trực tiếp, resize 1280×720, giữ frame mới nhất. Detector chạy YOLO, tạo hang/trong cho các ROI xác định được; bỏ điểm không chắc chắn và điểm 10001546.
6. Gửi kết quả JSON về master; không gửi ảnh/video và không tự quyết định nhiệm vụ robot.

AI báo trong heartbeat các cặp camera_id/epoch còn quyền và chưa yêu cầu dừng. Master chỉ gia hạn nếu claim khớp. Camera lỗi process, bị quên hoặc đã từ chối epoch sẽ không được gia hạn chỉ vì máy còn online.

## Khi chuyển camera

Master xóa chủ cũ, giữ nguyên thời điểm hết lease và chờ tới hạn trước khi cấp lại với epoch mới. AI biết bị thu hồi qua danh sách heartbeat hoặc tự hết hạn quyền cục bộ nếu mất mạng.

`_stop_camera()` bỏ quyền ngay để chặn capture/detect/report rồi yêu cầu thread dừng. Không gửi STOPPED lên master; event STOPPED chỉ dùng giữa process con và controller cục bộ. Master luôn dùng hạn lease làm ranh giới chuyển quyền.

Khi AI restart/đăng ký lại, master thu hồi quyền cũ của worker. AI không tự mở danh sách camera trước restart. Epoch cũ bị loại kể cả camera được giao trở lại cho cùng máy.

## Bên trong một máy

`NUM_PROCESS` là số process capture; mỗi camera là một thread trong process, ưu tiên phân vào process ít camera nhất. Một detector process gom frame thành batch. Frame/kết quả cũ có thể bị frame mới thay thế; không tích hàng đợi mọi ảnh.

Ba task controller: `_control_loop()` đăng ký/heartbeat; `_report_loop()` gửi kết quả; `_watchdog_loop()` dừng quyền hết hạn và phục hồi process lỗi. HTTP được tuần tự hóa, không áp dụng hai phản hồi điều khiển chồng nhau.

Quyền cục bộ dùng monotonic deadline tính từ đầu request và trừ biên an toàn. Capture/detector/report đều kiểm tra quyền. Thread đọc RTSP bị treo có thể chưa dừng vật lý ngay, nhưng master không chấp nhận kết quả thuộc chủ/epoch cũ.

## Payload và cấu hình

Body detect giữ key ID điểm tại root, value là label/group_id; `_cluster` chỉ chứa worker_id và cameras. Mỗi camera chỉ có camera_id, assignment_epoch. Không gửi config_version, schema_version, frame_observed_at, inferred_at, point_ids hoặc trường thời gian thay thế. Master cần tra catalog để liên kết điểm với camera khi tích hợp bộ nhận riêng. Chi tiết: [contract AI → logic](../docs/contract-ai-to-logic.md).

Gửi quan sát mới khoảng một giây/lần, kể cả nhãn không đổi. Key điểm chỉ có chữ số, bỏ start_/end_. Chỉ gửi hang/trong; ROI không chắc chắn không đưa vào point map. captured_at chỉ dùng trong RAM AI để chọn/bỏ frame và theo dõi phản hồi, không nằm trong HTTP. Bộ nhận không thể suy ra tuổi frame hoặc nhận diện snapshot gửi lại bằng timestamp từ payload.

| Tham số mẫu | Giá trị |
|---|---|
| WORKER_ID | AI-01 / AI-02 / AI-03 / AI-04, duy nhất toàn hệ thống |
| MASTER_URL | IP LAN master, port 8001 |
| TARGET_FPS | 5 |
| NUM_PROCESS | 4 |
| CLUSTER_HEARTBEAT_INTERVAL | 3 giây, sau đó theo phản hồi master |
| CLUSTER_LEASE_MARGIN | 1 giây |
| CLUSTER_REPORT_INTERVAL | 1 giây |
| CLUSTER_HTTP_TIMEOUT | 2 giây |
| CLUSTER_MAX_FRAME_AGE | 3 giây |

Không dùng cùng WORKER_ID trên hai máy: khóa cục bộ chỉ bảo vệ cùng đường dẫn bản cài, không phải khóa phân tán. Đồng bộ giờ máy để kiểm tra timestamp. Một camera RTSP lỗi được retry tại chỗ; chưa tự chuyển máy chỉ vì thiếu frame. Cluster không cần MongoDB; module legacy chỉ dùng khi CLUSTER_ENABLED=false.

Sau khi bộ nhận format rút gọn được làm riêng, nâng master và cả bốn AI cùng đợt vì nó không tương thích envelope v3 cũ. Cập nhật .env cũ nếu muốn áp dụng chu kỳ 1 giây/timeout 2 giây; giá trị đã đặt trong .env không tự bị ghi đè bởi default mới. Giữ nguyên lease qua nâng cấp hoặc chờ quyền cũ hết sau khi dừng AI.

Các file chính: [cluster_runtime.py](services/cluster_runtime.py), [cluster_capture.py](services/cluster_capture.py), [cluster_detector.py](services/cluster_detector.py), [worker_lock.py](core/worker_lock.py).

Xem [master điều phối](../logic_service/README.md), [phân tích code](../docs/camera-cluster-code-walkthrough.md), [triển khai](../docs/camera-cluster-deployment.md).
