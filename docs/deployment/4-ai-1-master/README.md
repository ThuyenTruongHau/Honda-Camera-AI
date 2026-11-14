# Hướng dẫn cài đặt 4 máy AI và 1 máy master

Tài liệu theo source hiện tại, dành cho Windows x64 và PowerShell. Ví dụ đặt code tại `D:\Honda-Camera-AI`, dùng Python 3.10 x64 theo môi trường GPU được ghi trong repo. Thay đường dẫn, IP master và IP ICS/RCS bằng giá trị thực tế trước khi chạy. Đây là hướng dẫn cài đặt; chưa phải kết quả nghiệm thu trên 5 máy đích.

## 1. Phân chia phần mềm và địa chỉ

| Máy | IP ví dụ | Phần mềm cần copy/chạy | Cổng HTTP | Worker ID |
|---|---|---|---|---|
| Master | 192.168.1.10 | `camera_cluster` và `logic_service` | 8002 và 8001 | Không có |
| AI 1 | 192.168.1.21 | `ai_service` và model | 8000 | AI-01 |
| AI 2 | 192.168.1.22 | `ai_service` và model | 8000 | AI-02 |
| AI 3 | 192.168.1.23 | `ai_service` và model | 8000 | AI-03 |
| AI 4 | 192.168.1.24 | `ai_service` và model | 8000 | AI-04 |

Các IP trên chỉ là ví dụ, cần kiểm tra không trùng thiết bị trong LAN. Bốn máy AI đều phải truy cập được **mọi camera có thể được giao**, master:8002 và master:8001. Master phải truy cập ICS/RCS tại `ICS_HOST:7000`; phía ICS/RCS cần truy cập ngược master:8001 nếu sử dụng callback.

```mermaid
flowchart LR
    C[Camera RTSP] --> A[4 máy ai_service :8000]
    A <-->|Đăng ký, heartbeat, phân camera| CC[camera_cluster :8002 trên master]
    A -->|POST /ai-data| L[logic_service :8001 trên master]
    L -->|HTTP :7000| R[ICS/RCS]
    R -->|Callback :8001| L
```

Master chia camera tự động, không cần chia sẵn 4 file camera cho 4 máy AI. AI đọc RTSP trực tiếp. Kết quả detect gửi thẳng tới logic_service. Chế độ này không cần chạy MongoDB hoặc MQTT broker; các package legacy có thể vẫn nằm trong requirements.

## 2. Chuẩn bị code và cấu hình

Chọn cùng một bản source cho cả 5 máy. Repo làm việc có thể chứa thay đổi chưa commit và file chưa được theo dõi; `git clone` một mình có thể thiếu model hoặc cấu hình vận hành. Kiểm tra bộ chuyển giao có đủ các thư mục/file dưới đây.

```text
D:\Honda-Camera-AI\                     # Trên master
  camera_cluster\
    main.py, requirements.txt, core\, api\, schemas\, services\, ...
    .env
    config\cameras.json
    runtime\cluster_boot.json          # Sinh ở lần cài mới; giữ lại khi nâng cấp
  logic_service\
    main.py, requirements.txt, core\, api\, services\, logic\, shared\, ...
    .env
    config\map_config\*.json           # Bao gồm HaNam_config.json nếu dùng Hà Nam
    config\zone_config\*.json
    config\robot_config\*.json
    config\ui_zones.json
  docs\deployment\4-ai-1-master\       # Bộ mẫu trong tài liệu này

D:\Honda-Camera-AI\                     # Trên mỗi máy AI
  ai_service\
    main.py, requirements.txt, requirements-gpu.txt, core\, services\, ...
    .env
    weights\ModelHN_170926.engine
  docs\deployment\4-ai-1-master\       # Để thực hiện các lệnh copy mẫu bên dưới
```

