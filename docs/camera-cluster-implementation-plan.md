Kế hoạch triển khai phân công camera và chuyển tải giữa các máy AI

> Kế hoạch lịch sử. Từ 11/11/2026 code đã đổi sang bốn trường quyền camera; bộ nhận master dùng detect v3, phía gửi AI đang chuyển sang map điểm + _cluster rút gọn và chưa sửa bộ nhận theo yêu cầu. Đã bỏ session, revision, frame_seq, DRAINING và camera-status. Các bước dự kiến dưới đây cần đối chiếu [phân tích code hiện hành](camera-cluster-code-walkthrough.md), [contract](contract-ai-to-logic.md) và [nhật ký thay đổi](logic-service-change-log.md), không dùng làm hợp đồng API hiện tại.

Ngày lập và cập nhật: 10/11/2026. Đã triển khai code và kiểm thử local; chưa triển khai trên hệ thống camera/robot thực. Quyết định mới nhất là JSON + RAM, chưa làm HA; xem mục 11. Các mục MongoDB bên dưới lưu lại kế hoạch đợt đầu, đã được thay thế về backend bởi mục 11.

Thiết kế tham chiếu: [camera-cluster-architecture.md](camera-cluster-architecture.md).

Yêu cầu ghi nhận thay đổi của người dùng: mọi sửa đổi file đã có trong logic_service phải được ghi vào một tài liệu duy nhất: [logic-service-change-log.md](logic-service-change-log.md). Nhật ký phải được cập nhật cùng đợt sửa, ghi rõ file, lý do, hành vi trước/sau, kiểm thử và kết quả thực tế. Không chuyển một đầu việc sang hoàn thành khi thiếu ghi nhận này.

Phạm vi triển khai: một master chạy logic_service, bốn ai_service, 300 camera; chia đều theo số camera; tự tiếp quản dưới 60 giây khi một máy AI hỏng; tự cân lại khi máy phục hồi; master loại dữ liệu sai quyền, gửi lặp và quá cũ. Không tính trọng số phần cứng. Bảo đảm chính là một nguồn dữ liệu có quyền được áp dụng cho mỗi camera; không tuyên bố tuyệt đối chỉ có một kết nối RTSP trong mọi tình huống treo tiến trình hoặc chia cắt mạng.

1. Trình tự và điều kiện hoàn thành từng giai đoạn

| Giai đoạn | Việc chính | Phụ thuộc | Điều kiện hoàn thành | Hiện trạng |
|---|---|---|---|---|
| P0 | Ghi nhận baseline, chuẩn hóa hợp đồng v2, mapping camera/ROI và cấu hình | Không | Contract thống nhất; inventory file; baseline lỗi tách riêng; fixtures dùng được | Đã code; mapping JSON thực cần kiểm tra khi rollout |
| P1 | Master quản lý worker, session, quyền camera và scheduler | P0 | Bốn AI giả lập chia đều; quyền/epoch bền vững; chuyển giao không cấp hai quyền hiện hành | Đã chuyển JSON/RAM và test local; xem mục 11 |
| P2 | AI thêm/dừng camera động và giữ metadata xuyên pipeline | P0; có thể làm cùng P1 | START/STOP idempotent; model nạp sẵn; không tự chạy camera theo cấu hình cũ | Đã code; capture video local đã kiểm tra |
| P3 | Ingest v2, chống trùng và tích hợp POS/nghiệp vụ | P1 | Snapshot sai quyền không tới POS; UNKNOWN đúng; khóa task không mất khi đổi camera | Đã code; test POS và guard đạt, cần UAT nghiệp vụ |
| P4 | Nối AI với master: heartbeat, reporter, sức khỏe và phục hồi | P1, P2, P3 | Luồng đăng ký → phân công → detect → nhận dữ liệu → chuyển tải hoạt động | Đã code; cần chạy thử model/GPU và bốn máy thực |
| P5 | Kiểm thử lỗi và hồi quy trên môi trường thử nghiệm | P4 | Qua bộ ca lỗi; giả lập đủ 300 camera; hồi quy PA/KD/DCC và callback | Test local đạt; kiểm thử hiện trường còn lại |
| P6 | Chuyển đổi nhóm thử, mở rộng và nghiệm thu vận hành | P5 | Một đường ghi dữ liệu/camera; cân đúng số lượng; đo camera cuối phục hồi <60 giây | Đã có runbook, chưa triển khai hiện trường |

