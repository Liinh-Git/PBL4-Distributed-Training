# Review và kế hoạch phát triển Sync + Async-SGD + Worker Rejoin

Ngày review: 2026-11-04. Repository: `D:/PBL4`.

**Cập nhật triển khai:** P0–P6 đã thực hiện theo yêu cầu tiếp theo của người dùng.
Các phần bên dưới giữ snapshot/lập luận của lượt review; trạng thái hiện tại và
accounting T0–T8 xem [verification](ASYNC_REJOIN_VERIFICATION.md), semantics đã chốt
xem [execution contract](ASYNC_EXECUTION_CONTRACT.md).

**Kết luận:** giữ StrictBSP làm một chức năng độc lập và thêm Async-SGD là hướng phù hợp với code hiện tại. Cần tách cả điều phối tiến độ và hành vi Worker theo strategy; chỉ thêm `apply_async_gradient()` rồi sửa vòng lặp hiện có sẽ để lại coupling với global Step, ACK N/N và recovery cursor của sync.

Đây là tài liệu review/đề xuất thiết kế và kế hoạch triển khai, chưa phải xác nhận hệ thống đã hỗ trợ async. Không thay implementation hoặc tự sửa canonical specs/governance trong lượt review này. Các mục ghi “đề xuất” cần được đưa vào nguồn thiết kế tương ứng trước khi triển khai semantics mới.

## 1. Source Snapshot

### 1.1. Code và hai plan được review

- Branch: `feat/events-ui-checkpoints`.
- HEAD: `b8964e9405cd0dc7f77f4d5f8e88b9e6a6082c0c` — `feat(checkpoints): retain recent checkpoints and download trained models`.
- Working tree sạch lúc bắt đầu review.
- Plan A: `C:/Users/LENOVO/Downloads/async_training (2).md`, 443 dòng.
- Plan B: `C:/Users/LENOVO/Downloads/worker_disconnect (1).md`, 350 dòng.
- Audit commit/branch/revision của hai plan: **NOT_AVAILABLE**. Không thể lập exact historical diff; đối chiếu trực tiếp các nhận định/path/symbol với HEAD.
- Các tài liệu `data_plan.md`, `ASYNC_TRAINING_FLOW_PLAN_VI.md` ở checkout `d:/HKI 2026-27/PBL4/demo/` được hai plan dẫn chiếu: **chưa được cung cấp/đọc**, không xem các quyết định bên trong là đã xác minh.
- Câu “đã thống nhất” trong hai file là nội dung cần review, không tự trở thành chỉ thị hoặc phê duyệt của người dùng trong chat này.
- Codebase hiện tại quyết định cơ chế đang tồn tại, vị trí file, owner, interfaces và regression baseline. Semantics mới bên dưới là phần phát triển từ baseline đó; không áp một danh sách sửa file của checkout cũ vào HEAD.

### 1.2. Nguồn chuẩn đã truy cập

Đã dùng Google Drive connector để đọc nguồn đăng ký, kiểm tra tabs và đọc nội dung đúng tab khi có. Các locator dưới đây là mục nội dung, không phải chỉ dựa vào tên tài liệu.

