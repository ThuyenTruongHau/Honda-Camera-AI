Triển khai một master và bốn máy AI bằng file cấu hình và RAM

Cập nhật 11/11/2026: ownership bốn trường, bộ nhận master hiện dùng detect v3. Phía gửi AI đã có thay đổi map điểm + _cluster rút gọn theo [contract](contract-ai-to-logic.md); phần nhận format rút gọn chưa triển khai theo yêu cầu chỉ làm phía gửi. Chưa triển khai AI mới cùng master v3 để chạy nghiệp vụ. Ví dụ Windows/PowerShell, source ở D:/Honda-Camera-AI, IP master 192.168.1.10; thay bằng địa chỉ/đường dẫn thật. HA master chưa triển khai. Trong cluster mode không cần MongoDB hoặc SQLite.

Khi nâng từ bản v2/v3: dừng bốn AI và chờ hết lease cũ, giữ boot-state master, cập nhật master cùng mọi AI rồi khởi động lại. Không trộn phiên bản. Mỗi WORKER_ID phải duy nhất trên toàn hệ thống; khóa AI cục bộ chỉ chặn instance cùng đường dẫn bản cài, không phát hiện trùng ID trên hai máy. Đặt CLUSTER_REPORT_INTERVAL=1 và CLUSTER_HTTP_TIMEOUT=2 trong .env AI nếu muốn áp dụng chu kỳ/timeout mới; .env có sẵn không tự cập nhật.

1. Bố trí

| Máy | Service | Cấu hình riêng |
|---|---|---|
| Master | logic_service | cameras.json chứa toàn bộ camera, worker tokens, map/robot config |
| AI 1 | ai_service | WORKER_ID=AI-01, token 1, model |
| AI 2 | ai_service | WORKER_ID=AI-02, token 2, model |
| AI 3 | ai_service | WORKER_ID=AI-03, token 3, model |
| AI 4 | ai_service | WORKER_ID=AI-04, token 4, model |

Copy cùng source mới lên năm máy, gồm các module cluster mới. Không copy .env, virtualenv hoặc credential giữa các máy. Bốn AI cần truy cập API master và mọi camera. Đồng bộ đồng hồ. Master cần truy cập ICS/RCS khi bật robot; port 8000 trên AI dùng kiểm tra health, master không gọi AI để giao camera.

2. Chuẩn bị master

Từ môi trường Python đang chạy được dự án hoặc tạo virtualenv mới:

```powershell
Set-Location D:/Honda-Camera-AI/logic_service
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
Copy-Item config/cameras.example.json config/cameras.json
```

Chỉ copy khi tạo file mới. Nếu đã có .env/cameras.json, sao lưu và chỉnh file đó thay vì ghi đè. requirements.txt cũ còn chứa dependency của dự án; cluster runtime không import MongoDB hay thư viện inference trên master. Giữ config/map_config và cấu hình robot/zone thực.

File hiện có 74 camera/206 ROI chuyển từ config.py; đối chiếu danh sách thực, tỷ lệ tọa độ 1280×720 và bổ sung map nghiệp vụ còn thiếu. ROI name phải khớp position ID trong map nghiệp vụ; group_id không chỉ định máy AI. Ví dụ một phần tử:

```json
{
  "camera_id": "CAM-001",
  "camera_name": "Camera 01",
  "camera_path": "rtsp://192.168.10.101/stream",
  "enabled": true,
  "config_version": 1,
  "group_id": 1,
  "roi": [{"name": "POSITION-001", "x1": 0, "y1": 0, "x2": 400, "y2": 400}]
}
```

Đặt phần tử trong mảng cameras của file mẫu. Không đưa credential thật vào git; cameras.json đã được ignore. Master nạp file khi startup, chưa hot-reload. Nếu chuyển từ catalog MongoDB, giữ camera ID dưới dạng chuỗi, giữ ROI/map và chỉ lấy các trường trong schema được hỗ trợ. Không cần di chuyển dữ liệu runtime cũ.

Các khóa chính trong master .env:

```dotenv
APP_DEBUG=false
CLUSTER_ENABLED=true
CLUSTER_ROBOT_ENABLED=false
CLUSTER_CAMERA_CONFIG_PATH=config/cameras.json
CLUSTER_BOOT_STATE_PATH=runtime/cluster_boot.json
CLUSTER_WORKER_TOKENS={"AI-01":"TOKEN_1","AI-02":"TOKEN_2","AI-03":"TOKEN_3","AI-04":"TOKEN_4"}
CLUSTER_HEARTBEAT_INTERVAL=3
CLUSTER_LEASE_SECONDS=15
CLUSTER_RECOVERY_DELAY=10
CLUSTER_HISTORY_LIMIT=1000
```

Thay token placeholder bằng chuỗi riêng. MONGO_URL/MONGO_DB không còn được master cluster dùng. Kiểm tra file mà không mở camera:

