# DBS_IMPLEMENTATION_PLAN.md

> Trạng thái: Kế hoạch triển khai chuẩn cho DBS + Work Unit.

## Authority

Tài liệu này là implementation plan **normative** cho DBS, dưới authority của
kiến trúc canonical, `docs/IMPLEMENTATION_CONTRACT.md`, `AGENTS.md` và
`docs/DBS_DESIGN.md`. Nếu execution note hoặc code cũ mâu thuẫn với Design thì
phải sửa plan/code; không sửa Design để hợp thức hóa implementation cũ.

## 1. Sự thật của codebase hiện tại

### 1.1. Training strategy

src/pbl4/runtime/synchronization/strict_bsp.py:

- chỉ chấp nhận context.training_strategy == "strict_bsp";

- giữ fixed membership;

- full N/N contribution;

- full N/N PARAMETER_APPLIED.

src/pbl4/runtime/synchronization/registry.py:

- chỉ tạo StrictBSP.

MUST KEEP. Không thêm dbs_bsp.

### 1.2. BatchScheduler

src/pbl4/runtime/batch_scheduler.py hiện:

- nhận các BatchAssignment đã gắn worker_id;

- yêu cầu mọi Worker có cùng tập batch_id;

- hash seed + epoch + batch_id để chọn một physical batch;

- mỗi Worker nhận đúng một physical batch/step.

Đây là phần phải thay để scheduling trên global Work Unit catalog.

### 1.3. Dataset provisioning

src/pbl4/runtime/process.py hiện:

- yêu cầu dataset.shard_count == expected_workers;

- gửi mỗi Worker DatasetAssignment với shard_id = worker_id;

- _schedule() biến shard_id thành worker_id.

src/pbl4/worker/shard_cache.py:

- cache/verify tốt một shard;

- load_batch(batch_id) trả x, y, sample_ids.

Giữ ShardCache; thêm DatasetCache quản lý nhiều shard. Không xây chunk cache mới.

### 1.4. Worker compute

src/pbl4/worker/training_loop.py hiện:

- giữ một CachedShard;

- một StepAssignment có một shard_id/batch_id;

- gọi adapter.compute_loss_and_gradients() một lần.

src/pbl4/adapter/base.py xác nhận ModelAdapter trả gradient AVERAGED over local batch.

src/pbl4/adapter/pytorch_adapter.py đã implement đúng semantics mean gradient.

Không sửa PyTorchAdapter nếu không có lý do khác.

### 1.5. Aggregator

src/pbl4/runtime/aggregator.py đã:

sum(sample_count_i * gradient_i) / total_sample_count

MUST KEEP nguyên công thức.

### 1.6. Timing

src/pbl4/protocol/messages.py::GradientMeta đã có optional compute_ms.

Nhưng:

- worker/process.py chưa đo compute_ms;

- worker/worker_client.py::send_gradient() chưa nhận/gửi compute_ms;

- runtime/parameter_server.py::_to_contribution() chưa giữ compute_ms;

- Contribution chưa có compute_ms.

Phải nối đầy đủ đường dữ liệu này.

### 1.7. Checkpoint

Checkpoint V1 hiện chỉ hỗ trợ training_strategy == strict_bsp và lưu RecoveryCursor(epoch, next_batch_ordinal).

MUST KEEP schema V1. Không thêm BatchPlan/p_i vào checkpoint.

### 1.8. Contract

management_backend/schemas/job.py::RequestedContractV1 hiện có đúng:

- dataset_build_id

- model_id

- epochs

- learning_rate

- training_seed

- training_strategy

contract_resolver.py hiện chỉ freeze strict_bsp, expected_workers=3 và chưa có workload section.

Cần mở contract tối thiểu cho workload; không biến DBS thành training_strategy.

### 1.9. State machine hiện tại

Không thêm state mới cho DBS.

Attempt/Coordinator giữ nguyên:

CREATED → WAITING_WORKERS → PROVISIONING → INITIALIZING → RUNNING → COMPLETING → COMPLETED; FAILED/ABORTED là terminal.

WorkerSession giữ nguyên:

CONNECTING → REGISTERING → PROVISIONING → SHARD_READY → MODEL_SYNCING → READY; DISCONNECTED/FAILED là terminal.

Step giữ nguyên:

COLLECTING_GRADIENTS → AGGREGATING → UPDATING → WAITING_PARAMETER_APPLIED → CHECKPOINTING → COMMITTED.

WorkloadPlan và epoch statistics chỉ là state trong bộ nhớ Runtime. Không thêm DB enum, WorkerSession state hoặc synchronization state cho DBS.

## 2. File map mục tiêu

### ADD

src/pbl4/runtime/workload_policy.py

src/pbl4/runtime/workload_scheduler.py

src/pbl4/worker/dataset_cache.py

### MODIFY

src/pbl4/management_backend/schemas/job.py

src/pbl4/management_backend/services/contract_resolver.py

src/pbl4/protocol/messages.py

src/pbl4/runtime/synchronization/context.py

src/pbl4/runtime/synchronization/strict_bsp.py

src/pbl4/runtime/batch_scheduler.py

src/pbl4/runtime/contribution.py

src/pbl4/runtime/parameter_server.py

src/pbl4/runtime/coordinator.py

src/pbl4/runtime/process.py

src/pbl4/worker/training_loop.py

src/pbl4/worker/process.py

src/pbl4/worker/worker_client.py

