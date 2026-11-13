# Đóng gói ai_service để cài trên máy không có Internet

## Phương án đề xuất

Chuẩn bị một bộ cài offline trên máy có Internet: source ai_service, model weights, thư viện Python dạng wheel, danh sách phiên bản đã khóa và bộ cài Python/driver cần thiết. Chuyển qua USB, ổ cứng hoặc LAN nội bộ. Trên máy AI tạo venv mới và cài thư viện chỉ từ bộ wheel.

Chỉ cần ai_service trên máy AI, không cần logic_service hoặc file camera của master. Máy AI không cần Internet để trao đổi với master và camera nếu LAN truy cập được các địa chỉ đó.

Người dùng đã xác nhận máy AI dùng Windows và GPU NVIDIA. Máy phát triển hiện dùng Windows, Python 3.10.9; chưa xác nhận Python, model GPU và driver trên máy AI nên chưa chọn phiên bản PyTorch/CUDA. Các lệnh dùng Windows/PowerShell. Đây là hướng dẫn chuẩn bị, chưa phải bộ cài đã được tải/build và nghiệm thu.

## Điều kiện cần khớp

| Thông tin máy đích | Ảnh hưởng |
|---|---|
| Windows/Linux và phiên bản OS | Wheel và thư viện native phải chạy được trên OS đích |
| CPU x64/ARM64 | Phải tải đúng kiến trúc |
| Python major/minor | Không dùng wheel CPython 3.10 cho 3.11 một cách tùy ý; nên dùng cùng bản Python đã kiểm thử |
| GPU/model và NVIDIA driver | Chọn đúng bộ torch/torchvision, bản CUDA wheel hỗ trợ driver/GPU |
| Cài mới hay cập nhật | Cài mới cần Python/wheels/model; cập nhật chỉ code có thể dùng lại môi trường đã cài nếu dependency không đổi |

Từ một máy AI có Python/NVIDIA, lấy thông tin bằng:

```powershell
python --version
python -c "import platform; print(platform.platform()); print(platform.machine())"
nvidia-smi
```