| Key | Nguồn / locator đã đọc | Vai trò với kế hoạch |
| --- | --- | --- |
| SYNC | [Đồng bộ tham số](https://docs.google.com/document/d/1_2rUYoc_y-xpbV1Uuh-87cvV-xzCL-JBYZdM-vgDUQ0/edit), `Chính`, §§1–8, đặc biệt §8.2 | Giữ StrictBSP; policy không gọi socket/checkpoint; async cần đặc tả riêng về membership, checkpoint và convergence |
| RUNTIME | [Runtime huấn luyện](https://docs.google.com/document/d/1b_A6suHcAZe5Y2ffO6h61x6NxM9Z7lAokulWkn5zRm4/edit), `Chính`, ownership và concurrency | Coordinator sở hữu lifecycle; single writer; snapshot bất biến; không network/filesystem I/O dưới state lock |
| DOMAIN | [Mô hình miền](https://docs.google.com/document/d/1jtAQhZQ3_KOUzdwhzs2GHfBnrvet8E2kMD4lm85N9vQ/edit), `Chính`, resolved contract, Attempt, Worker Session | Contract freeze/hash; state hiện hữu; RESUME tạo Attempt mới |
| DTP | [DTP/1](https://docs.google.com/document/d/1s4x5HmuHpB4gDn3mwWpncuiPAUfdRCM0qyEUNUcHiu8/edit), `Chính`, §§4–5, đường mở rộng | Fixed header, generic operation_id, parameter direction và semantic ACK |
| CHECKPOINT | [Checkpoint](https://docs.google.com/document/d/1w9uJ8OeEB53jXx7miBd4rEz50R9Dm4TQJ1LyxXYZClY/edit), `Chính`, §§2,4, recovery | Periodic mỗi N epoch, manual/final; model và progress phải cùng recovery point |
| NODE | [NODE_AGENT_DESIGN.md](https://docs.google.com/document/d/1ADHTM0VzUkgcY6JLaMlBCayc0MAvbTr1E0fzeoW1IIs/edit), toàn tài liệu, §§6,10–11 | Allocation idempotency, token, không DTP reconnect trong V1 hiện tại |
| DBS | [DBS_DESIGN.md](https://docs.google.com/document/d/1dGP5PAFq__FEXJhvq3fS8X1i_MtuwLziapXcajPWuTw/edit), toàn tài liệu | DBS thuộc StrictBSP; K là tổng unit của global step; có global drop_last |
| RECOVERY | [Phục hồi](https://docs.google.com/document/d/10cxyVaicpt7MlFi-_RxCd_6uDMRHfAeLLlIl7uL05wk/edit), nội dung tab hiện có `Tab 1` | Supporting failure/recovery context; SOURCE_REGISTRY ghi `Chính` nhưng file thực tế chỉ có `Tab 1`: locator drift cần giải quyết khi đồng bộ spec |

Các lần đọc native Docs trả về revisionId; các nguồn không bị báo lỗi quyền truy cập. Không dùng tab Nháp để thiết kế. Registry, AGENTS cấp root/runtime/protocol/backend, `docs/IMPLEMENTATION_CONTRACT.md`, architecture checker, code và tests liên quan cũng đã được đọc.

Lưu ý drift tài liệu: DBS còn diễn giải cadence checkpoint blocking theo mỗi update ở một số đoạn. Không khôi phục semantics lịch sử đó: quyết định checkpoint ngày 2026-11-02 ở implementation contract, nguồn CHECKPOINT hiện tại và code HEAD dùng periodic mỗi N epoch + manual/final.

## 2. Frozen Decisions

### 2.1. Quyết định người dùng xác nhận trong lượt review

1. **Giữ hai chế độ sync và async.** Phát triển lên từ code hiện tại, không xóa StrictBSP.
2. **Rejoin chỉ cho async.** Sync tiếp tục fail-stop khi mất Worker đang tham gia và RESUME từ checkpoint bằng Attempt mới.
3. **Gradient quá cũ bị drop vẫn tính Work Unit đã xử lý.** Thống kê `applied` và `dropped` riêng; không tự requeue unit chỉ vì staleness.
4. **Giữ no-barrier epoch rollover.** Checkpoint async phải lưu thêm tiến độ đủ để resume đúng, kể cả khi nhiều epoch có công việc đang xen kẽ.

Các quyết định này khóa yêu cầu cấp tính năng. Chúng chưa tự định nghĩa opcode, field layout hoặc checkpoint schema version cụ thể.

### 2.2. Bất biến phải giữ

- Gradient và canonical parameter chỉ đi Worker ↔ Runtime qua DTP/1 TCP; Worker-0 cùng đường TCP với các Worker khác. Nguồn: AGENTS rules 2,3,9,16.
- Management Backend, DB, Redis và Dataset Manager sau provisioning không trở thành gate cho admission/update đang chạy. Nguồn: AGENTS rules 4,12,16.
- `UpdateEngine` là writer của canonical update; restore path giữ vai trò hiện tại. Không thêm optimizer trên Worker. Nguồn: runtime AGENTS ownership và `canonical_model.py`.
- Coordinator sở hữu Attempt lifecycle; policy sở hữu admission/update-ready; CheckpointPolicy sở hữu cadence; CheckpointManager sở hữu durability. Nguồn: runtime AGENTS và SYNC §§1.2–1.3.
- Strategy chọn từ frozen resolved contract, không cờ môi trường, không fallback im lặng, không đổi strategy giữa Attempt. Nguồn: SYNC §2.1 và DOMAIN resolved contract.
- `strict_bsp + equal/dbs` giữ semantics hiện có. DBS không trở thành async scheduler bằng cách đổi tên. Nguồn: AGENTS rule 17 và DBS.
- Không tự thêm Attempt state `PAUSED`, Worker lifecycle enum `IDLE`, DTP/2 hoặc migrate toàn bộ checkpoint chỉ để thuận tiện cho async. Điều kiện tạm chờ có thể là quan sát/runtime-local condition với tên/schema được duyệt riêng.
- Sync checkpoint V1 và checkpoint/export/retention hiện tại phải tiếp tục đọc và sử dụng được.

## 3. Drift Analysis và phản biện hai plan

### R01 — “Chuyển đổi/bỏ sync” không còn đúng phạm vi

**SEMANTIC_CONFLICT với yêu cầu hiện tại.** `synchronization/registry.py:create_policy()` đã là điểm chọn strategy; `strict_bsp.py` đã cô lập barrier/admission. Không xóa hoặc nới lỏng StrictBSP để chạy async. Thêm strategy và execution flow riêng.

### R02 — Hai file không đủ nếu global Step vẫn nằm trong phần dùng chung

**IMPLEMENTATION_CHANGED_SEMANTICS_SAME ở seam, thiếu scope ở plan.** `coordinator.py:open_step/admit/parameter_applied/commit_synchronized_step`, `_AttemptRunner._training_loop()` và Worker `TrainingLoop.apply_parameters()` đều có điều kiện sync. Worker hiện yêu cầu `output_version == input_version + 1`, sai với async nhận snapshot nhảy nhiều version hoặc không tăng khi drop.

Tách flow sync/async, giữ shared services. Không copy nguyên `process.py`/ParameterServer thành hai bản; không tạo một Coordinator mới chứa nhiều `if async` ở từng bước.

### R03 — Plan đảo chiều và đổi nghĩa `PARAMETER_APPLIED`

**SEMANTIC_CONFLICT.** `protocol/messages.py:ParameterApplied` và `protocol/session.py:_INBOUND_BY_PEER` hiện chỉ cho Worker → Runtime; `apply_ok` phải là true. Đây là ACK Worker đã load parameter, không phải kết quả Runtime nhận/drop gradient.

Đề xuất giữ nghĩa ACK hiện có cho cả hai mode. Kết quả gradient dùng extension/result metadata được đặc tả riêng. Không tự reuse opcode `0x0024` theo chiều ngược hoặc dùng `apply_ok=False` để báo stale drop. Sync vẫn chờ ACK N/N; async không có global ACK gate.

### R04 — `PARAMETER_META` trong plan không khớp schema/direction hiện tại

**SEMANTIC_CONFLICT.** Schema hiện không có `work_units`; server update dùng `model_version_out`, `source_step_id`, `attempt_id`; `model_init` là Worker-0 → Runtime, không phải Runtime → Worker khác. Plan dùng `model_version`, `purpose`/`transfer_purpose` không thống nhất và gửi `model_init` từ Runtime.

Đề xuất giữ tensor metadata hiện có cho sync; chốt một extension async có assignment, result và correlation rõ. Dùng đúng payload JSON metadata; không đưa assignment vào fixed 48-byte header. Giới hạn kích thước, validate sender/receiver/phase và capability đều thuộc scope.

### R05 — Đổi ngầm nghĩa `work_units_per_step` là breaking contract

**SEMANTIC_CONFLICT.** `BatchScheduler`, `WorkloadScheduler`, contract resolver và DBS dùng K là **tổng unit của cả global step**; equal cần K ≥ N, DBS cần K > N. Plan dùng k **cho mỗi Worker/contribution**, mặc định 1.

Giữ K và hash của sync jobs cũ. Đề xuất một cấu hình riêng theo strategy cho số unit mỗi async contribution, mặc định 1; tên/path chính thức chốt ở P0. Không dùng lại field cũ với nghĩa mới rồi coi là tương thích. Không tự hỗ trợ `async + dbs`; reject rõ tổ hợp chưa triển khai.

### R06 — Có nhiều thứ đã được triển khai, không nên xây lại

**COMPATIBLE / plan đánh giá thiếu baseline.** `_AttemptRunner` đã gửi `cache_scope=all_shards`; Worker đã có DatasetCache đa shard và local sample-weighted accumulation; Runtime đã có catalog WorkUnitRef, tensor assembler, immutable ModelSnapshot, UpdateEngine exactly-once, CheckpointPolicy và event outbox.

Tái sử dụng các thành phần đó. `GlobalWorkUnitPool` mới là phần quản lý dispatch/ownership/reclaim/occurrence, không phải dataset cache mới. Tái sử dụng quy tắc permutation dựa trên hash hiện tại thay vì tạo RNG shuffle thứ hai.

### R07 — Không thể dùng chỉ `(worker_id, units)` cho reclaim/dedup

**THIẾU CORRECTNESS CONTRACT.** Worker rank được tái sử dụng, unit vật lý lặp lại ở mỗi epoch, callback session cũ có thể đến trễ. Cần phân biệt physical unit `(shard_id,batch_id)`, occurrence `(epoch,physical unit)` và assignment của session/operation cụ thể.

Đề xuất Runtime cấp `operation_id` duy nhất trong Attempt cho từng async assignment. Server giữ mapping authoritative tới epoch/unit/session. Wire không cần echo nguyên danh sách units hoặc thêm assignment hash chỉ để tiện. Khóa dedup/audit phải bao gồm Attempt và active session; không dùng `model_version`, timestamp hoặc rank đơn lẻ làm update identity.

### R08 — Race apply/reclaim cần một điểm quyết định nguyên tử

**THIẾU CORRECTNESS CONTRACT.** Chỉ khóa số học trong UpdateEngine rồi gọi `pool.mark_completed()` bên ngoài vẫn có cửa sổ: model đã update nhưng disconnect reclaim unit, dẫn đến update lần hai.

Đề xuất một vùng quyết định serialize tại owner điều phối async: validate active session/assignment → dedup → đọc current version/tính tau → apply hoặc stale-drop → ghi kết quả unit → chọn snapshot và công việc tiếp. Reclaim dùng cùng thứ tự khóa/owner. Socket gửi sau khi rời lock. Nếu lỗi nội bộ xảy ra sau publish mà chưa ghi ledger, phải fail closed; không reclaim và tiếp tục như chưa update.

### R09 — Managed rejoin hiện bị chặn có chủ đích

**SEMANTIC_CONFLICT.** `WorkerRegistry.register()` cấm thay membership sau freeze. `ParameterServer._admitted_allocation_ids` từ chối allocation đã từng vào Attempt; join token có expiry; NODE §11.4 hiện cấm reconnect trong cùng Attempt.

Không chỉ bỏ duplicate guard hoặc kéo dài token vô hạn. Cần auth rejoin do Runtime kiểm tra cục bộ, một active session/rank/allocation, fencing phiên cũ, xác thực Attempt và giới hạn replay. Thiết kế credential dành cho rejoin phải được chốt trước implementation; Backend không được là nơi phải gọi mỗi lần reconnect. Admission secrets vẫn ngoài frozen training contract.

### R10 — Cleanup hiện có chưa an toàn khi hot-rejoin

**IMPLEMENTATION_CHANGED_SEMANTICS_SAME cho sync, cần thay cơ chế khi thêm async.** `ParameterServer._serve_connection():finally` đang `pop(worker_id)` và `discard(worker_id)` khỏi tập manifest. Nếu session mới đã thay thế, finally của session cũ có thể xóa connection/readiness mới.

Mọi cleanup, timeout, assembler, manifest readiness và callback phải ràng buộc session/generation. Chỉ xóa nếu entry vẫn thuộc chính connection đó. Reclaim idempotent cho lần disconnect và heartbeat timeout trùng nhau.

### R11 — Worker hiện exit khi socket lỗi, compute chặn reader

**IMPLEMENTATION_CHANGED_SEMANTICS_SAME, plan thiếu impact.** `WorkerProcess._on_disconnect()` set failed/stop. Reader gọi trực tiếp provisioning/compute callbacks; heartbeat bị bỏ qua khi `_busy`; `TrainingLoop.compute()` giữ lock xuyên compute. Chỉ thêm reconnect thread chưa đủ: compute cũ có thể kết thúc sau reconnect và gửi gradient vào session mới; heartbeat cũng có thể bị kẹt sau model lock.

Đề xuất async có connection supervisor, compute task gắn generation và một compute/model owner; reader xử lý control, assembler và signal. Khi mất session: invalidate task cũ, bỏ pending gradient/partial tensor, chờ compute cũ kết thúc hoặc hủy an toàn trước khi load weights mới. Liveness snapshot không chờ compute lock. Không chạy hai compute cùng adapter hoặc gửi bytes của hai session lẫn nhau.

### R12 — Idle + reclaim có thể deadlock

**THIẾU LIVENESS CONTRACT.** Ví dụ A/B đã nhận `work_units=[]`, C giữ phần còn lại rồi disconnect. Unit được requeue nhưng không ai gửi gradient nữa để kích hoạt “giao việc kế tiếp”.

Cần server chủ động đánh thức session idle khi có pending/reclaimed work. Trigger gồm reclaim, rejoin-ready và dispatch mới; dùng condition/event, không polling Work Unit từ Worker. Thông điệp giao việc unsolicited và legal phases phải nằm trong đặc tả async. Terminal khi không còn unprocessed lẫn in-flight work, không chỉ queue đã được cấp hết.

### R13 — No-barrier rollover buộc giữ tiến độ nhiều epoch

**SEMANTIC_CHANGE được người dùng chọn.** Có thể epoch e chưa xong nhưng unit epoch e+1 đã được apply. Reclaim “về epoch hiện tại” sẽ gán sai occurrence; `(epoch,next_batch_ordinal)` không biểu diễn được các lỗ tiến độ.

Pool phải nhớ epoch gốc của từng assignment, không cấp trùng occurrence, và tính completed-epoch frontier theo prefix các epoch thật sự đã xử lý hết. Giới hạn metadata/buffering để worker cực chậm không làm số epoch mở hoặc snapshot phình vô hạn; giới hạn không được âm thầm biến thành global step barrier.

### R14 — Drop được tính processed, không phải đã dùng gradient để học

**YÊU CẦU ĐÃ CHỐT.** Hoàn thành khi E × M occurrence được processed, gồm cả stale-drop. Cần counters unit/sample riêng cho applied/dropped; số update khác số unit và khác model_version gốc khi RESUME.

Ví dụ 100 unit, 20 bị drop: coverage processed là 100%, applied là 80%; không báo “100% dữ liệu đã được dùng cập nhật mô hình”. Gradient k unit bị drop thì cả k occurrence đều processed-dropped theo quyết định hiện tại. Disconnect trước quyết định cuối vẫn requeue; không tính drop chỉ vì đứt socket.

### R15 — Checkpoint async thiếu ledger sẽ resume sai

**THAY ĐỔI BẮT BUỘC THEO LỰA CHỌN NO-BARRIER.** `checkpoint_v1.py`, `snapshot.py`, `RecoveryCursor`, event/API projections hiện lưu cursor của sync. Không thể tái dùng nguyên V1 bằng cách ghi một scalar cursor giả.

Checkpoint async cần model snapshot + tiến độ tất cả occurrence liên quan ở **cùng một thời điểm quyết định**. Chọn extension/serializer/version riêng phù hợp sau khi duyệt schema; giữ khả năng đọc sync V1. CheckpointPolicy vẫn sở hữu cadence. Không persist runtime sockets, credentials hay DBS statistics vào checkpoint.

### R16 — Dynamic initializer promotion chưa có đường ra lệnh

**THIẾU PROTOCOL / không nên ghép vào MVP âm thầm.** Runtime/validator/Worker hiện cố định W0 là sender. Xóa `worker_id == 0` không chỉ định được ai được gửi thay, không ngăn hai initializer cũ/mới cùng hoàn tất. Manifest hash mô tả cấu trúc, không chứng minh weights cùng seed giống từng bit trên mọi thiết bị.

Đề xuất tách promotion thành milestone sau async+rejoin, giữ bootstrap W0 hiện tại cho milestone đầu. Nếu triển khai promotion: cần Runtime-issued authorization/generation, một init commit, reject transfer cũ và chính sách determinism/hash parameter bytes. Dù promote thành công, starting gate N READY vẫn phải đợi worker thiếu; promotion không tự loại bỏ mọi điểm chờ khởi động.

### R17 — Điều kiện zero workers, STOP và lỗi cuối còn quá tuyệt đối

**THIẾU FAILURE CONTRACT.** “Có HELLO trong 60 giây” chưa đủ phục hồi: Worker có thể chưa verify dataset/model. “Mọi Worker phải nhận STOP mới thoát” không thể bảo đảm khi Runtime chết hoặc mạng partition.

Đề xuất async continuing khi có ít nhất một execution-ready Worker; deadline grace monotonic từ lúc mất Worker đủ điều kiện cuối, không reset bởi HELLO/heartbeat chưa ready. Cluster waiting là condition quan sát trong Attempt RUNNING, không tự thêm Attempt PAUSED. Grace hết thì terminal fail, stop reconnect và checkpoint best-effort. Reconnect gặp Attempt terminal phải nhận kết quả terminal/rejection rõ, không spin vô hạn. Safe shutdown phải chịu được disconnect ở cuối, không rollback update đã quyết định chỉ vì STOP/ACK bị mất.

### R18 — Plan “minimal 7 file / pool ~100 dòng” bỏ sót contract và sản phẩm

**PLAN_PATH_STALE / THIẾU SCOPE.** Backend job schemas/resolver/service, Runtime validator/capabilities, Worker advertised capabilities, Web form/types và telemetry đều chỉ cho strict_bsp ở nhiều chỗ. Runtime gateway còn project `model.updated` như một global Step có worker_steps.

Cần end-to-end rollout, snapshot reconnect, session history và progress async riêng. Không emit các Step giả để đánh lừa API/UI. `worker_sessions` đã có session primary key và partial unique active rank; chưa có lý do mặc định phải thêm bảng/state. Chỉ thêm migration khi projection/schema đã được phê duyệt cần dữ liệu chưa biểu diễn được.

### R19 — Luận điểm nghiên cứu cần trình bày đúng mức

Plan dùng `tau = current_version - base_version` và modulation LR là hướng có cơ sở. [Zhang et al., §2.4, Eq.3](https://arxiv.org/html/1511.05950v5) chia LR cho tau khi tau > 0. Quy ước tau=0, ngưỡng drop R=6, cấp unit không lặp và k-unit accumulation là các lựa chọn của hệ thống này, không tự suy ra bảo đảm hội tụ cho toàn tổ hợp từ paper. Paper dùng các giả định/hardware khác; R=6 phải xem là default đề xuất cần đo. So sánh chất lượng theo dữ liệu processed/applied, thời gian và validation accuracy, không chỉ số model update.

## 4. Kiến trúc đề xuất và Impact Map

### 4.1. Tách sync/async đến đúng owner

Các tên file mới dưới đây là dự kiến implementation, không tạo thêm process hoặc đổi protocol major version.

```text
runtime/
  process.py                    # composition, startup/stop, chọn flow một lần
  coordinator.py                # owner Attempt lifecycle + ghép các policy
  training_flows/
    sync.py                     # global Step, N/N, ACK và commit hiện tại
    async_sgd.py                # dispatch, per-contribution progression, rejoin/grace
  synchronization/
    base.py                     # seam hiện có, chỉ generalize chỗ thực sự cần
    registry.py                 # lựa chọn từ resolved contract
    strict_bsp.py               # giữ tên/path hiện có
    async_sgd.py                # async admission, staleness/update-ready intents
  workload_pool.py              # ownership/progress/reclaim của async occurrences
  update_engine.py               # writer duy nhất, atomic/dedup update
  checkpoint*.py                # service chung + serializer/cursor theo strategy

worker/
  process.py                    # lifecycle/composition và connection supervision
  training_flows/
    sync.py                     # STEP_START-driven, strict version/ACK rules
    async_sgd.py                # assignment-driven, catch-up và generation fencing
  training_loop.py               # tái dùng compute đa unit, cache và sample weighting
  worker_client.py               # DTP connection/frame/tensor handling
```

“Hai file sync và async” áp dụng cho **luồng điều phối khác nhau**. Hạ tầng dùng chung vẫn có file riêng. Không rename `strict_bsp.py` chỉ để đủ cặp tên; không dồn toàn bộ fault tolerance/checkpoint/protocol vào hai file khổng lồ.

Flow không sở hữu lifecycle riêng: Coordinator vẫn là nơi chuyển Attempt state. Policy không ghi socket/checkpoint; flow thực thi action intents ngoài lock. Interface chung không ép async phải `open_step()`/`commit_synchronized_step()` hoặc giả lập một barrier luôn true. Sync-facing facade có thể giữ để hạn chế phá callers/tests hiện hữu.

### 4.2. Bản đồ thay đổi

| Loại | Owner / file và symbol hiện tại | Producer → consumer / tác động | Verification |
| --- | --- | --- | --- |
| MODIFY | `runtime/process.py:_AttemptRunner`, `coordinator.py:Coordinator` | frozen contract → flow → shared services; bỏ coupling global Step khỏi đường async | coordinator + production/network regression |
| ADD | `runtime/training_flows/sync.py`, `async_sgd.py` | orchestration sync hiện tại / async mới | flow + concurrency integration |
| MODIFY + ADD | `synchronization/base.py, registry.py, context.py, update_plan.py, contribution.py`; thêm async policy | complete tensor → admission → immutable execution intent | identity, version và duplicate tests |
| KEEP semantics | `synchronization/strict_bsp.py`, `barrier.py`, `batch_scheduler.py`, `workload_scheduler.py` | N/N, K toàn cụm, equal/dbs, sync cursor | sync/DBS regression; shared permutation helper chỉ tách nếu cần |
| ADD | `runtime/workload_pool.py` | catalog → occurrence/assignment/progress → dispatch/checkpoint | coverage, reclaim, epoch overlap, idle wakeup |
| MODIFY | `update_engine.py:UpdateEngine`, giữ `sgd_updater.py` arithmetic | admitted intent → canonical snapshot; atomic staleness/LR/dedup | numerical oracle + update/reclaim race |
| MODIFY | `worker_registry.py`, `parameter_server.py`, `heartbeat.py` | connection + local credential → active session → lifecycle/flow | duplicate rejoin, fencing, timeout/finally races |
| MODIFY | `protocol/messages.py`, `session.py`, tensor metadata consumers | approved async payload → Runtime/Worker, shared DTP/1 framing | exact schema/direction/phase/malformed/size tests |
| MODIFY + ADD | `worker/process.py`, `worker_client.py`, `training_loop.py`; thêm worker flow files | assignment → local compute → push/pull/ACK | version jump/drop, stale compute, partial stream |
| MODIFY + ADD | `snapshot.py`, `checkpoint_v1.py` integration, serializer/cursor async mới sau schema approval | coherent model+ledger → filesystem → new Attempt RESUME | sparse progress roundtrip, no double count/skip |
| MODIFY | Backend `schemas/job.py`, `services/contract_resolver.py`, `job_service.py`, `schemas/runtime.py`, `api/system.py` | request → frozen hash/capability → Runtime | old contract unchanged, async validation/hash |
| MODIFY | Backend `gateways/runtime_gateway.py`, `mcp_projection.py`, `repositories/worker_session_repository.py`, attempt/checkpoint projections | async events/snapshots → PostgreSQL/API/history | event replay/reconnect, active session order, checkpoint projection |
| CONDITIONAL | `common/worker_admission.py`, Node allocation/control owners | initial admission/rejoin credential/replacement authority | local auth, expired token, Backend outage |
| MODIFY | `web/src/pages/NewTrainingFlowPage.tsx`, `types/api.ts`, `types/index.ts`, `api/jobs.ts`, training/history consumers | strategy choice + mode-specific settings → request; async progress → display | request payload, mode switching, loss/drop/progress rendering |
| CONDITIONAL | `migrations/versions/` | only approved persisted shape delta | migration + repository integration |
| KEEP | transport raw-byte primitives, adapters, shard artifacts, DatasetCache, generic event buffering | shared services; training tensors remain DTP | existing tests + architecture checker |

Wire constants should contain approved wire identifiers only. Default R/LR scheduling belongs to resolved policy configuration, not an arbitrary policy default in pure `protocol/constants.py`.

## 5. Contract thiết kế đề xuất cho async

Những mục này là nội dung phải hoàn chỉnh ở P0, không phải schema/opcode đã tồn tại.

### 5.1. Mode và tham số

- Strategy identifier dự kiến `async_sgd`, giữ `strict_bsp` làm default cho jobs hiện có; unknown strategy reject trước RUNNING.
- Sync: giữ `equal|dbs`, K global-step, checkpoint V1 và failure semantics.
- Async: pull-based dynamic dispatch từ pool; số unit mỗi contribution mặc định 1 trong cấu hình riêng; không dùng DBS adaptation của sync.
- R dự kiến 6, validate integer không âm và cấm bool; LR finite positive; min execution-ready Worker 1; reconnect grace dự kiến 60 giây, retry backoff 1→2→…→30 giây có jitter. Chốt field paths tại design, freeze các giá trị ảnh hưởng thực thi trong contract; không rải default khác nhau ở Worker/Runtime/Backend.
- expected_workers giữ starting gate và upper bound/capacity của membership async ở phiên bản đầu; không tự hỗ trợ scale-out vượt N hoặc user-selected new Nodes giữa Attempt.

### 5.2. Dispatch và update

1. Bootstrap/provision/model validation dùng lại code hiện có. Chỉ chạy sau starting gate N READY; initial assignments được cấp một lần.
2. Mỗi session có tối đa một assignment in-flight. Runtime cấp operation correlation, epoch và units; pending assignment được giữ authoritative ở Runtime.
3. Worker tính sample-weighted mean trên units, gửi đúng một complete gradient và tổng sample_count.
4. Runtime kiểm tra identity/integrity/assignment trước strategy decision. Trong điểm serialize cập nhật, tính tau bằng canonical version **lúc quyết định**, không phải lúc bắt đầu nhận META.
5. Nếu base_version > current_version: reject lỗi, không biến thành tau âm rồi apply. Nếu tau > R: không mutate model/version, đánh dấu các unit processed-dropped. Nếu hợp lệ: dùng LR dự kiến `eta / max(1,tau)`, đúng một canonical update, đánh dấu processed-applied.
6. Chọn immutable snapshot có version khớp bytes; có thể mới hơn update vừa nộp nếu contract cho phép, nhưng một response không được ghép bytes/version từ hai thời điểm khác nhau.
7. Gửi snapshot + result/assignment theo schema async đã duyệt. Worker load trọn vector rồi ACK theo nghĩa parameter applied; không chờ ACK toàn cluster để Runtime xử lý Worker khác.
8. Worker không có việc thì chờ control/assignment hoặc terminal outcome; có reclaimed work phải được server chủ động giao lại.

Không dùng duy nhất `STEP_START(step_id=0)` như identity cho mọi batch. Có thể giữ một start signal, nhưng mỗi dispatch sau đó và mỗi Worker rejoin cần correlation riêng. Không khóa thiết kế vào “broadcast đúng một lần duy nhất trong cả Attempt” vì Worker đến sau/mất signal vẫn cần cách bắt đầu xác định.

### 5.3. Rejoin và failure

- In-process TCP reconnect giữ process, cache và adapter; bỏ gradient/pending computation của session cũ. Không mặc định retransmit gradient chưa biết kết quả.
- Runtime là nguồn quyết định batch cũ đã applied/dropped hay còn chưa xử lý. Reconnect sau commit không rollback model hoặc requeue batch cũ.
- Fence session cũ trước reclaim/rebind. Callback/gradient/ACK từ session cũ không ảnh hưởng session mới.
- Xác thực dataset cache theo build/hash; tái dùng shard hoàn chỉnh hợp lệ, sửa/download phần thiếu/hỏng. Không hứa phục hồi vài mili-giây: hashing, tensor transfer, backoff và GPU load vẫn có chi phí.
- EOF phát hiện ngay có thể reclaim ngay; silent partition phải qua detection/heartbeat timeout, không thể hứa immediate từ lúc dây mạng đứt.
- Worker crash khác socket reconnect. NODE hiện không auto-respawn allocation terminal: replacement process cần allocation mới theo control-plane authority. Tách optional replacement orchestration khỏi in-process rejoin; không cho Node Agent tự tái dùng allocation cũ.
- Một Worker còn execution-ready thì tiếp tục. Không Worker thì grace theo monotonic deadline; xác thực + ready mới hủy deadline. Attempt terminal luôn thắng late reconnect/checkpoint completion.
- Không lôi Backend/Agent/DB vào commit path của training. Rejoin credential được xác thực cục bộ tại Runtime.

### 5.4. Progress và checkpoint no-barrier

- Physical catalog có M Work Unit; mỗi epoch có M occurrence. Async xử lý cả phần đuôi, không sao chép `floor(M/K)`/drop_last của sync.
- Tổng mục tiêu E×M. Các tập pending/in-flight/processed tạo partition; processed có applied/dropped. Counters unit và sample kiểm tra được từ ledger.
- Dispatch epoch e+1 có thể diễn ra trước khi e hoàn tất. Mỗi occurrence vẫn thuộc epoch gốc. Metrics theo epoch phải tích lũy theo các occurrence đó, không theo “epoch hiện tại” toàn cụm.
- Cadence periodic tính theo frontier các epoch đã processed xong liên tục; đã cấp hết unit không đồng nghĩa epoch completed. Manual/final dùng cùng cơ chế snapshot nhất quán.
- Recovery payload cần biểu diễn catalog/deterministic order identity, các epoch đang mở, dispatch positions và holes/terminal outcomes cần thiết, counters và model revision. Có thể compact epoch đã xong bằng frontier và chỉ lưu bitmap/ledger cần thiết cho phần còn lại; chọn biểu diễn cụ thể sau giới hạn kích thước.
- Chụp model, progress và counters trong cùng serialization boundary; copy immutable data rồi ghi I/O ngoài state lock. Checkpoint publication phải chống late completion sau abort và chống checkpoint cũ ghi đè mốc mới.
- Khi RESUME: Attempt mới, restore đúng model+ledger của checkpoint; các occurrence chưa processed tại snapshot được cấp lại, kể cả đang in-flight lúc snapshot. Không restore sockets/session/credentials cũ. Những update sau recovery point có thể phải tính lại như rollback checkpoint thông thường; không tuyên bố exactly-once xuyên crash vượt recovery point.
- Checkpoint format async cần được đặc tả rõ; V1 parser hiện kiểm tra exact fields nên không được nhét thêm JSON rồi gọi là tương thích. Sync V1 vẫn đọc được; async resume không được fallback thành fresh/sync hoặc lấy checkpoint strategy khác.
- Final save failure phải hiển thị độc lập với training completed theo policy hiện tại; không tự thêm durability failure rule trái quyết định checkpoint 2026-11-02.

## 6. Phase DAG

```text
P0 chốt đặc tả async + rejoin + wire + recovery
 └─ P1 tách seam sync, regression giữ nguyên
     ├─ P2 pool + atomic async execution
     ├─ P3 DTP/Worker async integration
     └─ P5 schema checkpoint async (sau P0; tích hợp cần P2)
P2 + P3 ─ P4 rejoin/fencing/grace/idle wakeup
P0 ─ P6 contract/capabilities/projections/UI (phát triển song song theo spec)
P2 + P3 + P4 + P5 + P6 ─ P7 acceptance + release gate
P7 ─ P8 optional dynamic initializer / crash replacement
```

Đây là quan hệ phụ thuộc công việc, không phải chỉ thị sử dụng nhiều agent. Không public capability async trước khi toàn bộ P7 đạt.

## 7. Task Checklists

### P0 / T0 — Đặc tả đủ trước implementation semantics mới

- **TASK:** ghi design delta từ review, resolve duy nhất owner cho từng contract.
- **WHY:** hiện canonical V1 chưa định nghĩa async dynamic membership/recovery/wire extensions.
- **SOURCE:** quyết định người dùng §2.1; SYNC §8.2; DOMAIN; DTP; CHECKPOINT; NODE.
- **FILES/SYMBOLS:** thiết kế chuẩn của các owner trên; đối chiếu local `docs/IMPLEMENTATION_CONTRACT.md`, API projection và SOURCE_REGISTRY locator recovery. Không sửa AGENTS/skills trong feature task.
- **DEPENDS ON:** không có.
- **EXPECTED CHANGE:** khóa async settings, strategy matrix, result/assignment/ACK directions, operation/dedup, local rejoin auth và expiry/replay, progress/format compatibility, grace và scope initializer. Chốt giới hạn payload/state và hành vi unsupported mixed-version cluster.
- **TEST:** design scenarios R03–R17 có expected outcomes cụ thể; sender/receiver và restore consumers có mapping.
- **DONE WHEN:** mỗi semantic delta có owner/source locator được duyệt; không còn field/opcode/version/failure rule ngầm.

### P1 / T1 — Tách flow sync mà giữ hành vi

- **TASK:** đưa điều phối sync vào `runtime/training_flows/sync.py` và Worker flow tương ứng; giữ facade/callers cần thiết.
- **WHY:** giảm rủi ro sửa sync đồng thời phát triển async; P2 không phải mô phỏng global Step.
- **SOURCE:** R01–R02; shared ownership §2.2; code `Coordinator`, `_AttemptRunner`, `WorkerProcess`.
- **FILES/SYMBOLS:** runtime/worker `process.py`, `coordinator.py`, `training_loop.py`; flow files mới; registry seam.
- **DEPENDS ON:** T0 cho interface chung; phần refactor bảo toàn semantics có thể chuẩn bị độc lập.
- **EXPECTED CHANGE:** composition chọn implementation một lần; lifecycle vẫn Coordinator; tensor/cache/update services dùng chung.
- **TEST:** sync N/N + ACK, exact version, DBS equal/adaptive, failure/resume, production loopback và checkpoint/export regressions.
- **DONE WHEN:** contract/hash/wire/numerical behavior sync không đổi; không duplicated process/transport implementations.

### P2 / T2 — Pool occurrence và atomic async execution

- **TASK:** triển khai pool, async policy/flow và serialized execution của complete contribution.
- **WHY:** bảo đảm dispatch không trùng và apply/drop/reclaim không double-count.
- **SOURCE:** R05–R08, R12–R15; design T0.
- **FILES/SYMBOLS:** thêm `workload_pool.py`, `training_flows/async_sgd.py`, `synchronization/async_sgd.py`; sửa registry/context/plan/contribution seams, `UpdateEngine`; tái dùng canonical snapshot/SGD.
- **DEPENDS ON:** T0, T1.
- **EXPECTED CHANGE:** server-issued operation; session-scoped assignment; tau tại update; atomic outcome/ledger; no-barrier epoch progress, full tail coverage, idle redispatch intents.
- **TEST:** tau 0/1/R/R+1/future; multi-unit sample weighting; duplicate/update races; apply-vs-reclaim; M không chia hết k; N/k biến đổi; late old-epoch completion/reclaim; idle-only survivors.
- **DONE WHEN:** deterministic numerical oracle và partition/counter invariants đạt; socket I/O không nằm dưới state lock; state growth có giới hạn/compaction hợp lệ.

### P3 / T3 — DTP và Worker loop async

- **TASK:** triển khai extension đã duyệt và Worker push/pull theo assignment.
- **WHY:** worker/version/phase hiện tại đều strict; không thể dùng nguyên callbacks để tự lặp vô hạn.
- **SOURCE:** R03–R04, R11; DTP và design T0.
- **FILES/SYMBOLS:** `protocol/messages.py, session.py`, assembler metadata consumers, `parameter_server.py`, `worker_client.py`, `worker/process.py`, `training_loop.py`, worker async flow.
- **DEPENDS ON:** T0, T1; integration cần T2.
- **EXPECTED CHANGE:** đúng chiều parameter ACK; result không đổi nghĩa ACK; version jump hoặc unchanged-after-drop hợp lệ ở async; một reader/compute/model owner; responsive STOP/heartbeat.
- **TEST:** mixed capability reject trước train; wrong phase/direction/missing fields/oversize; fragmented tensor; disconnect partial stream; unsolicited assignment; long compute không bị falsely expired; STOP trong compute; sync legal-order tests nguyên vẹn.
- **DONE WHEN:** cluster thật bằng TCP chạy async nhiều contribution, có stale-drop và idle redispatch, không có global Step gate.

### P4 / T4 — Rejoin thực sự và session fencing

- **TASK:** in-process reconnect, local auth, catch-up, reclaim, grace và terminal races.
- **WHY:** registry/admission/client hiện chủ động chặn same-Attempt reconnect.
- **SOURCE:** quyết định người dùng; R07–R12, R17; NODE và design T0.
- **FILES/SYMBOLS:** `WorkerRegistry`, `ParameterServer._serve_connection/_read_bound`, `_AttemptRunner._on_disconnect`, async flow, Worker supervisor/client callbacks, admission credential owner.
- **DEPENDS ON:** T2, T3.
- **EXPECTED CHANGE:** invalidate phiên cũ trước rebind; same allocation reconnect theo auth đã duyệt; old callback không pop session mới; một reconnect supervisor; grace chờ execution-ready.
- **TEST:** concurrent duplicate reconnect; token expired/replay/wrong Attempt; finally cũ sau HELLO mới; heartbeat timeout rồi EOF; disconnect trước/sau publish; rejoin khi pending/dropped/idle; Backend/DB/Agent WSS down; all-zero recovery/deadline; terminal/deadline-ready race.
- **DONE WHEN:** mất một Worker không dừng Worker khác, không mất/trùng processed occurrence; sync vẫn fail-stop; reconnect không cần management round trip.

### P5 / T5 — Checkpoint/resume async có holes

- **TASK:** thêm serializer/recovery state async và integrate periodic/manual/final.
- **WHY:** yêu cầu no-barrier không biểu diễn được bằng sync cursor.
- **SOURCE:** người dùng §2.1.4; R13–R15; CHECKPOINT và design T0.
- **FILES/SYMBOLS:** `CheckpointSnapshot`, serializer routing, `CheckpointManager.restore` compatibility, async progress owner, Runtime resume composition, Backend checkpoint projections.
- **DEPENDS ON:** T0 cho schema; T2 cho ledger; acceptance cùng T3/T4.
- **EXPECTED CHANGE:** immutable coherent model+ledger; restore pending occurrences, terminal counters và overlapping epochs; giữ V1 sync reader; reject cross-strategy checkpoint.
- **TEST:** e còn hole trong khi e+1 đã update; in-flight ở snapshot; checkpoint I/O chậm nhưng snapshot không trộn revision; abort/race; corruption; periodic/final failure; resume hai lần từ một recovery point; old sync V1/retention/export regression.
- **DONE WHEN:** oracle restore không skip/double-count occurrence đã có trong recovery point, counters khớp model/ledger; no silent fresh fallback.

### P6 / T6 — Contract và quan sát end-to-end

- **TASK:** API/capabilities/form/events/history/snapshot theo strategy.
- **WHY:** thay Runtime mà không thay resolver/capabilities thì người dùng không tạo được async job; project Step giả làm sai dữ liệu.
- **SOURCE:** R05, R14, R18; design T0.
- **FILES/SYMBOLS:** Backend/schema/resolver/gateway/projection và Web paths tại impact map; chỉ thêm numbered migration nếu approved persisted shape thực sự cần.
- **DEPENDS ON:** T0; integration dùng T2–T5.
- **EXPECTED CHANGE:** giữ default sync/hashes cũ; mode-specific async settings; capability đúng thực tế; applied/dropped/processed units+samples, versions/staleness/ready-workers, session history; epoch metrics theo epoch occurrence. UI phân biệt training completed với final artifact failure.
- **TEST:** request validation/hash; old job resume; unsupported async+dbs; event replay/dedup; snapshot sau Backend reconnect; session-old/new event ordering và partial unique active rank; UI chuyển mode không gửi field mode cũ.
- **DONE WHEN:** có thể tạo, chạy, quan sát, reconnect và resume async qua đường sản phẩm; management outage không chặn training.

### P7 / T7 — Acceptance và rollout

- **TASK:** chạy matrix sync+async, fault injection và chất lượng training trước công bố capability.
- **WHY:** unit test pool không chứng minh pipeline/rejoin/recovery đúng trên TCP.
- **SOURCE:** invariants §2, matrix §10 và scenarios T1–T6.
- **FILES/SYMBOLS:** tests hiện hữu liên quan; thêm tests cụ thể cùng feature, không pre-create fixtures/hierarchy rỗng; architecture checker; Web build/test commands.
- **DEPENDS ON:** T1–T6.
- **EXPECTED CHANGE:** capability chỉ bật khi Runtime và Worker hoàn chỉnh; reject version/capability mismatch rõ; tài liệu vận hành giới hạn.
- **TEST:** numerical trace oracle, network partitions, process crashes, slow worker, all workers lost, model transfer interruption, checkpoint/resume, management outage, sync/DBS regression. Benchmark validation quality vs wall time và processed/applied samples; không hứa async luôn nhanh/chính xác hơn sync.
- **DONE WHEN:** mọi acceptance criterion có evidence mới; negative/race tests đạt; không còn phần feature lõi bị ghi “sẽ bổ sung sau” nhưng UI đã bật.

### P8 / T8 — Optional: initializer promotion và process replacement

- **TASK:** mở rộng bootstrap/replacement nếu được đưa vào scope tiếp theo.
- **WHY:** đây là hai tính năng khác in-process rejoin, không phải điều kiện để async training loop đúng.
- **SOURCE:** R16–R17; NODE; đặc tả bootstrap mới nếu được duyệt.
- **FILES/SYMBOLS:** Runtime bootstrap owner, protocol authorization, Worker init sender; allocation/control service nếu thay process.
- **DEPENDS ON:** T0 scope approval, T7.
- **EXPECTED CHANGE:** chỉ initializer được cấp quyền/generation mới được commit W0; crash replacement dùng allocation mới, không respawn trái lifecycle.
- **TEST:** stale init completion, double promotion, stream partial, ready gate N; duplicate START_WORKER, replacement while old process survives.
- **DONE WHEN:** bootstrap/replacement rõ quyền và identity, không sửa ngầm sync V1.

## 8. Derived Implementation Decisions

| Decision | Evidence | Vì sao là implementation detail / lựa chọn bị loại |
| --- | --- | --- |
| Giữ `strict_bsp.py`, dùng flow `sync.py` riêng nếu extraction cần | policy đã tồn tại và tests import hiện tại | Không cần rename/alias policy chỉ để tạo hai tên đối xứng |
| Tái dùng cache và multi-unit compute | Worker `_provision`, DatasetCache, `TrainingLoop.compute` | Tránh code dataset/weighting trùng; tách compute core khỏi strict pending/ACK checks |
| Tái dùng immutable snapshot và SGD arithmetic | `CanonicalModel`, `ModelSnapshot`, `SGDUpdater` | Async đổi admission/progression, không cần writer hoặc numerical backend thứ hai |
| Dùng server-issued operation mapping | DTP generic operation_id, current transport identity | Cơ chế triển khai cho identity đã chốt; không cần assignment hash/full echo; payload cụ thể thuộc T0 |
| Một serialized decision owner, I/O sau lock | Coordinator lock ownership hiện tại và R08 | Không thêm queue/broker vào training; không lock socket send toàn Runtime |
| Snapshot/liveness không chờ compute model lock | Worker giữ training lock trong compute và skip heartbeat busy | Sửa cơ chế luồng/lock cần cho liveness, không thay optimizer/domain lifecycle |
| Không mặc định migration session table | session primary key + active-rank partial unique index hiện hữu | Phải sửa ordering/projection trước; chỉ migrate nếu thêm data shape thực sự cần |
| Không sửa transport byte layer để biết sync/async | transport AGENTS và code exact-byte primitives | Strategy nằm Runtime/Worker, không nằm recv_exact/send_all |

Các lựa chọn R, stale-drop, dynamic membership, format recovery và credential semantics **không** được ngụy trang thành implementation details; chúng thuộc design/contract và user decisions.

## 9. Risks, Conflicts và Non-Goals

- Phạm vi lớn hơn plan cũ, chủ yếu ở recovery no-barrier và managed rejoin, không phải ở công thức SGD. Không ước lượng độ an toàn bằng số dòng của pool.
- Stale-drop có thể thiên lệch dữ liệu theo tốc độ Worker và giảm effective samples; cần hiển thị và đo chất lượng. Rejoin bắt kịp version lúc snapshot không bảo đảm gradient tiếp theo tau=0 vì Worker khác vẫn update.
- Kích thước sparse ledger/checkpoint, repeated stale/slow Worker, outstanding tensor buffers và pending sends cần giới hạn/backpressure cụ thể.
- No-barrier không có nghĩa không serialize update hoặc không cần coherent checkpoint cut. Giữ serialized canonical writer là bắt buộc.
- Nội dung canonical hiện chỉ định StrictBSP V1; cần design delta cho async. Không xem proposal này hoặc nhãn “đã thống nhất” trong file đính kèm là lý do tự sửa wire trong code.
- Non-goals của milestone đầu: sync hot-rejoin; live strategy switch; async DBS; scale-out vượt N; auto restart process bằng allocation cũ; multi-Parameter-Server; optimizer có momentum; DTP major bump; thay management event transport.
- Dynamic initializer promotion và crash replacement ở T8 là đề xuất scope sau, không đánh dấu đã triển khai hoặc đã bị người dùng loại khỏi yêu cầu vĩnh viễn.

## 10. Verification Matrix

| Nhóm | Bất biến/acceptance bắt buộc | Kiểm thử |
| --- | --- | --- |
| Sync compatibility | N/N, full ACK, sample-weighted update, fail-stop, equal/dbs, old hash/V1 resume | existing sync/coordinator/DBS/contract/network tests |
| Async numerical | tau tại quyết định, đúng LR, reject future, drop không tăng model_version, update đúng một lần | deterministic gradient/version trace |
| Pool coverage | E×M processed, unit/sample applied+dropped đúng, không trùng occurrence, full tail | unit + randomized scheduling/property scenarios |
| Epoch overlap | e+1 tiến khi e còn pending; reclaim đúng epoch; frontier/metrics đúng | deliberately delayed epoch-e unit |
| Rejoin | một active session, stale callbacks/compute không ảnh hưởng mới, local auth, lost ACK không double update | TCP fault injection + scheduling barriers trong race tests |
| Idle liveness | idle Worker nhận reclaimed work dù không còn gradient mới | disconnect last busy Worker with idle survivors |
| Zero workers | grace monotonic, ready mới resume, terminal wins late reconnect | controlled clock/concurrency tests |
| Checkpoint | model+ledger cùng cut, holes restore, old V1 vẫn đọc, corruption reject | roundtrip + crash/restore numerical oracle |
| Management boundary | Backend/DB/Redis/Agent WSS down không dừng worker/update đã provisioning | outage integration + snapshot reconciliation |
| Product | chọn mode, validated config, truthful processed/applied/dropped, no fake Steps, correct session history | Backend/API/Web acceptance |
| Wire/boundary | đúng direction/phase/size/fragmentation, no tensor management route | protocol negative tests + architecture checker |

Lệnh baseline hiện có (PowerShell tại `D:/PBL4`):

```powershell
.\.venv\Scripts\python.exe scripts/check_architecture.py
.\.venv\Scripts\python.exe -m pytest tests/test_synchronization.py tests/test_update_pipeline.py tests/test_runtime_membership_schedule.py tests/unit/test_contract_workload.py tests/unit/test_runtime_managed_admission.py tests/integration/test_dbs_failure_semantics.py tests/integration/test_dbs_checkpoint_resume.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests/test_coordinator.py tests/test_worker_training.py tests/integration/test_full_training_network.py tests/unit/test_dtp_messages.py tests/unit/test_training_loop_multi_unit.py -q -p no:cacheprovider
```

Khi implementation chạm checkpoint/export/retention, phải chạy thêm các suite hiện có tương ứng; tests async mới đi cùng feature, không suy baseline sync pass thành async đã pass.

## 11. Completion Accounting

### Review đã hoàn thành

- Đã đọc hai plan được cung cấp và đối chiếu ownership/paths/definitions/callers ở HEAD.
- Đã kiểm tra nguồn canonical liên quan và đánh dấu locator drift/nguồn chưa có.
- Đã xác nhận ba lựa chọn hành vi với người dùng: async-only rejoin; drop tính processed; no-barrier + recovery state async.
- Đã lập phản biện R01–R19, impact map ADD/MODIFY/KEEP/CONDITIONAL, phase dependencies, task prerequisites/exit criteria và negative/recovery acceptance.
- Baseline lần 1: **106 passed, 5 subtests passed**. Baseline lần 2: **77 passed, 100 subtests passed**. Tổng hai tập không trùng: **183 passed, 105 subtests passed**. Mỗi lần có warning deprecation `pynvml` từ dependency; không có test failure.
- Architecture import-boundary check: **PASSED**.
- Các kết quả này xác nhận baseline được review, không chứng minh có implementation async/rejoin.

### Implementation chưa thực hiện

| Node | Trạng thái | Tiêu chí tính hoàn tất |
| --- | --- | --- |
| P0/T0 | PLANNED — design delta cần hoàn chỉnh/đưa vào owners | toàn bộ semantics/schema/auth/recovery decisions có locator rõ |
| P1/T1 | PLANNED | extraction + sync regression đạt |
| P2/T2 | PLANNED, depends T0/T1 | pool/update/epoch/counter invariants đạt |
| P3/T3 | PLANNED, depends T0/T1/T2 integration | wire+Worker async trên TCP đạt |
| P4/T4 | PLANNED, depends T2/T3 | rejoin/fencing/grace/idle matrix đạt |
| P5/T5 | PLANNED, depends T0/T2 | checkpoint holes+resume oracle và V1 regression đạt |
| P6/T6 | PLANNED, depends T0 và integration T2–T5 | contract/capabilities/product projections đúng |
| P7/T7 | PLANNED, depends T1–T6 | toàn acceptance matrix đạt trước advertise capability |
| P8/T8 | DEFERRED PROPOSAL | chỉ thực hiện khi initializer/replacement vào scope đã duyệt |

Tất cả ADD/MODIFY trong impact map thuộc T0–T7 hoặc optional T8; KEEP là regression obligations tại T1/T7; CONDITIONAL phải có quyết định/reason trước khi triển khai. Không có node implementation nào được đánh dấu DONE trong lượt review.

## 12. Rà cuối plan rút gọn — 04/11/2026

HEAD vẫn `b8964e9`; chưa có thay đổi implementation. Các mục dưới là lỗ hổng/thiếu đặc tả của kế hoạch, không phải khẳng định sync hiện tại mắc lỗi async. Đã đưa yêu cầu và test tương ứng vào P0–P6 của `ASYNC_REJOIN_PLAN_VI.md`; hành vi mới còn thiếu đặc tả phải giải quyết tại P0.

| ID | Mức | Lỗ hổng và bằng chứng | Yêu cầu đóng / kiểm thử |
| --- | --- | --- | --- |
| F01 | Cao | `UpdatePlan.__post_init__()` buộc contribution.model_version bằng input model của plan; `UpdateEngine.apply_once()` lại buộc input bằng canonical hiện tại. Dùng nguyên hai điều kiện sẽ từ chối stale gradient async; sửa bằng cách ghi đè base_version sẽ mất dấu phiên bản thực sự đã tính. | P1/P2 tách source version và canonical version lúc update; Runtime kiểm tra source đúng snapshot đã giao cho assignment. Test base giả, future và hai gradient cùng base nhưng apply khác thời điểm; sync vẫn exact-version. |
| F02 | Cao | Độ trễ theo heartbeat trong `HeartbeatMonitor` chỉ đo kết nối. Compute kẹt vẫn gửi heartbeat có thể giữ unit cuối mãi; zero-worker grace không bao giờ chạy. Ngược lại transfer đang tiến triển không nên bị coi chết chỉ vì heartbeat không chen được vào logical tensor transfer. | P0/P3/P4 chốt deadline công việc và timeout truyền riêng với liveness; timeout phải fence trước reclaim, không cho reconnect lặp mãi để giữ việc. Test heartbeat tiếp tục nhưng compute không kết thúc, slow transfer còn tiến triển, lỗi compute fatal và partial upload. |
| F03 | Cao | `CheckpointPolicy.due_epoch()` dùng modulo; với sync frontier chỉ tăng một epoch nên phù hợp. Async có thể nhảy 0→6 khi unit epoch 0 cuối cùng xong trong khi epoch 1–5 đã xong. Chỉ gọi due_epoch(6) sẽ bỏ cadence mỗi 5 epoch. | P5 phát hiện vượt mốc từ frontier trước đến frontier mới, không chỉ thử modulo giá trị mới; ghi recovery point hiện tại hợp lệ, không dựng lại snapshot quá khứ giả. Test bước nhảy vượt một/nhiều mốc và coalesce yêu cầu checkpoint. |
| F04 | Cao | `Coordinator.has_verified_checkpoint_for_current_revision()` so model_version và sync cursor. Trong async, stale-drop thay đổi ledger/counters nhưng không tăng model_version; hai recovery points có cùng weights vẫn có thể khác tiến độ. | P5 nhận diện recovery revision bao gồm tiến độ; không skip final/manual chỉ vì weights không đổi. Test drop sau checkpoint, drop-only tail, checkpoint completion đến sai thứ tự và resume counters. |
| F05 | Cao | Plan chỉ nói cấp hết việc/processed mà chưa khóa thời điểm terminal. Nếu admission còn mở, late contribution/rejoin có thể đến sau snapshot cuối hoặc sau ABORT; STOP bị mất còn có thể khiến Worker reconnect vô hạn. | P2/P4/P6 hoàn thành khi processed=E×M và không còn pending/in-flight; đóng admission trước snapshot cuối; terminal thắng late callbacks và kết thúc retry Worker. Test update-vs-abort, last-result/ACK loss, late reconnect và STOP giữa transfer. |
| F06 | Cao | Initial join token có expiry, allocation đã từng admit bị từ chối. Chỉ ghi “auth tại Runtime” chưa giải quyết long-running rejoin, mạng partition khi session cũ chưa timeout hoặc HELLO_ACK chứa thông tin rejoin bị mất. | P0 chốt chứng cứ rejoin, expiry/replay và phân biệt phiên cũ còn sống/đã fence mà không gọi Backend trong training path; P4 test mất HELLO_ACK, token hết hạn, hai kết nối tranh rank và handshake trước RUNNING. Không tự gia hạn token vô hạn hoặc bỏ duplicate guard. |
| F07 | Vừa | Không nói rõ giới hạn mỗi assignment, grouping ở đuôi epoch và tác động slow consumer. Trộn epoch vào cùng contribution làm outcome/metrics/reclaim khó truy vết; gửi socket dưới lock sẽ biến một Worker chậm thành điểm chặn toàn cụm. | P0 chốt grouping; đề xuất một epoch/assignment và cho phép tail < k. P2/P3 giới hạn một in-flight assignment/Worker; snapshot/buffer/queue có bound, external I/O ngoài state lock. Test M<k, M mod k khác 0, idle wakeup, slow receiver và bounded memory. |
| F08 | Vừa | “Dùng chung context” dễ kéo active session map vào frozen StrategyContext; context hiện chứa membership cố định, Contribution.logical_key hiện là `(attempt,step,worker)`. Rejoin không được sửa frozen contract hoặc dựng global Step giả để thỏa type cũ. | P1/P2 tách contract bất biến, active membership và assignment/update identities. P6 giữ hash Job sync cũ, capability đúng thực tế, snapshot sau mất Backend khôi phục được counters/session; cache hợp lệ rejoin được khi Dataset Manager down. |

Kiểm chứng lượt này: đọc lại định nghĩa/callers nêu trên và rà kịch bản đối nghịch; kiểm tra cấu trúc/độ dài/link của tài liệu sau sửa. Không chạy lại hay ghi nhận thêm test implementation: số 183 test/105 subtest ở §11 là evidence của lượt baseline trước.