tests/unit/*

tests/integration/*

### KEEP UNCHANGED unless test chứng minh cần sửa

src/pbl4/runtime/synchronization/registry.py

src/pbl4/runtime/aggregator.py

src/pbl4/adapter/base.py

src/pbl4/adapter/pytorch_adapter.py

src/pbl4/runtime/checkpoint_v1.py

src/pbl4/runtime/checkpoint.py

src/pbl4/runtime/update_engine.py

src/pbl4/transport/*

## 3. Contract change tối thiểu

### 3.1. RequestedContractV1

MODIFY management_backend/schemas/job.py.

ADD:

- workload_policy: str = "equal"

- work_units_per_step: int | None = None

Validation:

- workload_policy in {"equal", "dbs"};

- bool không được coi là int;

- nếu equal và work_units_per_step is None: resolver dùng expected_workers;

- nếu dbs: work_units_per_step bắt buộc;

- equal yêu cầu K >= expected_workers;

- dbs yêu cầu K > expected_workers.

RequestedContractPatchV1 phải có hai field tương ứng.

training_strategy vẫn chỉ nhận "strict_bsp".

### 3.2. Resolved contract

ADD model:

ResolvedWorkload {

policy: str

work_units_per_step: int

}

ADD workload vào ResolvedContractV1.

Resolver:

- U = resolved dataset.batch_size;

- K = requested work_units_per_step hoặc expected_workers;

- B = U*K chỉ tính khi Runtime cần;

- reject U <= 0;

- equal: reject K < expected_workers;

- dbs: reject K <= expected_workers.

Không thêm:

- db_min_batch;

- smoothing;

- gain threshold;

- hardware profile;

- worker-specific batch size vào contract.

### 3.3. Runtime validation

runtime/process.py::_validate_contract():

- tiếp tục yêu cầu strict_bsp;

- validate workload section;

- validate U == contract.dataset.batch_size;

- validate theo policy: equal cần K >= expected_workers; dbs cần K > expected_workers;

- dtp_version vẫn 1;

- checkpoint schema vẫn 1.

## 4. Work Unit types

MODIFY runtime/synchronization/context.py.

ADD immutable type:

WorkUnitRef:

- shard_id: int >= 0

- batch_id: int >= 0

- sample_count: int > 0

Evolve BatchAssignment thành:

BatchAssignment:

- worker_id

- batch_ordinal

- work_units: tuple[WorkUnitRef, ...]

- sample_count

Validation:

- work_units không rỗng;

- sample_count == sum(unit.sample_count);

- không trùng (shard_id, batch_id) trong cùng assignment;

Không để WorkUnitRef biết đường dẫn HTTP hoặc torch tensor.

## 5. Pure workload policy

### ADD: runtime/workload_policy.py

Không import torch, DB, HTTP, transport, protocol.

Types:

WorkerEpochStats {

worker_id

sample_count

compute_ms

}

WorkloadPlan {

epoch

policy

units_per_worker

target_ratios

}

Functions/classes:

- EqualWorkloadPolicy

- DbsWorkloadPolicy

- project_units(...)

### 5.1. Equal projection

Input N Worker, K Work Unit.

Chia:

- floor(K/N) cho mỗi Worker;

- phần dư theo worker_id tăng dần.

Invariant:

- sum(k_i)=K;

- k_i>=1.

### 5.2. DBS

Fresh attempt:

- epoch 0 dùng Equal.

Cuối epoch j:

- total_samples = sum(sample_count_i);

- d_i = sample_count_i / total_samples;

- p_i = d_i / compute_ms_i;

- r_i = p_i / sum(p_i);

- q_i = r_i*K;

- project q -> integer k.

Reject:

- thiếu Worker;

- duplicate Worker;

- sample_count <= 0;

- compute_ms <= 0;

- NaN/inf;

- K <= N.

Không fallback âm thầm.

### 5.3. Projection integer

Normative implementation:

1. k_i = 1 cho mọi Worker.

2. remaining = K-N.

3. Lặp remaining lần.

4. Với mỗi Worker tính:

delta_i = (k_i + 1 - q_i)^2 - (k_i - q_i)^2

5. Chọn delta nhỏ nhất.

6. Tie-break worker_id nhỏ hơn.

7. k_i += 1.

Đây chỉ là projection target DBS sang Work Unit nguyên.

### 5.4. Unit tests

ADD tests/unit/test_workload_policy.py.

Bắt buộc:

- N=1;

- equal với K=N;

- dbs reject K=N;

- dbs với K>N;

- equal remainder deterministic;

- workers equal -> gần đều;

- performance 1:2:4 -> Worker nhanh nhận nhiều unit hơn;

- extreme skew vẫn k_i>=1;

- deterministic tie;

- invalid stats;

- paper Appendix A với U=1, K=64:

[13.7, 16.5, 19.6, 14.2] -> [14,16,20,14].

## 6. WorkloadScheduler runtime state

### ADD: runtime/workload_scheduler.py

Trách nhiệm:

- giữ active WorkloadPlan của epoch;

- tích lũy stats chỉ từ COMMITTED steps;

- đổi plan chỉ ở epoch boundary;

- xử lý warm-up sau resume.

State tối thiểu:

- policy

- worker_ids fixed

- K

- active_plan

- stats_by_worker

- current_epoch

- collect_stats: bool

API tối thiểu:

- plan_for_epoch(epoch)

- record_committed(contributions)

- on_epoch_completed(epoch)

- reset_after_resume(cursor)

Không gọi DB/network.

### Resume rule

Fresh:

- policy = equal: mọi epoch Equal, không tính DBS plan;

- policy = dbs: epoch 0 Equal và collect_stats=true; cuối epoch 0 nếu stats hợp lệ thì tính plan cho epoch 1.

Resume tại boundary (cursor.next_batch_ordinal = 0):

- epoch hiện tại Equal và collect_stats=true;

- epoch sau mới dùng DBS.

Resume giữa epoch:

- phần còn lại epoch hiện tại Equal và collect_stats=false;

- không dùng stats epoch dở;

- epoch đầy đủ kế tiếp Equal và collect_stats=true;

- DBS bắt đầu từ epoch sau epoch đầy đủ đó.

Không sửa checkpoint schema.

## 7. BatchScheduler mới

### MODIFY: runtime/batch_scheduler.py

Current assumption "worker -> same batch_id set" phải bỏ.

Constructor target:

- global tuple[WorkUnitRef]

- training_seed

- epochs

- K

Catalog:

- flatten mọi physical batch từ các shard manifest;

- chỉ lấy batch có sample_count == U;

- sort canonical theo (shard_id,batch_id) trước khi hash order;

- reject duplicate WorkUnitRef identity;

- require count >= K.

Epoch order:

sort Work Unit theo sha256_canonical_json([

training_seed,

epoch,

shard_id,

batch_id

])

M = len(eligible_units)

steps_per_epoch = floor(M / K)

Chỉ lập lịch steps_per_epoch × K Work Unit đầu tiên trong thứ tự của epoch. M mod K Work Unit cuối bị loại theo cơ chế drop_last cho epoch đó; không tạo bước cuối nhỏ hơn K và không chuyển phần dư sang epoch sau.

assignments(cursor, plan):

1. lấy K Work Unit tiếp theo;

2. worker_id sort tăng dần;

3. lấy đúng k_i unit liên tiếp cho Worker i;

4. trả tuple BatchAssignment.

Equal và DBS phải lấy cùng global set ở cùng cursor.

next_cursor():

- tăng batch ordinal;

- cuối steps_per_epoch -> epoch+1, ordinal=0.

ADD property:

- steps_per_epoch.

Coordinator xác định epoch boundary bằng next_cursor.epoch > operation.epoch; không thêm helper/state riêng chỉ cho việc này.

Tests:

- deterministic;

- no duplicate;

- same global set giữa equal/dbs;

- phần dư M mod K bị loại theo cơ chế drop_last;

- resume cursor.

## 8. Dataset provisioning

### 8.1. Không đổi Dataset Manager artifact format

runtime/process.py tiếp tục pin root manifest và fetch shard manifests.

Không thêm endpoint Dataset Manager mới.

Không thêm storage chunk schema.

### 8.2. ADD worker/dataset_cache.py

DatasetCache giữ:

- dataset_build_id;

- dataset_manifest_hash;

- dict[shard_id, CachedShard].

API:

- load_work_unit(WorkUnitRef)

- verify_all()

- shard_count

- eligible_work_unit_count

load_work_unit:

- chọn CachedShard theo shard_id;

- load_batch(batch_id);

- verify len(x) == WorkUnitRef.sample_count.

### 8.3. Worker provisioning

worker/process.py khi nhận DatasetAssignment có cache_scope="all_shards":

1. tải root manifest;

2. duyệt toàn bộ shard references;

3. reuse ShardDownloader + ShardCache cho từng shard;

4. tạo DatasetCache;

5. chỉ báo SHARD_READY sau khi toàn bộ shard đã verify.

protocol/messages.py:

- DatasetAssignment OPTIONAL cache_scope, enum {"assigned_shard","all_shards"}; nếu vắng mặt thì hiểu là assigned_shard để tương thích;

- không thêm field mới vào ShardReady;

Runtime Work Unit mode luôn gửi cache_scope="all_shards". Với scope này, Worker chỉ gửi SHARD_READY sau khi toàn bộ shard cần thiết đã cache và verify.

Production artifact-origin plumbing:

- Dataset Manager status/resolve trả `artifact_base_url` và `manifest_uri`;
- Backend persist và forward đúng descriptor authoritative qua MCP/1;
- Runtime validate same-origin/path containment, derive relative
  `root_manifest_path`, rồi dùng field đã có của `DatasetAssignment`;
- Worker/Sh​ardDownloader resolve root, shard manifest và batch relative path
  dưới cùng base URL; reject `..`, encoded traversal và cross-origin URI;
- không thêm DTP field, không hard-code `manifest.json`; legacy local
  `manifest.json` chỉ dùng khi descriptor authoritative xác định path đó.

Giữ shard_id hiện tại làm primary/compatibility field; nó không còn giới hạn Worker chỉ được xử lý shard đó.

Không thêm DATASET_READY message type mới.

## 9. DTP/1 assignment payload

Không đổi DTP version, 48-byte framing, message catalogue hoặc tensor transfer. Chỉ mở rộng JSON payload tối thiểu để mô tả nhiều Work Unit.

### 9.1. StepStart

MODIFY protocol/messages.py.

ADD OPTIONAL cho Work Unit mode:

- work_units: array

Runtime Work Unit mode phải gửi work_units. Worker không cần biết policy equal hay dbs; policy chỉ tồn tại ở Runtime/contract.

Mỗi work_units item:

- shard_id

- batch_id

- sample_count

Giữ shard_id/batch_id hiện tại trong giai đoạn migration:

- đặt bằng Work Unit đầu tiên;

- chỉ phục vụ compatibility/logging;

- không dùng làm identity đầy đủ của contribution.

StepStart._validate():

- work_units không rỗng;

- sum sample_count == expected_sample_count;

- first work unit khớp shard_id/batch_id compatibility field;

### 9.2. GradientMeta

Không thêm trường định danh assignment mới vào GradientMeta.

compute_ms đã có nhưng trong Work Unit mode phải là số hữu hạn > 0.

Worker Work Unit mode luôn gửi compute_ms. Không echo toàn bộ assignment hoặc một assignment hash về Runtime.

shard_id/batch_id compatibility field dùng Work Unit đầu tiên.

Không echo toàn work_units trong GradientMeta.

## 10. Worker multi-Work-Unit compute

### MODIFY: worker/training_loop.py

StepAssignment target:

- giữ attempt/session/worker/operation/step/model_version/batch_ordinal;

- work_units;

- expected_sample_count;

TrainingLoop giữ DatasetCache thay vì một CachedShard.

compute():

1. validate model version;

2. validate assignment;

3. for each WorkUnitRef:

- DatasetCache.load_work_unit();

- adapter.compute_loss_and_gradients();

4. vì adapter trả mean gradient, gộp:

total = sum(n_u * gradient_u) bằng FP64 accumulator;

5. divide by total_sample_count;

6. cast FP32;

7. weighted loss tương tự;

8. trả một LocalGradient có sample_count tổng.

Không gọi optimizer.

Không apply parameter giữa các Work Unit.

Không sửa PyTorchAdapter.

Unit test:

- 1 Work Unit;

- nhiều Work Unit cùng size;

- Work Unit khác sample_count ở test helper vẫn weighted đúng;

- global result khớp direct weighted mean.

## 11. compute_ms end-to-end

### worker/process.py

Trong _compute():

- start = time.perf_counter() ngay trước loop.compute();

- end ngay sau local gradient hoàn thành;

- compute_ms=(end-start)*1000;

- không tính send_gradient.

### worker/worker_client.py

send_gradient(...):

- thêm compute_ms;

- đưa vào GradientMeta.

### runtime/parameter_server.py

_to_contribution():

- đọc compute_ms;

- fail nếu thiếu trong Work Unit mode;

- đưa vào Contribution.

### runtime/contribution.py

ADD timing field:

- compute_ms: float

Giữ sample_count.

Có thể giữ shard_id/batch_id compatibility tới khi migration protocol được dọn riêng.

## 12. StrictBSP integration

### MODIFY: synchronization/strict_bsp.py

Không đổi constructor/training_strategy.

Khi admit:

- vẫn kiểm attempt/session/operation/model version;

- tìm BatchAssignment của Worker;

- với Work Unit mode, đối chiếu contribution với BatchAssignment canonical của Worker trong operation đang mở:

- contribution.batch_ordinal == assignment.batch_ordinal

- contribution.sample_count == assignment.sample_count

- shard_id/batch_id chỉ kiểm tra Work Unit đầu tiên trong giai đoạn tương thích; không dùng chúng làm identity đầy đủ. Exact work_units[] được Worker validate/load trước compute, còn Runtime đối chiếu contribution với BatchAssignment canonical của operation đang mở.

Full membership, UpdatePlan, ACK barrier và failure semantics giữ nguyên.

snapshot type vẫn "strict_bsp".

### registry.py

Không sửa.

## 13. Coordinator integration

### MODIFY: runtime/coordinator.py

Constructor ADD:

- workload_scheduler.

open_step():

- lấy active plan từ WorkloadScheduler cho cursor.epoch;

- scheduler.assignments(cursor, plan);

- phần còn lại của OperationContext/StrictBSP giữ nguyên.

admit():

- aggregator/update không đổi.

checkpoint():

- giữ progression gate hiện tại: WAITING_PARAMETER_APPLIED → CHECKPOINTING → COMMITTED;

- chỉ sau checkpoint write thành công và step đã COMMITTED:

1. lấy contributions của UpdatePlan vừa commit;

2. nếu collect_stats=true thì workload_scheduler.record_committed(...);

3. dùng next_cursor đã được checkpoint để advance;

4. nếu next_cursor.epoch > operation.epoch:

- workload_scheduler.on_epoch_completed(operation.epoch);

- nếu policy=dbs và epoch vừa hoàn tất là epoch thu stats đầy đủ thì validate stats và freeze plan cho epoch mới;

- có thể emit workload.plan_changed để quan sát, nhưng không persist plan vào DB/checkpoint.

Không record stats trước COMMITTED.

Không đưa DB I/O vào lock.

## 14. RuntimeProcess integration

### MODIFY: runtime/process.py

Bỏ semantics _schedule() gắn shard với Worker.

New flow:

1. validate contract;

2. pin dataset và fetch all shard manifests;

3. build global WorkUnit catalog, validate M >= K và K theo policy;

4. chờ đủ N/N Worker như hiện tại;

5. PROVISIONING: gửi DatasetAssignment cache_scope=all_shards;

6. wait N/N SHARD_READY;

7. giữ model initialization hiện tại; sau khi có Parameter Manifest/model init hợp lệ, tạo StrategyContext từ membership hiện tại;

8. create WorkloadPolicy + WorkloadScheduler + BatchScheduler(global units, seed, epochs, K), rồi create Coordinator với StrictBSP như hiện tại;

9. advance Coordinator theo state machine hiện có tới INITIALIZING;

10. mark Worker MODEL_SYNCING, broadcast parameter khởi tạo, wait N/N READY;

11. advance Coordinator lần cuối để freeze membership và chuyển RUNNING;

12. mỗi open_step lấy active plan → scheduler.assignments(cursor, plan) → gửi StepStart work_units.

MUST REMOVE assumption:

worker_id = manifest["shard_id"]

Giữ dataset.shard_count == expected_workers trong V1 nếu contract hiện tại còn khóa như vậy; không cần mở thêm thay đổi Dataset Manager chỉ vì DBS.

## 15. Telemetry tối thiểu

Không thêm bảng DB và không mở rộng snapshot schema chỉ để chạy DBS.

Khi active WorkloadPlan thay đổi ở epoch boundary, emit một event workload.plan_changed chứa tối thiểu epoch, policy, units_per_worker và target_ratios để debug/benchmark.

Không bắt buộc WebUI mới để merge feature. Không persist từng compute_ms vào DB; Runtime chỉ giữ statistics cần cho epoch hiện tại.

## 16. Checkpoint/resume implementation

Không sửa checkpoint_v1.py.

START_ATTEMPT RESUME dùng additive trusted descriptor:

```
resume_checkpoint = {
  checkpoint_id,
  source_attempt_id,
  model_sha256,
  metadata_sha256
}
```

Backend resolve descriptor từ durable checkpoint catalog. Runtime không query
Database và không nhận arbitrary filesystem path. Runtime derive location dưới
`checkpoint_root/source_attempt_id/sha256(checkpoint_id)`, reject invalid
identity/path escape, verify model/metadata hashes, parse Checkpoint V1 và verify
contract/dataset/parameter compatibility trước khi restore model,
`model_version` và `RecoveryCursor`.

Runtime khi resume phải gọi workload_scheduler.reset_after_resume(cursor).

Test:

- cursor ở boundary: current epoch Equal + collect_stats=true, next epoch mới DBS;

- cursor giữa epoch: phần còn lại Equal + collect_stats=false; epoch đầy đủ kế tiếp Equal + collect_stats=true; epoch sau mới DBS;

- global Work Unit set sau resume đúng cursor;

- không dùng partial epoch stats để tính DBS.

Negative tests bắt buộc: unknown checkpoint, corrupt metadata/model, checksum
mismatch, wrong contract, wrong dataset build/hash, invalid source/checkpoint
identity, locator escape và Runtime restart rồi resume thành công.

Nếu codebase sau này yêu cầu bitwise reproducibility của Worker assignment, đó là yêu cầu mới và phải cập nhật design; không tự đổi checkpoint schema trong PR này.

## 17. Failure semantics

MUST:

- equal và K&lt;N -&gt; validation error;

- dbs và K&lt;=N -&gt; validation error;

- M&lt;K hoặc steps_per_epoch=0 -&gt; fail trước RUNNING;

- invalid DBS stats tại epoch boundary cần tính plan -> Attempt FAILED trước khi mở epoch tiếp theo;

- Worker disconnect -> StrictBSP fatal như hiện tại;

- contribution có batch_ordinal hoặc sample_count không khớp BatchAssignment đang mở -> StrictBSP reject theo validation hiện có;

- cache lỗi trước SHARD_READY -> provisioning fail; cache miss/corrupt sau RUNNING -> Worker FAILED và StrictBSP làm Attempt FAILED; không tự thay Work Unit;

- duplicate Work Unit trong assignment -> validation error;

- Dataset Manager down sau SHARD_READY -> current Attempt vẫn đọc local cache.

Không:

- redistribute mid-step;

- shrink membership;

- fallback sang heuristic;

- tự tăng/decrease K.

## 18. Thứ tự phase/PR

Agent có thể tách nhỏ hơn nhưng không đổi dependency.

### Phase 0 — Audit guard

- xác nhận HEAD;

- chạy test baseline;

- thêm test đảm bảo registry chỉ strict_bsp;

- ghi rõ old adaptive docs là historical/superseded trong docs nếu repo đang trỏ tới chúng.

Gate:

- existing tests pass;

- architecture check pass.

### Phase 1 — Pure policy + contract

- workload_policy.py;

- policy tests;

- Requested/Resolved contract;

- resolver validation.

Chưa sửa Worker/protocol.

### Phase 2 — Work Unit scheduler

- WorkUnitRef/BatchAssignment;

- BatchScheduler global catalog;

- deterministic K-unit sets;

- equal/dbs same global set tests.

### Phase 3 — DatasetCache

- DatasetCache;

- Worker tải toàn bộ shards;

- cache_scope semantics; giữ nguyên ShardReady payload;

- provisioning tests.

### Phase 4 — DTP assignment + Worker compute

- StepStart work_units;

- GradientMeta compute_ms;

- multi-unit TrainingLoop;

- WorkerClient.

### Phase 5 — Runtime plumbing

- Contribution;

- ParameterServer;

- StrictBSP assignment validation;

- WorkloadScheduler;

- Coordinator epoch boundary;

- RuntimeProcess.

### Phase 6 — Resume + observability

- reset_after_resume;

- workload.plan_changed event;

- không đổi snapshot schema;

- không đổi checkpoint schema.

### Phase 7 — Integration/E2E

3 Worker:

- equal baseline;

- synthetic unequal compute speed;

- DBS plan shifts units toward faster Worker;

- N/N StrictBSP remains;

- gradient correctness;

- Dataset Manager can stop after provisioning;

- disconnect failure unchanged.

Benchmark timing không phải flaky CI assertion.

## 19. Test matrix bắt buộc

Algorithm:

- paper Appendix A;

- equal;

- 1:2:4;

- extreme skew;

- equal với K=N;

- dbs reject K=N;

- dbs với K>N;

- invalid stats.

Scheduler:

- deterministic seed;

- no duplicate;

- same global set equal/dbs;

- drop remainder;

- cursor resume.

Gradient:

- one unit;

- multiple units;

- weighted local;

- weighted global;

- same global sample set -> equivalent global mean.

Protocol:

- StepStart work_units;

- work_units rỗng/trùng hoặc tổng sample_count khác expected_sample_count;

- compute_ms valid/invalid;

- cache_scope.

Failure:

- Worker disconnect;

- stale/duplicate gradient;

- wrong model version;

- corrupt cache;

- insufficient units.

Resume:

- boundary;

- middle epoch;

- warm-up rule;

- DBS starts only after full measured epoch.

## 20. Review checklist

Reject nếu PR có:

- dbs_bsp;

- DbsStrictBSP;

- registry branch dbs;

- EMA/smoothing;

- db_min_batch;

- heuristic c_i/d_i cũ;

- DTP/2 chỉ để feature này;

- Checkpoint V2;

- DB table DBS;

- new chunk storage format;

- Dataset Manager call trong synchronized step;

- Worker gửi nhiều contribution cho một step;

- unweighted local gradient combine;

- Aggregator bỏ sample_count weighting;

- workload plan đổi giữa epoch;

- stats lấy từ step chưa COMMITTED.

Reviewer phải xác nhận:

- strict_bsp giữ nguyên;

- Work Unit artifact reuse;

- K/B invariant;

- global work set independent of workload policy;

- local + global weighted mean đúng;

- compute_ms đi đủ Worker -> Contribution -> WorkloadScheduler;

- resume không dùng partial epoch stats;

- old adaptive docs không được agent dùng để override design mới.

## 21. Definition of Done

[ ] Codebase HEAD đã được đối chiếu lại.

[ ] Tài liệu authority/supersession rõ ràng.

[ ] training_strategy vẫn strict_bsp.

[ ] equal và dbs là workload policy.

[ ] Work Unit dùng physical batch hiện có.

[ ] DatasetCache đọc được mọi shard đã verify.

[ ] equal: K>=N; dbs: K>N; K Work Unit/global step deterministic.

[ ] DBS đúng p_i=d_i/t_i.

[ ] Projection nguyên deterministic.

[ ] Paper Appendix A pass.

[ ] Worker multi-unit weighted gradient pass.

[ ] compute_ms end-to-end pass.

[ ] Attempt/WorkerSession/Step state machine hiện có unchanged; StrictBSP N/N unchanged.

[ ] Aggregator formula unchanged.

[ ] Checkpoint V1 unchanged.

[ ] Resume warm-up semantics pass mà không thêm checkpoint/state persisted mới.

[ ] Dataset Manager không nằm trong synchronized step.

[ ] Unit/integration/E2E tests pass.

[ ] scripts/check_architecture.py pass.

[ ] ruff format --check pass.

[ ] ruff check pass.

## 22. Một câu cho coding agent

Giữ nguyên StrictBSP và toàn bộ đường cập nhật mô hình; dùng DBS ở Runtime để tính tỉ lệ workload từ số mẫu và compute time của epoch đã commit, chuyển tỉ lệ đó thành số Work Unit nguyên có tổng K, giao đúng K physical batch Work Unit toàn cục cho các Worker, gộp nhiều Work Unit thành một local gradient có trọng số theo sample_count, rồi tiếp tục pipeline N/N -> weighted aggregation -> update -> parameter ACK -> checkpoint như hiện tại.
