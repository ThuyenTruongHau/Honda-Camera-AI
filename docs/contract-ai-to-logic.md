# Hợp đồng giao tiếp: `ai_service` → `logic_service` (Honda Hà Nam)

> ai_service gửi map điểm trực tiếp tới logic_service. camera_cluster chỉ quản lý/chia camera, không nhận ai_data.
> Bên gửi: ai_service · Bên nhận: logic_service

Luồng hiện hành: AI lấy quyền camera từ CLUSTER_URL; kết quả detect gửi riêng tới AI_DATA_URL của logic_service. Body HTTP chỉ có key ID điểm và label/group_id, không _cluster. Phần POS/nghiệp vụ/robot giữ nguyên.

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
   - AI dùng CLUSTER_REPORT_INTERVAL=1, gửi quan sát mới kể cả nhãn không đổi. Thời gian capture chỉ giữ trong RAM AI để bỏ frame cũ, không gửi qua HTTP. Không sửa xử lý POS/robot.
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

## 6. Đích dữ liệu và đích điều phối tách biệt

```dotenv
CLUSTER_URL=http://192.168.1.10:8002
AI_DATA_URL=http://192.168.1.10:8001/ai-data
```

CLUSTER_URL là camera_cluster trên master: register/heartbeat/assignment, không có /ai-data. AI_DATA_URL là endpoint đầy đủ của logic_service trên master; port thực theo APP_PORT, không nhất thiết là 8001. Máy AI chỉ cài ai_service.

Body gửi tới logic_service giữ nguyên ví dụ ở mục 2, không có _cluster, worker_id, camera_id, assignment_epoch, config_version, schema_version, timestamp hoặc point_ids. Cặp camera_id/epoch và worker_id dùng trên heartbeat/assignment và quyền cục bộ AI; không dùng token. Hàm build_payload() còn có thể biểu diễn metadata rút gọn trong bộ nhớ AI; build_logic_payload() bỏ _cluster trước POST để không đưa metadata vào POS như một điểm.

camera_cluster chỉ giữ bốn trường quyền mỗi camera, catalog cấu hình, readiness/heartbeat worker và generation. Không nhận, xử lý hay chuyển kết quả detect; không phụ thuộc logic_service. Logic nhận điểm qua update_state() hiện có; thuật toán xác nhận, callback và payload robot không đổi.

AI kiểm tra quyền, bỏ dữ liệu quá cũ cục bộ và dừng gửi khi hết lease. Bộ nhận nghiệp vụ không đối chiếu epoch/lease hoặc biết tuổi frame từ body này. Không bổ sung chống lệnh robot trùng hay thứ tự dữ liệu ở logic_service trong đợt tách coordinator. Kết quả API success chỉ là đã xử lý request, không phải xác nhận robot đã nhận nhiệm vụ.

Chi tiết cài đặt: [camera_cluster/README.md](../camera_cluster/README.md).