P1 và P2 có thể triển khai song song sau P0 vì đã có hợp đồng API. P3 có thể tiếp tục phía master trong khi hoàn thiện runtime AI. Không đưa một nhóm camera vào cơ chế phân công động trước khi master có lớp chặn quyền và dữ liệu cũ cho nhóm đó.

2. P0 — hợp đồng, baseline và chuẩn bị chuyển đổi

- P0.1: Chụp baseline mã nguồn/cấu hình đang dùng và danh sách camera; không ghi credential hoặc URL camera có mật khẩu vào tài liệu/log. Xác định camera_id ổn định từ MongoDB, quan hệ camera_id + roi_id → position_id và group_id nghiệp vụ.
- P0.2: Kiểm tra tên ROI/vị trí trùng hoặc mapping mơ hồ. Nếu hai camera cùng ghi một vị trí, phải có quy tắc nguồn hợp lệ rõ ràng trước chuyển đổi; không để dictionary ghi đè ngẫu nhiên.
- P0.3: Chốt schema register/heartbeat/camera-status/assignment/snapshot-v2/per-item-result. Bắt buộc worker_id, session_id, camera_id, assignment_epoch, config_version, frame_seq, frame_observed_at. Phiên bản hợp đồng dùng chung fixtures giữa hai service.
- P0.4: Quy định state machine worker, assignment và observed camera status; danh sách mã từ chối, retry, deadline, khởi động lại, STOP cũ và phản hồi đến trễ. READY cần model và pool sẵn sàng; worker khỏe nhưng chưa có camera không bị coi là YOLO treo.
- P0.5: Thêm bộ kiểm thử có ý nghĩa cho các hành vi trên. Hai service hiện dùng module top-level cùng tên core/services; test tích hợp nên chạy chúng trong process/cwd riêng hoặc cấu hình import tách biệt, tránh vô tình import nhầm service.
- P0.6: Ghi riêng lỗi baseline và sửa tối thiểu các lỗi chặn nghiệm thu khi bắt đầu triển khai; mỗi sửa logic_service vẫn có nhật ký. Không gộp việc đổi quy tắc nghiệp vụ chưa rõ vào refactor cluster.

Kết quả rà soát baseline trước triển khai: ast.parse đọc 24 file Python và phát hiện lỗi cú pháp ở logic_service/logic/PA_logic.py. Các lỗi baseline đã xử lý và giới hạn nghiệp vụ còn lại được cập nhật trong nhật ký thay đổi; kết quả kiểm thử sau triển khai được ghi riêng trong báo cáo kiểm chứng.

Cấu hình ban đầu để thử: heartbeat 3 giây; lease 15 giây; scheduler tick 1 giây; max_frame_age/observation_timeout 3 giây; xác nhận trạng thái 5 giây; worker trở lại ổn định 10 giây trước cân tải. Đây là cấu hình đo thử, không phải hiệu năng đã xác nhận.

3. P1 — quyền camera và scheduler trên master

| Task | File mới dự kiến | Nội dung / nghiệm thu |
|---|---|---|
| L-01 | schemas/cluster.py, schemas/detection.py | Validate hợp đồng; không dùng camera_name/group_id làm khóa quyền |
| L-02 | core/database.py, repositories/cluster_repository.py | MongoDB camera_runtime, ai_workers, assignment_events; một document quyền/camera; index; không reset epoch |
| L-03 | services/worker_registry.py | Register idempotent; phiên mới; từ chối worker_id bị dùng đồng thời; phân biệt liveness/readiness/progress |
| L-04 | services/assignment_manager.py | Cấp/gia hạn/thu hồi nguyên tử; tăng epoch; deadline; khóa thao tác ngắn theo camera; STOPPED khớp phiên |
| L-05 | services/camera_scheduler.py | floor/ceil theo số camera; giữ tối đa phân công cũ; chia lại khi lỗi và cân lại khi máy trở về |
| L-06 | api/cluster.py | register, heartbeat, camera-status, state; revision và heartbeat_seq chống phản hồi cũ |

