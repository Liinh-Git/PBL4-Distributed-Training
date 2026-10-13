# Phase 2 — System Completion & Distributed E2E

Ngày kiểm chứng: 2026-10-13. Branch: `fix/system-completion-network-e2e`, kế thừa
Phase 1 `1097edfc5965e57edb57431b4d101a44d75bd090`.

**Cập nhật sau báo cáo Phase 2:** theo yêu cầu xử lý dữ liệu riêng, đã tạo Build
SmallCNN trên Hugging Face, đăng ký READY vào Aiven và kiểm tra cache local thật.
Xem [DATASET_READINESS_REPORT.md](DATASET_READINESS_REPORT.md). Các giới hạn HF
dưới đây mô tả thời điểm kết thúc Phase 2; training E2E trên Aiven vẫn chưa chạy.

## Kết luận và phạm vi

**Hoàn thành:** workflow Dataset Manager → READY Build → Job/Attempt → Node
allocation → Worker thật → StrictBSP/SGD → checkpoint → COMPLETED; auto-enrollment;
model identity rõ ràng; Equal/DBS với K; cache reuse; E2E qua ba Linux network
namespace; hồi quy và kiểm tra bằng API frontend thật.

**Hoàn thành có giới hạn:** giao diện đã bổ sung model catalog, Node selection và
K cho cả Equal/DBS, typecheck/test/build PASS. API client TypeScript đã tạo và chạy
Job thật; chưa xác minh thao tác click/render bằng browser. Mạng đã kiểm chứng là
bridge trên WSL2, chưa phải ba máy vật lý hay WAN.

**Chưa hoàn thành:** browser acceptance thực tế và lần demo tương tác có người dùng.
Không còn blocker chức năng được quan sát trong các workflow PASS bên dưới.
Không tuyên bố hệ thống production-ready hoặc DBS nhanh hơn Equal.

**Chưa kiểm thử:** training E2E với Aiven; upload/download Hugging Face thật;
LAN nhiều máy, WAN, NAT, GPU và benchmark/convergence quy mô lớn.

## Thay đổi và lý do

| Nhóm file | Thay đổi và mục đích |
|---|---|
| `node_agent/{entrypoint,enrollment,config,client}.py` | Áp dụng hướng PR #12: `start` tự enroll nếu chưa có identity, lưu và dùng lại identity; retry lỗi kết nối khi Backend chưa lên; bỏ vòng telemetry phần cứng định kỳ. Giữ heartbeat, static capabilities và Worker status. |
| Backend `api/nodes.py`, `schemas/node.py`, `services/node_enrollment_service.py`, `app.py` | Bỏ quy trình cấp/kiểm tra enrollment code khỏi API hoạt động. Không thêm join secret hay approval UI. Bảng/migration lịch sử không bị xóa. |
| `agent_protocol/messages.py`, Backend allocation, Worker entrypoint/process | Managed START_WORKER bắt buộc model_id hợp lệ; mất trường bị từ chối thay vì âm thầm chạy ResNet. Unmanaged legacy vẫn giữ mặc định tương thích. |
| Backend `api/jobs.py`, `schemas/job.py`, `services/attempt_service.py` | Start hỗ trợ Node IDs tùy chọn, kiểm tra đúng N Node ONLINE khác nhau và capacity; Node selection là execution data, không sửa frozen contract. Idempotency tính cả lựa chọn Node. |
| `web/src/pages/{NewTrainingFlowPage,SystemPage}.tsx`, API/types | Model lấy từ catalog; hiện Node thật và lựa chọn Node tùy chọn; K được gửi cho cả Equal và DBS. |
| Backend `gateways/runtime_gateway.py` | Tự lấy snapshot lifecycle qua MCP hiện có để thiết lập Worker session trước event model.updated; giữ model version projection tăng đơn điệu. Client không phải gọi thêm runtime snapshot mới thấy training hoàn tất. |
| `worker/shard_cache.py` | Đọc/kiểm tra cache dùng cùng publication lock với sửa cache; tránh Windows WinError 5 khi reader giữ file trong lúc writer thay cache hỏng. Giữ cơ chế cache hiện có. |
| Runtime `coordinator.py` | Event step.started ghi các Work Unit thực tế để kiểm chứng assignment; không đổi scheduler/SGD/DBS. |
| `scripts/e2e_agents.py`, `e2e_local.py`, `e2e_network.py` | Harness thật, cấu hình K/epoch/policy, resume ở hai vị trí, stable state, Node choice, Agent-before-Backend và kiểm tra network namespace của Worker đang sống. |
| Tests Python/TypeScript | Numerical oracle, managed model, enrollment/reconnect, Node selection, projection, cache và API thật. Cross-repo test chỉ sửa environment/port/temp, không sửa production để che lỗi setup. |

PR #12 được đọc tại head `d1b427d`; áp dụng chọn lọc thay đổi từ `ca1e8de` và
hướng bỏ periodic telemetry. Không merge PR, không push. Auto-enrollment mở chỉ
phù hợp môi trường test tin cậy; không có thay đổi xác thực WAN.

