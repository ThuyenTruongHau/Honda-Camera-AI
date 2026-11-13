Nhật ký thay đổi các file có sẵn trong logic_service

Ngày tạo và cập nhật: 10/11/2026. Đợt triển khai: camera cluster, P0–P5 và chuyển JSON/RAM. Mục 1–5 là lịch sử đợt đầu; mục 6 là thay đổi hiện hành thay backend MongoDB. Trạng thái: đã sửa code và kiểm thử local; chưa triển khai hệ thống camera/robot thực.

Đây là tài liệu duy nhất ghi các file có sẵn của logic_service bị sửa trong đợt này theo yêu cầu của người dùng. Kế hoạch: [camera-cluster-implementation-plan.md](camera-cluster-implementation-plan.md). Kết quả và giới hạn kiểm thử: `camera-cluster-validation.md`. Cách cấu hình/chuyển đổi: [camera-cluster-operations.md](camera-cluster-operations.md).

1. Danh sách thay đổi đã thực hiện

Có 10 file có sẵn của logic_service bị sửa. Tất cả mục dưới đây thuộc ngày 10/11/2026; ghi cả thay đổi CLUSTER và sửa lỗi BASELINE khi cùng nằm trong một file. Đây là bản ghi thực hiện, thay cho inventory dự kiến ban đầu.

| Mã | File | Task | Vùng sửa và hành vi trước → sau | Kiểm chứng thực tế / giới hạn |
|---|---|---|---|---|
| LC-20261110-001 | main.py | P1/P3/P4 | CLUSTER: lifespan khởi tạo/dừng runtime cluster cùng POS, dọn task cả khi startup thất bại; đăng ký router cluster; health phản ánh controller; từ chối WEB_CONCURRENCY khác 1 khi bật cluster. Chỉ log loại lỗi startup để không đưa cấu hình kết nối vào log. Trước chưa có scheduler hoặc master lease. | AST đạt; lifecycle controller được test qua runtime; test lỗi startup xác nhận POS/SSE được dọn. Chưa thử toàn bộ ứng dụng với cấu hình DB/RCS hiện trường. |
| LC-20261110-002 | core/config.py | P0/P1 | CLUSTER: bổ sung Mongo config, cờ cluster/robot, token theo worker, heartbeat/lease, freshness, recovery delay và batch cân lại. Validate cấu hình cluster, không cho APP_DEBUG khi bật. Mặc định cluster và robot cluster tắt. | AST và import trong suite đạt; chưa kiểm thử mọi tổ hợp biến môi trường. |
| LC-20261110-003 | api/receive_data.py | P3 | CLUSTER: /ai-data nhận snapshot v2 có token, chuyển qua kiểm tra ownership/session/epoch/config/seq trước POS, trả kết quả từng camera. Khi cluster bật, legacy bị từ chối; khi tắt giữ luồng legacy. BASELINE: thêm import HTTPException cho nhánh lỗi. | Test HTTP bằng ASGI: auth, heartbeat, legacy gate, ingest v2; không kết nối robot. |
| LC-20261110-004 | services/POS_manager.py | P3 | CLUSTER: thêm apply_camera_snapshot/invalidate_camera idempotent, freshness, UNKNOWN, applied cursor; xác nhận trạng thái theo frame mới. Tách observation khỏi reservation theo orderId; task giữ context quan sát và kiểm tra lại ngay trước gửi robot. Lệnh mạng không nằm trong khóa camera. Quản lý task nền tự động/thủ công để shutdown và ghi lỗi. Callback chỉ mở khóa đúng order. | Test debounce, mất frame, duplicate, đổi epoch, reservation, context hết quyền sau await và cờ robot; test wrapper nghiệp vụ bằng stub. Không chứng minh quy tắc PA/KD/DCC trên toàn bộ map thực. |
| LC-20261110-005 | services/Task_manager.py | P3 | CLUSTER: callback truyền order_id vào un_block_point để không mở khóa task khác; callback manual 3-* cũng giải phóng reservation trước clear_monitor. Trước callback không kiểm tra chủ sở hữu khóa và manual chỉ clear monitor. | Test callback 4-* và 3-* kiểm tra đúng orderId được truyền. Task vẫn nằm trong RAM; chưa thêm khôi phục task sau master restart. |
| LC-20261110-006 | api/advanced_debug.py | P0/P3 | CLUSTER: chuẩn hóa payload points/point/dictionary thành danh sách point cho block/unblock. BASELINE: thêm import HTTPException. | AST đạt; thao tác POS được test riêng. Chưa có test HTTP riêng cho các route debug. |
| LC-20261110-007 | logic/PA_logic.py | P0/P3 | CLUSTER: add_task đi qua POS.send_robot_task để guard/reserve trước gọi RCS; đăng ký tracking trước gửi để xử lý callback sớm, xóa tracking nếu guard từ chối và giữ khi kết quả mạng chưa rõ. BASELINE: sửa elif đầu nhánh thành if để module import được. Đường đi không phải 2/4 điểm ghi lỗi và không tạo lệnh. | Module import và wrapper guard bằng stub đạt. Nhánh ba điểm vốn tồn tại chưa có contract RCS rõ; cần UAT/xác nhận nghiệp vụ, không tự suy ra payload mới. |
| LC-20261110-008 | logic/KD_logic.py | P0/P3 | CLUSTER: chuyển gửi lệnh qua guard/reservation, không block khi bị guard từ chối; manual task được POS quản lý; vòng chờ tiếp tục kiểm tra dữ liệu mới khi chưa đủ điều kiện. BASELINE: sửa truy cập _tracking_task thành tracking_task đúng tên thuộc tính. | Import, wrapper guard và callback manual đạt; chưa chạy đủ mọi vòng chờ/nhánh KD với robot thực. |
| LC-20261110-009 | logic/DCC_AE3_AE4_logic.py | P3 | CLUSTER: add_task qua guard, xóa tracking khi bị guard từ chối; chỉ cập nhật zone sau HTTP thành công. BASELINE: thay truy cập robots_in_zone không được khai báo bằng robot_service.robot_in_zones. | Test wrapper guard và zone không đổi khi guard từ chối / đổi sau thành công. Chưa UAT mọi route DCC. |
| LC-20261110-010 | logic/DCC_AF3_AF4_logic.py | P0/P3 | CLUSTER và BASELINE: như AE3/AE4 cho guard và zone; sửa states[3] thành states[2] trong handler có ba phần tử, tương ứng phần tử cuối matching[1:4]. | Test wrapper guard/zone và handler ba trạng thái không truy cập ngoài mảng. Mapping nghiệp vụ cuối cùng cần UAT. |