Copy toàn bộ source của service tương ứng, không chỉ các file được liệt kê. Có thể copy cả repo nếu thuận tiện. Tạo venv mới trên từng máy, không copy `.venv`, `.venv-gpu`, `venv`, cache hoặc log từ máy lập trình. Với cài mới, dùng mẫu theo máy bên dưới để tạo `.env`; với cập nhật, sao lưu rồi đối chiếu cấu hình đang vận hành trước khi sửa. Không ghi đè `.env` thực tế bằng mẫu.

### Sáu file .env mẫu

| Mẫu trong bộ tài liệu | Copy tới máy/thư mục đích |
|---|---|
| [master/camera_cluster/.env.example](master/camera_cluster/.env.example) | Master: `camera_cluster/.env` |
| [master/logic_service/.env.example](master/logic_service/.env.example) | Master: `logic_service/.env` |
| [AI-01/.env.example](AI-01/.env.example) | AI 1: `ai_service/.env` |
| [AI-02/.env.example](AI-02/.env.example) | AI 2: `ai_service/.env` |
| [AI-03/.env.example](AI-03/.env.example) | AI 3: `ai_service/.env` |
| [AI-04/.env.example](AI-04/.env.example) | AI 4: `ai_service/.env` |

Không cần `.env` ở gốc repo. Đặt riêng trong mỗi service và luôn chạy lệnh từ đúng thư mục service. AI và logic đọc `.env` theo thư mục làm việc; các biến môi trường của Windows hoặc terminal đã đặt sẵn có thể ghi đè giá trị trong `.env`. Không dùng chung `.env` cho các service.

## 3. Cài master

Cài Python 3.10 x64, kiểm tra `py -3.10 --version`. Master không cần GPU để chạy hai service này. Các lệnh pip bên dưới cần Internet; nếu cài offline, xem mục 9.

### 3.1. Tạo hai môi trường Python

```powershell
Set-Location D:\Honda-Camera-AI\camera_cluster
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check

Set-Location D:\Honda-Camera-AI\logic_service
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
```

Mỗi lệnh cài phải hoàn tất thành công trước khi tiếp tục. `logic_service/requirements.txt` hiện có cả thư viện AI/tiện ích legacy; hướng dẫn dùng nguyên file repo để tránh bỏ sót dependency.

### 3.2. Tạo .env cho master khi cài mới

Chạy tại gốc bộ source, chỉ copy nếu chưa có file đích:

```powershell
Set-Location D:\Honda-Camera-AI
if (-not (Test-Path camera_cluster/.env)) {
    Copy-Item docs/deployment/4-ai-1-master/master/camera_cluster/.env.example camera_cluster/.env
}
if (-not (Test-Path logic_service/.env)) {
    Copy-Item docs/deployment/4-ai-1-master/master/logic_service/.env.example logic_service/.env
}
```

Trong `logic_service/.env`, sửa `ICS_HOST` thành IP controller thực, chỉ ghi IP/hostname, ví dụ `ICS_HOST=192.168.50.39`. Code tự ghép thành `http://<ICS_HOST>:7000`. Giữ `APP_PORT=8001`, `APP_DEBUG=false`. `TIME_RECOGNITION=5` là mặc định thời gian xác nhận nhãn; từng điểm trong map có thể cấu hình thời gian riêng.

Trong `camera_cluster/.env`, giữ `APP_PORT=8002`, heartbeat 3 giây và lease 15 giây. Lease phải lớn hơn hai lần heartbeat. Với bản hiện tại, không cần token hoặc danh sách khai báo sẵn 4 worker.

Mẫu `.env.example` gốc của logic dùng port 8000; bộ mẫu **trong tài liệu này dùng 8001** để khớp `AI_DATA_URL`. Các lệnh uvicorn ghi rõ host/port, vì uvicorn CLI không tự lấy `APP_PORT` của lớp Settings làm cổng chạy.

### 3.3. Cấu hình camera và map nghiệp vụ