Lỗi projection được phát hiện bằng client chỉ poll Attempt API: Worker đã hoàn
tất version 6 nhưng Backend kẹt RUNNING do FK `worker_steps.session_id` chưa có
`worker_sessions`. Harness cũ poll Runtime snapshot đã vô tình che lỗi này.
Sau sửa, client TypeScript tạo/validate/start Job và quan sát COMPLETED, 6 step
COMMITTED, version 6, 6 checkpoint COMPLETE mà không poll Runtime snapshot.

## Runtime correctness

Giữ `training_strategy=strict_bsp`, SGD, N/N membership, DTP/1 và checkpoint schema.
K là tổng Work Unit của synchronized step, không phải local optimizer steps.
Với N=3, U=16, K=6: B=96; 192 mẫu tạo 12 Work Unit, hai step mỗi epoch.

Numerical oracle chạy TrainingLoop, weighted contribution, GradientAggregator
và UpdateEngine với `[2,2,2]`, `[1,2,3]`, `[1,1,4]`. Gradient toàn cục và tham số
sau `theta - learning_rate * gradient` khớp oracle; Worker không cập nhật canonical
model, một canonical update/step. Tests hiện có tiếp tục kiểm tra duplicate,
session/version/operation mismatch, NaN/Inf, N/N ACK, checkpoint durability,
K validation và RecoveryCursor.

