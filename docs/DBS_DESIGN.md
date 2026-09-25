# DBS_DESIGN.md

> Trạng thái: Thiết kế chuẩn cho phạm vi phân phối khối lượng huấn luyện thích ứng bằng DBS.
> Mục tiêu: Cài đặt thuật toán DBS từ paper arXiv:2007.11831, nhưng giữ nguyên kiến trúc huấn luyện cốt lõi của PBL4.
> Phạm vi: Runtime, Worker, Dataset provisioning cần thiết cho Work Unit và dữ liệu quan sát phục vụ DBS.

## 1. Authority

Tài liệu này là đặc tả **normative** cho semantics DBS và Work Unit của PBL4. Nó
phải tuân theo kiến trúc canonical, `docs/IMPLEMENTATION_CONTRACT.md` và
`AGENTS.md`. `docs/DBS_IMPLEMENTATION_PLAN.md` phải tuân theo tài liệu này;
`docs/DBS_EXECUTION_BLUEPRINT.md` chỉ là execution note non-normative và không
được dùng để thay đổi semantics.

Các ý tưởng có giá trị được giữ lại:
- Work Unit là đơn vị nhỏ, cố định để Runtime chia việc.
- Runtime sở hữu việc chia khối lượng huấn luyện; Node Agent không tham gia.
- StrictBSP vẫn yêu cầu đủ N/N Worker.
- Tổng lượng dữ liệu của một bước toàn cục giữ cố định.
- Worker có thể xử lý nhiều Work Unit rồi gửi một gradient duy nhất.
- Gradient toàn cục tiếp tục tổng hợp theo sample_count.
- Thứ tự dữ liệu phải xác định được từ seed + epoch.
- Dữ liệu phải được chuẩn bị/cached trước khi bước huấn luyện dùng đến.
- Checkpoint chỉ cần giữ trạng thái ảnh hưởng correctness; trạng thái ước lượng hiệu năng có thể đo lại.

## 2. Mục tiêu

DBS giải quyết tình trạng Worker nhanh phải chờ Worker chậm trong huấn luyện đồng bộ.

Hệ thống cần:
- đo hiệu năng thực tế của từng Worker trong epoch trước;
- giao nhiều Work Unit hơn cho Worker xử lý nhanh, ít hơn cho Worker xử lý chậm;
- giữ tổng số mẫu của mỗi bước toàn cục không đổi;
- giữ StrictBSP, Parameter Server và cập nhật mô hình phía Runtime không đổi semantics;
- không dự đoán hiệu năng từ tên CPU/GPU;
- không đưa Database, Backend hoặc Dataset Manager vào vòng gradient -> barrier -> update.

## 3. Kiến trúc tổng thể

Dataset Manager
  -> tạo Dataset Build bất biến
  -> physical batch hiện có được dùng làm Work Unit

Worker
  -> cache dữ liệu đã xác minh
  -> nhận danh sách Work Unit của bước
  -> tính từng Work Unit
  -> gộp gradient cục bộ theo số mẫu
  -> gửi đúng một contribution

Runtime
  -> BatchScheduler chọn tập Work Unit toàn cục
  -> WorkloadScheduler quyết định mỗi Worker nhận bao nhiêu Work Unit
  -> StrictBSP chờ N/N contribution
  -> GradientAggregator tổng hợp theo sample_count
  -> UpdateEngine cập nhật mô hình chuẩn
  -> checkpoint
  -> cuối epoch tính kế hoạch DBS cho epoch sau

DBS chỉ thay đổi "mỗi Worker làm bao nhiêu dữ liệu". DBS không thay đổi "khi nào một bước được phép cập nhật mô hình".

## 4. Những phần bắt buộc giữ nguyên

1. training_strategy vẫn là strict_bsp.
2. Tập Worker cố định trong một Attempt.
3. Runtime cấp worker_id/session_id.
4. Mỗi synchronized step dùng cùng input model version.
5. Mỗi Worker gửi đúng một logical gradient contribution cho một step.
6. Runtime chỉ update khi nhận đủ N/N contribution hợp lệ.
7. GradientAggregator tiếp tục weighted average theo sample_count.
8. Worker không gọi optimizer.step() cho canonical model.
9. PARAMETER_APPLIED N/N và checkpoint gate hiện tại tiếp tục giữ nguyên.
10. Gradient/parameter chỉ đi qua DTP/1.

