# Local E2E stabilization — 2026-10-13

**LOCAL E2E PASS; STABILITY PASS.** Phạm vi xác nhận: một máy Windows, ba
Node Agent độc lập, ba Worker do Agent supervisor tạo, mạng TCP DTP/1 thật,
Dataset Manager thật và PostgreSQL local tạm riêng.

Database cấu hình bình thường của dự án là **Aiven**, connection string nằm
trong `.env`. Đã xác nhận hostname thuộc Aiven và chạy `SELECT 1` với transaction
chỉ đọc thành công. Training E2E trong báo cáo này dùng database local riêng;
chưa tuyên bố training E2E trên Aiven. Không migration/purge dữ liệu Aiven.

## Git và môi trường

- Nhánh PBL4: `fix/local-e2e-stabilization`, nền
  `integration/runtime-node-agent-dataset`.
- Commit ứng dụng/harness được chạy hai lần với working tree sạch:
  `a395dd6dc2f4e3741ddd1aad4ad8c31a96ab83d8`.
- Commit local trước báo cáo:
  `813b957` SmallCNN/managed dispatch/compatibility/RESUME;
  `610a8a9` telemetry ordering/worker exit;
  `e6592ce` launcher/fault scenarios/hướng dẫn;
  `a395dd6` UI telemetry/model options.
- Windows 11 build 26200; Python 3.12.12; PyTorch 2.14.0+cpu; PostgreSQL 18.
- Dataset Manager local tại `.var/dataset-manager-local`, nhánh
  `fix/local-e2e-smoke`, commit `05340cbedd9c66ae777dd61d73de89c95d82ef70`.
- Dataset storage: LocalArtifactStore; không dùng HF upload/token.
- Console subprocess, HTTP và Agent WS trên loopback; TLS/WSS WAN chưa kiểm thử.
- PBL4 không push, không PR/merge. Dataset Manager cũng không push/deploy.

## Workload và bằng chứng cuối

`small_cnn` / `SMALL_CNN_V1`, 162 tham số FP32 (648 bytes); 192 ảnh
`synthetic_smoke_v1`, shape `3×32×32`; seed dữ liệu 42, partition/training seed
20260910; ba shard 64 mẫu; batch 16; bốn Step trong một epoch.

| Lượt chạy trên commit đã lưu | Job | Attempt | Kết quả |
|---|---|---|---|
| `agents-committed-1` | `job_17061848317a` | `atm_0dfe1dc79908` | COMPLETED, version 4, cleanup PASS |
| `agents-committed-2` | `job_65310dbfa64b` | `atm_d15476d27005` | COMPLETED, version 4, cleanup PASS |

Mỗi lượt xác nhận ba identity/enrollment riêng, ba Agent PID, ba Worker PID và
ba session Runtime cấp. Ví dụ lượt 1: Agent PID `17824, 22648, 22884`;
Worker PID `18512, 20024, 7684`. Runtime allocation/node identity khớp records
supervisor. Cả ba Worker nhận Dataset Assignment, tải/cache dữ liệu và tính
gradient; log Worker và API evidence được giữ.

Mỗi Step có đúng ba contribution, từng Worker `sample_count=16`, tổng 48.
Input model versions `0,1,2,3`, output `1,2,3,4`; 12 `parameter.applied` ACK.
Event order được kiểm tra: start → update → đủ ACK → checkpoint saved → Step
kế tiếp. Có bốn checkpoint COMPLETE; metadata canonical JSON, manifest identity,
payload size và SHA-256 đều được kiểm tra. Loss thật qua API theo Step 0..3:
`2.3445, 2.2566, 2.3735, 2.4359`; compute time từng Worker dương.

Parameter manifest hash:
`71884ba4174bfa32c18dcbcce244dad8d06a70b8e91ed580699674e38fcfcb54`.
Checkpoint cuối có payload SHA-256
`3387a906cbcab7f853471c4ada8a1da43ad8207535b98645a642157751e06975`.
Bốn payload checkpoint thay đổi qua bốn updates và khớp byte giữa hai lượt
chạy trên commit đã lưu.

Evidence: `artifacts/e2e/<run-id>/result.json`, `api-evidence.jsonl`,
`logs/` và `checkpoints/`. Worker logs/cache/identity ở `.var/e2e/<run-id>/`.
Các artifact được gitignore; không đưa identity/credential vào commit.

## Kiểm thử đã chạy