Đối chiếu DBS với `docs/DBS_DESIGN.md`, `docs/DBS_IMPLEMENTATION_PLAN.md` và
[paper đã chọn](https://arxiv.org/abs/2007.11831): epoch đầu Equal, thống kê từ
COMMITTED steps của epoch đầy đủ, kế hoạch đổi ở boundary, integer projection
giữ tổng K và ít nhất một unit/Worker. Golden tests/thống kê không đồng đều được
giữ. E2E ba CPU tương tự cho `[2,2,2]` ở các epoch sau là kết quả hợp lệ.

Equal K6 và DBS K6 đều COMPLETED, 3 epoch/6 step/version 6/6 checkpoint. So sánh
artifact xác nhận cùng Build/hash và cùng tập Work Unit toàn cục ở cả 6 step:
`artifacts/e2e/phase2-final-verification/equal-dbs-comparison.json`.

DBS RESUME từ checkpoint version 1 (giữa epoch) và version 2 (boundary) hoàn
tất tương ứng 5 và 4 step còn lại. Work Unit remainder/RecoveryCursor và tham số
cuối khớp uninterrupted run trong tolerance đã có; checkpoint nguồn giữ nguyên.
Không dùng partial epoch statistics như một epoch đầy đủ. RETRY/fault cases
Phase 1 được tái sử dụng và chạy lại qua full regression; không tuyên bố mọi
fault case đã được lặp lại riêng trong namespace.

## Evidence E2E

Mỗi đường dẫn dưới đây nằm trong `artifacts/e2e/<run-id>/result.json`, kèm
`logs/`, `api-evidence.jsonl`, parameter manifest và checkpoint tương ứng.

| Run ID | Kết quả |
|---|---|
| `phase2-baseline` | Phase 1 baseline tại 1097edf: 3 Agent/Worker thật, SmallCNN, 4 step, cleanup PASS. |
| `phase2-local-equal-k6` | Equal, 3 epoch, 6 step/version 6, 9 shard warm. |
| `phase2-local-dbs-k6` | DBS, 3 epoch, 6 step/version 6, kế hoạch epoch 1/2 hợp lệ. |
| `phase2-dbs-resume` | Fresh + hai RESUME giữa/boundary epoch, tham số và unit sequence khớp. |
| `phase2-network-cold-k3-v2` | 3 namespace, cold cache, Equal K3, 4 step, cleanup process/network PASS. |
| `phase2-network-warm-k3` | Restart, cùng Build/hash/Node identity, 9/9 shard reuse, 0 byte và 0 HTTP batch download. |
| `phase2-network-dbs-k6` | Cùng Build, DBS K6, 3 epoch, 6 step/version 6, warm cache và cleanup PASS. |
| `phase2-network-agent-first` | Agent lên trước Backend, connection retry rồi auto-enroll, chọn Node và training PASS. |
| `phase2-resnet-explicit-v2` | ResNet-18 GroupNorm thật, 4 step/version 4, cùng dataset SmallCNN, 9/9 shard reuse, 0 batch download. |
| `phase2-frontend-api-final` | API clients frontend thật: tạo/validate/start DBS K6, chọn 3 Node, COMPLETED và 6 checkpoint. |
| `phase2-committed-workflow` | Kiểm tra cuối trên implementation commit 740467c: SmallCNN warm + workflow frontend API thật. |

Topology network: control `10.203.42.1`, Nodes `.11`, `.12`, `.13`; Agent qua
WebSocket/HTTP tới Backend, Worker con qua DTP/TCP tới Runtime. Runtime và DM
advertise bridge IP; `0.0.0.0` chỉ là bind address. Harness quan sát `/proc/PID/ns/net`
của Worker thật, đối chiếu với namespace Agent, ghi inode/PID/IP/Node ID vào
result. Không dùng mock Worker hay localhost làm đích xuyên namespace.

Cold network Build `3f7d131f-8cf0-43e0-ac9d-697dd9483296` được giữ trong
`/var/tmp/pbl4-network-e2e/phase2-network-cold-k3-v2`. Windows local dùng Build
`e09b0929-27c8-43f3-a8d5-a740b26a6b85`, hash
`d9303298644afaec439ad9a0f5d33d7774ba50aed40536e11742cacd27169874` tại
`.var/e2e/phase2-baseline`. Tạo Build riêng cho môi trường Linux mới là có chủ ý;
warm run và đổi model không rebuild. Manifest metadata vẫn có thể được kiểm tra
qua HTTP; khẳng định zero-download ở đây là batch artifact payload.

Cache identity vẫn là Build ID + manifest hash + shard ID; kiểm tra hash/batch,
sửa chọn lọc trước SHARD_READY, giữ `all_shards`. Cleanup giữ artifacts, cache,
Agent identities, private database và checkpoint; chỉ dừng owned process và
gỡ owned namespace/bridge. Không purge Hugging Face hay dữ liệu shared.

## Regression và giới hạn môi trường

| Gate | Kết quả |
|---|---|
| PBL4 full Python suite | 701 passed, 150 subtests passed, 6 dependency/config warnings, không skip; private PostgreSQL mới. |
| Dataset Manager suite | 62 passed, 2 dependency warnings; gồm HF adapter tests bằng fixtures/mocks, không live HF. |
| Frontend tests | 117 passed, một live test skip mặc định khi thiếu endpoint; live test chạy riêng với Backend thật PASS. |
| Frontend typecheck/build | PASS; cảnh báo bundle >500 kB còn tồn tại, không phải lỗi build. |
| Architecture/scaffold | PASS. |
| Ruff | Baseline lint debt tồn tại; không dọn hàng loạt. Các lỗi mới từ thay đổi đã được xử lý. |
| Browser automation | Không chạy được: CUA lỗi ghi kernel assets (os error 3); không đánh dấu UI browser E2E PASS. |

Log hồi quy được sao chép vào `artifacts/e2e/phase2-final-verification/`.
Lần gọi scaffold đầu dùng nhầm tên script; chạy đúng `scripts/verify_scaffold.py`
sau đó PASS. Dataset Manager lần đầu lỗi quyền temp Windows, chạy lại với TEMP/TMP
trong workspace đạt 62/62. Không sửa production vì lỗi temp này.

Các failed run được giữ: network cold đầu lỗi Git safe.directory cho checkout
DM; sửa process-scoped Git config rồi chạy v2 PASS. Frontend API trước sửa
projection timeout dù Worker hoàn tất; bằng chứng PASS là các run sau sửa.
ResNet lần đầu cùng lúc full regression dùng heartbeat 15s bị FAILED; chạy riêng
với 120s đạt PASS. Điều này không chứng minh ResNet ổn định dưới tải host tùy ý.

Sau những network run PASS, một lần mở thêm WSL để giữ UI demo bị lỗi localhost
relay/E_UNEXPECTED trước khi ứng dụng chạy. Không tự shutdown toàn bộ WSL của
người dùng. Những network result trước đó vẫn hợp lệ; môi trường WSL cần hoạt
động bình thường để tái hiện. API frontend cuối chạy trên Windows localhost,
không được trình bày như browser/API acceptance trong namespace.

Evidence trước implementation commit ghi `source_commit=1097edf` và
`working_tree_dirty=true`, phản ánh đúng thời điểm chạy. Run
`phase2-committed-workflow` gắn với commit implementation sạch; commit tài liệu
sau đó không thay production code. Không gán ngược SHA cuối cho network run cũ.

## Git và remote

- PBL4 local implementation commit: `740467c` — managed workflow, tests và network harness.
- Commit tài liệu: commit tiếp theo trên cùng branch, xem `git log -2 --oneline`.
- Dataset Manager checkout `.var/dataset-manager-local`, branch
  `fix/system-completion-tests`, commit `8a9a65d`, kế thừa `05340cb` Phase 1.
  Phase 2 chỉ sửa smoke server test helper để nhận port/store tách biệt và h11.
  Bundle local: `artifacts/e2e/dataset-manager-phase2.bundle`.
- Không push hai repo, không tạo/merge PR, không sửa governance.
- Không đổi `.env` Aiven, không migration/destructive test vào Aiven.
  Phase 1 chỉ có kiểm tra kết nối readonly; chưa có remote training evidence.
- HF deployment chưa thực hiện. Muốn chuyển remote cần đưa đúng DM revision lên
  môi trường đích theo yêu cầu riêng, cấu hình storage/token/origin và chạy live
  build/download/cache checks; không đưa token vào log hoặc commit.

Hướng dẫn vận hành và các bước chuyển lên LAN/WAN nằm trong
[DISTRIBUTED_DEMO_GUIDE.md](DISTRIBUTED_DEMO_GUIDE.md).