Không tạo dbs_bsp và không tạo DbsStrictBSP.
### 4.1. Trạng thái hiện có — DBS không tạo state mới
DBS không thêm state mới vào Database, Attempt, WorkerSession hoặc StrictBSP. Giữ nguyên state machine hiện có trong codebase:
- Attempt/Coordinator: CREATED → WAITING_WORKERS → PROVISIONING → INITIALIZING → RUNNING → COMPLETING → COMPLETED. FAILED và ABORTED là trạng thái kết thúc.
- WorkerSession: CONNECTING → REGISTERING → PROVISIONING → SHARD_READY → MODEL_SYNCING → READY. DISCONNECTED và FAILED là trạng thái kết thúc.
- Step: COLLECTING_GRADIENTS → AGGREGATING → UPDATING → WAITING_PARAMETER_APPLIED → CHECKPOINTING → COMMITTED.
WorkloadPlan và thống kê theo epoch chỉ là state nội bộ trong bộ nhớ Runtime; không tạo enum/state mới trong Database và không đưa vào WorkerSession lifecycle.
### 4.2. Luồng chuẩn
Khởi động Attempt:
Worker đủ N/N → PROVISIONING → Runtime gửi DatasetAssignment → mỗi Worker cache và verify dữ liệu theo cache_scope → N/N SHARD_READY → MODEL_SYNCING → N/N READY → freeze membership → RUNNING.
Mỗi synchronized step:
1. WorkloadScheduler trả active plan đã được cố định cho epoch hiện tại.
2. BatchScheduler lấy đúng K Work Unit toàn cục tại RecoveryCursor hiện tại; tập K unit này chỉ phụ thuộc dataset, seed, epoch và batch ordinal, không phụ thuộc policy equal hay dbs.
3. BatchScheduler chia K Work Unit theo số lượng k_i trong active plan và Runtime gửi STEP_START(work_units[]) cho từng Worker.
4. Worker chỉ load đúng work_units[] đã nhận, tính gradient từng Work Unit và gộp theo sample_count thành đúng một contribution.
5. StrictBSP nhận đủ N/N contribution hợp lệ → GradientAggregator tổng hợp có trọng số → UpdateEngine cập nhật canonical model đúng một lần.
6. Runtime broadcast parameter mới → nhận đủ N/N PARAMETER_APPLIED → ghi checkpoint blocking.
7. Chỉ khi checkpoint thành công thì step chuyển COMMITTED, RecoveryCursor mới được advance và statistics của step mới được ghi cho DBS.
Tại ranh giới epoch, nếu policy là dbs và epoch vừa hoàn tất có statistics đầy đủ, Runtime tính WorkloadPlan cho epoch kế tiếp. WorkloadPlan được cố định suốt một epoch và không thay đổi giữa các step.
Khi schedule hết và step cuối đã COMMITTED, Attempt chuyển COMPLETING → COMPLETED.

## 5. Work Unit

### 5.1. Định nghĩa V1

Để tránh xây thêm định dạng dữ liệu không cần thiết, V1 dùng chính physical batch đã materialize trong Dataset Build làm Work Unit.

Một Work Unit được nhận diện bởi:

WorkUnitRef {
  shard_id
  batch_id
  sample_count
}

Work Unit phải bất biến và đã được kiểm tra hash theo Dataset Build hiện có.

Không tạo thêm storage chunk format, chunk index database hoặc một Dataset Manager pipeline mới chỉ để chạy DBS.

### 5.2. Kích thước Work Unit

Gọi:
- N: số Worker cố định của Attempt.
- U: số mẫu của một Work Unit; V1 lấy từ dataset.batch_size của Dataset Build.
- K: số Work Unit của một bước toàn cục.
- B = U x K: số mẫu mục tiêu của một bước toàn cục.

Điều kiện:
- với policy = equal: K >= N;
- với policy = dbs: K > N; nếu K = N thì ràng buộc mỗi Worker có ít nhất một Work Unit buộc k_i = 1 cho mọi Worker, nên DBS không còn khả năng thích ứng;
- Dataset Build phải có đủ Work Unit đầy đủ cho ít nhất một bước;
- Work Unit cuối có sample_count khác U không tham gia tập Work Unit thích ứng V1.

Nếu muốn giữ global batch tương đương cấu hình cũ nhưng có granularity nhỏ hơn, tạo Dataset Build với U nhỏ hơn và chọn K sao cho B không đổi.