| Kiểm thử | Kết quả và bằng chứng |
|---|---|
| Full PBL4 regression với PostgreSQL test riêng | 689 PASS, 150 subtest PASS, 1 SKIP, exit 0 |
| Dataset Manager toàn bộ suite, interpreter có dependency HF sẵn | 62 PASS, exit 0; HF tests dùng fake client, không gọi HF thật |
| Frontend | typecheck PASS, 117 test PASS, build PASS; còn cảnh báo bundle >500 kB |
| Architecture / scaffold | cả hai script PASS, exit 0 |
| Smoke trên source commit sạch, chạy lặp | `agents-committed-1`, `agents-committed-2`: PASS |
| Một Worker chậm; độ trễ TCP thay đổi 100–300 ms | `agents-slow`: COMPLETED, đủ 3/3 mỗi update, 4 checkpoint, cleanup PASS |
| Worker chết giữa Attempt; RETRY | `agents-disconnect-retry`: Attempt đầu FAILED tại version 1, đúng một update 3/3; RETRY `atm_844a94873179` COMPLETED version 4, cleanup PASS |
| Restart Agent giữa training | `agents-restart`: Worker PID 1100/allocation được reconcile, không spawn trùng; COMPLETED 4 Step, cleanup PASS |
| RESUME checkpoint version 1 | `agents-recovery`: `atm_bd6e87e54bc9` chạy thêm 3 Step, version 4, 3 checkpoint hợp lệ; tham số khớp uninterrupted với tolerance `rtol=2e-5, atol=2e-6` từ test SmallCNN network hiện có |
| Checkpoint corrupt / missing | Hai RESUME Attempt FAILED trước update, model version 0; cleanup PASS; file checkpoint nguồn được phục hồi |
| Dataset/model không tương thích, RESUME sai dataset ID | Regression reject cả SmallCNN/ResNet và sai nested dataset ID |
| Enrollment/admission/cache/heartbeat | Các unit/integration hiện có được thực thi trong full suite; gồm token tamper/expiry/scope/duplicate, enroll và cache/hash failures |
| Ctrl+C thật trong terminal | `agents-interrupt`: KeyboardInterrupt, exit 1 và cleanup PASS; đây là kết quả mong đợi của test hủy |
| Đếm process còn lại sau test | Không còn process dùng state/checkpoint riêng của các lượt harness |

Full suite được gọi bằng
`.venv\Scripts\python.exe -m pytest tests src\pbl4\management_backend\tests -q --tb=short`,
với `DATABASE_URL` và `TEST_DATABASE_URL` cùng trỏ database local test riêng.
Suite có mutation DB; không dùng connection string Aiven của dự án để chạy
trực tiếp suite này. Một test cross-repo bị SKIP vì `DATASET_MANAGER_REPO_ROOT`
chưa đặt; harness đã kiểm chứng riêng pipeline thật qua Dataset Manager.

Theo taxonomy repository: unit, integration, distributed, failure và architecture
đều EXECUTED thông qua các suite/script hiện có; các ca distributed/failure nằm
trong `tests/integration/` và tests gốc. Benchmark SKIPPED vì ngoài phạm vi.

Full lint/format gate còn lỗi có sẵn: Ruff baseline 47 lỗi → hiện tại 43,
không có lỗi mới trong `src/` và `scripts/`; format baseline 9 file → 6 file.
Các helper/test mới được kiểm tra lint riêng. Không sửa lan sang các module
khác để làm sạch baseline.

## Những lỗi đã sửa

1. SmallCNN chưa đi xuyên catalog/manifest/managed command/Worker/Runtime.
   Thêm model identity và builder có seed; `START_WORKER.model_id` optional,
   mặc định vẫn ResNet-18. Model hash được cấu hình theo model.
2. Runtime tải shard bằng đường dẫn filesystem trong manifest của local store,
   gây HTTP 404. Dùng HTTP artifact route của standalone Dataset Manager như
   Worker downloader hiện có.
3. MCP dispatch mỗi event trên thread riêng, đảo thứ tự projection; snapshot
   polling còn nhảy cursor qua Step chưa project. Dùng một hàng xử lý semantic
   theo thứ tự và khóa projection; routine snapshot giữ cursor lịch sử.
4. DB operation của Worker status/ACK chặn event loop WSS, dẫn tới STOP timeout.
   Chuyển các operation đó sang thread ngoài event loop.
5. Loss/compute thật bị bỏ khi chuyển gradient metadata sang management event.
   Giữ chúng qua Contribution → event → worker_steps/API, không đưa tensor lên
   management plane.
6. Worker exit 0 bị coi là crash. Supervisor/client báo kết thúc sạch; forced
   STOP vẫn được ghi như explicit lifecycle action.
7. RETRY chạy ngay sau Coordinator FAILED gặp runner chưa kết thúc/port chưa
   giải phóng. Nhận terminal state từ Coordinator và join cleanup hữu hạn trước
   thay runner, ngoài Runtime state lock.
