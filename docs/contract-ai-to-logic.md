# Hợp đồng giao tiếp: `ai_service` → `logic_service` (Honda Hà Nam)

> Phía gửi dùng map điểm và `_cluster` rút gọn, không có trường phiên bản/timestamp/point_ids. Phần nhận chưa chỉnh theo yêu cầu chỉ làm phía gửi; logic_service vẫn nhận envelope v3 khi bật cluster.
> Bên gửi: ai_service · Bên nhận: logic_service

Phía AI giữ map ID điểm → label/group_id ở body và thêm `_cluster` theo mục 6. Phần gửi đã được cài đặt; bộ nhận cần tích hợp riêng, không thay đổi POS hoặc lệnh robot trong đợt này. Payload mới bị bộ nhận cluster v3 hiện tại trả 422; chưa triển khai hai format khác nhau cùng nhau để chạy nghiệp vụ.

## 1. Endpoint

```
POST http://<logic_host>:8000/ai-data
Content-Type: application/json
```
(port theo `APP_PORT` trong `.env` của logic_service, mặc định `8000`)

## 2. Body

Một **object JSON**: key = **ID điểm**, value = trạng thái của điểm đó.

```json
{
  "10001244": { "label": "hang",  "group_id": "AF" },
  "10000772": { "label": "trong", "group_id": "AF" },
  "10001299": { "label": "hang",  "group_id": "AE5" }
}
```

| Trường | Kiểu | Bắt buộc | Quy định |
|---|---|---|---|
| key | string | ✅ | **Chỉ chữ số**, bỏ tiền tố `start_` / `end_` của `config.py`. Vd `start_10001244` → `"10001244"` |
| `label` | string | ✅ | Chỉ nhận đúng `"hang"` (có kệ/hàng) hoặc `"trong"` (trống). Viết thường, không dấu |
| `group_id` | string | ⬜ | Zone của camera (`AE5`, `AE6`, `AF`, `5L`, `6L`, `Sub6`). Chỉ để log/tra cứu |

## 3. Quy tắc gửi (quan trọng)

1. **Gửi lặp liên tục** khoảng mỗi 1 giây (`PROCESSING_LOOP_DELAY`), gửi **toàn bộ ROI**, kể cả khi trạng thái không đổi.
   - Logic chỉ xác nhận trạng thái mới khi nhận **cùng một label liên tục ≥ 5 giây** (`TIME_RECOGNITION`).
   - Sau khi xác nhận, task chỉ được kích hoạt ở **lần gửi tiếp theo** có `"hang"`.
   - Nếu một điểm **không được gửi lại trong 10 phút**, logic sẽ xóa trạng thái của điểm đó.
   - Phía AI, chu kỳ là `CLUSTER_REPORT_INTERVAL=1`; gửi toàn bộ điểm xác định được khi có quan sát mới, kể cả nhãn không đổi. AI vẫn dùng thời gian capture nội bộ để bỏ dữ liệu quá cũ nhưng không gửi timestamp qua HTTP. Chính sách xử lý dữ liệu/nhãn ở master giữ nguyên cho tới đợt tích hợp phần nhận.
2. **Không chắc chắn thì không gửi** điểm đó. Không gửi label lạ như `"unknown"` hay `""`, vì label lạ sẽ làm reset bộ đếm 5 giây.
3. **Không gửi `10001546`** (`END_POINT_EMPTY`). Điểm này không có camera, logic tự xử lý.
4. Có thể gom nhiều camera vào 1 request, hoặc gửi mỗi camera 1 request. Cả hai cách đều được.

## 4. Response

| HTTP | Body |
|---|---|
| 200 | `{"status": "success", "message": "Data updated"}` |
| 500 | `{"detail": "<lỗi>"}`: bên AI chỉ cần log lại, sau đó tiếp tục gửi chu kỳ sau |

Timeout đề xuất phía AI: 2s. Không retry dồn dập, vì chu kỳ sau sẽ gửi lại.

## 5. Ví dụ kiểm tra nhanh

