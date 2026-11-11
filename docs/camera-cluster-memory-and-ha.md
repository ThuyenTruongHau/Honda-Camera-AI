Ước tính RAM master và các điều kiện để phát triển HA

> Cập nhật 11/11/2026: bộ điều phối hiện chỉ lưu bốn trường quyền/camera; không giữ session/revision/sequence/latest_sample trong repository. Nhãn và timestamp phục vụ POS vẫn nằm trong RAM. Số liệu dưới đây là dự trù/đo ở bản trước, chưa đo lại sau đơn giản hóa; phần HA vẫn chỉ là định hướng, chưa triển khai. Xem [code hiện hành](camera-cluster-code-walkthrough.md).

Ngày đánh giá: 10/11/2026. Đây là phép đo dữ liệu tổng hợp trước đợt chuyển backend. Cập nhật triển khai: master hiện đọc JSON và dùng RamClusterRepository, history đã giới hạn; SSE có queue/client limit, logger đã xoay theo kích thước. Chưa triển khai HA master. Các phân tích HA bên dưới là hướng tương lai, được người dùng yêu cầu hoãn.

1. Phạm vi và cách đo

Chạy ba process Python 3.10 riêng trên Windows, import ứng dụng logic_service và nạp config map/robot/zone từ source. Dùng ClusterRuntime, Position_Manager, DetectionBatch và MemoryClusterRepository hiện có để tạo 300 camera, bốn worker, phân công và cập nhật snapshot đầy đủ. Snapshot mới ghi đè snapshot cũ; diagnostic events được giới hạn bằng deque(maxlen=1000), giữ 900 event trong mỗi phép đo. Không bật robot, không kết nối camera hoặc MongoDB.

Mỗi lần nhận tối đa 32 snapshot trong một batch. Hai kịch bản 10/30 ROI chạy 20 vòng cập nhật toàn bộ 300 camera; 100 ROI chạy 10 vòng. Nới lease/freshness chỉ trong script đo để thời gian tracing không làm mẫu giả bị loại. Phép đo RSS/working set dùng Windows GetProcessMemoryInfo; tracemalloc đo allocation Python sau khi import/nạp cấu hình. Tracemalloc cũng gây thêm overhead cho RSS.

Script local: artifacts/measure_master_memory.py. Raw report: artifacts/master-memory-10.json, master-memory-30.json và master-memory-100.json. Artifacts không commit. Không sửa file ứng dụng logic_service cho phép đo này.

2. Kết quả

Đơn vị MiB = 1024 × 1024 byte. Hai cột bên phải khác phạm vi, không cộng lại với nhau.

| Kịch bản | Tổng vị trí/ROI | Allocation trạng thái sau cập nhật | RSS cả tiến trình thử nghiệm |
|---|---:|---:|---:|
| Chỉ import ứng dụng/nạp config | — | Chưa tạo dữ liệu giả | 44–45 MiB |
| 300 camera × 10 ROI | 3.000 | 5,81 MiB | 55,86 MiB |
| 300 camera × 30 ROI | 9.000 | 14,70 MiB | 71,28 MiB |
| 300 camera × 100 ROI | 30.000 | 47,16 MiB | 132,11 MiB |

Allocation bao gồm catalog, worker/session/lease, camera rows, snapshot, trạng thái/pending của POS, locks và lịch sử diagnostic có giới hạn. Adapter RAM dùng deepcopy nên không coi đây là dung lượng tối thiểu hoặc dự báo chính xác cho backend sản xuất sau này. RSS gần ổn định ở các vòng cuối trong thử nghiệm ngắn; chưa chứng minh không rò rỉ sau nhiều ngày.

Chưa chạy HTTP server/tải HTTP thực, SSE client chậm, nhiều task robot đồng thời, đồng bộ standby hay thử lỗi kéo dài. Không tính MongoDB process, hệ điều hành, các phần mềm khác hoặc ai_service/model trên bốn máy AI. Không suy ra khả năng xử lý 1.500 snapshot/giây từ phép đo này.

3. Ngân sách đề xuất

Tạm dành 512 MiB cho một process logic_service trên mỗi master khi lập ngân sách máy. Đây là mức dự trù có khoảng trống so với phép đo, chưa phải mức trần đã kiểm chứng hay bảo đảm RSS tối đa. Hai master active/standby cần mỗi máy đủ khả năng chạy đầy tải; dự trù 512 MiB mỗi máy, tổng cộng 1 GiB cho hai process, cộng riêng dịch vụ HA/đồng bộ và các phần mềm khác.

