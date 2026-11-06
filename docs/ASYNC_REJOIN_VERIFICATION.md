# Nghiệm thu Sync + Async + Rejoin

## Chốt bản 1 — 06/11/2026

**Draft để review; chưa xác nhận sẵn sàng merge.** Các mục DONE bên dưới là
phạm vi triển khai và bằng chứng lịch sử ngày 04–05/11, không thay thế kết quả
rà soát cuối này. Baseline vẫn là `b8964e9`; bản 1 được gom thành một commit
trên `feat/async-rejoin-v1`, PR phụ thuộc nhánh `feat/events-ui-checkpoints` của #17.

### Phần bổ sung trong lượt kiểm tra cuối

- Async có Training Output theo epoch, tiến độ toàn bộ và biểu đồ từng lượt.
- Runtime dùng lại bộ tính sample-weighted loss/accuracy của sync, tích lũy theo
  epoch gốc của assignment; phát `epoch.metrics.finalized` khi epoch thật sự xong.
  Gradient stale-dropped vẫn thuộc dữ liệu processed. Epoch chạy xen kẽ và rejoin
  không làm đếm trùng; không thêm barrier hoặc thay lịch checkpoint.
- Snapshot/event có `epoch_progress` tùy chọn. Terminal và biểu đồ epoch dùng
  lịch sử PostgreSQL được phân trang riêng, không phụ thuộc cửa sổ 1.024 event gần nhất.
- Không đổi checkpoint shape để lưu measurement sums: epoch đã xử lý một phần
  trước checkpoint có loss/accuracy chưa biết trong Attempt resume. Các epoch được
  đo trọn trong Attempt mới có metrics bình thường; không dựng số liệu lịch sử giả.
- Đã kiểm tra browser thật trên Job đang chạy: biểu đồ từng lượt vẽ được, reload
  phục hồi dữ liệu; terminal xử lý được Runtime cũ thiếu epoch telemetry; màn hình
  hẹp không tràn ngang khi thu gọn sidebar và phần details dùng được bằng bàn phím.
  Runtime/Backend của Attempt đang chạy chưa được restart để nạp epoch telemetry mới.

### Kết quả mới trên đúng snapshot chuẩn bị commit

| Kiểm tra | Kết quả |
| --- | --- |
| Full Python: `tests` + `src/pbl4/management_backend/tests` | **894 passed, 150 subtests passed, 1 skipped, 5 failed** |
| Bốn ca fixture trên baseline `b8964e9` chưa sửa | **4 failed**, tái hiện đúng bốn lỗi baseline nêu dưới |
| Chạy riêng ca async resume vừa lỗi trong full suite | **1 passed**; lỗi phụ thuộc thời điểm chưa được giải quyết |
| Web `npm test` | **206 passed, 1 skipped**, không có lỗi |
| Web `npm run build` (gồm typecheck) | PASS; còn cảnh báo bundle > 500 kB |
| Architecture, scaffold/syntax, diff whitespace | PASS |
| Ruff check/format cho 16 file Python mới | PASS |
| Ruff toàn bộ `src scripts` | 68 diagnostics so với 69 ở baseline; không thêm diagnostic mới |
| Ruff format toàn bộ `src scripts` | Cùng 14 file tồn đọng cần format ở baseline; không format ngoài phạm vi |

Python dùng môi trường hiện có, `torch.set_num_threads(1)`, PostgreSQL **pbl4_test
trên localhost**, `DATABASE_URL`/`TEST_DATABASE_URL` cùng trỏ test DB và `REDIS_URL`
trống trong test process. Không chạy fixture ghi dữ liệu trên DB training đang hoạt động.

Bốn lỗi baseline: fixture resume thiếu `artifact_retired`; ba fixture
`test_event_ingest_*` trong `test_targeted_repairs.py` mock đường insert cũ.
Health smoke không lỗi khi Redis tắt trong test process. Full suite **không xanh**.

### Điểm chưa đạt của bản 1

1. **Rejoin 30 giây với Job ResNet-18/CIFAR-10 thật: FAIL.** Đã reset riêng TCP
   của một Worker trên loopback trong đúng 30 giây, giữ nguyên process. Sau khi
   trả mạng Worker qua bước cache/SHARD_READY nhưng thoát exit code 1 trước khi
   gửi contribution mới. Hai Worker còn lại tiếp tục, Attempt RUNNING, model
   v103 → v107. Can thiệp đã dừng; không đổi firewall, adapter hoặc routing.
   Ngân sách reconnect Worker mặc định 60 giây bao gồm readiness là nghi vấn có
   cơ sở; thiếu log exit reason nên chưa kết luận tuyệt đối, còn nhánh queue-full
   cũng dừng im lặng. Không coi `reconnect_grace_seconds=180` của Runtime là hạn
   reconnect của từng Worker. Không sửa bằng cách tăng timeout tùy ý.