## 6. Dataset provisioning V1

Thiết kế trước có hướng cache/prefetch theo khối. V1 chọn cách đơn giản hơn để tránh xây hệ thống prefetch nền phức tạp:

- trong PROVISIONING, Runtime gửi DatasetAssignment với cache_scope = "all_shards" cho Work Unit mode; mỗi Worker tải và xác minh toàn bộ shard của pinned Dataset Build trước khi báo SHARD_READY;
- ShardCache hiện có vẫn dùng để lưu/verify từng shard;
- thêm lớp DatasetCache để quản lý nhiều CachedShard;
- SHARD_READY giữ nguyên message/state hiện có; trong cache_scope = "all_shards", SHARD_READY có nghĩa toàn bộ artifact cần cho Dataset Build đã được cache và verify; không thêm state mới chỉ cho DBS;
- sau N/N SHARD_READY và model synchronization, các step chỉ đọc local cache;
- Dataset Manager không được gọi trong synchronized step.

Artifact origin được chốt trước RUNNING. Dataset Manager status/resolve trả
`artifact_base_url` và `manifest_uri`; Management Backend giữ descriptor này và
Runtime nhận nó qua control plane. Runtime phải kiểm tra `manifest_uri` cùng
origin và nằm an toàn dưới path của `artifact_base_url`, rồi derive
`root_manifest_path` tương đối để điền vào field đã có của `DatasetAssignment`.
Worker/Sh​ardDownloader dùng field đó để tải root manifest, rồi resolve mọi shard
manifest và batch path tương đối dưới cùng artifact origin. Không thêm field DTP
mới; `manifest.json` chỉ là legacy local path khi descriptor authoritative nói
rõ như vậy. Path traversal, encoded traversal hoặc cross-origin URI phải bị từ
chối trước provisioning.

Cách này tốn dung lượng hơn nhưng phù hợp quy mô demo, đơn giản và bảo toàn ranh giới training path. Selective prefetch là tối ưu hóa về sau, không thuộc V1.

shard_id từ đây là định danh phân vùng lưu trữ, không còn đồng nghĩa worker_id trong lúc chia Work Unit.

## 7. Thuật toán DBS

Nguồn: Q. Ye et al., "DBS: Dynamic Batch Size for Distributed Deep Neural Network Training", arXiv:2007.11831.

### 7.1. Epoch đầu

Epoch đầu chia gần đều vì chưa có số đo lịch sử.

Kế hoạch Equal:
- mọi Worker có ít nhất 1 Work Unit;
- K Work Unit được chia cân bằng, tie-break theo worker_id.

### 7.2. Đo hiệu năng

Với Worker i ở epoch j:

d_i^j = samples_i^j / total_samples^j

t_i^j = tổng compute_ms của các step đã COMMITTED trong epoch

p_i^j = d_i^j / t_i^j

Chỉ dùng step đã vượt qua StrictBSP + PARAMETER_APPLIED + checkpoint và được COMMITTED.

compute_ms gồm:
- đọc Work Unit từ local verified cache;
- forward/loss/backward;
- gộp gradient cục bộ.

compute_ms không gồm:
- upload gradient;
- chờ barrier;
- nhận/apply parameter;
- HTTP tải dataset.

### 7.3. Tỉ lệ cho epoch sau

p_sum = sum(p_i)

r_i = p_i / p_sum

q_i = r_i x K

q_i là số Work Unit lý tưởng trước khi chuyển sang số nguyên.

### 7.4. Chuyển tỉ lệ DBS sang số Work Unit

Việc chuyển q_i sang số nguyên chỉ là bước lượng tử hóa do kiến trúc Work Unit, không phải một heuristic adaptive khác.

Ràng buộc:
- sum(k_i) = K;
- k_i >= 1;
- cố gắng gần q_i nhất;
- kết quả xác định được.

V1 dùng projection theo sai số bình phương:
1. khởi tạo mỗi Worker 1 Work Unit;
2. còn K-N Work Unit;
3. mỗi lần thêm 1 Work Unit cho Worker làm tăng tổng sai số (k_i - q_i)^2 ít nhất;
4. nếu bằng nhau, worker_id nhỏ hơn được chọn.

DBS quyết định q_i. Projection chỉ chuyển q_i thành nghiệm nguyên hợp lệ cho PBL4.

### 7.5. Ví dụ kiểm thử paper

