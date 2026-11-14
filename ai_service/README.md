# ai_service — Đọc camera và xuất kết quả detect

Chạy trên từng máy AI Windows/NVIDIA. Không cần cài camera_cluster hoặc logic_service trên máy AI. Mỗi máy một WORKER_ID/instance duy nhất; kết nối coordinator không dùng token.

## Hai kết nối tách biệt

| Cấu hình | Đích | Dữ liệu |
|---|---|---|
| CLUSTER_URL | camera_cluster trên master, ví dụ http://192.168.1.10:8002 | Register/heartbeat, nhận cấu hình và quyền camera |
| AI_DATA_URL | logic_service trên master, ví dụ http://192.168.1.10:8001/ai-data | POST map điểm label/group_id theo format nghiệp vụ cũ |

Không gửi /ai-data tới camera_cluster. Service này không có endpoint nhận hoặc chuyển detect. Nếu AI_DATA_URL rỗng thì chỉ chạy control/capture/inference, chưa gửi dữ liệu HTTP. MASTER_URL cũ là alias dự phòng của CLUSTER_URL, cần đổi .env khi di chuyển controller.

## Hoạt động

1. Giữ khóa worker cục bộ, bắt đầu không có camera, tạo process capture/detector.
2. Register và heartbeat khoảng 3 giây/lần tới coordinator. AI báo ready và claim camera_id/epoch còn quyền; nhận assignment RTSP/ROI và lease.
3. Reconcile mở camera mới, cập nhật deadline hoặc dừng camera bị bỏ/đổi epoch. Quyền cục bộ dùng monotonic và biên dừng sớm 1 giây.
4. Camera đọc RTSP trực tiếp; frame resize 640×480. Capture chia vào NUM_PROCESS theo số camera, mỗi camera một thread; một detector chạy YOLO theo batch.
5. Detector tạo hang/trong cho điểm xác định được, bỏ ROI không chắc chắn và 10001546; chỉ giữ dữ liệu mới nhất.
6. Report khoảng 1 giây/lần dùng HTTP client dữ liệu riêng, gửi map điểm thẳng logic_service. Lỗi nhận dữ liệu không khiến AI tự đăng ký lại coordinator.

```json
{
  "10001244": {"label": "hang", "group_id": "AF"},
  "10000772": {"label": "trong", "group_id": "AF"}
}
```

Body tới logic không có _cluster, config_version, schema_version, frame_observed_at, inferred_at, point_ids hoặc trường thời gian thay thế. build_payload() vẫn biểu diễn dữ liệu nội bộ với worker/camera/epoch; build_logic_payload() bỏ _cluster cho bộ nhận cũ. Quyền worker/camera/epoch được trao đổi trên control API của coordinator.

captured_at chỉ dùng nội bộ để chọn/bỏ frame cũ và đối chiếu phản hồi; không gửi qua HTTP. Gửi nhãn không đổi khi có quan sát mới; không xử lý lại tất cả frame tồn đọng. Logic nhận điểm như trước, không kiểm tra epoch/lease của request đó; AI tự giới hạn nguồn gửi theo authority.

## Khi AI chết hoặc quay lại

Coordinator chờ lease cũ hết rồi cấp camera cho máy còn lại với epoch tăng. AI quay lại register từ danh sách rỗng, không tự nhận lại camera cũ. Khi cân lại, coordinator xóa owner camera dư, chờ lease cũ hết và cấp cho máy thiếu. AI cũ dừng theo response hoặc deadline; watchdog phục hồi process lỗi. Một RTSP riêng lỗi được retry tại chỗ, chưa tự chuyển máy chỉ vì thiếu frame.

300 camera: 75/75/75/75 → 100/100/100 → 75/75/75/75. Với 74 camera mẫu: 19/19/18/18 → 25/25/24 → 19/19/18/18.

## Cấu hình mẫu

```dotenv
CLUSTER_ENABLED=true
CLUSTER_URL=http://192.168.1.10:8002
AI_DATA_URL=http://192.168.1.10:8001/ai-data
WORKER_ID=AI-01
APP_DEBUG=false
WEIGHT_PATH=weights/ModelHN_170926.engine
```

Đổi WORKER_ID cho từng máy. Các mặc định khác: TARGET_FPS=5, NUM_PROCESS=4, report interval=1 giây, HTTP timeout=2 giây, max frame age cục bộ=3 giây. Khi cluster tắt, luồng legacy vẫn giữ cấu hình riêng hiện có.

Từ ai_service chạy `python -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1`. Không --reload và không tạo hai instance cùng worker ID. Khóa cục bộ chỉ bảo vệ cùng đường dẫn bản cài, không phát hiện trùng ID trên máy khác.