File có sẵn dự kiến sửa: main.py, core/config.py. requirements.txt chỉ sửa nếu kiểm tra dependency cho thấy cần bổ sung/điều chỉnh; không nâng cấp toàn bộ thư viện trong đợt này. Bổ sung cấu hình MongoDB cho master, worker identity, timeout và cờ bật cluster; credential lấy qua cấu hình môi trường.

Điều kiện kỹ thuật:

- Chỉ một process ứng dụng master và một scheduler trong phiên bản đầu; tắt auto-reload khi vận hành. Nếu cấu hình nhiều worker, phát hiện/cảnh báo hoặc từ chối chế độ không được hỗ trợ, không giả định asyncio.Lock dùng chung nhiều process.
- Cấp quyền mới chỉ sau khi cập nhật MongoDB được xác nhận. Conditional update thay owner/session, tăng epoch, xóa snapshot cũ và reset cursor cùng nhau. Kiểm thử cuộc đua với MongoDB thử nghiệm thật, không chỉ mock dictionary.
- Không dùng TTL index để kích hoạt failover. Scheduler xét deadline; AI tự dừng theo monotonic deadline bảo thủ khi không gia hạn được.
- Camera đang STARTING tính vào số đã giao; camera đang chuyển không được tạo thêm một kế hoạch chuyển chồng lên. Khi K=0, giữ UNASSIGNED, không chia cho 0 hoặc phát quyền giả.
- Khi mất MongoDB, không cấp/gia hạn không xác nhận được. Khi master khởi động lại, vô hiệu quyền cũ trước readiness; không tái cấp epoch đã dùng. Bài toán khôi phục task robot sau restart master là hạng mục riêng.

Nghiệm thu P1: kiểm tra N=0, N<K, N không chia hết K, 300/4, 300/3, một worker rời rồi vào; sau ổn định chênh lệch tối đa một camera, tổng số camera đúng, không camera có hai owner hiện hành. Heartbeat/session/STOPPED cũ không làm thay đổi quyền mới.

4. P2 — runtime camera động trên AI

| Task | File tạo/sửa dự kiến | Nội dung / nghiệm thu |
|---|---|---|
| A-01 | Mới schemas/cluster.py, schemas/detection.py; sửa core/config.py | worker_id ổn định, session mới mỗi lần chạy, master URL, timeout và hợp đồng v2 |
| A-02 | Sửa camera_orchestrator_service.py, camera_process_worker.py | Tạo capture pool và YOLO với danh sách camera rỗng; command/ACK queue; map camera → process; không nạp model lại khi giao camera |
| A-03 | Sửa camera_thread_worker.py | Capture gắn session/epoch/seq/config/time; khóa shared state bằng camera_id; timeout đọc và dừng có giới hạn |
| A-04 | Sửa yolo_detector.py | Không inference lại cùng frame; metadata không bị mất trong batch; một snapshot chứa đủ ROI/camera |
| A-05 | Mới services/assignment_reconciler.py | Đối chiếu desired/observed; START/STOP cùng epoch idempotent; lệnh cũ không dừng phiên mới |

Khi dừng camera, chặn quyền publish/send trước, dừng capture, loại frame/kết quả cũ và xác nhận sau khi worker thực sự dừng. Inference đang tính dở kiểm tra lại quyền trước ghi output. Nếu cap.read hoặc mở camera bị kẹt, không được chỉ đổi bool rồi báo STOPPED.

Nếu phải khôi phục process chứa nhiều camera, phục hồi tất cả camera trong process theo phân công hợp lệ; xin epoch mới với camera bị reset bộ đếm. Khởi động lại YOLO mà bộ đếm capture còn nguyên không tự reset frame_seq.