```powershell
curl.exe -X POST http://localhost:8000/ai-data -H "Content-Type: application/json" `
  -d '{\"10001244\": {\"label\": \"hang\", \"group_id\": \"AF\"}}'
```

## 6. Payload rút gọn phía AI — hiện hành

```json
{
  "10001244": {"label": "hang", "group_id": "AF"},
  "10000772": {"label": "trong", "group_id": "AF"},
  "10001299": {"label": "hang", "group_id": "AE5"},
  "_cluster": {
    "worker_id": "AI-01",
    "cameras": [
      {"camera_id": "CAM-AF-01", "assignment_epoch": 4294967297},
      {"camera_id": "CAM-AE5-01", "assignment_epoch": 4294967297}
    ]
  }
}
```

POST tới `MASTER_URL + /ai-data`, có `Authorization: Bearer <worker-token>`. ID camera/epoch minh họa, khi chạy lấy từ assignment thực tế. Mỗi camera xuất hiện tối đa một lần/request; mỗi key điểm chỉ xuất hiện một lần; chỉ nhận hang/trong, key số, không gửi 10001546. ROI không chắc chắn không đưa vào map.

Đã bỏ hoàn toàn khỏi request: config_version, schema_version, frame_observed_at, inferred_at và point_ids. Không bọc dữ liệu điểm vào items/rois. Cấu hình master và phản hồi phân công heartbeat chưa đổi; config_version còn trong assignment cũ không có nghĩa nó được gửi trong /ai-data.

### Kiểm tra quyền ở bộ nhận tương lai

1. Xác thực worker_id bằng token.
2. Tra catalog của master để biết mỗi ID điểm thuộc camera nào; không cần lặp point_ids trong request. Không suy ra nguồn camera chỉ bằng group_id vì nhiều camera cùng zone.
3. Tìm camera tương ứng trong _cluster.cameras, kiểm tra đúng owner, epoch và còn lease trên master. Điểm ngoài catalog hoặc không có camera metadata phải bị từ chối.
4. Khi đổi RTSP/ROI phải thu hồi quyền và cấp epoch mới. Hiện master nạp cấu hình qua restart, boot generation đã tạo khoảng epoch mới; nếu thêm hot-reload sau này thì vẫn phải tăng epoch.

Những bước nhận format mới chưa được triển khai trong lượt này. Bốn trường quyền trên master không đổi; owner_worker_id đối chiếu với worker đã xác thực, lease_expires_at vẫn do master quản lý, không tin hạn lease do client gửi.

### Thời gian xử lý và phản hồi

AI giữ captured_at chỉ trong RAM để chọn frame mới, bỏ frame quá cũ trước khi gửi và đánh dấu chính snapshot đã được phản hồi. Trường nội bộ này không được đưa vào JSON. Bỏ timestamp trên wire đồng nghĩa bộ nhận mới không biết tuổi frame từ request; nếu dùng thời điểm nhận để xác nhận nhãn thì không phân biệt được snapshot cũ gửi lại với một quan sát mới cùng nhãn. Đây là đánh đổi đã chốt, không sửa chính sách POS ở đợt này.

Response đơn giản theo mục 4 được hỗ trợ. Nếu bộ nhận tương lai trả results theo camera thì chỉ cần camera_id, assignment_epoch, status:

```json
{
  "status": "success",
  "message": "Data updated",
  "results": [
    {"camera_id": "CAM-AF-01", "assignment_epoch": 4294967297, "status": "accepted"},
    {"camera_id": "CAM-AE5-01", "assignment_epoch": 4294967297, "status": "accepted"}
  ]
}
```

AI đối chiếu phản hồi với chính batch đã gửi, không cần timestamp từ server. Nếu kết quả mới xuất hiện trong lúc request đang chờ thì không bị đánh dấu nhầm là đã gửi. Mạng lỗi/500 được log loại lỗi và chờ vòng sau, không retry dồn dập; chu kỳ mặc định 1 giây và HTTP timeout 2 giây. Không đổi schema/adapter/POS/robot phía logic_service: bộ nhận cluster hiện vẫn v3 nên chưa đọc payload rút gọn này.