2. **State projection Worker cũ còn READY** sau phép thử dù process đã thoát;
   `async.progress.active_workers=2` phản ánh hai Worker còn lại. Cần đối chiếu
   đường batch ingestion/session reconciliation khi xử lý tiếp.
3. **Async resume có lỗi phụ thuộc thời điểm.** Trong full suite, ca
   `test_production_async_train_rejoin_checkpoint_resume[normal]` không hoàn tất
   Attempt resume; log có DTP message bị từ chối ở phase INITIALIZING. Chạy riêng
   lại đạt. Chưa xác định frame/race cụ thể; không ghi là đã sửa hoặc PASS full suite.
4. Chưa benchmark hội tụ/throughput hoặc chạy ma trận nhiều máy/WAN. Không có
   auto replacement cho Worker process đã chết, sync hot-rejoin hay async DBS.

### Phân loại suite

- **Unit:** EXECUTED trong full Python và Web.
- **Integration:** EXECUTED, gồm PostgreSQL test DB, checkpoint/resume và schema.
- **Distributed:** EXECUTED qua TCP/HTTP loopback và phép thử trên cụm process thật;
  ma trận nhiều máy/WAN SKIPPED vì không có topology thử nghiệm tương ứng.
- **Failure:** EXECUTED admission/reclaim/session fencing/network cases; test 30 giây
  thực tế và ca resume phụ thuộc thời điểm chưa đạt như trên.
- **Architecture:** EXECUTED, PASS; không sửa governance, dependencies hoặc migrations.
- **Benchmark:** SKIPPED; lượt này chốt V1 và bằng chứng correctness, không đo hiệu năng/hội tụ.

## Tinh gọn sau review — 05/11/2026

- Pool sở hữu cấp operation cho cả assignment và lượt chờ; flow không sửa counter private.
- Helper FP32 chuyển sang `worker/tensor_bundle.py`, bỏ import ngược từ flow vào process.
- Bounds cấu hình tra theo tên field; kiểm tra min/max, bool/float và operation qua reclaim.
- Kiểm chứng lượt này: **158 test liên quan đạt**; Ruff check/format, architecture,
  scaffold và diff whitespace đạt. Không chạy lại toàn bộ suite/Web vì không đổi UI/API/wire.

Ngày 04/11/2026 · Baseline `b8964e9` · Thay đổi còn trong working tree.
Không commit, push hoặc pull. Không sửa governance hoặc canonical Drive documents.

## Phạm vi đã triển khai

| Bước | Trạng thái | Kết quả / vị trí chính |
| --- | --- | --- |
| P0 | DONE | [Execution contract](ASYNC_EXECUTION_CONTRACT.md); cấu hình chung `common/async_training.py`; Backend resolver/schemas; DTP metadata và negotiation |
| P1 | DONE | Runtime và Worker có `training_flows/sync.py` riêng; dùng lại compute, cache, model, SGD và checkpoint |
| P2 | DONE | `workload_pool.py`, `synchronization/async_sgd.py`, Runtime async flow; một assignment/Worker; update/drop và tiến độ cùng decision lock |
| P3 | DONE | DTP/1 TCP thật; Worker async flow; một compute owner; heartbeat độc lập; bounded queue, HELLO và stalled-write timeout |
| P4 | DONE | Registry/session fencing, managed binding, retry/backoff; rejoin trước/sau RUNNING; reclaim và idle wakeup; terminal chặn late work |
| P5 | DONE | Serializer chọn V1/V2; sparse async progress; checkpoint tuần tự; resume vào Attempt mới và kiểm tra catalog/counters/cursor |
| P6 | DONE | Form tạo/sửa Job, payload theo mode, async progress và session history; Backend/WS projection; capability cả hai mode |

StrictBSP, UpdatePlan/OperationContext, BatchScheduler/WorkloadScheduler, aggregator,
CheckpointV1Serializer và cơ chế durability/retention/export giữ nguyên.
Async dùng AsyncAssignment và đường UpdateEngine riêng thay vì sửa nghĩa global Step.
Coordinator chỉ thêm hook capture/readiness để tái sử dụng checkpoint lifecycle.
Contribution/parameter ACK cho phép không có Step ở async; sync vẫn kiểm tra Step như cũ.

Không cần migration: chỉ thay cách ghi session replacement để giữ history và tôn trọng
unique active rank. Node Agent, START_WORKER, management protocol và transport package
không đổi; không có tensor đi qua Backend/DB. `synchronization/base.py` chỉ đổi kiểu
Step của ACK; không ép async vào barrier interface của StrictBSP.