Nghiệm thu P2 bằng nguồn video/detector giả lập trước: START lặp; STOP lặp; STOP epoch cũ sau START mới; STOP trong lúc inference; hai camera trùng tên/ROI không ghi đè; process đọc video treo; khôi phục process không bỏ quên camera cùng process; thêm camera không restart cả service.

5. P3 — nhận kết quả và tích hợp logic_service

| Task | File tạo/sửa dự kiến | Nội dung / nghiệm thu |
|---|---|---|
| L-07 | Mới services/detection_ingest.py; sửa api/receive_data.py | Xác thực phiên, owner/epoch/config/lease, seq và tuổi frame; trả kết quả từng item; không nhận legacy cho camera đã chuyển |
| L-08 | Sửa services/POS_manager.py | Applied epoch/seq; freshness; UNKNOWN; xác nhận bằng frame mới; tách observation khỏi reservation |
| L-09 | Mới module điều phối áp dụng snapshot nếu cần | Khôi phục áp dụng snapshot đã lưu nhưng chưa vào POS; idempotent; chỉ dùng snapshot còn mới và đúng quyền |
| L-10 | Mới services/observation_guard.py hoặc adapter tương đương; rà/sửa logic PA/KD/DCC | Mang context các camera/epoch quan sát; kiểm tra lại trước quyết định tạo công việc; vô hiệu công việc chờ dùng dữ liệu hết quyền |
| L-11 | Rà/sửa services/Task_manager.py, api/advanced_debug.py nếu cần | Giữ nghĩa block/unblock/callback; không mở khóa task do camera UNKNOWN; sửa lỗi baseline liên quan có ghi riêng |

Không gọi thẳng update_state bằng payload chưa kiểm tra. Không nhận một frame rồi bỏ metadata khi đưa vào hàng đợi. Việc đổi quyền, vô hiệu quan sát cũ và áp dụng POS cùng camera phải được tuần tự hóa; không giữ khóa đó trong lúc chờ HTTP RCS.

Frame mới có cùng label vẫn là quan sát mới hợp lệ để duy trì freshness và xác nhận trạng thái. Chỉ bỏ frame trùng định danh, không bỏ mọi label lặp. Một frame bị gửi lại không kéo dài freshness hoặc hoàn thành khoảng xác nhận 5 giây.

Khóa/reservation nghiệp vụ được giữ qua chuyển camera. UNKNOWN không được coi là trong. Việc đọc trạng thái rồi await tác vụ khác có thể làm context hết hạn; vì vậy kiểm tra get_state tại đầu hàm chưa đủ. Cần thử đổi epoch giữa bước đọc và tạo task. Nếu reservation gắn task_id, callback cũ chỉ được nhả khóa của đúng task đó, không nhả khóa của task mới. Chống trùng frame không bảo đảm robot thực thi lệnh đúng một lần; giao thức chống trùng lệnh RCS nằm ngoài cam kết của đợt camera này.

Snapshot phải khớp tập ROI được cấu hình, không chỉ kiểm tra các ROI có mặt. Snapshot thiếu ROI không được để lại trạng thái cũ của ROI bị thiếu. Timestamp quá xa trong tương lai hoặc quá cũ phải bị từ chối theo ngưỡng cấu hình; không dùng thời gian nhận để che mất tuổi frame.

Nghiệm thu P3: hai request trùng chạy đồng thời chỉ áp dụng một lần; frame cũ/epoch cũ không đổi POS; toàn bộ ROI của frame cập nhật cùng nhau; lỗi sau lưu snapshot trước áp dụng POS có thể tiếp tục idempotent; callback task vẫn mở đúng khóa; các nhánh PA/KD/DCC xử lý UNKNOWN và dữ liệu hết hạn đúng.

6. P4 — nối thành luồng hoạt động hoàn chỉnh

