# Kế hoạch Sync + Async + Rejoin

Ngày: 04/11/2026 · Baseline: `b8964e9` · Đã triển khai P0–P6.
Kết quả và giới hạn kiểm chứng: [verification](ASYNC_REJOIN_VERIFICATION.md).

## 1. Mục tiêu đã chốt

- Giữ **Sync (StrictBSP)** và thêm **Async-SGD**, chọn khi tạo Job.
- **Sync:** mất Worker thì fail Attempt; phục hồi bằng checkpoint như hiện tại.
- **Async:** Worker mất mạng có thể kết nối lại trong cùng Attempt; Worker khác tiếp tục chạy.
- Gradient quá cũ bị bỏ vẫn tính công việc đã xử lý; ghi riêng **applied / dropped**.
- Giữ **no-barrier:** có thể cấp việc epoch sau khi epoch trước chưa xong. Checkpoint async phải lưu đủ tiến độ để phục hồi đúng.

## 2. Cách chia code

```text
Runtime/Worker
  training_flows/sync.py       → điều phối sync
  training_flows/async_sgd.py  → điều phối async

Dùng chung: TCP, tensor transfer, dataset cache, compute,
canonical model, UpdateEngine, checkpoint và event pipeline.
```

Giữ `synchronization/strict_bsp.py`; thêm async policy riêng. Coordinator vẫn quản lý vòng đời Attempt; UpdateEngine vẫn là nơi cập nhật model. Các đường dẫn mới là cấu trúc dự kiến trong từng package Runtime/Worker.

## 3. Checklist triển khai

Mỗi bước chỉ đánh dấu xong khi cả công việc và kiểm tra đều đạt.

### P0 — Chốt contract và giao thức

- [x] Chốt cấu hình, identity, applied/drop, checkpoint; quyền rejoin khi token hết hạn hoặc mất HELLO_ACK; giới hạn retry và thời gian một lượt việc.
- [x] Giữ nghĩa `PARAMETER_APPLIED` là Worker xác nhận đã nạp trọng số.
- [x] Giữ `work_units_per_step` của sync; cấu hình số unit mỗi contribution async riêng.
- **Phạm vi:** Backend contract, DTP messages/session, admission, checkpoint schema.
- **Đã chốt:** R=6, grace=60s; cấu hình và wire fields tại [execution contract](ASYNC_EXECUTION_CONTRACT.md).

### P1 — Tách luồng sync

- [x] Tách flow sync; tách membership đang hoạt động khỏi contract bất biến, phiên bản tính gradient khỏi phiên bản model lúc update.
- [x] Tái sử dụng cache, compute đa unit và tensor transfer hiện có.
- **Phạm vi:** Runtime `process.py`, `coordinator.py`; Worker `process.py`, `training_loop.py`; flow mới.
- **Đạt khi:** kiểm thử sync/DBS, mất Worker, checkpoint/resume và TCP vẫn đạt.

### P2 — Xây luồng async

- [x] Mỗi Worker tối đa một lượt việc; gắn Attempt/session/operation, epoch, units và phiên bản trọng số đã giao. Mỗi lượt thuộc một epoch; phần đuôi có thể ít unit hơn cấu hình.
- [x] Kiểm tra base_version khớp việc đã giao; tính τ = current − base lúc quyết định. Future bị từ chối; τ > R thì drop; còn lại LR = η/max(1,τ). Apply/drop và ghi tiến độ nguyên tử.
- [x] Không cấp trùng; đánh thức Worker chờ khi reclaim. Chỉ kết thúc khi processed = E×M và không còn việc chờ/đang xử lý; đóng admission trước chốt snapshot cuối.
- **Phạm vi:** pool, async flow/policy, Contribution/UpdatePlan/context và UpdateEngine.
- **Đạt khi:** đúng công thức update; duplicate không update hai lần; drop không tăng model version; applied + dropped khớp số việc processed.

### P3 — Nối Worker với async

- [x] Worker nhận việc, tính gradient, gửi và nạp snapshot mới rồi tiếp tục.
- [x] Cho phép version nhảy nhiều bước hoặc giữ nguyên sau drop.
- [x] Reader/heartbeat không chờ compute lock; chỉ một tác vụ sở hữu model. Gửi socket/ghi đĩa ngoài state lock; giới hạn buffer, hàng đợi và timeout truyền.
- **Phạm vi:** DTP schema/validator, `parameter_server.py`, `worker_client.py`, Worker async flow.
- **Đạt khi:** chạy async qua TCP thật; truyền tensor dở, message sai và STOP được xử lý đúng; sync vẫn đạt.