Các mục conditional đã chốt: không tạo recovery engine mới, không sửa sync V1,
không đổi artifact/export format và không thêm opcode/header/version DTP.
Initializer promotion, thay process crash tự động, sync hot-rejoin và async DBS:
**SKIPPED — ngoài phạm vi đã duyệt**. P7/T7 trong bản review được gộp vào nghiệm thu
P0–P6; P8/T8 vẫn hoãn.

## Bằng chứng tự động

- Acceptance sau sửa cuối: **157 passed** — async unit/protocol/admission/network,
  contract, PostgreSQL session history, sync/coordinator, production composition,
  checkpoint mechanics, DBS resume và epoch checkpoint lifecycle.
- TCP/HTTP dùng `_AttemptRunner` và `WorkerProcess` thật với model nhỏ: train xong;
  checkpoint giữa chừng rồi RESUME bằng Attempt mới; disconnect lúc compute;
  disconnect trước READY/RUNNING; mất parameter ACK. Rejoin dùng cache vẫn đạt
  sau khi tắt HTTP phục vụ dataset.
- Oracle: stale/future/base version; duplicate; update-vs-reclaim; session cũ không
  commit/reclaim phiên mới; idle survivor nhận việc thu hồi; zero-ready grace;
  heartbeat còn nhưng assignment hết hạn; checkpoint sau drop cùng model_version;
  checkpoint completion đúng thứ tự; frontier vượt nhiều mốc; corrupt progress.
- Managed admission: token hết hạn chỉ rejoin binding đã xác thực; replay/different
  process không đẩy session sống; allocation mới/token hết hạn bị từ chối; đóng
  admission không tạo session mới. Socket gửi bị chặn thật được phát hiện/đóng.
- Web: **196 passed, 1 skipped**; `npm run typecheck` và `npm run build` đạt.
  Kiểm tra payload chuyển mode, input rỗng/sai giới hạn, controls/progress render.
  Build còn cảnh báo bundle lớn có sẵn; không đổi bundling ngoài phạm vi.
- Architecture, scaffold/syntax, `git diff --check`: đạt.
  Ruff cho 15 file Python mới: đạt format/check; không thêm diagnostics so với HEAD
  trên các file sửa. Không reformat toàn repo để xử lý lint tồn đọng.

Full Python regression trong lượt triển khai: **878 passed, 150 subtests passed,
6 skipped, 5 failed**. Sau đó các guard cuối và hai test bổ sung được kiểm tra lại
trong acceptance ở trên. Full suite không được ghi là xanh.

## Năm lỗi baseline đã đối chiếu

| Test | Kết quả xác minh trên HEAD chưa sửa |
| --- | --- |
| `test_resume_rejects_nested_dataset_mismatch_before_allocation` | Fixture thiếu `artifact_retired`; tái hiện |
| `test_event_ingest_exact_duplicate_is_idempotent` | Mock insert_event không khớp đường ingest hiện tại; tái hiện |
| `test_event_ingest_different_occurred_at_raises_conflict` | Cùng nhóm event-ingest fixture; tái hiện |
| `test_event_ingest_different_immutable_field_raises_conflict` | Cùng nhóm event-ingest fixture; tái hiện |
| `test_health_ok` | Tái hiện với cùng `.env`: Redis consumer degraded nhưng smoke test đòi healthy |

Đối chiếu bằng `git archive HEAD` trong thư mục tạm, cùng Python/dependencies.
Full baseline không có `.env` cho 841 passed/150 subtests, 6 skipped và bốn lỗi đầu;
health test baseline với `.env` hiện tại tái hiện lỗi thứ năm. Không sửa production
hoặc fixture không thuộc tính năng để làm toàn bộ suite xanh.

## Giới hạn kiểm chứng

- Playwright runner: **NOT_AVAILABLE** trong môi trường hiện có; không cài thêm.
  Đã kiểm tra React render/payload và build; chưa kiểm thử tương tác browser thật.
- Chưa benchmark convergence/throughput hoặc chạy nhiều máy/mạng WAN.
  Các test phân tán ở đây dùng loopback; không khẳng định cải thiện chất lượng model.
- Training network tests dùng management stub ở bootstrap; isolation khỏi Backend/DB
  được kiểm bằng dependency boundary và đường train/rejoin không gọi management.
  Chưa chạy ma trận tắt từng service bằng cụm process triển khai thật.
- Giữ semantics rollback checkpoint: phần sau checkpoint có thể chạy lại khi Runtime
  crash; async ordering sau resume không hứa bit-identical với lịch chạy trước crash.

Chạy lại: dùng `.venv/Scripts/python.exe -m pytest tests src/pbl4/management_backend/tests`;
với torch CPU có thể đặt `torch.set_num_threads(1)` trong test process để tránh
oversubscription. Web dùng `npm test`, `npm run build`; không cần đồng bộ dependencies.