requirements.txt, services/Robot_manager.py, services/SSE_manager.py, api/sse_connection.py và config/map_config/*.json không bị sửa trong đợt này. Dependency kiểm thử nằm trong requirements-test.txt ở gốc repo. Không sửa giá trị URL/credential sản xuất để chạy test.

2. Thay đổi tương thích và hành vi vận hành

- CLUSTER_ENABLED=false giữ entry point và đường nhận legacy. Khi bật, toàn bộ /ai-data của master yêu cầu schema_version=2 và worker token; không trộn bản AI cũ với mới trên cùng master. Nhóm thử cần master/catalog riêng.
- Worker có worker_id ổn định, session_id mới mỗi lần khởi động. Master cấp camera từ catalog, lưu epoch và cursor trong MongoDB. AI không đọc MongoDB để tự mở lại camera cũ khi chạy cluster.
- Callback robot giữ route/payload hiện có. Tách reservation khỏi trạng thái quan sát nên mất camera/UNKNOWN không giải phóng khóa của task đang chạy. Callback cũ không mở khóa task mới.
- Các nhánh tạo task dùng POS.send_robot_task. Trong cluster, CLUSTER_ROBOT_ENABLED=false chặn gửi robot; khi bật vẫn phải có context quan sát còn mới, đúng epoch và reservation phù hợp. PA/KD/hai DCC bỏ lần block_point dư sau HTTP vì reservation đã lấy trước gửi; callback đến sớm không bị khóa lại sau response (có test cả bốn module). Lỗi HTTP/timeout giữ reservation vì có thể robot đã nhận lệnh; cần đối soát orderId, không tự phát lại để giả định exactly-once.
- MongoDB có camera_runtime, ai_workers, assignment_events và khóa cluster_master. Không xóa epoch khi restart/rollback. Catalog được nạp khi startup; thay cấu hình camera cần tăng config_version và restart có đối soát task. Camera runtime lưu mốc chuyển quyền/frame đầu cùng CAS; assignment_events là lịch sử chẩn đoán và có thể thiếu event nếu crash giữa hai lần ghi, không dùng làm nguồn quyết định ownership.
- Singleton trong MongoDB và chế độ một process giúp phát hiện master chạy trùng. Đây không phải triển khai master active–standby; task robot vẫn lưu RAM.

3. Các file mới trong logic_service

| Nhóm | File mới và trách nhiệm |
|---|---|
| API/schema | api/cluster.py; schemas/cluster.py; schemas/detection.py — register, heartbeat, camera-status, state và snapshot v2 |
| Repository | repositories/cluster_repository.py — Memory repository cho test, MongoDB conditional update và khóa master |
| Runtime | services/cluster_runtime.py — registry, assignment, scheduler, ingest và projection cùng lifecycle/khóa camera |
| Guard | services/observation_guard.py — context các quan sát đã dùng khi quyết định tạo công việc |
| Cấu hình mẫu | .env.example — bật cluster rõ ràng, token placeholder, robot mặc định tắt |
| Kiểm thử | tests/test_cluster.py; tests/test_positions.py; tests/test_api_business.py — điều phối, Mongo thật, API, POS và tích hợp nghiệp vụ |

Runtime được gom trong một module thay vì các wrapper worker_registry/assignment_manager/detection_ingest riêng dự kiến ở kế hoạch. Các trách nhiệm vẫn tách theo phương thức và repository; việc này giữ thứ tự khóa ingest/chuyển quyền rõ ràng. Pipeline AI cluster là các module mới độc lập với pipeline legacy.

4. Lỗi baseline và giới hạn còn lại

| Mã | Vấn đề | Kết quả đợt này |
|---|---|---|
| B01 | PA elif không có if, lỗi cú pháp | Đã sửa; AST và import đạt |
| B02 | receive_data/advanced_debug thiếu HTTPException | Đã bổ sung; receive_data có HTTP test, advanced_debug mới kiểm tra cú pháp |
| B03 | KD dùng _tracking_task thay vì tracking_task | Đã sửa tên thuộc tính |
| B04 | DCC_AF handler ba phần tử truy cập states[3] | Đã sửa phần tử cuối thành states[2], có test nhánh |
| B05 | DCC dùng robots_in_zone không khai báo | Đã dùng robot_service.robot_in_zones, chỉ cập nhật sau HTTP thành công |
| B06 | PA có đường ba điểm nhưng request_RCS chỉ hỗ trợ hai/bốn | Chưa bổ sung quy tắc RCS; ghi lỗi và không phát lệnh. Cần xác nhận nghiệp vụ trước chạy nhánh này |

5. Kiểm chứng và hoàn nguyên

Lệnh đã dùng từ gốc repo: `python tools/run_cluster_checks.py --with-mongo`. Công cụ chạy hai suite ở process riêng, dùng MongoDB tạm trên loopback, rồi dừng instance tạm. Báo cáo máy đọc được: artifacts/cluster-checks.json; mô tả kết quả và tiêu chí hiện trường còn lại: `camera-cluster-validation.md`.

Đối chiếu trước bàn giao: danh sách tracked file từ `git diff --name-only -- logic_service` phải khớp 10 mục LC ở trên. File mới được theo dõi riêng tại mục 3. AST và `git diff --check` dùng để phát hiện cú pháp/whitespace; không thay thế test runtime.

Hoàn nguyên theo runbook: dừng tạo task mới, dừng AI cluster và chờ hết lease, đối soát task, giữ epoch rồi mới khởi động lại nguồn legacy duy nhất. Không xóa reservation/epoch để che lỗi. Đã sửa code và kiểm thử local; chưa thực hiện thao tác hoàn nguyên hoặc triển khai trên máy sản xuất.


6. Đợt JSON/RAM ngày 10/11/2026 — hiện hành, HA hoãn

Yêu cầu mới: dùng file config camera và RAM, không SQLite; chấp nhận khả năng nhiệm vụ cũ tạo lại trong đợt khôi phục. Người dùng yêu cầu chưa triển khai HA master. Đợt này thay các hành vi MongoDB ghi ở mục 1–5, giữ lịch sử đợt trước để đối chiếu.

| Mã | File đã có khi bắt đầu đợt này | Thay đổi trước → sau, lý do | Kiểm chứng thực tế |
|---|---|---|---|
| LC-20261110-011 | core/config.py | Bỏ mongo_url/mongo_db của master; thêm camera config path, boot state path, giới hạn camera/ROI/history/SSE. Validate path không rỗng; mặc định robot/cluster vẫn tắt trong code. | Config import trong suite; loader/path/giới hạn được test. |
| LC-20261110-012 | repositories/cluster_repository.py | Mongo repository + memory fixture → RamClusterRepository dùng cho runtime; alias MemoryClusterRepository giữ test cũ. Conditional update kiểm tra revision/epoch/session trong cùng event loop; ring buffer giới hạn history; epoch có khoảng riêng mỗi boot. Không kết nối DB, không lưu snapshot xuống đĩa. | CAS 20 cạnh tranh chỉ một thành công; history cap; bộ test điều phối/ingest và factory JSON/RAM. |
| LC-20261110-013 | services/cluster_runtime.py | Factory Mongo → nạp JSON, lấy OS lock/boot counter rồi tạo RAM repository. Startup chờ lease cũ; state API có storage/recovery/history. Dọn khóa khi startup lỗi/cancel hoặc stop. Giữ kiểm tra owner/session/epoch/seq/freshness và chuyển tải AI. | Test factory restart RAM rỗng, epoch tăng, stale packet bị loại, grace, lock giải phóng; regression 300 camera. |
| LC-20261110-014 | services/SSE_manager.py | Queue vô hạn → queue/client có giới hạn trong cluster mode; queue đầy ngắt client bằng sentinel; shutdown không đợi queue có chỗ trống. Legacy giữ queue không giới hạn như trước. | Test max client/queue, slow client và shutdown không treo. Client thực cần UAT reconnect; không có replay. |
| LC-20261110-015 | api/sse_connection.py | Generator nhận None thì kết thúc stream thay vì yield None, tương thích sentinel khi ngắt client chậm/shutdown. | AST đạt; manager/sentinel có test, chưa UAT trình duyệt. |
| LC-20261110-016 | shared/logger.py | Log theo ngày với basename chứa ngày → tên cố định, xoay theo kích thước 5 MiB và ba backup (khoảng 20 MiB mỗi nhóm logger), tránh tập file ngày tăng qua restart. Áp dụng logger master cả legacy/cluster. Không xóa log cũ đã tồn tại. | Import/lifecycle suite và AST đạt; chưa stress xoay log. |
| LC-20261110-017 | .env.example | Bỏ Mongo sample, thêm JSON/boot-state path và giới hạn dữ liệu/history/SSE. Token vẫn placeholder, robot tắt. | Đối chiếu với tên field Settings; chưa chạy trên máy sản xuất. |
| LC-20261110-018 | tests/test_cluster.py | Bỏ hai test MongoDB không còn phù hợp backend; giữ regression phân công/ingest/restart/POS; đổi tên ca repository failure. | Tất cả ca còn lại đạt; test CAS/factory backend RAM thay thế nằm trong test_file_ram.py. |

File mới trong logic_service của đợt này: core/camera_catalog.py, core/local_master_session.py, config/cameras.example.json và tests/test_file_ram.py. Bộ đếm boot chỉ lưu version/generation, ghi đè qua file tạm; file mất/hỏng sau khởi tạo hoặc lỗi ghi khiến startup dừng, không reset epoch. Khóa cục bộ không cung cấp HA.

Ngoài logic_service: ai_service/main.py lazy-import database chỉ trong legacy; .gitignore bỏ qua camera config thật/runtime/.venv; requirements-test.txt bỏ motor; tools/run_cluster_checks.py bỏ mongod/--with-mongo. Giữ nguyên schema v2 và giao thức AI, không cần field HA mới.

Kết quả hiện hành: `python tools/run_cluster_checks.py` đạt 36 master + 14 AI = 50 test, không cần DB; AST 44 file không lỗi. Có cảnh báo deprecation thư viện. Chi tiết tại `camera-cluster-validation.md`. Các test master mới gồm JSON schema/limit, OS lock ở process khác, counter mất/hỏng/lỗi ghi, factory restart với lease grace, bounded CAS/history/SSE. Không coi các test này là nghiệm thu GPU/RTSP/robot hoặc HA.

Đối chiếu toàn đợt với git baseline: hiện có 13 file logic_service tracked bị sửa — 10 file mục 1 cộng services/SSE_manager.py, api/sse_connection.py và shared/logger.py. Những file cluster đã tạo ở đợt trước nhưng còn untracked cũng có mục 012/013/017/018 để ghi nhận sửa tiếp. Không sửa requirements.txt, Robot_manager.py hoặc JSON map nghiệp vụ.

Runbook hiện hành dùng JSON/RAM. Không dùng lệnh --with-mongo ở đợt cũ. Giữ boot state qua restart/rollback; dữ liệu task/observation không lưu bền. Chưa triển khai standby, swap, VIP, witness hoặc đồng bộ task master; không tuyên bố giới hạn nhiệm vụ trùng trong đúng một vòng lặp sau failover. Lỗi PA ba điểm ở B06 vẫn cần xác nhận nghiệp vụ.

7. Bộ giả lập bốn AI ngày 10/11/2026

Đợt này không sửa thêm file ứng dụng có sẵn trong logic_service hoặc ai_service. Thêm tools/simulate_camera_cluster.py và tools/cluster_simulator/{__init__,components,runner}.py; requirements-test.txt bổ sung uvicorn. Endpoint /simulation/observations chỉ được thêm vào app trong entry point test để kiểm tra POS, không nằm trong app triển khai mặc định.

Master chạy HTTP thật và bốn AI chạy ClusterAIService thật trong process riêng; capture/inference được thay bằng target giả trong process test, hoặc dùng capture OpenCV thật với RTSP local và inference giả. Config/boot state/token/port/cwd được tạo riêng trong artifacts, robot tắt. Công cụ kill đúng cây process AI do nó tạo, kiểm tra chuyển quyền, khởi động lại AI và loại snapshot epoch/session cũ. HA master vẫn chưa triển khai.

Kết quả: 300 camera virtual đạt 75/75/75/75 → 100/100/100 → 75/75/75/75, nhóm camera lỗi xác nhận lại cuối cùng sau 21,047s ở timing mặc định. Kịch bản 12 kết nối RTSP local thật/detect giả đạt với profile quick, mốc tương ứng 12,062s. Không coi hai số đo khác profile là so hiệu năng hoặc nghiệm thu 300 RTSP vật lý. Regression vẫn 50 test đạt, AST hiện 48 file không lỗi. Xem `camera-cluster-simulation.md` và `camera-cluster-validation.md` để chạy lại/đọc báo cáo.
8. Chuyển danh sách camera từ config.py ngày 10/11/2026

| Mã | File có sẵn được sửa | Thay đổi | Kiểm chứng |
|---|---|---|---|
| LC-20261110-019 | config/cameras.example.json | Thay hai camera minh họa bằng 74 camera và 206 ROI đang khai báo trong CAMERAS của config.py; bỏ qua các mục đã comment. Giữ nguyên URL RTSP, enabled=true, config_version=1; group_id giữ tên zone. camera_id tạo từ IP, cổng và kênh để không phụ thuộc thứ tự danh sách. | Loader thực tế load_camera_catalog đọc thành công; đối chiếu đủ URL, zone, số ROI và tọa độ với nguồn; camera_id và tên ROI không trùng. |

Quy tắc chuyển ROI: node_id dạng start_N/end_N thành name="N" để khớp khóa vị trí dạng số mà map nghiệp vụ hiện dùng; [x, y, width, height] thành x1=x, y1=y, x2=x+width, y2=y+height. Không tự đổi tỷ lệ tọa độ. Cần đối chiếu hệ tọa độ nguồn với ảnh AI đang xử lý (pipeline hiện resize 1280×720) trước khi chạy thực tế.

Phân bố nguồn: AE5=14, AE6=15, 5L=5, 6L=7, AF=19, Sub6=14. group_id hiện là chuỗi zone từ nguồn; endpoint SSE nhận group_id kiểu int cần được đối chiếu nếu dùng các nhóm này trên giao diện. Không tự suy diễn mã nhóm số.

Chỉ 9/206 tên vị trí sau chuyển đổi có trong các file map_config hiện tại; 197 vị trí chưa có ánh xạ nghiệp vụ. Catalog hợp lệ không đồng nghĩa các vị trí đã sẵn sàng gọi robot. Không sửa map nghiệp vụ trong đợt này. File đích giữ thông tin truy cập RTSP theo yêu cầu; nhật ký không ghi URL hay mật khẩu. Không tạo cameras.json, không đổi cấu hình chạy hoặc kết nối camera.

9. Dọn file không phục vụ triển khai ngày 10/11/2026

Theo yêu cầu xóa file không dùng và kiểm thử, đã xóa các mục dưới đây. Những lệnh test, đường dẫn tools/artifacts và số liệu test trong mục 1–7 chỉ còn là lịch sử, không phải hướng dẫn áp dụng cho cây mã hiện tại.

| Mã | File/thư mục logic_service bị xóa | Lý do |
|---|---|---|
| LC-20261110-020 | test.html | Trang thử SSE thủ công; không được ứng dụng phục vụ hoặc import. |
| LC-20261110-021 | tests/test_positions.py, tests/test_file_ram.py, tests/test_cluster.py, tests/test_api_business.py | Bộ kiểm thử phát triển, không phải dependency chạy service. Xóa toàn bộ thư mục tests. |

Ngoài logic_service: xóa ai_service/tests, requirements-test.txt, toàn bộ tools (runner kiểm thử và simulator), artifacts (báo cáo, script tạm, video/cấu hình/log thử và MediaMTX tải cho giả lập), docs/camera-cluster-simulation.md và docs/camera-cluster-validation.md. Xóa cache Python __pycache__ trong dự án. Sửa deployment/operations để bỏ hướng dẫn gọi công cụ đã xóa; giữ lịch sử thay đổi trong tài liệu này.

Không sửa mã ứng dụng trong đợt dọn này. Giữ các module legacy, api/advanced_debug.py vì vẫn được main/orchestrator gọi; giữ weights, cấu hình camera/map/robot, config.py nguồn và tài liệu kiến trúc/triển khai. Không xóa log vận hành hoặc boot state. Kiểm chứng sau dọn: phân tích cú pháp Python còn lại, nạp catalog 74 camera/206 ROI bằng loader thực tế và git diff --check; không chạy lại bộ test đã xóa.

10. Đơn giản hóa quyền camera ngày 11/11/2026 — hiện hành

Theo yêu cầu chỉ giữ camera_id, owner_worker_id, assignment_epoch, lease_expires_at trong bản ghi ownership. Những mô tả session/revision/sequence/CAS/DRAINING và giao thức v2 ở các mục trước chỉ còn là lịch sử.

| Mã | File logic_service có sẵn được sửa | Trước → sau |
|---|---|---|
| LC-20261111-001 | services/cluster_runtime.py | Nhiều khóa/revision/session, drain/STOPPED và lưu snapshot → một control lock cho register/heartbeat/tick/ingest/state. Ownership đúng bốn trường; thu hồi xóa owner và giữ lease cũ, cấp lại sau hạn với epoch tăng. Register luôn thu hồi quyền của worker; heartbeat chỉ gia hạn claim đúng camera/epoch, còn hạn và ready. Ingest áp dụng trực tiếp vào POS. |
| LC-20261111-002 | repositories/cluster_repository.py | CAS/revision, worker và lease controller trong repository → load/list/get/save ownership bốn trường và history deque giới hạn. Validate đúng key và khoảng epoch của generation. Không DB, không snapshot cache. |
| LC-20261111-003 | schemas/cluster.py | Bỏ session_id, heartbeat_seq, inference_alive/progress frame_seq và CameraStatusRequest. Register chỉ worker_id; heartbeat thêm ready và danh sách camera_id/epoch đang giữ quyền. |
| LC-20261111-004 | schemas/detection.py | Detect v2/session/frame_seq → v3, worker_id và snapshot camera/epoch/config_version/timestamps/ROI. Các trường detect không thuộc ownership. |
| LC-20261111-005 | api/cluster.py | Bỏ route /cluster/camera-status; giữ register, heartbeat, state và xác thực token theo worker. |
| LC-20261111-006 | api/receive_data.py | Thông báo lỗi validation v2 → v3; router vẫn chọn legacy khi cluster tắt. |
| LC-20261111-007 | services/POS_manager.py | apply_camera_snapshot bỏ seq; dùng (epoch, observed_at) để bỏ snapshot đã áp dụng hoặc đến muộn; bỏ seq khỏi state vị trí. Giữ freshness, xác nhận nhãn, reservation và guard nghiệp vụ. |
| LC-20261111-008 | README.md | Viết lại theo quy trình bốn trường, giới hạn không session, chờ lease và nâng cấp v3. |

Ngoài logic_service: sửa ai_service/schemas/{cluster,detection}.py, services/{cluster_runtime,cluster_capture,cluster_detector}.py và README.md. AI bỏ session/revision/frame_seq và báo camera-status; request HTTP được tuần tự hóa, heartbeat chỉ claim camera còn quyền/chưa stopping. Capture/detector/report dùng timestamp có sẵn để chọn dữ liệu mới. Event STOPPED vẫn dùng cục bộ để dọn process, không báo master. Thêm core/worker_lock.py và ignore ai_service/runtime/ để ngăn hai instance cùng worker trong cùng bản cài.

Sửa tài liệu deployment/operations/walkthrough theo giao thức hiện tại; gắn nhãn lịch sử cho architecture/implementation-plan/memory-and-ha. Giữ nguyên RTSP/ROI trong cameras.example.json, cấu hình map/robot, requirements và boot counter master. Chưa làm HA.

Đánh đổi có chủ ý: không cấp lại sớm nhờ STOPPED; phải chờ lease cũ kể cả AI đã dừng. Không còn session để phân biệt hai instance cùng worker ID trên hai máy: triển khai phải bảo đảm WORKER_ID duy nhất và một instance; khóa file chỉ bảo vệ cùng đường dẫn cài. Khi nâng cấp cần dừng toàn bộ AI, chờ hết lease cũ, giữ boot counter và nâng master/AI cùng đợt. Payload v2 và trường session thừa bị từ chối. State API cameras đổi từ _id/state/frame metadata sang đúng bốn trường; client giám sát phải cập nhật.

Kiểm chứng chạy trực tiếp, không tạo lại thư mục test/tools/artifacts:

- Đồng hồ giả lập, master runtime/repository/schema thật: 300 camera 75/75/75/75 → mất AI-01 → 100/100/100 → AI-01 trở lại → 75/75/75/75; mọi row đúng bốn key; không cấp trước lease cũ; loại dữ liệu chủ/epoch cũ; register retry giữ hàng rào lease.
- AI runtime với queue/dict và HTTP transport giả: START/STOP/reconcile, rejected epoch, kiểm tra worker response, detector chọn timestamp mới, payload v3 và chỉ một HTTP request cùng lúc. Khóa worker được kiểm tra bằng interpreter thứ hai; nhả khóa thì process mới mở được.
- POS thật: snapshot cùng timestamp hoặc đến muộn không thay pending state; epoch cũ bị chặn sau invalidate. Contract từ chối trường session/heartbeat_seq cũ và envelope v2.
- FastAPI routes thật qua ASGI transport, factory với catalog/boot state tạm: auth 401, v3 accepted, v2/old fields 422, camera-status 404, health, bốn trường state, generation tăng qua restart và khoảng chờ lease mới.
- Capture thread/queue thật với nguồn OpenCV giả: START/STOP, không chạy chồng epoch trong process, xóa frame/release khi hết quyền và shutdown; không còn shared dict tiến độ camera không được dùng. Assignment của catalog 74 camera được validate bằng schema AI và envelope AI v3 được master validate/ingest thành công.

Đây là kiểm tra logic và giao thức local, chưa chạy model/GPU, kết nối camera RTSP hoặc phát lệnh robot thật. Không khẳng định đã nghiệm thu phục hồi dưới một phút trên hệ thống thật.

11. Format gửi map điểm — giới hạn phạm vi theo yêu cầu ngày 11/11/2026

Người dùng yêu cầu chỉ làm tới phần ai_service gửi /ai-data, không sửa xử lý trạng thái hoặc lệnh robot. Đã hoàn nguyên các sửa đổi thử trong schemas/detection.py, services/cluster_runtime.py, api/receive_data.py, services/POS_manager.py, core/camera_catalog.py và README.md của logic_service về nội dung trước đợt đổi format. File core/point_contract.py vừa thêm bên master cũng được bỏ. Không đổi nghiệp vụ, thời điểm xác nhận/kích hoạt, reservation, API nhận, catalog hoặc chia camera của master.

Thay đổi giữ lại chỉ ở AI: schemas/detection.py tạo map ID điểm → label/group_id với _cluster v4 (worker_id, camera_id, epoch, config_version, timestamps, point_ids). Thêm core/point_contract.py chuẩn hóa key số/bỏ start_/end_ và END_POINT_EMPTY. Capture truyền group_id; detector bỏ class lạ, ROI không chắc chắn và điểm 10001546. Report gửi qua build_payload, hỗ trợ response success đơn giản hoặc results theo camera, log lỗi và chờ vòng sau. Default report interval=1 giây, HTTP timeout=2 giây trong core/config.py/.env.example; giữ bảo vệ quyền cục bộ và cơ chế heartbeat.

Contract và tài liệu AI/walkthrough/deployment được ghi rõ tình trạng: sender mới v4 nhưng bộ nhận logic_service vẫn v3. Payload mới bị bộ nhận cluster hiện tại trả 422; tích hợp phần nhận cần làm ở đợt riêng theo yêu cầu. Không tuyên bố thay đổi đã chạy xuyên suốt hay đã tương thích với master v3. Quy tắc nhận/POS v4 trong contract chỉ là yêu cầu tương lai, chưa triển khai.

Kiểm chứng cuối phạm vi tập trung vào tạo payload, detector và vòng HTTP gửi bằng transport giả, không gọi RTSP/GPU/robot thật. Không giữ lại test/tools/artifacts. Các kiểm tra thử với adapter/POS mới trước lúc thu hẹp phạm vi không được coi là bằng chứng của bản hiện hành vì adapter và thay đổi POS đã hoàn nguyên.

12. Rút gọn metadata /ai-data — chỉ phía AI

Theo yêu cầu mới, bỏ config_version, schema_version, frame_observed_at, inferred_at và point_ids khỏi request. _cluster chỉ còn worker_id và cameras gồm camera_id/assignment_epoch. Schema AI cấm trường thừa; build_payload chỉ chọn đúng các trường được giữ lại. Kiểm tra key số, label hang/trong, camera/điểm không trùng và không gửi 10001546 vẫn giữ.

Chỉ sửa ai_service/schemas/detection.py và services/{cluster_capture,cluster_detector,cluster_runtime}.py cùng tài liệu. Capture/detector bỏ config_version/inferred_at khỏi dữ liệu ảnh trung gian; captured_at chỉ là thời gian cục bộ để chọn frame mới, bỏ frame cũ và theo dõi ack, không gửi qua HTTP. Report không còn đọc timestamp từ response; lấy mốc của chính batch gửi để không đánh dấu nhầm kết quả mới xuất hiện trong lúc chờ mạng. Hỗ trợ success đơn giản hoặc results camera/epoch/status; từ chối ack không thuộc batch.

Không sửa file code nào trong logic_service ở đợt rút gọn này; giữ nguyên bộ nhận v3, POS và robot. Format mới chưa tương thích bộ nhận hiện tại (422). Bộ nhận tương lai phải tra điểm → camera từ catalog và kiểm tra owner/epoch/lease, không suy ra nguồn theo group. Bỏ timestamp khỏi wire nghĩa master không biết tuổi ảnh và không phân biệt được snapshot cũ gửi lại với quan sát mới bằng payload; không bổ sung xử lý để thay đổi đánh đổi này.

Đổi cấu hình camera phải cấp epoch mới thay cho config_version. Master hiện chỉ nạp lại qua restart và đã đổi khoảng epoch bằng boot generation; không đổi cơ chế đó. Contract/README/walkthrough được cập nhật theo payload rút gọn, giữ rõ phạm vi chỉ phía gửi.

13. Kiểm tra lại chết/khôi phục AI sau rút gọn payload

Không sửa code ứng dụng. Chạy kiểm tra trực tiếp bằng Python, không tạo lại thư mục test/tools/artifacts. Dùng master runtime/repository và FastAPI routes thật qua HTTPX ASGI transport; dùng các vòng _control_loop, _report_loop, _watchdog_loop và reconcile của AI hiện tại. Process/capture/detect giả, đồng hồ ảo; máy chết được mô phỏng bằng ngừng mọi vòng AI-01, khôi phục bằng đối tượng AI mới và register lại. Không chạy kill process OS, RTSP, GPU hoặc robot thật.

Giữ timing mẫu: heartbeat 3 giây, lease 15 giây, recovery delay 10 giây, tick 1 giây, rebalance batch 10. AI report payload rút gọn thật trong lúc heartbeat/điều phối vẫn chạy. Catalog 300 camera tổng hợp; catalog 74 camera lấy từ cameras.example.json nhưng không mở URL camera.

| Số camera | Bốn AI ổn định | AI-01 mất liên lạc | AI-01 trở lại | Chia lại sau chết, giây mô phỏng | Cân lại sau trở lại, giây mô phỏng |
|---|---|---|---|---|---|
| 300 | 75/75/75/75 | 100/100/100 | 75/75/75/75 | 15 | 33 |
| 74 | 19/19/18/18 | 25/25/24 | 19/19/18/18 | 15 | 27 |

Phần điều phối PASS: 79 tick của kịch bản 300 và 73 tick của kịch bản 74 không có capture giả chạy trùng cùng camera; mọi row đúng bốn key; không cấp epoch mới trước lease cũ; heartbeat claim epoch cũ không kéo dài quyền mới. API register 200 tổng cộng 5 lần mỗi kịch bản (bốn lần đầu, một lần AI-01 trở lại). Heartbeat 200 lần lượt 102 và 94.

Luồng dữ liệu chưa tương thích như đã ghi: /ai-data trả 422 lần lượt 196 và 172 request; POS được cập nhật 0 lần. Nguyên nhân là sender đã rút gọn nhưng bộ nhận master vẫn schema v3, không phải lỗi chia camera. Không sửa phần nhận/POS/robot vì ngoài phạm vi người dùng đã chốt. Phải tích hợp bộ nhận riêng mới kiểm thử được dữ liệu detect chạy xuyên suốt.

Các số giây là thời gian đồng hồ mô phỏng, không phải số đo hiệu năng mạng/RTSP/model thật và không xác nhận SLA phục hồi ngoài hiện trường.

14. Tách điều phối sang camera_cluster — 11/11/2026

Phạm vi đã chốt: ai_service chạy trên các máy AI; camera_cluster chạy trên master, chỉ quản lý/chia camera; logic_service nhận ai_data, xử lý nghiệp vụ và gửi robot theo code có sẵn. Hai service trên master là hai process độc lập. Hướng dẫn hiện hành tại [camera_cluster/README.md](../camera_cluster/README.md); mục 11–13 ở trên là lịch sử trước lần tách này, không còn mô tả giao thức dữ liệu hiện tại.

Các file có sẵn trong logic_service được sửa ở đợt này:

| File | Trước | Sau và lý do |
|---|---|---|
| main.py | Khởi tạo cả POS/robot và runtime chia camera; có router /cluster và health điều phối | Gỡ import/router/start/stop/health điều phối. Giữ startup POS, cấu hình robot, các router nghiệp vụ và shutdown nghiệp vụ |
| api/receive_data.py | /ai-data chọn nhánh ingest v3 khi bật cluster, hoặc update_state khi tắt | Gỡ nhánh ingest/auth/schema của controller; truyền map điểm trực tiếp vào update_state() có sẵn và giữ response success. Các endpoint callback/task/robot khác không đổi |
| core/config.py | Có các tham số catalog/boot/token/lease và cờ bật controller | Chuyển cấu hình điều phối sang service mới; giữ cấu hình app/nghiệp vụ. Thuộc tính tương thích cluster_enabled luôn false để các nhánh nghiệp vụ có sẵn chạy đường nhận điểm gốc, kể cả khi .env cũ còn CLUSTER_ENABLED=true |
| .env.example | Gộp cấu hình controller và nghiệp vụ | Chỉ giữ cấu hình logic, port mẫu 8001; token/catalog/lease nằm ở camera_cluster/.env.example |
| README.md | Mô tả điều phối cùng nghiệp vụ | Mô tả vai trò nhận điểm, format cũ và liên kết tới controller độc lập |

Các file điều phối được di chuyển ra khỏi logic_service:

| Đường dẫn cũ trong logic_service | Đường dẫn mới trong camera_cluster | Điều chỉnh |
|---|---|---|
| api/cluster.py | api/cluster.py | Giữ register/heartbeat/state và xác thực worker |
| core/camera_catalog.py | core/camera_catalog.py | Giữ kiểm tra catalog; đường dẫn tương đối tự tính từ root service mới |
| core/local_master_session.py | core/local_master_session.py | Giữ khóa OS và generation; không reset boot state khi chuyển bản vận hành |
| repositories/cluster_repository.py | repositories/cluster_repository.py | Giữ RAM/bốn trường quyền/history giới hạn |
| schemas/cluster.py | schemas/cluster.py | Giữ schema register/heartbeat/assignment |
| services/cluster_runtime.py | services/cluster_runtime.py | Giữ scheduler/lease/epoch/readiness; bỏ đối tượng POS, invalidate POS, ingest detect và counters detect. Không có xử lý ai_data trong service mới |
| config/cameras.example.json | config/cameras.example.json | Giữ nguyên nội dung catalog mẫu 74 camera/206 ROI |

Bỏ logic_service/schemas/detection.py vì schema v3 chỉ phục vụ ingest cũ và không còn được import. Không tạo schema detection hoặc /ai-data trong camera_cluster. Service mới có main.py, core/config.py, .env.example và requirements.txt riêng, mặc định port 8002; tài liệu kiến trúc/từng hàm đặt trong folder camera_cluster.

Không sửa nội dung POS_manager.py, Task_manager.py, Robot_manager.py, SSE_manager.py, observation_guard.py hoặc các file logic/*.py trong đợt này. Đã đối chiếu source với HEAD để xác nhận. Giữ helper nghiệp vụ có sẵn, không chuyển chúng sang controller. Cờ CLUSTER_ROBOT_ENABLED cũ thuộc nhánh cluster đã gỡ; không còn là công tắc chặn lệnh robot trong đường nhận điểm gốc. Quyết định/cấu hình vận hành robot tiếp tục thuộc logic_service hiện có.

Phía AI: thay một MASTER_URL bằng CLUSTER_URL (register/heartbeat) và AI_DATA_URL (POST dữ liệu trực tiếp tới logic). MASTER_URL còn là alias dự phòng nếu chưa đặt CLUSTER_URL. HTTP client dữ liệu riêng; lỗi 409 của bộ nhận dữ liệu không reset đăng ký worker. build_logic_payload() xuất đúng map ID số → label/group_id; bỏ _cluster trước gửi. Quyền camera vẫn được kiểm tra ở capture/detector/report/watchdog. Timestamp captured_at chỉ ở RAM AI; giữ ack theo batch để không đánh dấu nhầm quan sát mới sinh trong lúc chờ HTTP. Không gửi các trường config_version/schema_version/frame_observed_at/inferred_at/point_ids đã bỏ.

Ranh giới đã chốt: camera_cluster không nhận/chuyển detect, logic_service không tra owner/epoch/lease cho request dữ liệu. Việc ngừng nguồn cũ dựa trên lease/epoch và kiểm tra cục bộ AI; không bổ sung bảo đảm thứ tự request hoặc chống lệnh robot trùng. Lỗi 422 vì envelope không khớp ở mục 11–13 đã được giải quyết bằng map điểm tới đường nhận gốc; không sửa thuật toán POS hoặc payload robot để giải quyết.

Kiểm chứng sau khi tách (Python chạy trực tiếp, không giữ lại test/tools/artifacts):

- Controller thật, HTTP ASGI và vòng control/watchdog/reconcile thật của AI, process/capture giả và đồng hồ ảo: 300 camera chia 75/75/75/75 → chết AI-01 → 100/100/100 → trở lại → 75/75/75/75; 74 camera chia 19/19/18/18 → 25/25/24 → 19/19/18/18. Lần lượt 15 giây mô phỏng để chia sau chết, 33/27 giây để cân sau phục hồi. Không có capture giả trùng camera, không cấp epoch trước lease cũ, claim epoch cũ không gia hạn lượt mới; mọi row đúng bốn trường.
- Settings/lifespan/start_runtime thật, catalog/boot tạm và background tick: register/heartbeat/health/state thành công, token sai 401; /ai-data và /task-status trên camera_cluster trả 404; restart tăng generation và đặt khoảng chờ lease mới.
- logic_service app thật qua ASGI, mock duy nhất update_state() để không kích hoạt robot: map điểm trả 200/success và được truyền nguyên vẹn tới hàm có sẵn; /cluster/register trả 404, /health trả 200. Đây là kiểm tra biên API, không phải kiểm thử robot thực.
- Vòng report/start/stop thật của AI với multiprocessing giả và HTTP MockTransport: gửi đúng URL logic/đúng map điểm, không có các trường đã bỏ; không gửi lại cùng mẫu sau ack; quan sát mới trong lúc chờ HTTP vẫn được gửi vòng sau; consumer 409 không mất đăng ký; hết quyền không gửi; đóng cả hai HTTP client. AI_DATA_URL rỗng chỉ tắt gửi dữ liệu, không tắt client điều phối. Alias MASTER_URL và thứ tự ưu tiên CLUSTER_URL được kiểm tra.
- Kiểm tra cuối: AST 41 file Python hợp lệ; chín file nghiệp vụ/helper giữ nguyên source so với HEAD; sáu file di chuyển ngoài runtime giữ nguyên nội dung; catalog đúng 74 camera/206 ROI; 13 tài liệu Markdown có link nội bộ/code fence hợp lệ; git diff --check đạt. Không giữ script hoặc thư mục kiểm thử.

Chưa chạy GPU, RTSP, robot hoặc năm máy thật; chưa làm HA. Khi chuyển máy vận hành, bảo toàn catalog thật và file generation cũ, dừng controller cũ và không chạy song song hai controller. Workspace hiện không có .env/catalog/runtime vận hành để tự chuyển; chỉ catalog mẫu được di chuyển. Không tải/cài dependency hoặc khởi động service vận hành trong đợt này.
