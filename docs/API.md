# Tra cứu API đang triển khai

Tài liệu này chỉ dẫn đến implementation hiện tại, không thay thế đặc tả canonical
trong [source registry](../.agents/SOURCE_REGISTRY.md).

Khi Backend đang chạy, mở `/api/docs` để xem REST API và `/api/openapi.json`
để lấy OpenAPI trên chính Backend đó. Các đường dẫn này được cấu hình trong
[app.py](../src/pbl4/management_backend/app.py).

| Nội dung | Nơi đối chiếu |
|---|---|
| REST endpoints | [api/](../src/pbl4/management_backend/api/) |
| Request/response models | [schemas/](../src/pbl4/management_backend/schemas/) |
| HTTP envelopes, middleware, WebSocket routes | [app.py](../src/pbl4/management_backend/app.py) |
| WebUI API client | [web/src/api/](../web/src/api/) |
| WebUI types và stream consumer | [types/api.ts](../web/src/types/api.ts), [useAttemptStream.ts](../web/src/hooks/useAttemptStream.ts) |
| Backend contract tests | [management_backend/tests/](../src/pbl4/management_backend/tests/) |

OpenAPI mô tả REST; khi kiểm tra WebSocket cần đọc cả route và consumer.

Luồng training dùng `/ws/v1/attempts/{attempt_id}?after_seq=N`. Các event
`step.started`, `gradient.accepted`, `model.updated`, `parameter.applied` và
`step.committed` mang `details.strategy_state` tại thời điểm phát, để hiển thị
contribution/ACK và trạng thái StrictBSP mà không polling theo từng step.
`step.started.started_at`, `model.updated.update_completed_at` và các mốc thời
gian trong `step.committed` cho phép hiển thị duration/throughput từ số đo thật.
`model.updated.contributions` giữ loss, sample_count và compute_ms của từng Worker;
loss/accuracy theo epoch vẫn đến từ `epoch.metrics.finalized`.

Backend chỉ cập nhật snapshot quản trị và phát WebSocket sau khi transaction
projection commit, trên cả MCP và Redis Streams. Event lịch sử đến chậm vẫn được
phát lại nhưng không ghi đè snapshot Runtime mới hơn. Read snapshot có cursor
tương ứng với trạng thái đã áp dụng; snapshot không thay thế lịch sử metrics.

Khi thay đổi semantics API, đối chiếu canonical owner trước; không coi
implementation là nguồn phê duyệt semantics mới. API contract lịch sử có thể
tra cứu trong Git, không dùng làm contract hiện hành.

## Training preparation, launch và resume

Launch/Resume kiểm tra không có active Attempt toàn hệ thống trước khi gửi lệnh;
Backend vẫn quyết định admission cuối cùng. Khi request còn pending, UI giữ nhãn
nút, hiển thị spinner/aria-busy và dùng ref guard chống gửi trùng. Confirmation
chờ kết quả request thay vì đóng trước khi biết thành công hay lỗi.

Resume picker tải checkpoint theo job_id và state=COMPLETE, có phân trang/dedup;
gửi đúng checkpoint_id đã chọn tới POST /api/v1/jobs/{job_id}/resume. Khi thành
công, điều hướng bằng attempt_id mới Backend trả về. Checkpoint list trả job_id
được join từ Attempt tạo checkpoint. Empty/error/selection không hợp lệ không
được gửi resume hoặc tự thay bằng Start.

Live Training hiển thị preparation từ các state Runtime hiện có và membership
thực: kết nối DTP, dataset đã xác minh và Worker READY. Trạng thái stale chỉ là
lần quan sát cuối; không suy phần trăm tải/ETA hoặc giả báo đã RUNNING.

WebSocket EVENT dùng payload.details; SNAPSHOT dùng payload.snapshot_seq/state.
Snapshot preparation có thể đổi Worker ở cùng event cursor. Client xử lý message
và catch-up theo thứ tự; REST response chậm không ghi đè live snapshot mới hơn.
Ordinary REST refresh không tăng applied event cursor; live event memory giới
hạn 1024 entries, full history tiếp tục truy vấn qua Backend.

START_ATTEMPT chỉ thay runner cũ khi DTP resources đã cleanup xong. Runtime chờ
tối đa 5 giây ngoài state lock rồi kiểm tra lại; chưa xong trả ACTIVE_ATTEMPT_EXISTS.
Abort trong provisioning/initialization vẫn chạy cleanup, không coi một predicate
ready là hợp lệ sau abort. Terminal snapshot giữ tới lần khởi chạy tiếp theo.
