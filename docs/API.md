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

## Tải lịch sử huấn luyện trong WebUI

Trang Attempt tải thông tin lần chạy, snapshot, Workers và page tối đa 200 step
mới nhất để hiển thị trước. Các page step cũ được tải tuần tự ở nền; event chẩn
đoán và epoch.metrics.finalized được đọc riêng theo cursor/filter, không phải
đợi hết step history mới có metrics. Reconnect chỉ đọc thêm tới vùng step đã biết.

Các GET trùng path/query/options/headers đang pending được chia sẻ. Mỗi nơi gọi
có signal hủy riêng; chỉ hủy request nền khi không còn nơi nào chờ. POST và các
mutation không được gộp. Cache history tối đa 24 entries, TTL 60 giây; baseline
chỉ cache khi tất cả request thành công và terminal Attempt có snapshot fresh
cùng state. Active/stale/error baseline không được dùng lại như dữ liệu fresh.

Đổi Attempt hoặc rời trang hủy lượt tải cũ; response cũ không thay dữ liệu mới.
Page lỗi giữ row đã tải và cursor để Retry, không làm mất lịch sử đang xem.
Khi thêm step cũ, chart giữ step người dùng đang chọn; nếu đang theo newest thì
tiếp tục theo newest. Metrics không bị sampling hay lấy trung bình để giảm request.

## Điều hướng và dữ liệu WebUI

/jobs quản lý cấu hình Job; READY là cấu hình đã chốt, không phải một lượt đang
huấn luyện. Trang Job hiển thị riêng lần chạy hiện tại/gần nhất, execution mode,
trạng thái và lỗi của Attempt; tải thêm lịch sử theo cursor của đúng Job.
/runs là danh sách lượt huấn luyện, có lọc và tải thêm theo cursor; chọn lượt chạy
mở metrics của attempt_id tương ứng. /live phục vụ Attempt hiện tại và hiển thị
cluster idle khi không có lượt active. Các URL /training và /training/runs được
chuyển tới /jobs và /runs để giữ đường dẫn điều hướng cũ.

Metadata dòng history đi theo Job.dataset_build_id -> DatasetBuild.dataset_id
-> Dataset.dataset_id. Thiếu metadata thì hiển thị không khả dụng, không lấy
Dataset đầu tiên thay thế. Số thứ tự lượt chạy chỉ suy từ attempt_count khi
latest_attempt khớp prefix history đã tải; thiếu/inconsistent metadata không đoán.
Bộ đếm và bộ lọc trên /runs ghi rõ phạm vi các lượt đã tải. Tải page lỗi vẫn giữ
các row hiện có và cho thử lại; thời gian thiếu/sai không hiển thị NaN hoặc giả
báo một lượt terminal còn đang chạy.

Checkpoint list bổ sung epoch nullable từ recovery_cursor_jsonb hiện có, nhận cả
object và JSON string, giữ đúng epoch 0 và không suy giá trị khi metadata thiếu.
Các trang Dataset/Build, charts, topology và drawer dùng chung format thời gian,
nhãn trạng thái và thành phần hiển thị; không thay training lifecycle hoặc API
điều khiển. WebUI tiếp tục chỉ gọi Management Backend.

## Checkpoint/model artifacts — quyết định người dùng 2026-11-02

Cadence đang dùng là periodic mỗi N epoch, cùng manual/final checkpoint hiện có.
Retention giữ 3 bản COMPLETE mới nhất mỗi Job, cộng bản còn được tham chiếu để resume.
Cleanup chạy ngoài training loop và dùng checkpoints/events hiện có; không cần migration.
File canonical nằm trên máy Runtime tại checkpoint root đã cấu hình:
`<root>/<attempt_id>/<sha256(checkpoint_id)>/model.bin` và `checkpoint.json`.
Launcher hiện có dùng `<PBL4_STATE_DIR>/checkpoints`, mặc định `var/checkpoints`
dưới repo; chạy Runtime trực tiếp dùng `--checkpoint-dir` hiện có.
Event quản trị checkpoint.artifact.retired ngăn resume/download mới và chống replay tạo lại
checkpoint đã hết hạn. Khi file purge thành công, bản ghi checkpoint cũ bị xóa.
List chỉ trả checkpoint chưa hết hạn; detail trả 404 ngay khi checkpoint đã được
đánh dấu dọn, kể cả khi purge đang chờ. Không đưa trạng thái cleanup ra DTO/WebUI.