Đặt catalog thực tại `camera_cluster/config/cameras.json`. Catalog này có thể bị Git bỏ qua và phải chuyển giao riêng. Định dạng ví dụ, **không dùng tài khoản/địa chỉ minh họa này cho vận hành**:

```json
{
  "schema_version": 1,
  "cameras": [
    {
      "camera_id": "cam-hn-001",
      "camera_name": "HaNam-001",
      "camera_path": "rtsp://USER:PASSWORD@192.168.1.101:554/Streaming/Channels/102",
      "enabled": true,
      "config_version": 1,
      "group_id": "HN",
      "roi": [
        {"name": "10001244", "x1": 100, "y1": 120, "x2": 180, "y2": 220}
      ]
    }
  ]
}
```

`group_id` phải theo nhóm thực tế; ROI đặt theo ảnh **640×480**. `x1,y1,x2,y2` là hai góc hình chữ nhật, không phải `x,y,width,height`. Camera ID duy nhất; tên ROI của camera enabled phải duy nhất toàn catalog. Khi dùng tiền tố `start_`/`end_`, AI chuẩn hóa về ID số khi gửi logic; cần tránh trùng ID sau chuẩn hóa. Point `10001546` đang bị loại khỏi kết quả trong code AI.

Map tại `logic_service/config/map_config/HaNam_config.json` và các file cùng thư mục phải khớp ID điểm được AI gửi. `logic_path` của mỗi cấu hình phải trỏ tới module tương ứng `logic/<logic_path>_logic.py`. Source hiện đọc **mọi file JSON** trong `map_config`; không để bản backup đuôi `.json` trong đó và kiểm tra ID trùng giữa các file vì mapping có thể bị ghi đè. Giữ đủ `zone_config`, `robot_config`, `ui_zones.json` theo nghiệp vụ thực tế.

Kiểm tra catalog bằng loader thực, không in URL camera:

```powershell
Set-Location D:\Honda-Camera-AI\camera_cluster
.\.venv\Scripts\python.exe -c "from core.config import Settings; from core.camera_catalog import load_camera_catalog; s=Settings(); c=load_camera_catalog(s.cluster_camera_config_path, s.cluster_max_cameras, s.cluster_max_rois_per_camera); print('Enabled cameras:', len(c)); print('ROIs:', sum(len(x['roi']) for x in c))"
```

Catalog và map được nạp lúc khởi động; sau khi sửa JSON, khởi động lại service tương ứng theo quy trình bảo trì. Khi AI gửi dữ liệu thật vào logic, logic có thể tự phát sinh lệnh robot theo map; chỉ kết nối luồng dữ liệu thật khi cấu hình nghiệp vụ và controller đã sẵn sàng vận hành.

### 3.4. Firewall và callback

Ví dụ mở inbound trên master trong PowerShell Administrator; thay subnet bằng mạng AI/controller thực tế:

```powershell
New-NetFirewallRule -DisplayName 'Honda coordinator 8002' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8002 -RemoteAddress 192.168.1.0/24
New-NetFirewallRule -DisplayName 'Honda logic 8001' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8001 -RemoteAddress 192.168.1.0/24,192.168.50.0/24
```

Nếu có firewall outbound hoặc VLAN, cho phép AI tới master:8001/8002 và RTSP theo cổng từng camera (thường 554), master tới ICS:7000. HTTP control API hiện không yêu cầu xác thực; giới hạn mạng truy cập theo thiết kế LAN.

Trên ICS/RCS, cập nhật địa chỉ callback đang được hệ thống sử dụng:

- `http://192.168.1.10:8001/task-status`: trạng thái task.
- `http://192.168.1.10:8001/robot-zone`: vị trí robot, nếu dùng tính năng này.
- Các client gọi `/request-ai` hoặc giao diện/SSE phải trỏ tới master:8001 theo luồng tích hợp thực tế.

