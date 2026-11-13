# Code điều phối camera độc lập

Folder camera_cluster chỉ có control plane; không nhận ai_data, không import logic_service/ai_service/POS hoặc robot. Các import core/services/schemas/repositories là module bên trong chính service, chạy từ working directory camera_cluster.

## File và hàm

| File/hàm | Hoạt động |
|---|---|
| main.lifespan() | Validate cấu hình một process; start/stop controller độc lập |
| main.root()/health() | Nhận diện service và kiểm tra vòng điều phối |
| core/config.Settings.validate_runtime() | Kiểm tra timeout lease, đường dẫn, không debug/reload |
| core/camera_catalog.service_path() | Tính đường dẫn tương đối từ camera_cluster |
| core/camera_catalog.Region.rectangle() | Kiểm tra tên ROI và tọa độ hữu hạn, hình chữ nhật hợp lệ |
| core/camera_catalog.load_camera_catalog() | Đọc JSON giới hạn dung lượng/camera/ROI, kiểm tra ID/ROI không trùng, lọc enabled |
| core/local_master_session.LocalMasterSession.open() | Giữ khóa OS và tăng generation qua file nhỏ ghi đè |
| LocalMasterSession.epoch_base | generation × 2^32 |
| LocalMasterSession.close() | Nhả khóa OS, giữ file generation |
| repositories/cluster_repository.load_catalog()/list_cameras()/get_camera() | Trả bản copy catalog/quyền trong RAM |
| RamClusterRepository.save_camera() | Chỉ nhận đúng bốn trường ownership và epoch thuộc generation hiện tại |
| RamClusterRepository.event()/close() | History deque giới hạn; không có DB để đóng |
| api/cluster.invoke() | Gọi runtime và chuyển lỗi thành HTTP error; không yêu cầu token |
| api/cluster.register()/heartbeat()/state() | Các HTTP route chỉ phục vụ quản lý camera |

## services/cluster_runtime.py

| Hàm | Tác động |
|---|---|
| ClusterError.__init__() | Mã lỗi/thông báo control API |
| ClusterRuntime.__init__() | Giữ repo/settings/clock, workers/catalog, control lock và health. Không có tham số positions/POS |
| require_ready() | Chỉ thao tác khi vòng điều phối còn healthy/deadline hợp lệ |
| _save_camera() | Ghi row bốn trường, thêm history nếu có reason |
| _revoke() | Xóa owner, giữ hạn lease cũ. Không invalidate POS hoặc tác động nghiệp vụ |
| start() | Load catalog; mỗi camera owner=null, epoch=epoch_base, lease=thời điểm hết chờ startup; tạo loop |
| stop() | Hủy loop, đóng repo và khóa OS |
| _loop() | Tick theo chu kỳ; lỗi thì ngừng điều phối và unhealthy |
| _worker() | Yêu cầu worker đã register |
| register() | Thu hồi quyền trước của worker, reset readiness; nhận lại từ trạng thái trống |
| heartbeat() | Cập nhật last_seen/ready/ready_since, gia hạn claim đúng chủ/epoch/còn hạn; trả assignments |
| _response() | Ghép config RTSP/ROI với row quyền hiện tại, chỉ trả camera đúng chủ/còn lease |
| tick() | Thu hồi quyền hết hạn, chọn worker đủ điều kiện, chia camera trống đã hết hàng rào lease, thu hồi phần dư để cân lại |
| state() | Trả quyền/worker/history chẩn đoán; không có snapshot detect |
| get_runtime() | Lấy singleton controller trong service này |
| start_runtime() | Load file, mở boot state/khóa, tạo repo và start controller; không nhận đối tượng POS |

Không có ingest(), _project(), schema detection hoặc route /ai-data trong camera_cluster.

## Từng bước của tick

1. Chọn eligible theo ready, heartbeat chưa quá lease và ready ổn định đủ recovery delay.
2. Thu hồi owner có lease hết; owner trở thành null.
3. Tính target N//M, phần dư chia thêm một camera cho các worker đầu theo ID.
4. Với camera owner=null và lease<=now, chọn máy chưa đủ target đang ít camera nhất; tăng epoch, cấp lease mới.
5. Chủ còn dư bị thu hồi một phần camera, tối đa rebalance batch/tick. Giữ lease cũ làm mốc chờ, không cấp cho chủ mới ngay.

Giữa bước 5 và lần cấp mới, AI cũ dừng theo phản hồi heartbeat không còn camera hoặc hết authority deadline. Coordinator không chờ STOPPED và không nhận frame để điều phối.

## Phía AI và nghiệp vụ

- AI _control_loop dùng CLUSTER_URL để register/heartbeat; reconcile mở/dừng camera theo assignment.
- AI capture/detector giữ dữ liệu mới nhất và kiểm tra authority; watchdog dừng lượt cũ khi quyền hết.
- AI _report_loop dùng AI_DATA_URL và HTTP client riêng. build_logic_payload() tạo map điểm thuần; thông tin quyền không được đưa vào body của logic_service.
- logic_service nhận map đó qua update_state() có sẵn. Không sửa thuật toán xác nhận trạng thái, logic tự động, callback hoặc lệnh robot để thực hiện việc chia camera.

Hai URL phải trỏ đúng service. Coordinator /ai-data trả 404. Khi đích dữ liệu lỗi, việc đó không buộc AI register lại với coordinator.
