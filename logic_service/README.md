# logic_service — Master chia camera

Bản hiện hành ngày 11/11/2026: một master, chia đều theo số camera, dữ liệu điều phối trong RAM. HA chưa triển khai. Bật bằng `CLUSTER_ENABLED=true`.

## Mỗi camera chỉ có bốn trường quyền

```json
{
  "camera_id": "CAM-01",
  "owner_worker_id": "AI-01",
  "assignment_epoch": 4294967297,
  "lease_expires_at": 1794390000.0
}
```

| Trường | Ý nghĩa |
|---|---|
| camera_id | Camera nào |
| owner_worker_id | Máy AI đang có quyền; null là chưa có chủ |
| assignment_epoch | Lượt cấp quyền, tăng khi cấp camera |
| lease_expires_at | Hạn quyền hiện tại; khi đã xóa chủ, đây là mốc phải chờ trước khi cấp lại |

RTSP, ROI, group và config_version nằm trong catalog tĩnh; nhãn/timestamp detect nằm ở tầng xử lý dữ liệu/POS. Chúng không nằm trong bản ghi quyền camera. Không còn session_id, revision, assignment_revision, blocked_until, frame_seq, latest_sample hoặc trạng thái DRAINING trong bộ điều phối.

## Phân chia và gia hạn

1. Master nạp camera enabled từ JSON, mặc định `config/cameras.json`.
2. AI đăng ký bằng worker_id/token. Mỗi lần register, master thu hồi mọi quyền còn gắn với worker đó và giữ nguyên hạn cũ; máy phải qua giai đoạn sẵn sàng ổn định để nhận lại camera.
3. AI gửi heartbeat, báo ready và các cặp camera_id/assignment_epoch đang thực sự còn giữ quyền cục bộ.
4. Master chỉ gia hạn camera nếu đúng owner, đúng epoch, còn lease và AI ready. Claim lượt cũ không gia hạn được quyền lượt mới.
5. Tick chia tổng camera cho số máy đủ điều kiện, ưu tiên máy còn thiếu và đang ít camera hơn. Phần dư phân theo worker ID; chênh tối đa một camera sau khi ổn định.

300 camera: bốn máy 75/75/75/75, ba máy 100/100/100. Với 74 camera hiện tại: 19/19/18/18 hoặc 25/25/24. Không xét tài nguyên phần cứng hay zone.

## Chuyển camera khi lỗi hoặc cân lại

```text
Xóa owner cũ → giữ nguyên lease_expires_at → chờ hết hạn
→ chọn chủ mới → tăng assignment_epoch → cấp lease mới
```

Khi AI chết, heartbeat không gia hạn được nên quyền tự hết. Khi cân lại, master xóa chủ của một số camera dư ngay lập tức; kết quả của chủ cũ bị loại từ lúc đó. AI nhận heartbeat không còn camera sẽ dừng; nếu không nhận được phản hồi, nó tự dừng khi quyền cục bộ hết hạn.

Master luôn chờ lease cũ hết, kể cả AI đã dừng sớm. Không còn API STOPPED/camera-status, không có đường cấp sớm nhờ xác nhận dừng. Đây là lựa chọn đơn giản hóa; mỗi camera chuyển máy có thể gián đoạn khoảng một lease cộng thời gian mở RTSP/detect/xác nhận POS.

## Nhận kết quả

`POST /ai-data` dùng schema_version=3, worker_id và danh sách snapshot có camera_id/epoch, config_version, thời gian quan sát/inference và toàn bộ nhãn ROI. Không gửi video lên master.

Master kiểm tra đúng chủ + epoch + còn lease, đúng config/ROI và độ mới rồi áp dụng trực tiếp vào POS. Không lưu latest_sample trong repository. POS dùng timestamp quan sát để không áp dụng lại dữ liệu cũ; timestamp là thông tin detect, không phải quyền camera. Phát lệnh robot vẫn phụ thuộc xác nhận nhãn, map nghiệp vụ và `CLUSTER_ROBOT_ENABLED`.

## Ràng buộc và vận hành

- Một process master; mọi đăng ký, heartbeat, tick, ingest và đọc state dùng cùng một khóa điều phối.
- Mỗi WORKER_ID dùng cho một máy AI, một instance. Không hỗ trợ hai máy cùng ID; không có session để phân biệt chúng.
- Giá trị mẫu: heartbeat 3 giây, lease 15 giây, recovery delay 10 giây, tick 1 giây, thu hồi tối đa 10 camera dư/tick.
- Giữ `runtime/cluster_boot.json` qua restart để cấp khoảng epoch mới; master đợi một lease sau startup. File này không phải DB và không lưu detect/task.
- Đổi giao thức: phải nâng master và toàn bộ AI cùng đợt; payload cũ v2 không được chấp nhận. Giữ lease cũ khi nâng cấp, hoặc dừng toàn bộ AI và chờ hết lease cũ trước khi chạy bản mới.
- Một RTSP lỗi riêng được retry tại AI, chưa có chính sách chuyển máy chỉ vì một camera lâu không có frame.

`GET /cluster/state?worker_id=AI-01` với Bearer token trả camera chỉ có bốn trường trên. API này không trả URL hay snapshot detect.

Các file chính: [cluster_runtime.py](services/cluster_runtime.py), [cluster_repository.py](repositories/cluster_repository.py), [camera_catalog.py](core/camera_catalog.py), [api/cluster.py](api/cluster.py), [POS_manager.py](services/POS_manager.py).

Xem [phân tích từng hàm](../docs/camera-cluster-code-walkthrough.md), [triển khai](../docs/camera-cluster-deployment.md), [nhật ký thay đổi](../docs/logic-service-change-log.md).
