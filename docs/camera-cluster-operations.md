Chạy và kiểm chứng camera cluster bằng file cấu hình và RAM

Cập nhật 11/11/2026: catalog camera nằm trong JSON trên master; ownership RAM mỗi camera chỉ có camera_id, owner_worker_id, assignment_epoch, lease_expires_at. Worker heartbeat/readiness và dữ liệu POS/task nằm riêng trong RAM; không có session/revision/frame_seq/latest_sample trong bộ điều phối. Cluster không kết nối MongoDB, không dùng SQLite. HA master chưa triển khai. Hướng dẫn theo từng máy: [camera-cluster-deployment.md](camera-cluster-deployment.md).

1. Chuẩn bị cấu hình

- Copy logic_service/config/cameras.example.json thành cameras.json, đối chiếu camera thực. File hiện chứa 74 camera và 206 ROI chuyển từ config.py; cần kiểm tra tỷ lệ tọa độ và bổ sung ánh xạ vị trí nghiệp vụ trước khi chạy robot.
- Đặt CLUSTER_CAMERA_CONFIG_PATH=config/cameras.json. Đường dẫn tương đối của camera config và boot state được tính từ logic_service, không phụ thuộc thư mục gọi lệnh.
- JSON nhận mảng camera hoặc object {schema_version: 1, cameras: [...]}. camera_id ổn định, camera_path là URL RTSP, camera_name để hiển thị, enabled, config_version dương, group_id nghiệp vụ và roi.
- Mỗi ROI có name/x1/y1/x2/y2; name là position ID trong config/map_config, duy nhất giữa các camera enabled. Tọa độ dùng ảnh 1280×720. _id dạng chuỗi được chấp nhận thay camera_id; raw Mongo Extended JSON cần chuyển ID sang chuỗi và chỉ giữ các trường được hỗ trợ.
- Catalog nạp lúc startup, chưa hot-reload. Thay RTSP/ROI tăng config_version và restart trong đợt bảo trì. Không sửa file runtime để chia camera bằng tay.
- Giới hạn mặc định: 1.000 camera trong file, 256 ROI/camera, file tối đa 8 MiB. Điều chỉnh giới hạn qua .env theo số camera/ROI thực. Đây là giới hạn dữ liệu, không bảo đảm RAM toàn process dưới 512 MiB.

2. Khởi động

Copy .env.example của mỗi service thành .env hoặc bổ sung các khóa vào cấu hình cũ. Master cần CLUSTER_ENABLED=true, APP_DEBUG=false, token của bốn worker, camera config và boot state path. Giữ CLUSTER_ROBOT_ENABLED=false khi kiểm chứng. AI cần WORKER_ID duy nhất, token tương ứng, MASTER_URL và WEIGHT_PATH đúng model.

Từ logic_service:

```powershell
python -m uvicorn main:app --host 0.0.0.0 --port 8001 --workers 1
```

Từ ai_service trên mỗi AI:

```powershell
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
```

Không --reload hoặc nhiều instance. Một master và mỗi máy AI một instance. Tất cả AI cần truy cập mọi camera có thể được giao và API master. Đồng bộ đồng hồ. AI cluster không import/kết nối MongoDB để khởi động.

3. Boot state và restart master

CLUSTER_BOOT_STATE_PATH mặc định runtime/cluster_boot.json, chỉ chứa version và generation. File nhỏ được flush và thay thế qua file tạm mỗi lần khởi động; không ghi từng frame, heartbeat, task hoặc lịch sử. Generation tạo khoảng epoch mới để không nhận quyền cũ sau restart. File .lock cùng thư mục dùng khóa OS để chặn process khác dùng cùng state path trên cùng máy; không cung cấp khóa phân tán/HA.

Giữ nguyên runtime directory qua nâng cấp. Không xóa, sửa tay, copy boot state của máy khác hoặc khôi phục về generation thấp hơn. File hỏng, file mất sau lần khởi tạo đầu hoặc ghi thất bại khiến startup dừng; không tự reset epoch. Khi cần phục hồi boot state, phải bảo đảm tất cả nguồn AI cũ đã dừng và có quy trình bảo toàn generation phù hợp.