Trước khi xác nhận hạn mức cần chạy tải theo số ROI thực, tốc độ gửi thực, số client SSE và lượng task robot thực. Hiện có các nguồn tăng RAM cần giới hạn khi phát triển backend RAM:

- SSE đã giới hạn queue/client và ngắt client chậm trong đợt JSON/RAM; cần nghiệm thu reconnect và tải lại trạng thái trên client thực.
- Task đang chờ callback/timeout và manual coroutine cần giới hạn số lượng, theo dõi tuổi và đối soát. Không tự xóa reservation của lệnh robot chưa rõ kết quả để tiết kiệm RAM.
- Ingress cần giới hạn kích thước request, số ROI thực, số request đồng thời và lượng tác vụ nền; backpressure khi quá tải.
- Lịch sử/chẩn đoán phải có retention hoặc ring buffer. RamClusterRepository hiện dùng deque(maxlen=CLUSTER_HISTORY_LIMIT), không còn events list tăng vô hạn.
- Thiết lập cảnh báo RAM và dừng nhận thêm công việc khi hết ngân sách; không loại bỏ âm thầm quyền camera/task robot.

4. Điều chỉnh thiết kế khi tính đến HA master

RAM phù hợp cho trạng thái nhanh. File epoch chỉ nằm trên ổ cục bộ một máy chưa đủ để master khác tiếp quản an toàn. Cần tách ba trách nhiệm:

| Trạng thái | Hướng phục hồi/đồng bộ |
|---|---|
| Cấu hình camera và map | Cùng config_version/checksum trên active và standby |
| Latest detection và debounce | Có thể nhận lại frame mới; đặt UNKNOWN và xác nhận lại khi tiếp quản, không coi dữ liệu cũ là mới |
| Owner/session/lease camera | Đồng bộ hoặc tái lập dưới quyền master generation mới, chờ hết quyền cũ và loại mọi kết quả thuộc quyền cũ |
| Ai là master active, master generation | Cơ chế phân xử và fencing đáng tin cậy, không chỉ ping hai máy |
| OrderId, lệnh đang gửi/chưa rõ kết quả, reservation và task robot | Lưu bền/đồng bộ theo giao thức trước tác động ngoài; tiếp quản phải đối soát với RCS, có dedup/idempotency nếu RCS hỗ trợ |

Ví dụ mô hình dự kiến: active và standby có cache RAM riêng; dùng cơ chế quorum/witness để chọn bên được hoạt động; đường gửi lệnh robot phải chặn bên đã mất quyền. VIP chỉ chuyển địa chỉ truy cập, không thay thế phân xử/fencing và không tự đồng bộ task robot.

Với Windows Failover Clustering hai node, Microsoft yêu cầu witness và giải thích quorum ngăn split-brain khi mất kết nối. Witness hỗ trợ phân xử, không tự lưu thay trạng thái nghiệp vụ của ứng dụng. Xem [quorum](https://learn.microsoft.com/en-us/windows-server/storage/storage-spaces/quorum) và [quorum witness](https://learn.microsoft.com/en-us/windows-server/failover-clustering/what-is-quorum-witness). Đây là nguyên tắc tham khảo khi chọn nền tảng HA, chưa phải xác nhận năm máy hiện có chạy Windows Server/Failover Clustering.

Không tự động gửi lại một lệnh chỉ vì master cũ chưa lưu ACK: robot có thể đã nhận lệnh trước khi master mất. Nếu chỉ đồng bộ RAM bất đồng bộ, vẫn có cửa sổ mất trạng thái khi active chết. Cần xác định RPO/RTO và khả năng truy vấn/dedup theo orderId của RCS trước khi chọn cơ chế lưu/đồng bộ. Việc này không bắt buộc SQLite nhưng bắt buộc có phương án cho trạng thái điều khiển quan trọng.

5. Quyết định còn cần dữ liệu thực

- Số ROI trung bình/tối đa mỗi camera, tốc độ snapshot và số task/client đồng thời.
- RAM tổng và RAM thực được phép dành cho logic_service trên mỗi master.
- Hệ điều hành và nền tảng HA sẵn có; có điểm phân xử độc lập hoặc shared storage HA hay chưa.
- Thời gian gián đoạn cho phép khi master chuyển quyền, mức mất trạng thái chấp nhận và API RCS đối soát orderId.

Mục tiêu phục hồi AI dưới 60 giây trước đây không tự áp dụng thành cam kết cho chuyển master. Code hiện tại là một master dùng JSON/RAM; mở rộng HA cần cập nhật kế hoạch và log mọi file logic_service có sẵn bị sửa theo yêu cầu của người dùng.