- A-06: Thêm services/cluster_client.py: register/heartbeat/status, HTTP client dùng lại, request correlation và revision, nhận full assignment khi thay đổi; retry có giới hạn và backoff. Phản hồi trễ không bắt đầu lại đủ lease kể từ lúc nhận.
- A-07: Thêm services/result_reporter.py: gửi snapshot mới nhất/camera; retry giữ nguyên định danh; batch trả kết quả từng camera; bỏ snapshot đã cũ hoặc bị mới hơn thay thế; loại ngay quyền bị master từ chối.
- A-08: Thêm services/health_monitor.py: heartbeat có model_ready, tiến độ capture/inference, số desired/observed, trạng thái process. Kiểm tra local recovery có thời hạn trước khi master thu hồi.
- A-09: Sửa ai_service/main.py và orchestrator: lifespan quản lý các task, process, HTTP client; startup rỗng, READY sau pool/model; shutdown cancel/join có giới hạn; /health phản ánh trạng thái thực. Bỏ phụ thuộc đọc MongoDB lúc startup trong cluster mode.
- L-12: Bổ sung cluster state/metrics: owner hiện hành, epoch, camera chưa có frame mới, thời gian failover, lý do reject, worker desired/observed. Không log frame lớn hoặc credential.

Nghiệm thu P4: khởi động lần lượt bốn AI; một máy không liên hệ được master phải không tự mở camera; mô phỏng AI-01 chết rồi quay lại với cấu hình cũ; máy quay lại bắt đầu rỗng; cân lại sau readiness ổn định; master loại toàn bộ kết quả của phiên cũ.

7. P5 — kiểm thử tích hợp và bằng chứng cần lưu

| Mã | Kịch bản | Tiêu chí đạt |
|---|---|---|
| T01 | 300 camera giả lập, bốn AI | 75/75/75/75; không thiếu ID, không trùng quyền |
| T02 | Tắt một AI | Sau ổn định 0/100/100/100; camera cuối có quan sát mới và xác nhận trong mục tiêu <60 giây |
| T03 | AI cũ khởi động lại | Session mới; không tự chạy camera cũ; cuối cùng 75/75/75/75 |
| T04 | AI cũ vẫn gửi sau chuyển quyền | Số snapshot epoch cũ được áp dụng vào POS bằng 0 |
| T05 | HTTP mất ACK, retry và request đồng thời | Không áp dụng lại frame; retry không làm mới timestamp |
| T06 | Frame, heartbeat, START/STOP đến đảo thứ tự | Không ghi đè bằng frame cũ, không hồi sinh quyền cũ, không dừng camera phiên mới |
| T07 | Dừng camera khi inference còn chạy | Không có kết quả cũ xuất hiện lại sau dọn buffer |
| T08 | YOLO treo nhưng API còn sống | Phát hiện mất tiến độ; phục hồi hoặc thu hồi, không false positive khi worker idle |
| T09 | Một camera hỏng hoặc cap.read bị kẹt | UNKNOWN; không đổi owner vô hạn; xử lý process kẹt có giới hạn |
| T10 | Ngắt đường AI → master và master → AI riêng | AI hết quyền thì dừng; gói muộn không thay đổi quyền mới |
| T11 | MongoDB lỗi hoặc master restart | Không cấp quyền chưa lưu; không dùng lại epoch; startup không nhận snapshot quyền cũ |
| T12 | Đổi epoch trong khi dữ liệu chờ vào POS/logic | Không áp dụng quan sát cũ sau vô hiệu; quyết định trì hoãn không dùng context đã hết quyền |
| T13 | Callback task, block/unblock, SSE/nhóm | Khóa task giữ qua UNKNOWN; callback và nhóm nghiệp vụ vẫn đúng |
| T14 | Trộn bản cũ/v2 trong giai đoạn chuyển | Camera đã vào cluster không có đường legacy ghi đè POS |

Kiểm thử unit dùng đồng hồ giả cho lease/freshness; kiểm thử tích hợp MongoDB kiểm tra conditional update thật; kiểm thử API dùng AI/detector/RCS giả lập, không phát lệnh robot thật. Kiểm thử runtime cần ít nhất một nguồn video thử để xác minh hành vi mở/đọc/dừng thực tế của backend.