Xem [coordinator và triển khai](../camera_cluster/README.md), [contract](../docs/contract-ai-to-logic.md) và [cài offline](../docs/ai-service-offline-deployment.md).

## Cách chạy model AI

Cả luồng legacy và cluster dùng cùng cách gọi như `tests/test_model_engine.py`:

```python
model = YOLO(weight_path, task="detect")
results = model.predict(
    frames, device=0, conf=0.4, iou=0.45,
    imgsz=[480, 640], classes=[0], verbose=False,
)
```

Đường dẫn model lấy từ `WEIGHT_PATH`; các tham số predict dùng chung tại `core/inference_config.py`. Frame đầu vào hiện được resize về **640×480**. `iou=0.45` là ngưỡng NMS của model, độc lập với ngưỡng giao nhau giữa box và ROI khi chuyển kết quả thành `hang`/`trong`.

Service dùng `WEIGHT_PATH=weights/ModelHN_170926.engine`, là engine YOLO26s của file test, với class duy nhất `{0: "hang"}`. File `.pt` có cùng phần tên nhưng chứa `hang, qr` là model YOLOv8s cũ; loader từ chối model này để tránh dùng nhầm. Đường dẫn tương đối của weights được tính từ thư mục `ai_service`, không phụ thuộc thư mục chạy lệnh.

Model TensorRT `.engine` cần PyTorch bản CUDA, GPU NVIDIA và TensorRT tương thích trong **cùng môi trường Python**. Service chọn GPU `0`, truyền device vào `predict()` và không gọi `model.to()` với engine. Thiếu CUDA/TensorRT sẽ báo `ModelRuntimeUnavailable`, không chuyển sang model khác. `.pt` đúng class vẫn có thể chạy CPU khi người vận hành chủ động cấu hình `WEIGHT_PATH`.

Loader chạy thử một frame **640×480** bằng đúng tham số predict, kiểm tra tên class, rồi mới ghi `MODEL_READY` và cho cluster nhận camera. Lỗi deserialize engine hoặc sai class khiến runtime chưa sẵn sàng; `/health` trả 503 kèm nguyên nhân. Log `MODEL_LOADING` có đường dẫn tuyệt đối và SHA-256 để đối chiếu model thực tế.

Kiểm tra model và môi trường mà không mở camera hoặc gửi dữ liệu:

```powershell
# Chạy từ ai_service bằng đúng Python dùng để khởi động service.
python -c "from core.config import settings; from shared.model_runtime import load_detection_model; load_detection_model(settings.weight_path)"
```

Kiểm thử bằng backend giả lập: `python -m unittest discover -s tests -p test_model_runtime.py -v` và `python -m unittest discover -s tests -p test_yolo_inference.py -v`. Các test này không chạy engine thật hoặc kết nối camera.

### Môi trường GPU riêng trên máy hiện tại

Máy có hai RTX 3060 và TensorRT 10.15.1.29 trong Python hệ thống. `.venv` hiện dùng PyTorch CPU. Tạo `.venv-gpu` từ gốc repo để giữ môi trường CPU hiện tại; `--system-site-packages` cho phép dùng TensorRT đã cài trong Python hệ thống:

```powershell
python -m venv --system-site-packages .venv-gpu
./.venv-gpu/Scripts/python.exe -m pip install --upgrade pip==25.3
./.venv-gpu/Scripts/python.exe -m pip install --timeout 120 --resume-retries 10 -r ai_service/requirements-gpu.txt
Set-Location ai_service
../.venv-gpu/Scripts/python.exe -c "from core.config import settings; from shared.model_runtime import load_detection_model; load_detection_model(settings.weight_path)"
../.venv-gpu/Scripts/python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
```