`ICS_HOST` chỉ cấu hình chiều logic gọi ICS, không tự cấu hình callback bên controller. `CORS_ORIGINS` có trong Settings nhưng `logic_service/main.py` hiện đặt trực tiếp `allow_origins=["*"]`; sửa biến này chưa thay đổi chính sách CORS.

## 4. Cài trên từng máy AI

### 4.1. Python, driver và thư viện GPU

Cài Python 3.10 x64 và NVIDIA driver phù hợp bộ GPU/runtime đã chọn. Kiểm tra:

```powershell
py -3.10 --version
nvidia-smi
Set-Location D:\Honda-Camera-AI\ai_service
py -3.10 -m venv .venv-gpu
.\.venv-gpu\Scripts\python.exe -m pip install --upgrade pip==25.3
.\.venv-gpu\Scripts\python.exe -m pip install --timeout 120 --resume-retries 10 -r requirements-gpu.txt
.\.venv-gpu\Scripts\python.exe -m pip check
.\.venv-gpu\Scripts\python.exe -c "import torch, tensorrt, ultralytics; print('torch', torch.__version__, 'CUDA', torch.version.cuda, 'available', torch.cuda.is_available()); print('TensorRT', tensorrt.__version__, 'Ultralytics', ultralytics.__version__); assert torch.cuda.is_available(); print(torch.cuda.get_device_name(0))"
```

`requirements-gpu.txt` trong repo chốt torch `2.10.0+cu130`, torchvision `0.25.0+cu130`, TensorRT `10.15.1.29`, Ultralytics `8.4.211`; ghi chú môi trường tham chiếu là RTX 3060/driver 591.74. Đây là bộ cấu hình tham chiếu của repo, cần kiểm tra trên GPU/driver thực của cả 4 máy. Không tự nâng TensorRT/PyTorch khi chuyển giao. Nếu pip không cài được TensorRT hoặc thiếu DLL, hoàn tất cài runtime tương ứng trước khi tiếp tục; không dùng môi trường torch CPU để chạy `.engine`.