Build môi trường trên máy/VM có cùng OS và kiến trúc với máy đích là cách dễ kiểm chứng nhất. Nếu máy đích Linux, không dùng wheel Windows; cần môi trường chuẩn bị Linux tương thích. pip có tùy chọn tải cho platform/Python khác, nhưng vẫn cần thử trên OS đích để kiểm tra thư viện hệ thống. Xem [pip download](https://pip.pypa.io/en/stable/cli/pip_download/).

## Cấu trúc bộ chuyển giao

```text
Honda-AI-offline/
  ai_service/
    main.py
    core/
    schemas/
    services/
    shared/
    weights/ModelHN_170926.pt
    .env.example
  wheelhouse/
    ... toàn bộ file .whl của môi trường đã chốt ...
  requirements.lock
  installers/
    ... bộ cài Python offline đúng phiên bản ...
    ... driver NVIDIA offline nếu máy chưa có bản phù hợp ...
    ... runtime hệ thống cần thiết theo OS ...
  RELEASE.md
  SHA256SUMS.txt
```

Không đóng gói .venv, .git, cache, log, runtime lock hay .env riêng của máy phát triển. Dùng .env.example làm mẫu, cấu hình WORKER_ID duy nhất tại từng máy. Model hiện có trong repo là ai_service/weights/ModelHN_170926.pt; chỉ dùng nếu đúng model vận hành đã chọn.

Python hướng dẫn tái tạo venv tại nơi đích, không coi venv là thư mục có thể di chuyển/copy tùy ý. Xem [tài liệu venv](https://docs.python.org/3/library/venv.html).

## Chuẩn bị trên máy có Internet

1. Tạo môi trường release sạch bằng Python đã chọn cho máy AI.
2. Cài torch/torchvision đúng GPU/driver từ hướng dẫn PyTorch chính thức, sau đó cài các dependency ứng dụng. Kiểm tra model hoạt động trước khi khóa phiên bản. Không tự nâng tất cả package tới latest khi chuẩn bị bản vận hành.
3. Khóa toàn bộ dependency, thu thập/build wheel cho đúng môi trường đó. Package chỉ có source distribution thì build wheel ngay trên máy chuẩn bị, không để máy offline phải tải compiler/build dependencies.
4. Cài thử wheelhouse vào một venv sạch khác bằng --no-index. Thử load model, inference ảnh nội bộ và RTSP LAN khi tắt Internet.
5. Sau khi đạt mới nén source/model/wheels/installers thành bộ chuyển giao và lưu checksum.

Chọn bộ torch/torchvision theo [PyTorch Start Locally](https://docs.pytorch.org/get-started/locally/). Ultralytics cũng hướng dẫn cài bản PyTorch phù hợp trước khi cài package của họ: [Ultralytics Quickstart](https://docs.ultralytics.com/quickstart/).

requirements.txt hiện tại có nhiều ràng buộc >=, httpx lặp và cả dependency legacy/tiện ích đóng gói. Nó là đầu vào phát triển, chưa phải lock vận hành. Không freeze toàn bộ Python global trên máy lập trình vì có thể lấy cả các package không liên quan. Có thể dùng nguyên requirements hiện có để chuẩn bị bản đầu, nhưng phải giải quyết dependency và freeze từ venv sạch. Việc tách requirements riêng cho cluster cần làm có kiểm chứng ở đợt đóng gói cụ thể.

### Lệnh thu thập wheel sau khi môi trường release đã chạy đúng

Giả sử đang ở gốc repo, đã có .venv-release được cài/test đúng máy đích. Các lệnh dưới đây là bước xuất môi trường, không tự chọn bộ CUDA:

```powershell
New-Item -ItemType Directory -Force offline-bundle/wheelhouse
./.venv-release/Scripts/python.exe -m pip check
./.venv-release/Scripts/python.exe -m pip freeze --exclude-editable | Set-Content -Encoding ascii offline-bundle/requirements.lock
```

Kiểm tra lock chỉ gồm phiên bản package có thể đưa vào wheelhouse. Nếu có đường dẫn file cục bộ, git URL hoặc URL cần Internet, phải chuyển thành wheel cục bộ cùng requirement phiên bản trước khi dùng offline. Không đưa token/credential nguồn package vào lock.

Với môi trường CPU hoặc các wheel đều có từ index đang cấu hình:

```powershell
./.venv-release/Scripts/python.exe -m pip wheel --wheel-dir offline-bundle/wheelhouse -r offline-bundle/requirements.lock
```

Với bản torch CUDA lấy từ index PyTorch riêng, phải dùng lại đúng index khi thu thập wheel. Ví dụ biến sau chỉ là chỗ điền, không phải bản CUDA đã chọn:

```powershell
$torchWheelIndex = 'https://download.pytorch.org/whl/<CUDA_TAG_DA_CHON>'
./.venv-release/Scripts/python.exe -m pip wheel --wheel-dir offline-bundle/wheelhouse --extra-index-url $torchWheelIndex -r offline-bundle/requirements.lock
```

Thay placeholder bằng index đã dùng cho bộ torch được kiểm thử. Nếu lock có bản CUDA mà không chỉ đúng nguồn wheel, quá trình thu thập có thể không tìm được package tương ứng. Không đổi sang bản CPU để làm lệnh hết lỗi nếu vận hành yêu cầu GPU.

pip wheel thu thập/build wheel cho requirements và dependency; xem [pip wheel](https://pip.pypa.io/en/stable/cli/pip_wheel/). Nếu chỉ tải wheel có sẵn, có thể dùng pip download --only-binary=:all: với cùng lock và index; lệnh sẽ lỗi khi một package không có wheel phù hợp, khi đó cần build nó trên máy chuẩn bị.

## Cài trên máy AI offline

Giả sử bộ chuyển giao được giải nén ở D:/Honda-AI-offline, và Python đúng phiên bản đã cài từ offline installer. Nếu có nhiều Python, thay python bằng đường dẫn tuyệt đối tới interpreter được chọn.

```powershell
Set-Location D:/Honda-AI-offline
python -m venv .venv
./.venv/Scripts/python.exe -m pip --disable-pip-version-check install --no-index --find-links=wheelhouse --only-binary=:all: -r requirements.lock
./.venv/Scripts/python.exe -m pip check
```

--no-index ngăn pip tra package index; --find-links chỉ tới thư viện đã chuyển. Cách cài này được mô tả trong [pip User Guide](https://pip.pypa.io/en/stable/user_guide/#installing-from-local-packages). Tất cả dependency và Python/driver phải đã có trong bộ cài; lệnh pip không thể cung cấp driver hoặc thư viện hệ thống còn thiếu.

Sau đó cấu hình riêng từng máy:

```powershell
Set-Location D:/Honda-AI-offline/ai_service
Copy-Item .env.example .env
```

Lệnh copy chỉ dùng lần cài đầu khi chưa có .env. Điền WORKER_ID duy nhất, CLUSTER_URL=http://<IP-master>:8002 và AI_DATA_URL=http://<IP-master>:8001/ai-data. Đặt WEIGHT_PATH=weights/ModelHN_170926.pt (hoặc file model thực tế), CLUSTER_ENABLED=true và APP_DEBUG=false. Máy AI chỉ cài ai_service; camera_cluster và logic_service chạy trên master, theo [hướng dẫn điều phối](../camera_cluster/README.md).

Không để WEIGHT_PATH trỏ tên model thiếu trong bộ cài: Ultralytics có cơ chế tải model dựng sẵn khi dùng tên pretrained; phải cung cấp model local và kiểm tra offline. Không dùng ảnh/URL Internet để test inference. Xem [Ultralytics Quickstart](https://docs.ultralytics.com/quickstart/).

Kiểm tra dependency/GPU trước khi mở dịch vụ:

```powershell
../.venv/Scripts/python.exe -c "import torch, cv2, ultralytics; print('torch', torch.__version__); print('CUDA build', torch.version.cuda); print('GPU available', torch.cuda.is_available())"
```

Code detector hiện có thể tự chạy CPU khi không thấy CUDA; nếu thiết kế yêu cầu GPU thì kết quả GPU available phải true và cần kiểm tra chạy model thực sự trên GPU.

Khởi động từ folder ai_service:

```powershell
../.venv/Scripts/python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
```

Giữ working directory này để .env/weights được tìm đúng. Mỗi worker một instance, không --reload. Không cần activate venv vì đã chỉ rõ python.exe.

## Chuyển giao và cập nhật

- Lần đầu chuyển bộ đầy đủ: Python/runtime cần thiết, wheelhouse, code, model, cấu hình mẫu. Thử trên một máy AI trước, sau đó dùng cùng bộ dependency cho các máy cùng cấu hình.
- Lần sau nếu chỉ sửa .py, chuyển gói code release mới; nếu model đổi thì kèm model. Giữ .env riêng và môi trường dependency đã cài; dừng service cũ trước khi chuyển và chạy bản mới.
- Nếu dependency đổi, tạo lock/wheelhouse mới và cài vào venv mới, giữ venv cũ để hoàn nguyên. Không ghi đè môi trường đang chạy.
- RELEASE.md ghi mã release/commit, OS/kiến trúc/Python, torch/torchvision/CUDA build đã kiểm thử, model và checksum, cách chạy. SHA256SUMS.txt dùng đối chiếu file sau khi chuyển.
- Nếu bốn máy AI khác OS/kiến trúc hoặc cần bộ torch khác, tạo bộ dependency tương ứng; không mặc định một gói dùng được mọi máy.

## Điều kiện ứng dụng hiện tại

Đóng gói offline chỉ giải quyết cài Python/dependency/code/model. Bản hiện hành tách camera_cluster khỏi logic_service: AI gửi map ID điểm → label/group_id tới bộ nhận /ai-data có sẵn, không gửi envelope _cluster. Lỗi 422 do không khớp envelope ở đợt trước đã được xử lý bằng cách tách đường control/data; POS và robot giữ nguyên. Kiểm thử API và mô phỏng điều phối chưa thay thế kiểm thử model/GPU/RTSP trên máy offline; cần kiểm tra đúng hai địa chỉ LAN trước triển khai. Xem [contract](contract-ai-to-logic.md) và mục 14 của [nhật ký thay đổi](logic-service-change-log.md).