`requirements-gpu.txt` chọn cặp PyTorch 2.10.0 / torchvision 0.25.0 CUDA 13.0 từ [hướng dẫn PyTorch chính thức](https://pytorch.org/get-started/previous-versions/), cùng TensorRT và Ultralytics đã chọn cho máy này. Máy khác cần kiểm tra lại driver và khả năng tải engine. Trong IDE, chọn `.venv-gpu/Scripts/python.exe` khi chạy service.

## Kiểm tra RTSP thật và kết quả detect (cluster)

Trong `.env` của **từng máy AI**, giữ `CLUSTER_ENABLED=true`, `APP_DEBUG=false`, điền đúng `CLUSTER_URL`, `WORKER_ID` và model đã train. Bật chẩn đoán như sau rồi khởi động lại service:

```dotenv
WEIGHT_PATH=weights/ModelHN_170926.engine
LOG_LEVEL=INFO
LOG_DIR=logs
CAMERA_SUMMARY_INTERVAL=15
DETECTION_LOG_INTERVAL=10
DEBUG_SAVE_SNAPSHOTS=true
DEBUG_SNAPSHOT_INTERVAL=30
DEBUG_SNAPSHOT_DIR=logs/snapshots
```

`DEBUG_SAVE_SNAPSHOTS=false` là mặc định. Khi bật, mỗi camera lưu JPG có số thứ tự trong thư mục theo tên camera sau mỗi 30 giây, ví dụ `logs/snapshots/cam57/cam57_000001.jpg`; đường dẫn được ghi tại dòng `SNAPSHOT`. Ảnh **640×480** giống frame inference; không mở cửa sổ GUI trong chế độ cluster. Tắt lưu ảnh sau khi đối chiếu xong để giảm I/O. Model engine phải chạy GPU; loader sẽ báo lỗi nếu Python đang dùng PyTorch CPU.

Từ thư mục `ai_service`, chạy:

```powershell
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
```

Ở cửa sổ PowerShell khác trên cùng máy AI:

```powershell
$diag = Invoke-RestMethod http://127.0.0.1:8000/diagnostics/cameras
$diag | Select-Object worker_id, registered, runtime_ready, expected, connected, detecting, all_connected, all_detecting, control_error, delivery_error
$diag.cameras | Format-Table camera_id, camera_name, status, connected, detecting, frame_age_seconds, detection_age_seconds, roi_count
$diag.cameras | Where-Object { -not $_.connected -or -not $_.detecting } | Format-List
$diag.cameras | Select-Object camera_id, points | ConvertTo-Json -Depth 8
Get-ChildItem logs/ai_*.log | Select-String 'RTSP_|CAMERA_SUMMARY|MODEL_|DETECTION|AI_DATA_|CLUSTER_CONTROL_FAILED'
```

| Trường | Cách đọc |
|---|---|
| `expected` | Số camera hiện được coordinator giao cho **worker này**, gồm camera đang dừng |
| `connected` / `all_connected` | Chỉ tính camera đã đọc được frame, trạng thái STREAMING, frame còn mới và còn quyền xử lý |
| `detecting` / `all_detecting` | Camera có hình mới và đã có kết quả inference từ frame còn mới; không chứng minh nhãn đúng |
| `frame_age_seconds` / `detection_age_seconds` | Tuổi frame nguồn và frame đã detect; quá `CLUSTER_MAX_FRAME_AGE` (mặc định 3 giây) thì không được tính là hoạt động |
| `points` | Nhãn gần nhất theo point ID; chỉ dùng khi `detecting=true`, kết quả cũ có thể còn hiển thị |
| `last_delivered_frame_at` | Timestamp của frame gần nhất đã được logic service xác nhận cho camera này |
| `control_error` / `delivery_error` | Loại lỗi và HTTP status nếu có; lỗi control có thể làm hết lease, lỗi delivery liên quan đường gửi kết quả |

Không có assignment thì `all_connected=false`, `all_detecting=false`. `/health` vẫn kiểm tra runtime; dùng `/diagnostics/cameras` để kiểm tra camera. `runtime_ready=true` và `registered=true` chưa đủ để kết luận đã có hình. Nếu model/worker còn khởi động, chờ coordinator cấp assignment sau giai đoạn ready ổn định.

Log ở `logs/ai_<pid>.log`, có PID/thread để phân biệt controller, capture và detector trên Windows. File xoay mỗi ngày, giữ tối đa 30 bản xoay cho mỗi file process; các file PID từ những lần khởi động cũ vẫn cần dọn theo chính sách vận hành. Log ứng dụng không ghi URL RTSP/token. Các thông báo native từ OpenCV/FFmpeg trên console nằm ngoài bộ lọc logging Python.

| Log | Ý nghĩa / hướng kiểm tra |
|---|---|
| `CAMERA_ASSIGNED` | Coordinator đã giao camera, có epoch và số ROI; chưa chứng minh RTSP kết nối |
| `RTSP_CONNECTING` | Đang thử mở luồng, có số lần thử |
| `RTSP_OPEN_FAILED` | Không mở được: kiểm tra mạng, port, tài khoản và đường dẫn RTSP |
| `RTSP_STREAMING` | Đã đọc được frame đầu tiên của lần kết nối; có kích thước ảnh nguồn |
| `RTSP_READ_FAILED` / `RTSP_ERROR` | Luồng không còn đọc được hoặc có exception; tự retry ở chế độ cluster |
| `CAMERA_SUMMARY` | Tổng số camera có hình/detect mới và danh sách camera có vấn đề, mỗi 15 giây |
| `MODEL_LOADING` / `MODEL_READY` / `MODEL_FAILED` | Đường dẫn và SHA-256 model; chỉ ready sau khi chạy thử và xác nhận class `hang`. Khi lỗi, kiểm tra CUDA/TensorRT và `WEIGHT_PATH` |
| `DETECTION` | Mỗi camera tối đa một dòng/10 giây: box, class, confidence, ROI, nhãn, ROI bị bỏ và ROI không có tâm box |
| `AI_DATA_DELIVERED` / `AI_DATA_DELIVERY_FAILED` / `AI_DATA_REJECTED` | Kết quả gửi sang logic service, HTTP status hoặc camera bị từ chối |
| `CLUSTER_CONTROL_FAILED` / `DETECTOR_RESTART` / `CAPTURE_PROCESS_RESTART` | Lỗi coordinator hoặc process cần phục hồi |

### Đối chiếu detect với hình thực tế

Mở JPG trong thư mục camera tương ứng dưới `logs/snapshots`. Box AI màu xanh lam nhạt kèm class/confidence; ROI đỏ = `hang`, xanh lá = `trong`. Kiểm tra ROI phủ đúng vị trí trên ảnh **640×480**, tên point/group khớp cấu hình và nhãn khớp vật thể thực trong ảnh. Ảnh đã vẽ box/ROI chỉ dùng để quan sát; khi so sánh inference giữa hai chương trình, dùng cùng frame gốc chưa vẽ.

Quy tắc hiện tại của cluster: box class `hang`, confidence **> 0.4**, phần giao box/ROI chia cho diện tích ROI **> 0.45** thì ROI có nhãn `hang`. Đây là tỉ lệ phủ ROI, không phải IoU NMS. Các ROI còn lại mặc định `trong`; box yếu hoặc class khác không xóa một nhãn `hang` đã xác định. Point `10001546` luôn bị loại; tên `start_123`/`end_123` được chuẩn hóa về `123`. Nhãn `trong` mặc định là quy tắc mapping, không phải bằng chứng chắc chắn vị trí trống.

Muốn kết luận AI đúng cần đối chiếu nhiều ảnh ở cả trạng thái có hàng/trống và điều kiện sáng khác nhau; log chạy được hoặc HTTP 200 chỉ chứng minh luồng xử lý/gửi dữ liệu hoạt động. Dữ liệu chẩn đoán giữ cục bộ; body gửi logic service vẫn theo contract hiện có.

### Kiểm tra toàn bộ catalog từ một máy AI

Lệnh sau thử mở từng camera **enabled** và đọc 3 frame, không cần model, không gửi `/ai-data`. Dùng catalog `camera_cluster/config/cameras.json`. Catalog ở master cần có sẵn trên máy chạy lệnh; `ai_service` không tự đọc được toàn bộ catalog qua heartbeat.

```powershell
python tools/check_cameras.py --catalog ../camera_cluster/config/cameras.json --workers 4 --output logs/camera_probe.json
$probe = Get-Content logs/camera_probe.json -Raw | ConvertFrom-Json
$probe | Select-Object expected, connected, all_connected
$probe.cameras | Where-Object { -not $_.connected } | Format-Table camera_id, camera_name, error_type
```

Probe có timeout mở/đọc mặc định 4 giây và giới hạn cứng 25 giây/camera; chỉnh bằng `--open-timeout-ms`, `--read-timeout-ms`, `--timeout`. Mã thoát: 0 = tất cả đọc được đủ frame; 1 = có camera lỗi; 2 = lỗi catalog. `OpenFailed` chỉ cho biết không mở được, không phân biệt chắc chắn sai mật khẩu với lỗi mạng. `HardTimeout` là process probe bị dừng do quá giới hạn. Kết quả là ảnh chụp trạng thái tại thời điểm probe, không bảo đảm kết nối liên tục. Lệnh tạo thêm phiên RTSP, nên giảm `--workers` nếu camera giới hạn client.

Thêm `--tcp-check` để kiểm tra cổng TCP trước RTSP; nếu TCP lỗi thì báo `TcpConnectFailed`, `tcp_error_type` và mã lỗi hệ điều hành (nếu có). Dùng `--camera-id <camera_id>` để khoanh vùng một camera, có thể lặp tham số này. TCP kết nối được chỉ chứng minh cổng mở, chưa chứng minh tài khoản/đường dẫn RTSP đúng.

Để kết luận toàn hệ thống đã kết nối, so danh sách camera **enabled** trong catalog với hợp các `camera_id` trên `/diagnostics/cameras` của mọi worker, rồi kiểm tra từng camera `connected=true`, `detecting=true`. Chỉ cộng số camera mà không so ID có thể bỏ sót camera hoặc tính trùng. Probe toàn catalog từ một máy xác nhận đường RTSP của máy đó; không thay thế kiểm tra từng worker đang vận hành.

Kiểm thử chức năng chẩn đoán (không cần GPU/model): `python -m unittest discover -s tests -v`. Cần OpenCV, NumPy và các dependency API đã cài. Test dùng frame/video tạo cục bộ và HTTP giả lập, không chứng minh kết nối camera thật hay độ chính xác model.