8. RESUME đọc dataset ID sai cấp. Validate theo
   `resolved_contract.dataset.dataset_build_id`.
9. Worker cache đặt dưới Agent state; bổ sung cache reuse bên dưới sửa tiếp
   allocation-specific root thành root ổn định theo Agent.
10. Hệ môi trường có httptools lỗi khi auto-select. Thêm lựa chọn `--http h11`
    cho Backend/Dataset Manager; harness dùng parser h11 có sẵn.
11. System UI có Node/IP/latency tự đặt; form model có lựa chọn và parameter
    count không từ API. Bỏ fallback giả, lấy model catalog và hiển thị dữ liệu
    chưa biết rõ ràng.

## Giới hạn còn lại

- Chưa chạy training E2E trên Aiven hoặc mạng WAN/TLS/WSS nhiều máy.
- Browser automation không khởi tạo được (`failed to write kernel assets`);
  Playwright không có sẵn. Chưa xác nhận UI bằng trình duyệt tự động; typecheck,
  API/frontend tests và build có bằng chứng PASS.
- Không kiểm thử upload/deployment Dataset Manager/Hugging Face. Dataset Manager
  sửa trong clone local riêng, đã commit `05340cb`; không cần deploy cho chế độ
  LocalArtifactStore đã kiểm thử. Bundle phục vụ chuyển máy nằm tại
  `artifacts/e2e/dataset-manager-smoke.bundle`.
- Lint/format baseline và cảnh báo bundle được ghi nhận ở trên, không cản local
  smoke. Không còn blocker đã biết cho chế độ local được mô tả.

Lệnh chạy lại và hướng dẫn cleanup: [LOCAL_E2E_SMOKE.md](LOCAL_E2E_SMOKE.md).

## Bổ sung Dataset Build & Cache Reuse

Các lượt dưới chạy với phần sửa cache trong working tree, trên nền `982c447`;
Dataset Manager không sửa thêm. Tất cả dùng Build
`4cdf29ea-48c0-41d6-bfc3-468c4d82873c`, manifest hash
`21f80f5c6cf956ccbbb54cb65630a652711ae9760c3f5ad966fb98fa4b6ce598`.
Mỗi lượt khởi động/dừng toàn bộ process; ba lượt sau dùng lại catalog local,
Node identity, physical artifact và cache của lượt đầu.

| Evidence tại `artifacts/e2e/` | Model | Cache reuse | HTTP GET batch | Worker download bytes |
|---|---|---|---|---|
| `cache-cold-1/result.json` | SmallCNN | 0/9, tải lần đầu | 36 | 7,132,059 |
| `cache-warm-2/result.json` | SmallCNN | 9/9 | 0 | 0 |
| `cache-model-resnet-3/result.json` | ResNet-18 GroupNorm | 9/9 | 0 | 0 |
| `cache-repair-4/result.json` | SmallCNN | 6/9; sửa đúng 3 entry hỏng | 2 | 401,293 |

Mỗi lượt COMPLETED, 4 Step, 3/3 contribution mỗi Step, 4 checkpoint được xác minh,
cleanup PASS. Chín entry = ba shard trên mỗi Worker; `all_shards` được giữ nguyên.
Warm/model-switch không POST tạo Dataset/Build; contract đóng băng đúng Build ID/hash.
Runtime/Backend vẫn đọc manifest phục vụ xác minh, không có Worker artifact download
trong hai lượt warm. Repair sửa một batch thiếu, một batch sai hash và một root
manifest hỏng; các batch tốt không tải lại, các shard tốt không bị thay thế.

Sau model-switch và repair, 70 file artifact/cache vẫn còn và fingerprint cả cây
trùng nhau: `79aa49923dce7273c943249eec2915374419f184c9b109de36074595d104a289`.
Cleanup mặc định không xóa Build, cache, artifact local hay HF.

Sửa production giới hạn ở cache root của supervisor, salvage batch đúng hash,
thay entry hỏng bằng publication đã xác minh có khóa OS và log từng shard.
Không đổi wire/domain/schema/scheduler hoặc xây hệ thống cache mới.
Harness bổ sung reuse persisted state, chọn model/storage và thu thập evidence.

Regression sau sửa: 696 PASS, 150 subtest PASS, 1 SKIP, exit 0.
Thêm test URL HF giả lập: lượt regression mở cross-repo đạt 697 PASS nhưng có
1 lỗi setup của cross-repo vì subprocess không tìm thấy package `dataset_manager`;
không coi lượt này PASS. Pipeline thật đã được xác minh qua bốn lượt Agent smoke.
Architecture/scaffold và Ruff scoped PASS. Chưa chạy training trên Aiven hoặc
upload/download HF thật; cấu hình dự án Aiven trong `.env` được giữ nguyên.