```powershell
./.venv/Scripts/python.exe -c "from core.config import settings; from core.camera_catalog import load_camera_catalog; cams=load_camera_catalog(settings.cluster_camera_config_path, settings.cluster_max_cameras, settings.cluster_max_rois_per_camera); print('Enabled cameras:', len(cams))"
```

Khởi động từ logic_service để map/robot config tương đối được tìm thấy:

```powershell
./.venv/Scripts/python.exe -m uvicorn main:app --host 0.0.0.0 --port 8001 --workers 1
```

Không --reload, không nhiều instance. Khóa OS chỉ chặn process dùng cùng boot-state path trên cùng máy. Giữ runtime directory qua các lần nâng cấp, không xóa/sửa/reset bộ đếm. Master chờ lease 15 giây trước phân công sau startup; đây không phải thời gian chờ khóa MongoDB như bản trước.

3. Chuẩn bị từng AI

Dùng môi trường Torch/CUDA đang chạy đúng model thực. Nếu tạo môi trường mới:

```powershell
Set-Location D:/Honda-Camera-AI/ai_service
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Không ghi đè .env cũ khi chưa sao lưu. Trên AI 1:

```dotenv
APP_DEBUG=false
CLUSTER_ENABLED=true
WORKER_ID=AI-01
WORKER_TOKEN=TOKEN_1
MASTER_URL=http://192.168.1.10:8001
WEIGHT_PATH=D:/Models/honda.pt
NUM_PROCESS=4
TARGET_FPS=5
```

Trên AI 2/3/4, đổi ID và token tương ứng ở master. Copy đúng model đã huấn luyện lên mỗi máy; không thay bằng model mặc định. NUM_PROCESS là số process capture trong một máy. SESSION_ID tự sinh, danh sách camera nhận từ master; GROUP_ID cũ không giới hạn camera cluster.

```powershell
./.venv/Scripts/python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
```

Mỗi máy một instance. Để chuyển từ bản cũ, dừng toàn bộ AI cũ trước, sau đó chạy master RAM và khởi động lại bốn AI bằng cấu hình cluster.

4. Kiểm tra

```powershell
Invoke-RestMethod http://192.168.1.10:8001/health
$clusterHeaders = @{ Authorization = 'Bearer TOKEN_1' }
$clusterState = Invoke-RestMethod 'http://192.168.1.10:8001/cluster/state?worker_id=AI-01' -Headers $clusterHeaders
$clusterState.storage
$clusterState.cameras | Group-Object owner_worker_id | Select-Object Name, Count
$clusterState.cameras | Select-Object camera_id, owner_worker_id, assignment_epoch, lease_expires_at
```

storage phải là ram. Trên từng AI chạy `Invoke-RestMethod http://127.0.0.1:8000/health`; model chưa sẵn sàng có thể trả 503. Sau ổn định, 300 camera chia 75/75/75/75; với 74 camera là 19/19/18/18. Camera owner=null và lease_expires_at còn ở tương lai đang chờ quyền cũ hết trước khi giao lại. State API chỉ trả bốn trường quyền, không trả frame sequence/độ mới detect.

Giữ robot tắt để thử dừng AI-01, chờ chuyển thành 100/100/100; bật lại và chờ 75/75/75/75. Thử restart master: task/camera state mất RAM, AI đăng ký lại và nhận epoch mới sau lease grace, dữ liệu cũ không được áp dụng. Camera cần xác nhận trạng thái mới trước tạo task.

5. Vận hành

- Thử riêng với catalog test trước. Giữ CLUSTER_ROBOT_ENABLED=false đến khi dữ liệu, callback và nghiệp vụ được nghiệm thu.
- Sau đó đặt ICS_HOST đúng controller, bật CLUSTER_ROBOT_ENABLED=true và restart trong đợt bảo trì đã đối soát task. Task chưa lưu bền; người dùng chấp nhận khả năng tạo lại nhiệm vụ trong giai đoạn khôi phục.
- Khi chọn port master, giữ URL callback robot hiện có hoặc đổi MASTER_URL/callback tương ứng. Master hiện vẫn kiểm tra envelope v3; map điểm + _cluster rút gọn phía AI cần bộ nhận phù hợp trước khi triển khai chung. Phần xử lý nghiệp vụ/robot không đổi.
- Dùng cơ chế quản lý tiến trình của máy với executable Python tuyệt đối, working directory đúng và một instance. Không tạo job trùng WORKER_ID. Chưa cấu hình VIP, standby, witness hay đồng bộ master trong đợt này.
- Log master mới xoay theo kích thước. Giữ boot-state file nhỏ; không lưu từng detect xuống đĩa. Task không rõ kết quả cần đối soát; nhánh PA ba điểm vẫn cần xác nhận contract RCS.

Runbook/rollback: [camera-cluster-operations.md](camera-cluster-operations.md). Nhật ký: [logic-service-change-log.md](logic-service-change-log.md). Bộ kiểm thử, giả lập và kết quả thử đã được xóa theo yêu cầu dọn dự án; các lệnh tools trước đây không còn áp dụng.
