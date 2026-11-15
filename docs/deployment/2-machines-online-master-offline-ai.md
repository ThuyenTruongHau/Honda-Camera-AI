# Hai máy Windows: master có Internet, AI không có Internet

Hướng dẫn dành cho một máy master chạy `logic_service` + `camera_cluster`, và một máy AI đọc camera RTSP, chạy `ai_service`. Máy AI không cần Internet nhưng **phải có LAN tới master và các camera**. Máy tính có Internet dùng để chuẩn bị wheelhouse có thể là máy lập trình hiện tại hoặc master mới.

Trạng thái: đây là quy trình chuẩn bị/cài đặt, chưa phải bộ wheelhouse đã được tạo hoặc kết quả nghiệm thu máy đích. Chưa xác nhận GPU/driver máy đích. Dừng ở bước lỗi, không chạy tiếp các bước sau.

## 1. Chuẩn bị thông tin và file

Ví dụ dùng Windows x64, Python 3.10, code tại `D:\Honda-Camera-AI` trên cả hai máy:

| Máy | IP LAN ví dụ | Chạy |
|---|---|---|
| Master có Internet | 192.168.1.10 | Logic :8001, điều phối :8002 |
| AI không Internet | 192.168.1.21 | AI :8000, WORKER_ID=AI-01 |

Thay các IP bằng mạng thực tế. Master phải gọi được ICS/RCS :7000 và ICS/RCS phải gọi ngược callback master :8001 nếu dùng. Chỉ chạy một coordinator cho bộ camera. Một AI sẽ nhận toàn bộ camera enabled; cần đo tải, không mặc định một GPU xử lý đủ số camera từng chia cho bốn máy.

Trên máy AI đích, thu thập trước:

```powershell
Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, OSArchitecture
nvidia-smi
py -0p
Get-PSDrive -PSProvider FileSystem | Select-Object Name, Used, Free
```

Cần quyền cài Python, driver/runtime; một số bước cần Administrator và restart. Phiên bản tham chiếu trên máy lập trình: Python 3.10.3 x64, Torch 2.10.0+cu130, torchvision 0.25.0+cu130, TensorRT Python 10.15.1.29. Không tự đổi sang Torch CPU nếu tải bản CUDA gặp lỗi.

File cần giữ ngoài Git và chuyển riêng nếu có:

- `camera_cluster/config/cameras.json`: catalog camera thực, chứa URL/tài khoản RTSP.
- `.env` của từng service: cấu hình riêng; máy mới có thể tạo từ mẫu rồi điền lại.
- Config nghiệp vụ tại toàn bộ `logic_service/config/`: map, zone, robot, ui_zones.
- Model `ai_service/weights/ModelHN_170926.engine`: có trong Git ở bản source này, vẫn kiểm tra file và SHA-256 khi chuyển.
- Nếu di chuyển master đang hoạt động: sao lưu `camera_cluster/runtime/cluster_boot.json`; dừng hệ thống cũ theo quy trình bảo trì trước khi chuyển. Cài mới hoàn toàn để service tự tạo file này.

Không đưa catalog có mật khẩu hoặc `.env` thực lên GitHub. Git không chứa các venv và toàn bộ runtime ngoài repo.

## 2. Lấy cùng một bản source

Trên master có Internet, cài Git, clone nhánh đã lưu code hiện tại vào đường dẫn mới chưa tồn tại:

```powershell
git clone --branch duc-local-backup --single-branch https://github.com/ThuyenTruongHau/Honda-Camera-AI.git D:\Honda-Camera-AI
Set-Location D:\Honda-Camera-AI
git rev-parse HEAD
```

Ghi commit để đối chiếu hai máy. Nếu không dùng Git trên AI, từ master tạo ZIP source (gồm file đã commit, không gồm venv/.env/catalog bị ignore):

```powershell
git archive --format=zip --output=D:\Honda-source.zip HEAD
```

## 3. Cài master có Internet

Cài Python 3.10 x64 từ bộ cài chính thức. Kiểm tra `py -3.10 --version`.

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

Giữ nguyên requirements để không loại package. Requirements logic có cả package AI/legacy nên tải nhiều hơn dependency tối thiểu. Master không cần GPU để chạy logic + điều phối.

Tạo cấu hình khi chưa có file đích:

```powershell
Set-Location D:\Honda-Camera-AI
if (-not (Test-Path camera_cluster/.env)) {
    Copy-Item docs/deployment/4-ai-1-master/master/camera_cluster/.env.example camera_cluster/.env
}
if (-not (Test-Path logic_service/.env)) {
    Copy-Item docs/deployment/4-ai-1-master/master/logic_service/.env.example logic_service/.env
}
```

- Sửa `ICS_HOST` trong `logic_service/.env` thành IP ICS/RCS thực, không kèm `http://` hoặc port; logic dùng port 7000.
- Đặt catalog camera thực ở `camera_cluster/config/cameras.json`. Định dạng xem [hướng dẫn cấu hình](4-ai-1-master/README.md#33-cấu-hình-camera-và-map-nghiệp-vụ). ROI theo ảnh 640x480, ID điểm phải khớp config logic.
- Kiểm tra toàn bộ map nghiệp vụ. Không để file backup đuôi `.json` trong `map_config` vì code đọc mọi JSON trong thư mục này.
- Chế độ cluster này không cần cài MongoDB hoặc MQTT broker.

Kiểm tra catalog mà không in URL camera:

```powershell
Set-Location D:\Honda-Camera-AI\camera_cluster
.\.venv\Scripts\python.exe -c "from core.config import Settings; from core.camera_catalog import load_camera_catalog; s=Settings(); c=load_camera_catalog(s.cluster_camera_config_path, s.cluster_max_cameras, s.cluster_max_rois_per_camera); print('Enabled cameras:', len(c)); print('ROIs:', sum(len(x['roi']) for x in c))"
```

Mở PowerShell Administrator trên master, thay subnet theo LAN thực:

```powershell
New-NetFirewallRule -DisplayName 'Honda coordinator 8002' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8002 -RemoteAddress 192.168.1.0/24
New-NetFirewallRule -DisplayName 'Honda logic 8001' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8001 -RemoteAddress 192.168.1.0/24,192.168.50.0/24
```

ICS/RCS cần cấu hình callback tới `http://192.168.1.10:8001/task-status` và `/robot-zone` nếu dùng; sửa `ICS_HOST` không tự sửa callback trên ICS/RCS.

## 4. Chuẩn bị bộ AI trên máy có Internet trước khi chuyển

Thực hiện trên **máy lập trình hiện tại**, tại gốc repo có `.venv-gpu` đã kiểm tra. Master mới clone code chưa có venv này. Các đường dẫn Torch/TensorRT dưới đây là nguồn thực đã tìm thấy trên máy lập trình, không phải đường dẫn mặc định mọi máy.

Mỗi lần release dùng thư mục mới; không trộn wheel của nhiều lần chuẩn bị. Tên ví dụ `Honda-AI-offline-01` phải chưa tồn tại.

```powershell
if (Test-Path Honda-AI-offline-01) { throw 'Thu muc da ton tai: chon ten release moi' }
New-Item -ItemType Directory Honda-AI-offline-01/wheelhouse,Honda-AI-offline-01/installers,Honda-AI-offline-01/runtime | Out-Null
.\.venv-gpu\Scripts\python.exe -m pip check
.\.venv-gpu\Scripts\python.exe -m pip list --format=freeze --disable-pip-version-check |
    Set-Content -Encoding ascii Honda-AI-offline-01/requirements-gpu.lock

Copy-Item -LiteralPath 'ai_service/runtime/wheels/torch-2.10.0+cu130-cp310-cp310-win_amd64.whl' -Destination Honda-AI-offline-01/wheelhouse
Copy-Item -LiteralPath 'D:/Programs/TensorRT-10.15.1.29/python/tensorrt-10.15.1.29-cp310-none-win_amd64.whl' -Destination Honda-AI-offline-01/wheelhouse
Copy-Item -LiteralPath 'D:/Programs/TensorRT-10.15.1.29' -Destination Honda-AI-offline-01/runtime -Recurse

.\.venv-gpu\Scripts\python.exe -m pip download --only-binary=:all: --find-links Honda-AI-offline-01/wheelhouse --extra-index-url https://download.pytorch.org/whl/cu130 --dest Honda-AI-offline-01/wheelhouse -r Honda-AI-offline-01/requirements-gpu.lock
if ($LASTEXITCODE -ne 0) { throw 'Chua du wheel: khong chuyen bo cai nay' }
```

`pip list --format=freeze` giữ cả pip/setuptools và package global mà venv nhìn thấy, dùng dạng tên==phiên_bản thay vì đường dẫn `file:///...`. Không dùng `--local` vì TensorRT hiện nằm ngoài venv. Đây là snapshot phiên bản, không thay thế việc kiểm chứng artifact/source của package. Nếu thiếu wheel, build package đó trên máy online bằng `pip wheel --wheel-dir ...`, rồi cài thử lại; không chép source distribution sang rồi mong máy offline tải build dependencies.

Thêm các file sau vào bộ trước khi chuyển:

- `Honda-source.zip` từ đúng commit ở bước 2. Có thể tạo bằng `git archive` trên máy lập trình từ cùng commit.
- Bộ cài đầy đủ Python 3.10 x64, ưu tiên đúng 3.10.3 của nguồn đã kiểm thử, không dùng web installer; lưu trong `installers`.
- Bộ cài NVIDIA driver offline phù hợp GPU và Windows máy đích, hỗ trợ CUDA của Torch đã chọn.
- Bộ cài Microsoft Visual C++ Redistributable x64 phù hợp runtime, lưu trong `installers`.
- Cấu hình cần thiết được chuyển riêng, bảo quản như dữ liệu có mật khẩu.
- Nếu cần dự phòng build lại engine: model nguồn đúng bản + bộ công cụ/dependency build đã thử offline. File `.pt` cùng tên trong repo được ghi nhận là model cũ khác class, không tự dùng thay thế engine.

Không cần mang `.venv` CPU sang máy AI chạy engine. Giữ toàn bộ package của `.venv-gpu` trong bộ GPU. Bộ CPU độc lập là bộ riêng nếu cần; phần này chỉ hướng dẫn bộ cần cho máy AI offline.

## 5. Cài thử offline trên máy chuẩn bị

Tạo venv mới chưa tồn tại, không dùng `--system-site-packages`:

```powershell
py -3.10 -m venv .venv-ai-offline-check
.\.venv-ai-offline-check\Scripts\python.exe -m pip --disable-pip-version-check install --no-index --find-links Honda-AI-offline-01/wheelhouse --only-binary=:all: -r Honda-AI-offline-01/requirements-gpu.lock
if ($LASTEXITCODE -ne 0) { throw 'Cai offline that bai' }
.\.venv-ai-offline-check\Scripts\python.exe -m pip check
.\.venv-ai-offline-check\Scripts\python.exe -m pip list --format=freeze --disable-pip-version-check |
    Set-Content -Encoding ascii Honda-AI-offline-01/installed-test.lock
Compare-Object (Get-Content Honda-AI-offline-01/requirements-gpu.lock) (Get-Content Honda-AI-offline-01/installed-test.lock)
```

Đối chiếu package không được có phiên bản thiếu/khác chưa giải thích. Khi thử GPU, ưu tiên PATH của TensorRT đóng gói theo bước 7. Máy chuẩn bị có runtime global nên test tại đây vẫn chưa chứng minh toàn bộ DLL độc lập; máy đích cần chạy lại kiểm tra và model. Không gọi bộ này đã nghiệm thu cho GPU đích khi chưa thử ở đó.

Sau khi bộ cài đầy đủ, tạo manifest checksum tại gốc bộ:

```powershell
Push-Location Honda-AI-offline-01
$bundleRoot = (Get-Location).Path
Get-ChildItem -Recurse -File | Where-Object Name -ne 'SHA256SUMS.csv' | ForEach-Object {
    [pscustomobject]@{Path=$_.FullName.Substring($bundleRoot.Length + 1); SHA256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash}
} | Export-Csv SHA256SUMS.csv -NoTypeInformation -Encoding UTF8
Pop-Location
```

Mang **toàn bộ `Honda-AI-offline-01`** bằng USB/ổ cứng/LAN; không chỉ mang wheelhouse. Trên AI, đối chiếu manifest trước khi cài:

```powershell
Set-Location D:\Honda-AI-offline-01
Import-Csv SHA256SUMS.csv | ForEach-Object {
    if (-not (Test-Path -LiteralPath $_.Path)) { throw "Thieu file: $($_.Path)" }
    if ((Get-FileHash -LiteralPath $_.Path -Algorithm SHA256).Hash -ne $_.SHA256) { throw "Sai checksum: $($_.Path)" }
}
```

## 6. Cài máy AI không Internet

1. Cài Python từ installer mang theo; kiểm tra `py -3.10 --version` và kiến trúc x64.
2. Kiểm tra/cài NVIDIA driver phù hợp, restart nếu installer yêu cầu. `nvidia-smi` phải nhận đúng GPU. Nếu driver hiện có đã phù hợp thì không cần thay.
3. Cài Visual C++ Runtime x64 khi cần. Giữ thư mục TensorRT đóng gói tại `D:\Honda-AI-offline-01\runtime\TensorRT-10.15.1.29`.
4. Giải nén `Honda-source.zip` vào `D:\Honda-Camera-AI` mới chưa có code cũ. Không ghi đè `.env`/config của bản đang chạy.
5. Tạo môi trường và cài toàn bộ thư viện từ file, không cần Internet:

```powershell
Set-Location D:\Honda-Camera-AI\ai_service
py -3.10 -m venv .venv-gpu
.\.venv-gpu\Scripts\python.exe -m pip --disable-pip-version-check install --no-index --find-links D:\Honda-AI-offline-01\wheelhouse --only-binary=:all: -r D:\Honda-AI-offline-01\requirements-gpu.lock
if ($LASTEXITCODE -ne 0) { throw 'Cai offline that bai' }
.\.venv-gpu\Scripts\python.exe -m pip check
```

Không chạy `pip install -r requirements-gpu.txt` trực tuyến trên máy offline. Không bật system-site-packages để che lỗi thiếu package.

## 7. Cấu hình AI và kiểm tra GPU/model

Tạo `.env` khi chưa có:

```powershell
Set-Location D:\Honda-Camera-AI
if (-not (Test-Path ai_service/.env)) {
    Copy-Item docs/deployment/4-ai-1-master/AI-01/.env.example ai_service/.env
}
```

Sửa trong `ai_service/.env`:

```dotenv
APP_DEBUG=false
CLUSTER_ENABLED=true
WORKER_ID=AI-01
CLUSTER_URL=http://192.168.1.10:8002
AI_DATA_URL=http://192.168.1.10:8001/ai-data
WEIGHT_PATH=weights/ModelHN_170926.engine
```

IP phải là IP LAN của master, không dùng localhost. Một AI vẫn dùng chế độ cluster, không đổi sang legacy. Không cần Internet để đăng ký và gửi dữ liệu trên LAN.

Trong **mỗi cửa sổ chạy kiểm tra hoặc chạy AI**, đặt runtime đóng gói trước các runtime khác trong PATH:

```powershell
$trtRoot = 'D:\Honda-AI-offline-01\runtime\TensorRT-10.15.1.29'
$env:PATH = "$trtRoot\bin;$trtRoot\lib;$env:PATH"
Set-Location D:\Honda-Camera-AI\ai_service
.\.venv-gpu\Scripts\python.exe -c "import torch,tensorrt; print('Torch',torch.__version__,'CUDA',torch.version.cuda); print('TensorRT',tensorrt.__version__,tensorrt.__file__); assert torch.cuda.is_available(); print(torch.cuda.get_device_name(0))"
Get-FileHash weights/ModelHN_170926.engine -Algorithm SHA256
.\.venv-gpu\Scripts\python.exe -c "from shared.model_runtime import load_detection_model; load_detection_model('weights/ModelHN_170926.engine'); print('PASS: model load and inference')"
```

Loader chạy inference ảnh đen và kiểm tra class, chưa mở camera hoặc gửi dữ liệu tới logic. Chỉ import TensorRT hoặc CUDA true chưa chứng minh engine tương thích. Nếu engine không load trên GPU đích, cần đúng engine hoặc build lại từ model nguồn đã xác nhận. Không thay bằng `.pt` cũ cùng tên.

## 8. Chạy hệ thống và kiểm tra LAN

Mỗi service một cửa sổ PowerShell, dùng một worker, không `--reload`.

Master, cửa sổ 1:

```powershell
Set-Location D:\Honda-Camera-AI\logic_service
.\.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8001 --workers 1
```

Master, cửa sổ 2:

```powershell
Set-Location D:\Honda-Camera-AI\camera_cluster
.\.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8002 --workers 1
```

Master, cửa sổ kiểm tra:

```powershell
Invoke-RestMethod http://127.0.0.1:8001/health
Invoke-RestMethod http://127.0.0.1:8002/health
```

AI: xác nhận cấu hình nghiệp vụ và controller đã sẵn sàng trước khi chạy, vì dữ liệu AI thật có thể làm logic phát sinh lệnh robot. Chạy các dòng PATH ở bước 7 trong cùng cửa sổ rồi:

```powershell
Test-NetConnection 192.168.1.10 -Port 8001
Test-NetConnection 192.168.1.10 -Port 8002
# Thay IP/cổng bằng camera thực, kiểm tra từ chính máy AI.
Test-NetConnection 192.168.1.101 -Port 554
Set-Location D:\Honda-Camera-AI\ai_service
.\.venv-gpu\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
```

TCP thành công chưa chứng minh URL/tài khoản RTSP đúng. Chờ model ready, worker đăng ký, lease/recovery delay rồi kiểm tra:

```powershell
# Trên master
$state = Invoke-RestMethod http://127.0.0.1:8002/cluster/state
$state.workers | Format-Table worker_id,ready
$state.cameras | Select-Object camera_id,owner_worker_id | Format-Table

# Trên AI
Invoke-RestMethod http://127.0.0.1:8000/health
$diag = Invoke-RestMethod http://127.0.0.1:8000/diagnostics/cameras
$diag | Select-Object worker_id,registered,runtime_ready,expected,connected,detecting,all_connected,all_detecting,control_error,delivery_error
$diag.cameras | Format-Table camera_id,connected,detecting,frame_age_seconds,detection_age_seconds
```

Đạt khi AI-01 ready, mọi camera enabled được giao, có hình/detect mới, không có lỗi gửi dữ liệu. Xem log logic nhận đúng ID/map, thử ảnh thật/ROI và kịch bản task/callback đã thống nhất. `/health` riêng lẻ chưa chứng minh toàn bộ luồng chạy đúng.

## 9. Tự khởi động và lỗi thường gặp

Chỉ cấu hình tự khởi động sau khi chạy thủ công đạt. Xem [Task Scheduler](4-ai-1-master/README.md#8-tự-khởi-động-khi-bật-máy-và-nâng-cấp): hai task master, một task AI. AI phải dùng wrapper `.cmd`/`.ps1` đặt PATH TensorRT như bước 7 rồi mới chạy Python; PATH đã đặt trong cửa sổ thử không tự truyền sang task. Đặt working directory đúng service, một instance, không giới hạn thời gian chạy, restart khi lỗi. Kiểm tra lại sau reboot.

| Lỗi | Kiểm tra |
|---|---|
| Pip tìm Internet trên AI | Dùng đúng lệnh `--no-index --find-links`, lock không có URL/file đường dẫn máy nguồn |
| Thiếu wheel | Bổ sung/build trên máy online và cài thử lại trước khi chuyển |
| CUDA false | Đúng Python GPU, Torch CUDA, driver hỗ trợ GPU/runtime |
| TensorRT/DLL lỗi | Wheel đúng Python x64, runtime đúng phiên bản, PATH đúng trong tiến trình chạy |
| Engine lỗi version/GPU/class | Không đổi model tùy ý; dùng engine đúng hoặc build lại từ nguồn đã xác nhận |
| Không đăng ký worker | LAN/master IP, cổng 8002, firewall, CLUSTER_ENABLED=true |
| Không gửi dữ liệu | AI_DATA_URL có `/ai-data`, logic chạy :8001, xem delivery_error |
| Worker ready nhưng camera lỗi | RTSP URL/tài khoản, LAN/VLAN, tải GPU và diagnostics camera |
| Nhận dữ liệu nhưng task sai/không có | Map, logic_path, ID, thời gian xác nhận, kết nối ICS và callback |

Nguồn tham khảo: [pip cài package cục bộ](https://pip.pypa.io/en/stable/user_guide/#installing-from-local-packages), [NVIDIA TensorRT installation](https://docs.nvidia.com/deeplearning/tensorrt/latest/installing-tensorrt/installing.html), [tương thích engine](https://docs.nvidia.com/deeplearning/tensorrt/latest/inference-library/engine-compatibility.html).