### P4 — Thêm rejoin

- [x] Mất mạng: vô hiệu hóa session và kết quả compute cũ, thu hồi việc chưa xử lý.
- [x] Reconnect có backoff: xác thực tại Runtime, session mới, dùng cache hợp lệ, kéo trọng số/việc mới; hỗ trợ cả trước RUNNING, không bỏ qua handshake cần thiết.
- [x] Chặn hai session hoạt động cho cùng Worker; cleanup cũ không được xóa session mới.
- [x] Grace dùng đồng hồ monotonic; chỉ Worker sẵn sàng mới hủy grace. Heartbeat còn nhưng việc treo phải có timeout riêng; terminal/abort chặn late update và dừng reconnect.
- **Phạm vi:** registry/admission, Runtime disconnect/timeout, Worker connection supervisor.
- **Đạt khi:** ngắt trước/sau update không mất hoặc xử lý trùng việc; Worker khác vẫn chạy; Backend mất kết nối không chặn rejoin.

### P5 — Checkpoint/resume async

- [x] Snapshot model + tiến độ cùng thời điểm; nhận diện revision tiến độ riêng vì drop không tăng model_version. Chặn checkpoint cũ ghi đè mốc mới.
- [x] Resume bằng Attempt mới: khôi phục model/tiến độ; giao lại việc chưa xử lý; không khôi phục session cũ.
- [x] Periodic theo các epoch đã xử lý hết liên tục; phát hiện vượt mốc dù tiến độ nhảy nhiều epoch. Giữ manual/final và đọc sync V1; giới hạn ledger/snapshot, ghi rõ lỗi final save.
- **Phạm vi:** snapshot, serializer/restore, async progress, checkpoint projections.
- **Đạt khi:** epoch chồng nhau và lượt chỉ drop vẫn resume đúng; reject checkpoint hỏng/sai contract/dataset/model/strategy. Cho phép chạy lại phần sau checkpoint khi Runtime crash.

### P6 — API, UI và nghiệm thu

- [x] Thêm lựa chọn strategy và cấu hình theo mode; giữ default sync cho Job cũ.
- [x] Hiển thị processed/applied/dropped, độ trễ, Worker đang hoạt động và lịch sử session đúng; không tạo Step giả cho async.
- [x] Công bố capability async sau kiểm thử luồng Runtime/Worker thật, contract, session repository và UI.
- **Phạm vi:** Backend resolver/schemas/gateway, Web form/types/training views.
- **Đạt khi:** chạy trọn Job/train/rejoin/checkpoint/resume; mất Backend/DB/Dataset Manager sau cache-ready vẫn train/rejoin; sync và architecture đạt.

## 4. Thứ tự và theo dõi

`P0 → P1 → P2 → P3 → P4 → P5 → P6`

| Tiến độ | Trạng thái |
| --- | --- |
| Review code và chốt yêu cầu | Đã xong |
| P0–P6 | Đã triển khai; kiểm chứng và lỗi baseline ở verification |
| Bootstrap đổi initializer; tự thay process bị crash | Đề xuất giai đoạn sau |

Không mở rộng sang sync hot-rejoin, async DBS hoặc đổi strategy giữa Attempt trong đợt này. Tensor vẫn chỉ đi DTP/1; Backend/DB/Agent không tham gia đường cập nhật model.

Test bắt buộc: duplicate + mất ACK; update/reclaim đồng thời; idle nhận việc thu hồi; heartbeat còn nhưng compute treo; drop-only checkpoint; tiến độ vượt nhiều mốc; abort/STOP khi đang truyền tensor.

Baseline đã kiểm tra ở lượt review: 183 test + 105 subtest đạt; architecture đạt. Đây là kết quả của code hiện tại, chưa phải kiểm chứng async.

Tra cứu nguồn chuẩn, file/symbol cụ thể, rủi ro và test cases tại [bản review chi tiết](ASYNC_SYNC_REJOIN_REVIEW_PLAN_VI.md).