GET /api/v1/checkpoints/{checkpoint_id}/model trả ZIP hoàn chỉnh qua Backend,
theo ngoại lệ model export đã được người dùng duyệt. ZIP gồm model.bin,
checkpoint.json, parameter-manifest.json, resolved-contract.json và README.
Runtime/Backend không import torch; helper pbl4.adapter.model_export dùng model factory
và adapter hiện có để nạp ZIP trên máy người dùng có worker dependencies.

Response thành công: application/zip, Content-Length, Content-Disposition attachment,
Cache-Control: no-store, Accept-Ranges: none. V1 không hỗ trợ tải tiếp bằng Range.
404 khi không có checkpoint; 409 khi WRITING/FAILED/đang hết hạn hoặc artifact không
thể xác minh/export; 503 khi chưa cấu hình hoặc Runtime artifact HTTP không sẵn sàng.
Không trả đường dẫn filesystem hay token ra client.

Inventory xác minh payload trước khi tính vào ba recovery point cần giữ. Retirement
kiểm tra lại cùng inventory dưới khóa theo Job; resume khóa cùng row checkpoint và
đọc lại retirement bằng statement mới sau khi chờ khóa. Purge thất bại được thử lại,
không làm mất durable resume reference.

HTTP nội bộ Runtime hỗ trợ GET /inventory?after=...&limit=..., POST /export và POST /purge.
Các POST dùng descriptor checkpoint/attempt/hash; export kèm frozen contract đã pin.
Endpoint dùng cổng nội bộ 9002 và Bearer credential dẫn xuất HMAC theo purpose riêng
từ PBL4_WORKER_ADMISSION_SECRET đã có. Backend dùng RUNTIME_HOST hiện có; không thêm
environment field hay CLI flag. Root secret không gửi qua HTTP. Browser chỉ gọi
Backend; credential không đưa vào WebUI, MCP, Redis hoặc WebSocket.

HTTP/1.1 tái sử dụng kết nối trong một lượt maintenance/download. Export hash và copy
model vào ZIP bằng buffer cố định; Backend stream từng chunk. Inventory có cache xác
minh tối đa 256 payload trong 5 phút, gắn với digest và file stat; file đổi phải xác
minh lại, export/purge luôn kiểm tra bytes thực tế. Thư mục ZIP tạm được dọn sau tải
hoặc lỗi/ngắt kết nối; HTTP chỉ cho tối đa bốn thao tác artifact đồng thời.

Sau khi duyệt code, khởi động lại Runtime rồi Backend bằng cấu hình shared secret
hiện có để bật HTTP và maintenance. Backend phải truy cập được Runtime ở cổng 9002.
Maintenance chạy mỗi 30 giây. Muốn xem candidate trước khi Backend tự dọn, chạy
trên máy Backend trước khi khởi động Backend bằng code mới:

```powershell
.venv/Scripts/python.exe -c "from pbl4.management_backend.config import get_settings; from pbl4.management_backend.services.checkpoint_artifacts import maintain_checkpoints; maintain_checkpoints(get_settings(), dry_run=True)"
```

Nếu shared secret để trống thì artifact HTTP/download/retention không bật.
Save checkpoint vẫn giữ cadence hiện có. Máy nạp model cần worker dependencies
của PBL4 tương ứng:

```python
from pbl4.adapter.model_export import load_exported_model
model = load_exported_model('model.zip')
```