Engine TensorRT có giới hạn tương thích nền tảng, phiên bản runtime và GPU; không mặc định một engine copy sang GPU khác sẽ chạy được. Xem [NVIDIA Support Matrix](https://docs.nvidia.com/deeplearning/tensorrt/latest/getting-started/support-matrix.html) và [các cặp phiên bản PyTorch chính thức](https://pytorch.org/get-started/previous-versions/). Nếu engine không tải được, cần bộ engine/runtime đã xác nhận cho máy đích hoặc build lại từ đúng model nguồn; file `.pt` cùng tên hiện được ghi nhận là model cũ `hang, qr`, không dùng thay engine chỉ vì cùng tên.

Không cần `--system-site-packages` khi tạo venv sạch theo cách này. Nếu máy đã có TensorRT global, vẫn cần bảo đảm interpreter của service import được đúng TensorRT và chạy được kiểm tra model bên dưới.

### 4.2. Tạo .env đúng máy

Trên AI 1, chạy:

```powershell
Set-Location D:\Honda-Camera-AI
if (-not (Test-Path ai_service/.env)) {
    Copy-Item docs/deployment/4-ai-1-master/AI-01/.env.example ai_service/.env
}
```

Trên AI 2/3/4 thay `AI-01` trong đường dẫn mẫu lần lượt bằng `AI-02`, `AI-03`, `AI-04`. Mỗi máy chỉ chạy **một instance**, ID duy nhất toàn hệ thống. Cùng port 8000 trên các máy khác IP là hợp lệ.

Nội dung quan trọng trong `.env` của từng máy:

```dotenv
APP_PORT=8000
APP_DEBUG=false
CLUSTER_ENABLED=true
WORKER_ID=AI-01
CLUSTER_URL=http://192.168.1.10:8002
AI_DATA_URL=http://192.168.1.10:8001/ai-data
WEIGHT_PATH=weights/ModelHN_170926.engine
```

Thay IP master ở **cả hai URL** trên tất cả AI; không dùng `127.0.0.1` để gọi master từ máy AI. `AI_DATA_URL` cần đầy đủ `/ai-data`, `CLUSTER_URL` là base URL. Giữ `CLUSTER_ENABLED=true`; nếu tắt sẽ quay về luồng legacy và có thể truy cập MongoDB. Không cần đặt `GROUP_ID` để chia máy trong chế độ cluster.

`NUM_PROCESS=4` là số process capture, không phải số máy AI hay số GPU. Code inference hiện chọn GPU `0`; một instance không tự dùng mọi GPU trong máy. FPS 5, batch 16 là giá trị khởi đầu; cần đo tải thật, gồm trường hợp một AI mất kết nối và các máy còn lại nhận thêm camera.

### 4.3. Kiểm tra model trước khi mở camera

```powershell
Set-Location D:\Honda-Camera-AI\ai_service
Get-FileHash weights/ModelHN_170926.engine -Algorithm SHA256
.\.venv-gpu\Scripts\python.exe -c "from core.config import settings; from shared.model_runtime import load_detection_model; load_detection_model(settings.weight_path)"
```

Chạy trên cả 4 máy bằng đúng Python sẽ dùng khởi động service. Loader phải chạy thử frame 640×480, kiểm tra class và ghi `MODEL_READY`. Nếu chuyển cùng engine, đối chiếu checksum. Nếu mỗi loại GPU cần engine riêng, lưu checksum và môi trường tương ứng của từng máy. Lệnh kiểm tra trên không mở camera và không gửi dữ liệu tới logic.

## 5. Khởi động theo thứ tự

Chạy mỗi lệnh service trong một cửa sổ PowerShell riêng, giữ cửa sổ mở trong lần nghiệm thu đầu. Khi triển khai vận hành lâu dài, cấu hình Task Scheduler như mục 8.

**Master, cửa sổ 1 — logic:**

```powershell
Set-Location D:\Honda-Camera-AI\logic_service
.\.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8001 --workers 1
```

**Master, cửa sổ 2 — coordinator:**

```powershell
Set-Location D:\Honda-Camera-AI\camera_cluster
.\.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8002 --workers 1
```

Kiểm tra trên master trước khi chạy AI:

```powershell
Invoke-RestMethod http://127.0.0.1:8001/health
Invoke-RestMethod http://127.0.0.1:8002/health
```

**Trên mỗi máy AI:**

```powershell
Test-NetConnection 192.168.1.10 -Port 8002
Test-NetConnection 192.168.1.10 -Port 8001
Set-Location D:\Honda-Camera-AI\ai_service
.\.venv-gpu\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
```

Không dùng `--reload` hoặc nhiều uvicorn worker cho bất kỳ service nào. Coordinator và logic giữ trạng thái RAM; nhiều process sẽ làm trạng thái/phân quyền hoặc nghiệp vụ không đồng nhất. Không chạy đồng thời hai coordinator cùng bộ camera.

Sau khi model ready, AI đăng ký/heartbeat. Coordinator có thời gian chờ lease khi khởi động và recovery delay 10 giây trước khi cấp camera cho worker đủ điều kiện. Cộng thêm thời gian model và RTSP khởi động; không kết luận lỗi chỉ vì camera chưa được giao ngay.

## 6. Kiểm tra nghiệm thu

### Trên master

```powershell
$state = Invoke-RestMethod http://127.0.0.1:8002/cluster/state
$state.workers | Format-Table worker_id, ready
$state.cameras | Group-Object owner_worker_id | Select-Object Name, Count
$state.cameras | Select-Object camera_id, owner_worker_id, assignment_epoch, lease_expires_at | Format-Table
Test-NetConnection 192.168.50.39 -Port 7000
```

Thay IP ICS ở lệnh cuối theo cấu hình thực. Kiểm tra có đủ `AI-01` đến `AI-04` và mọi camera enabled có owner sau khi hệ thống ổn định. Số camera chia lệch tối đa khoảng một camera khi đủ worker và đã cân bằng; cân bằng theo số lượng, không theo tải GPU.

### Trên từng AI

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
$diag = Invoke-RestMethod http://127.0.0.1:8000/diagnostics/cameras
$diag | Select-Object worker_id, registered, runtime_ready, expected, connected, detecting, all_connected, all_detecting, control_error, delivery_error
$diag.cameras | Format-Table camera_id, camera_name, connected, detecting, frame_age_seconds, detection_age_seconds
Get-ChildItem logs/ai_*.log | Select-String 'MODEL_READY|RTSP_STREAMING|AI_DATA_DELIVERED|CLUSTER_CONTROL_FAILED|AI_DATA_DELIVERY_FAILED'
```

`registered=true` và `/health` thành công chưa đủ chứng minh camera có hình hoặc nhãn đúng. Cần `connected=true`, `detecting=true` cho từng camera và không có delivery error. Đối chiếu hợp các camera ID trên 4 worker với catalog enabled, tránh chỉ cộng số lượng vì có thể trùng hoặc thiếu ID.

Trên master, xem `logic_service/logs/logic_YYYYMMDD.log` có nhận điểm và xử lý đúng map. `/health` của logic hiện chỉ trả trạng thái API, không xác minh map đầy đủ, kết nối ICS hay callback. Nghiệm thu thêm luồng task/callback thực theo kịch bản vận hành đã duyệt.

Để đối chiếu ảnh, bật tạm `DEBUG_SAVE_SNAPSHOTS=true` trong `.env` AI rồi restart. Kiểm tra JPG trong `logs/snapshots/<camera>/`, so ROI và nhãn với thực tế; tắt lại sau khi xong để giảm ghi đĩa. Hướng dẫn chi tiết nằm trong [README AI](../../../ai_service/README.md).

### Thử phân chia lại khi một AI dừng

Trong cửa sổ bảo trì, dừng một AI bằng Ctrl+C, theo dõi `/cluster/state`. Sau khi quyền cũ hết lease, camera được giao cho 3 máy còn lại. Khởi động lại AI và chờ recovery/cân bằng. Với 300 camera, mục tiêu là 75/75/75/75 → 100/100/100 → 75/75/75/75; đây là mục tiêu phân chia, không phải cam kết phần cứng xử lý đủ FPS.

Master hiện là điểm lỗi chung: dừng coordinator khiến AI ngừng camera khi lease hết hạn; dừng logic khiến dữ liệu không được nhận. Bản này chưa có master dự phòng tự động.

## 7. Lỗi thường gặp

| Hiện tượng | Kiểm tra/cách xử lý |
|---|---|
| AI không đăng ký được | IP master trong `CLUSTER_URL`, port 8002, firewall, coordinator đang chạy |
| Có hình/detect nhưng logic không nhận | `AI_DATA_URL` đúng master:8001/ai-data, logic đang chạy, delivery error; khởi động đúng port CLI |
| AI cố kết nối MongoDB | `.env` chưa được đọc hoặc `CLUSTER_ENABLED` đang false; kiểm tra thư mục làm việc và biến môi trường Windows |
| MODEL_FAILED, CUDA false, thiếu TensorRT/DLL | Đúng interpreter `.venv-gpu`, driver/runtime tương thích, engine đúng máy; chạy lại lệnh load model độc lập |
| Model bị từ chối class | Dùng đúng engine class `hang`; kiểm tra SHA-256, không thay bằng `.pt` cũ cùng tên |
| Worker đã đăng ký nhưng chưa có camera | Kiểm tra runtime ready, recovery delay, thời gian chờ lease, catalog có camera enabled |
| RTSP_OPEN_FAILED/READ_FAILED | Kiểm tra từ chính máy AI tới camera: mạng/VLAN, cổng, user/password và đường dẫn stream |
| Nhận điểm nhưng logic không tạo task | ID sau chuẩn hóa có trong map, JSON tải thành công, `logic_path` đúng, điều kiện nghiệp vụ/thời gian xác nhận và kết nối ICS |
| Logic báo thiếu config dù file tồn tại | Chạy từ `logic_service`, kiểm tra đầy đủ thư mục config và log khởi động |
| Camera liên tục chuyển/mất owner | Kiểm tra trùng WORKER_ID, hai instance, heartbeat/network và runtime đang restart |
| Sửa `.env` chưa có tác dụng | Restart service và kiểm tra biến môi trường terminal/Windows ghi đè |

AI không tự đọc toàn bộ catalog trên master để probe. Nếu cần probe bằng `tools/check_cameras.py`, phải chuyển catalog riêng tới máy chạy probe; xem README AI. Camera RTSP đơn lẻ hỏng được retry tại worker, chưa tự chuyển worker chỉ vì mất hình.

## 8. Tự khởi động khi bật máy và nâng cấp

Sau khi chạy thủ công đạt yêu cầu, tạo 2 task trên master và 1 task trên mỗi AI trong Windows Task Scheduler:

| Task | Program/script | Arguments | Start in |
|---|---|---|---|
| Honda-Logic | `D:\Honda-Camera-AI\logic_service\.venv\Scripts\python.exe` | `-m uvicorn main:app --host 0.0.0.0 --port 8001 --workers 1` | `D:\Honda-Camera-AI\logic_service` |
| Honda-Cluster | `D:\Honda-Camera-AI\camera_cluster\.venv\Scripts\python.exe` | `-m uvicorn main:app --host 0.0.0.0 --port 8002 --workers 1` | `D:\Honda-Camera-AI\camera_cluster` |
| Honda-AI trên mỗi AI | `D:\Honda-Camera-AI\ai_service\.venv-gpu\Scripts\python.exe` | `-m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1` | `D:\Honda-Camera-AI\ai_service` |

Chọn trigger **At startup**, tài khoản có quyền đọc code/model và ghi logs/runtime, **Run whether user is logged on or not**, bật restart khi task thất bại và **Do not start a new instance**. Bỏ giới hạn tự dừng sau một khoảng thời gian. Có thể đặt trễ khởi động để đợi mạng; AI tự retry control khi master chưa có. Dừng instance đang chạy thủ công trước khi chạy task. Xác minh lại cả 5 máy sau reboot; Task Scheduler không thay thế việc giám sát `/health` và diagnostics.

Trước nâng cấp, sao lưu `.env`, catalog, toàn bộ config nghiệp vụ và `camera_cluster/runtime/cluster_boot.json`. Giữ file boot state qua nâng cấp/di chuyển master để bảo toàn generation/epoch; cài mới hoàn toàn thì service tự tạo. Khi chuyển master, dừng AI/coordinator cũ, chờ ít nhất lease đã cấu hình, chuyển catalog/boot state và sửa **cả hai URL** trên mọi AI trước khi khởi động lại. Không chạy song song controller cũ và mới. Trạng thái task/position hiện nằm trong RAM; phối hợp bảo trì với luồng robot trước khi restart logic.

## 9. Trường hợp không có Internet

Chuẩn bị Python/driver/runtime và wheelhouse trên máy tương thích trước khi chuyển sang máy đích. Xem [hướng dẫn đóng gói offline](../../ai-service-offline-deployment.md). Thu thập dependency riêng cho AI, coordinator và logic từ môi trường đã kiểm tra, khóa phiên bản, rồi cài thử với `--no-index --find-links`. Không copy nguyên venv thay cho bộ cài. Các lệnh `pip install -r requirements*.txt` trực tuyến ở trên không thể tự chạy offline nếu chưa có đầy đủ wheel.