Mỗi lần startup master chờ một khoảng bằng CLUSTER_LEASE_SECONDS (mặc định 15 giây) trước cấp camera; worker cũng phải qua readiness ổn định (10 giây). Sau đó POS cần frame mới và khoảng xác nhận 5 giây. Giữ cùng lease giữa hai lần chạy; nếu giảm lease, phải dừng AI cũ hoặc chờ hết lease cũ trước restart. RAM quan sát/task/reservation không được khôi phục sau process restart. Người dùng chấp nhận khả năng nhiệm vụ cũ được tạo lại trong giai đoạn khôi phục; phiên bản này chưa bảo đảm một ranh giới duy nhất cho toàn bộ task cũ và chưa triển khai swap/HA master.

4. Giám sát và dung lượng

GET /cluster/state?worker_id=AI-01 với Authorization: Bearer <worker-token>. Kết quả có storage=ram, startup_recovery_until, history_size/history_limit, worker last_seen/readiness, counters và cameras chỉ chứa bốn trường quyền; không trả URL hoặc snapshot. 300 camera ổn định chia 75/75/75/75; khi một AI chết thành 100/100/100; khi trở lại cân về bốn máy.

Master không giữ snapshot/cursor trong ownership. Dữ liệu đúng owner/epoch/còn lease và đúng config/ROI/độ mới được áp dụng trực tiếp sang POS; POS dùng timestamp để không áp dụng lại dữ liệu cũ. Khi chuyển camera, master xóa owner nhưng giữ hạn lease cũ; chỉ giao lại khi hết hạn. Không dùng thông báo STOPPED/camera-status. Lịch sử chuyển quyền là ring buffer tối đa CLUSTER_HISTORY_LIMIT (mặc định 1.000), mất khi process dừng. Đặt 0 để không giữ lịch sử; chưa có API xuất lịch sử.

SSE mặc định tối đa 32 client, mỗi client 128 sự kiện chờ trong cluster mode. Client chậm làm đầy queue sẽ bị đóng kết nối thay vì tích lũy vô hạn; client cần reconnect và tải lại trạng thái nghiệp vụ, không có replay SSE trong thay đổi này. File log master dùng một tên cố định, 5 MiB/file và ba backup, khoảng 20 MiB mỗi nhóm logger. Log kiểu cũ có tên ngày không bị xóa tự động bởi thay đổi này.

RAM của task đang chờ và request HTTP đồng thời chưa có hạn mức tổng cứng; task không rõ kết quả cần đối soát, không tự xóa khóa để tiết kiệm RAM. Số đo/budget 512 MiB là dự trù, không phải trần được bảo đảm.

5. Chuyển đổi và hoàn nguyên

Đợt chuyển từ bản Mongo/legacy/v2: sao lưu source/.env/map và catalog, chuẩn bị JSON đúng ID/ROI, dừng mọi AI cũ và chờ lease cũ hết, giữ boot-state rồi nâng master cùng toàn bộ AI. Khởi động master RAM rồi bốn AI. Master hiện nhận envelope v3; thay đổi gửi map điểm + _cluster rút gọn chỉ làm ở AI, chưa tích hợp bộ nhận theo yêu cầu giới hạn phạm vi. Không triển khai ghép hai format khác nhau để chạy nghiệp vụ. Mỗi WORKER_ID chỉ dùng trên một máy/một instance. Chi tiết [contract AI → logic](contract-ai-to-logic.md).

Chỉ bật CLUSTER_ROBOT_ENABLED=true và ICS_HOST đúng khi dữ liệu/luồng nghiệp vụ đã nghiệm thu. Đối soát task trước restart; callback của task đã mất RAM không tự mở khóa task mới. Lỗi gửi RCS timeout giữ reservation trong phiên đang chạy, không tự gửi lại.

Rollback: dừng nhận task mới, dừng AI cluster/chờ hết lease, đối soát robot, giữ boot state rồi mới chạy lại nguồn legacy duy nhất với cấu hình trước. Master RAM không sửa/xóa MongoDB cũ. Mục tiêu camera cuối phục hồi dưới 60 giây chưa đo trên 300 RTSP/model thật. Nhánh PA ba điểm vẫn cần xác nhận quy tắc RCS.