Mỗi lần thử failover lưu mốc: lỗi máy, hết quyền, giao mới, frame đầu tiên từng camera, trạng thái nghiệp vụ xác nhận. Đánh giá camera cuối cùng, không chỉ trung bình hoặc camera đầu tiên. Giả lập 300 camera chứng minh logic điều phối; nghiệm thu thời gian cần thử trên luồng camera thực tương ứng.

8. P6 — chuyển đổi, mở rộng và quay về bản cũ

Chuẩn bị master v2 trước, scheduler chưa quản lý camera sản xuất; dùng môi trường/nhóm thử tách biệt và RCS giả lập để hoàn tất P5. Thiết lập một bảng danh sách camera thuộc legacy hoặc cluster, ánh xạ ROI/vị trí chính xác; không suy đoán nguồn từ group_id khi mapping mơ hồ.

Quy trình chuyển một nhóm:

1. Chọn nhóm có mapping xác định; ưu tiên chuyển các vị trí cùng phụ thuộc nghiệp vụ trong cùng đợt. Lưu cấu hình và phiên bản có thể quay về.
2. Dừng nguồn legacy của nhóm, xác nhận không còn gửi; master khóa đường nhận legacy của các camera/vị trí đó và vô hiệu quan sát cũ.
3. Bật quản lý cluster cho nhóm; AI nhận quyền mới; đợi frame mới và khoảng xác nhận. Không có lúc cả legacy và v2 cùng được ghi một camera/vị trí.
4. Kiểm tra owner/epoch, số camera, UNKNOWN, callback và logs reject. Thử mất một AI và máy trở lại trên nhóm này.
5. Mở rộng theo nhóm tới 300 camera; nghiệm thu T01–T14 phù hợp và thời gian thực tế. Bật vận hành robot thật theo quy trình vận hành của hệ thống sau khi dữ liệu và nghiệp vụ đã được kiểm chứng.

Quay về phiên bản trước nếu các tiêu chí không đạt: tạm dừng việc tạo công việc mới cho nhóm; thu hồi quyền cluster và chờ AI dừng/hết quyền; chặn dữ liệu v2 của nhóm; vô hiệu quan sát; chỉ sau đó khôi phục nguồn legacy duy nhất và đợi dữ liệu mới. Giữ nguyên lịch sử/epoch, không xóa camera_runtime để reset số phiên. Đối soát task đang chạy trước tiếp tục; không giải quyết rollback bằng cách xóa khóa task.

Đã sửa code và chạy kiểm thử local bằng MongoDB tạm, detector/RCS giả lập và video tổng hợp. Chưa đổi database sản xuất, dừng dịch vụ đang vận hành hoặc phát lệnh robot thực.

9. Quy tắc hoàn thành một đợt triển khai

- Mỗi task có thay đổi cụ thể, test phù hợp và kết quả thực tế; không ghi pass khi chỉ mới đề xuất test.
- Mọi file có sẵn của logic_service bị sửa có mục tương ứng trong [nhật ký duy nhất](logic-service-change-log.md), gồm cả requirements/config/json nếu bị thay đổi.
- Đối chiếu danh sách file logic_service sửa trong diff với nhật ký trước bàn giao. Nếu phát sinh file ngoài inventory, bổ sung ngay; file đã sửa nhiều lần cần ghi thêm đợt thay đổi, không ghi đè lịch sử cũ.
- Mỗi đợt chỉ mở rộng thử nghiệm khi kiểm tra trước đã đạt; lỗi baseline và lỗi do thay đổi mới được phân biệt.
- Bộ báo cáo cuối gồm phiên bản hai service, cấu hình timeout, mapping camera, test đã chạy, số liệu failover, log reject epoch cũ và nhật ký file logic_service.


10. Ghi nhận triển khai code và điều chỉnh tổ chức module