Với U=1, K=B=64 và ideal batch sizes:

[13.7, 16.5, 19.6, 14.2]

kết quả phải là:

[14, 16, 20, 14]

Đây là golden test bắt buộc.

## 8. Lập lịch dữ liệu

Gọi M là số Work Unit hợp lệ của Dataset Build. BatchScheduler tạo một thứ tự toàn cục trên M Work Unit theo:

training_seed + epoch + shard_id + batch_id

V1 dùng cơ chế drop_last ở mức bước toàn cục: steps_per_epoch = floor(M / K). Mỗi bước lấy đúng K Work Unit; M mod K Work Unit cuối trong thứ tự của epoch đó không được lập lịch. Không tạo bước cuối nhỏ hơn K và không chuyển phần dư sang epoch sau.

WorkloadScheduler chỉ cho biết:

worker_id -> số Work Unit

BatchScheduler mới ánh xạ số lượng đó vào K Work Unit cụ thể.

Hai policy equal và dbs với cùng dataset, seed, epoch, step phải xử lý cùng một tập Work Unit toàn cục. Chúng chỉ khác cách chia tập đó cho Worker.

Điều này giúp so sánh công bằng và giữ training semantics.

## 9. Tính gradient trên Worker

ModelAdapter hiện trả gradient trung bình của một batch và sample_count.

Không cần thêm API mới vào PyTorchAdapter.

Nếu Worker nhận nhiều Work Unit u:

g_local = sum(n_u x g_u) / sum(n_u)

loss_local cũng gộp theo sample_count.

Worker gửi:
- một gradient duy nhất;
- sample_count = tổng số mẫu của mọi Work Unit đã xử lý;

- compute_ms.

Runtime tiếp tục tính:

g_global = sum(n_i x g_local_i) / sum(n_i)

Vì vậy cách chia Work Unit không làm thay đổi gradient trung bình của cùng tập mẫu toàn cục, ngoài sai khác số học dấu chấm động do thứ tự cộng.

## 10. Giao thức DTP/1

Không tạo DTP/2 chỉ cho feature này.

Giữ:
- 48-byte framing hiện tại;
- message catalogue hiện tại;
- tensor transfer META/CHUNK/END;
- protocol_version = 1.

Chỉ mở rộng payload ở nơi cần để Worker biết chính xác Work Unit phải xử lý. Không thêm field định danh/hash mới nếu Runtime đã giữ assignment canonical của step.

DatasetAssignment:
- giữ field hiện có;
- cache_scope là field OPTIONAL để tương thích wire cũ: vắng mặt được hiểu là "assigned_shard"; Work Unit mode MUST gửi "all_shards". Field này chỉ phục vụ provisioning, không thuộc thuật toán DBS.

ShardReady:
- giữ nguyên message/state SHARD_READY và không thêm field đếm mới;
- với cache_scope = "all_shards", Worker chỉ gửi SHARD_READY sau khi toàn bộ shard cần thiết đã cache và verify thành công.

StepStart:
- thêm work_units[];
- giữ shard_id/batch_id hiện có bằng Work Unit đầu tiên trong giai đoạn migration để tương thích với code cũ;

GradientMeta:
- không thêm trường định danh assignment mới; Runtime dùng OperationContext và BatchAssignment canonical đang mở;
- sample_count là tổng sample thực tế;
- compute_ms phải được gửi thật, không chỉ tồn tại trong schema.

Các field shard_id/batch_id cũ được giữ tạm và mang identity của Work Unit đầu tiên để tương thích/logging. Runtime tiếp tục validate attempt/session/operation/model version, batch_ordinal và sample_count theo assignment canonical; Worker phải load đúng toàn bộ work_units[] trước khi compute. Không dùng một hash do Worker echo lại để chứng minh Worker đã xử lý đúng dữ liệu.

## 11. Workload policy trong training contract

training_strategy vẫn strict_bsp.

Resolved contract thêm phần workload tối thiểu:

workload {
  policy: "equal" | "dbs"
  work_units_per_step: K
}

Operator chỉ nhập:
- workload_policy;
- work_units_per_step.

U luôn lấy từ dataset.batch_size đã có trong resolved contract; B = U × K được Runtime tính ra khi cần. Không lưu lặp work_unit_size hoặc global_batch_size trong workload contract.

Mặc định để giữ hành vi cũ:
- policy = equal;
- K = expected_workers.