- Master: gom WorkerRegistry, AssignmentManager, Scheduler và DetectionIngest vào services/cluster_runtime.py để dùng chung khóa điều phối và lifecycle; tách schemas, API và repository. Không tạo các wrapper chỉ để trùng tên file dự kiến trong kế hoạch.
- AI: thêm services/cluster_runtime.py, cluster_capture.py và cluster_detector.py cho chế độ cluster; main.py chọn runtime theo CLUSTER_ENABLED. Pipeline legacy giữ riêng để không trộn dictionary ROI phẳng với snapshot v2.
- Hai service mặc định CLUSTER_ENABLED=false; cấu hình .env.example bật rõ ràng và master CLUSTER_ROBOT_ENABLED=false. Phiên bản này chuyển toàn bộ nguồn của một master sang v2; nhóm thử dùng master/catalog riêng. Chưa hỗ trợ trộn legacy/v2 theo camera trên cùng master. Đây là giới hạn so với quy trình chuyển từng nhóm trên cùng master tại P6; dùng runbook bên dưới cho phiên bản hiện tại.
- Catalog camera nạp khi master khởi động, chưa có hot-reload catalog. Thay ROI/path tăng config_version và thực hiện restart có đối soát task.
- Test local gồm MongoDB CAS thật, cạnh tranh ingest/handover, schema giữa hai service, API auth/legacy gate, POS freshness/reservation, luồng gọi robot bằng stub và video tổng hợp local. Chưa chạy Torch/Ultralytics/model thực trong môi trường kiểm thử này, chưa đo GPU hoặc RTSP thật.
- Xem [hướng dẫn vận hành](camera-cluster-operations.md), [nhật ký file đã sửa](logic-service-change-log.md) và `camera-cluster-validation.md` (removed during cleanup). Các tiêu chí hiện trường chưa được đánh dấu hoàn tất chỉ từ test local.


11. Đợt chuyển sang file cấu hình và RAM theo yêu cầu mới

- Phạm vi: master đọc config/cameras.json; toàn bộ phân công/session/heartbeat/lease/cursor/snapshot/POS/task hoạt động nằm trong RAM. Loại MongoClusterRepository và MongoDB khỏi đường chạy cluster, không thêm SQLite. AI API v2 giữ nguyên; AI chỉ lazy-import DB ở chế độ legacy.
- Thêm core/camera_catalog.py để validate JSON và giới hạn kích thước/số camera/ROI. config/cameras.example.json là mẫu; cameras.json thực bị gitignore để bảo vệ RTSP credential.
- repositories/cluster_repository.py dùng RamClusterRepository với conditional update trong cùng event loop, dữ liệu copy riêng và ring buffer history. Các tác vụ chuyển quyền/ingest vẫn dùng khóa camera như đợt trước.
- core/local_master_session.py giữ khóa OS cục bộ và ghi đè runtime/cluster_boot.json nhỏ mỗi startup để cấp khoảng epoch mới. Đây không phải HA hay đồng bộ task. Khi khởi động chờ lease 15 giây trước cấp lại, POS nhận frame mới và debounce lại.
- Người dùng chấp nhận khả năng phát lại nhiệm vụ trong giai đoạn khôi phục sau restart/chuyển master. Đợt này chỉ làm single-master restart; chưa làm swap/standby và chưa cam kết giới hạn lệnh trùng trong đúng một vòng lặp.
- SSE có giới hạn client/queue và đóng client chậm; logger master xoay theo kích thước với tên cố định. History chỉ giữ số event cấu hình trong RAM. Chưa có trần cứng cho toàn bộ RAM/request/task; 512 MiB/máy là ngân sách dự trù.
- Công cụ test không cần --with-mongo hoặc mongod. Đạt 50 test (36 master, 14 AI) và 44 file AST; camera/GPU/robot thật, tải dài ngày và mục tiêu camera cuối dưới 60 giây chưa nghiệm thu.
- HA master được người dùng yêu cầu hoãn: không triển khai VIP, witness, leader phân tán hoặc đồng bộ task. Giữ một master, một process và một state path cục bộ.
- Tài liệu hiện hành: [deployment](camera-cluster-deployment.md), [operations](camera-cluster-operations.md), `camera-cluster-validation.md` (removed during cleanup), [nhật ký](logic-service-change-log.md). Nội dung đợt mới này thay thế các mô tả dùng MongoDB ở P1/P3/P5 trong kế hoạch ban đầu.