Với dbs:
- K phải được khai báo;
- K > expected_workers.

## 12. Checkpoint và resume

Không tạo Checkpoint V2 chỉ để lưu số đo DBS.

Checkpoint V1 hiện đã giữ:
- model;
- model_version;
- contract_hash;
- dataset identity;
- RecoveryCursor(epoch, next_batch_ordinal).

workload policy và K nằm trong frozen contract nên đã được contract_hash bảo vệ.

Các số đo p_i, compute_ms tích lũy và phân phối hiện tại chỉ ảnh hưởng hiệu năng, không ảnh hưởng correctness của tập Work Unit toàn cục.

Quy tắc resume:
- không persist WorkloadPlan hoặc statistics DBS vào checkpoint;
- nếu RecoveryCursor ở đầu epoch (next_batch_ordinal = 0), epoch đó dùng Equal và thu statistics đầy đủ; epoch kế tiếp mới dùng DBS;
- nếu resume giữa epoch, phần còn lại của epoch hiện tại dùng Equal nhưng không thu statistics cho DBS; epoch đầy đủ kế tiếp tiếp tục dùng Equal để đo lại; DBS chỉ bật từ epoch sau đó;
- policy = equal luôn dùng Equal và không cần statistics DBS.

Nhờ đó không phải thay checkpoint schema và không dùng số đo thiếu nửa epoch.

Backend/control plane sở hữu việc resolve `checkpoint_id` thành trusted
descriptor tối thiểu gồm `checkpoint_id`, `source_attempt_id`, `model_sha256`
và `metadata_sha256`. Runtime không query Database và không trust filesystem
path từ command. Runtime derive checkpoint directory dưới configured
`checkpoint_root/source_attempt_id` bằng identity checkpoint canonical, từ chối
identity/path escape, verify cả hai digest, parse Checkpoint V1, rồi verify
`contract_hash`, dataset build/hash và parameter manifest/model layout trước khi
restore model, `model_version` và `RecoveryCursor`. Coordinator được tạo với
cursor đã restore và `WorkloadScheduler.reset_after_resume(cursor)` được gọi.

## 13. Trạng thái và lỗi

Worker disconnect hoặc heartbeat timeout:
- giữ semantics StrictBSP hiện tại;
- Attempt fail; không tự redistribute giữa step.

DBS stats không hợp lệ khi Runtime cần tính plan cho epoch kế tiếp:
- compute_ms <= 0, NaN/inf hoặc thiếu Worker -> Attempt FAILED trước khi mở epoch kế tiếp;
- không silent fallback sang Equal hoặc một công thức khác.

Dataset cache lỗi:
- lỗi trong provisioning -> Worker không được vào SHARD_READY và Attempt không được RUNNING;
- cache miss/corrupt sau khi đã RUNNING -> Worker FAILED; StrictBSP fixed membership mất thành viên nên Attempt FAILED.

K không hợp lệ hoặc không đủ Work Unit:
- equal yêu cầu K >= N; dbs yêu cầu K > N;
- nếu M < K hoặc steps_per_epoch = 0 thì validation fail trước RUNNING.

## 14. Những gì cố ý không làm

V1 không xây:
- dbs_bsp;
- DbsStrictBSP;
- DTP/2;
- Checkpoint V2;
- bảng DB riêng cho DBS;
- EMA/smoothing;
- db_min_batch;
- rebalance mỗi vài step;
- threshold gain;
- hardware score;
- network-aware cost formula;
- dynamic Work Unit size;
- storage chunk format mới;
- prefetch daemon phức tạp;
- auto elastic membership;
- WebUI dashboard mới như điều kiện bắt buộc;
- thay optimizer hoặc update policy.

## 15. Tiêu chí thiết kế hoàn thành

Thiết kế đạt khi:
- DBS nằm ở workload scheduling, không nằm trong synchronization strategy;
- Work Unit dùng được với artifact hiện tại;
- tổng K và global batch được giữ cố định;
- Worker nhiều Work Unit vẫn gửi một contribution;
- weighted local + global aggregation đúng toán học;
- StrictBSP N/N không đổi;
- Dataset Manager ra khỏi synchronized step;
- checkpoint V1 vẫn dùng được;
- resume có quy tắc đo lại rõ ràng;
- code có thể triển khai mà không phải tự phát minh thêm state, protocol version hoặc thuật toán.
