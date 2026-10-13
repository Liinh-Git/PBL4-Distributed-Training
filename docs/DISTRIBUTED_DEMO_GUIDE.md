# Demo Phase 2 — ba Node, Equal/DBS và cache reuse

## Môi trường

Dùng branch `fix/system-completion-network-e2e`. Windows local cần Python 3.12,
PostgreSQL binaries, Node.js và dependencies trong `.venv`/`web/node_modules`.
Network demo cần Linux/WSL2, quyền root để tạo namespace, `iproute2`, PostgreSQL,
Python 3.12 và virtualenv trên filesystem Linux. Không cần Docker/Kubernetes.

Checkout Dataset Manager dùng trong bằng chứng nằm ở
`D:\PBL4\.var\dataset-manager-local`, commit `8a9a65d`, bao gồm nguồn dữ liệu
`synthetic_smoke_v1` Phase 1. Không thay bằng upstream chưa chứa synthetic source.
Checkout `D:\Dataset-Manager` gốc không bị sửa. Có bundle local Phase 1/Phase 2
trong `artifacts/e2e/` để chuyển revision bằng Git; bundle Phase 2 cần base Phase 1
`05340cb` trước khi fetch branch `fix/system-completion-tests`.

Trên Ubuntu 24.04 mới, cài dependencies (cần mạng package index):

```bash
sudo apt-get update
sudo apt-get install -y python3.12-venv postgresql iproute2
sudo python3.12 -m venv /var/tmp/pbl4-phase2-env
cd /mnt/d/PBL4
sudo /var/tmp/pbl4-phase2-env/bin/pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
sudo /var/tmp/pbl4-phase2-env/bin/pip install -e '.[worker,runtime,management-backend,node-agent]' -e .var/dataset-manager-local
```

Venv đã dùng trên máy hiện tại là `/var/tmp/pbl4-phase2-env`. Dùng `/var/tmp` giúp
giữ venv/state qua lần khởi động WSL và tránh I/O cài package chậm trên `/mnt/d`.
Không dùng DATABASE_URL Aiven cho harness hoặc test migration. Harness network
tự tạo PostgreSQL riêng, local artifact store riêng và không nhận remote DB/DM.

## Chạy network cold/warm

Trong Ubuntu/WSL shell, ở `/mnt/d/PBL4`:

```bash
sudo /var/tmp/pbl4-phase2-env/bin/python scripts/e2e_network.py \
  --dataset-manager-repo .var/dataset-manager-local \
  --run-id demo-network-cold
```

Một lệnh tạo bridge/ba namespace, PostgreSQL riêng, DM, Runtime, Backend và ba
Agent. Agent tự enroll và spawn Worker qua START_WORKER; harness tạo Build 192
mẫu, chạy SmallCNN Equal K3 đến COMPLETED rồi thu bằng chứng/cleanup.
Không tự chạy cùng run-id hai lần. Chỉ chạy một cluster trên subnet demo tại
một thời điểm; chọn subnet riêng bằng `--control-ip` nếu `10.203.42.0/24` đã dùng.

Lượt warm dùng chính state của lần cold, không tạo Build mới:

```bash
sudo /var/tmp/pbl4-phase2-env/bin/python scripts/e2e_network.py \
  --dataset-manager-repo .var/dataset-manager-local \
  --reuse-runtime-data /var/tmp/pbl4-network-e2e/demo-network-cold \
  --scenario cache-reuse --run-id demo-network-warm
```

DBS K6, ba epoch, sáu synchronized steps trên cùng Build/cache:

```bash
sudo /var/tmp/pbl4-phase2-env/bin/python scripts/e2e_network.py \
  --dataset-manager-repo .var/dataset-manager-local \
  --reuse-runtime-data /var/tmp/pbl4-network-e2e/demo-network-cold \
  --scenario cache-reuse --workload-policy dbs \
  --work-units-per-step 6 --epochs 3 --run-id demo-network-dbs
```

Thêm `--agents-before-backend` vào một run mới để kiểm tra Agent retry trong lúc
Backend chưa sẵn sàng. Địa chỉ control là `10.203.42.1`, Nodes `.11/.12/.13`;
không dùng `127.0.0.1` hoặc `0.0.0.0` làm Runtime destination của Node khác.

State bền vững gồm PostgreSQL, artifacts và từng thư mục Agent/cache tại
`/var/tmp/pbl4-network-e2e/<cold-run-id>`. Checkpoint/log/result nằm trong
`artifacts/e2e/<run-id>`. Dùng lại state đòi hỏi giữ control IP và DM port vì
artifact URL đã lưu trong manifest; harness kiểm tra điều này.

## Demo bằng WebUI

Thêm `--hold-seconds 600 --backend-port 18080` vào cold hoặc warm command. Harness
chạy smoke trước, sau đó giữ các service và Node ONLINE tối đa 10 phút để thao tác.
Đợi log `holding services for UI inspection` rồi mở PowerShell ở `D:\PBL4\web`:

```powershell
$env:VITE_API_BASE_URL='http://127.0.0.1:18080'
$env:VITE_WS_BASE_URL='ws://127.0.0.1:18080'
npm run dev -- --port 18081
```

Mở `http://127.0.0.1:18081`. Với network demo, kết nối này cần WSL localhost
forwarding hoạt động. Backend bind 0.0.0.0 phục vụ demo trong môi trường tin cậy;
không public endpoint enrollment ra Internet.

1. Trang System: kiểm tra health và ba Node Agent ONLINE.
2. Trang Dataset/Build: dùng Build READY do harness đã tạo qua Dataset Manager
   thật. Khi chạy lại hoặc đổi model tương thích, chọn Build đó, không bấm rebuild.
3. New Training: chọn READY Build, model từ catalog (SmallCNN cho demo nhẹ),
   learning rate `0.01`, seed `20260910`, epochs `3`.
4. Chọn Equal hoặc DBS; nhập K `6`. N=3 từ Build, U=16, mỗi epoch có hai step.
   Equal K>=N; DBS K>N. Build phải có đủ Work Unit cho K.
5. Node selection có thể bỏ trống để scheduler chọn, hoặc chọn đúng ba Node ONLINE.
   Validate rồi Start. Node choice không thay frozen training contract.
6. Theo dõi Attempt, model version, loss thật, step và checkpoint. Kỳ vọng version
   6, sáu step COMMITTED và sáu checkpoint COMPLETE, Attempt COMPLETED.
7. Sau Attempt terminal, dùng Retry hoặc Resume từ checkpoint hợp lệ theo control
   hiện có. Không dùng checkpoint khác contract/dataset hoặc file hỏng.

Browser click/render chưa được automation xác minh trong phiên này. Kiểm chứng
tự động đã chạy qua API client TypeScript của frontend với Backend thật. Có thể
tái hiện trên Windows, kể cả khi WSL forwarding gặp lỗi:

```powershell
cd D:\PBL4
.venv\Scripts\python.exe scripts/e2e_agents.py --dataset-manager-repo .var/dataset-manager-local --run-id demo-api-cold --frontend-api-test
.venv\Scripts\python.exe scripts/e2e_agents.py --dataset-manager-repo .var/dataset-manager-local --reuse-runtime-data .var/e2e/demo-api-cold --scenario cache-reuse --run-id demo-api-warm --frontend-api-test
```

Các lệnh trên dùng ba Agent/process thật nhưng chung Windows network namespace;
không thay thế chứng cứ network namespace từ `e2e_network.py`. Harness API test
tạo thêm DBS K6 Job và chỉ poll Attempt API đến terminal, kiểm tra step/checkpoint.
Để giữ Windows cluster cho UI, thêm `--backend-port 18080 --hold-seconds 600`.

Kiểm tra RESUME giữa và cuối epoch tự động:

```powershell
.venv\Scripts\python.exe scripts/e2e_agents.py --dataset-manager-repo .var/dataset-manager-local --reuse-runtime-data .var/e2e/demo-api-cold --workload-policy dbs --work-units-per-step 6 --epochs 3 --scenario workload-recovery --run-id demo-resume
```

Đổi model trên cache cũ:

```powershell
.venv\Scripts\python.exe scripts/e2e_agents.py --dataset-manager-repo .var/dataset-manager-local --reuse-runtime-data .var/e2e/demo-api-cold --model-id resnet18_groupnorm --heartbeat-timeout 120 --training-timeout 300 --scenario cache-reuse --run-id demo-resnet
```

Không chạy ResNet đồng thời với full regression trên máy CPU hạn chế.

## Agent riêng, dừng và kiểm tra kết quả

Ngoài harness, mỗi Node chạy một lần (dùng backend URL Node truy cập được):

```bash
pbl4-agent start --backend-url http://10.203.42.1:18080 --var-dir /var/tmp/pbl4-agent-demo
pbl4-agent status --var-dir /var/tmp/pbl4-agent-demo
```

Identity được giữ trong var-dir; restart dùng lại identity. Không sao chép cùng
identity cho nhiều Node, không xóa identity để né revoke. Backend chưa lên thì
Agent retry lỗi kết nối. HTTP rejection/revoked identity cần kiểm tra cấu hình,
không tự cấp identity mới. Không cần enrollment code.

Harness tự dừng khi hoàn tất hoặc hết hold; Ctrl+C chạy cleanup trong finally.
Vite dừng bằng Ctrl+C ở terminal riêng. Không dùng `wsl --shutdown` hoặc kill toàn
bộ Python/PostgreSQL để cleanup demo. Không xóa state/cache/artifact khi chỉ muốn
restart. Reset dữ liệu cần yêu cầu riêng với phạm vi thư mục đã kiểm tra.

Đọc `artifacts/e2e/<run-id>/result.json`: `verdict`, `cleanup`, `network_cleanup`
(network run), source SHA/dirty flag, topology, Node/Worker IDs, Build/hash,
model, workload, assignments, checkpoint và cache. Warm run kỳ vọng 9 shard
reused, `worker_bytes_downloaded=0`, `artifact_batch_http_requests=0`.
Manifest HTTP metadata vẫn có thể xuất hiện để kiểm tra identity.

`api-evidence.jsonl` và `logs/` giúp đối chiếu request/event. Không chia sẻ thư mục
Agent identity hay `.env`. Checkpoint nguồn và artifact/cache được giữ sau cleanup.

## Lỗi thường gặp và bước tiếp theo

- Node OFFLINE/busy hoặc chọn thiếu/trùng Node: đợi ONLINE, hết allocation cũ và
  chọn đúng N Node; không giảm N để vượt barrier.
- Unsupported/missing model: sửa requested contract hoặc START_WORKER producer;
  managed Worker không tự chuyển sang ResNet.
- K không hợp lệ: Equal >=N, DBS >N và đủ Work Unit; K không phải local optimizer
  step. Với Build 192 mẫu/U16, có 12 Work Unit/epoch.
- Cross-repo import lỗi: dùng đúng checkout chứa `dataset_manager`, dependencies
  đã cài, `DATASET_MANAGER_REPO_ROOT` khi chạy regression. Smoke fixture thiết lập
  PYTHONPATH, port và store riêng cho subprocess.
- Windows pytest temp denied: đặt TEMP/TMP vào thư mục test writable trong workspace.
- ResNet heartbeat timeout dưới tải CPU: dừng test nặng khác, dùng allowance120s;
  không kết luận cache/model sai chỉ từ timeout.
- Namespace permission: chạy Linux root; xác minh `ip`, `pg_config`, `runuser`.
- WSL relay/E_UNEXPECTED: lỗi môi trường WSL đã gặp sau network tests; kiểm tra
  WSL từ terminal. Chỉ restart WSL khi người vận hành đã lưu công việc; agent
  không tự shutdown VM. Windows API demo vẫn là lựa chọn kiểm tra local riêng.
- HF: demo này dùng local storage; live HF cần token/origin/deployment được cấu
  hình riêng và kiểm thử upload/download. Không tự deploy checkout local.

Để chuyển sang LAN thật: đặt Backend/Runtime/DM advertised URL truy cập được từ
mọi máy, mở đúng port trong mạng tin cậy, cài cùng model/manifest/dependencies,
dùng cache/identity riêng từng Node, rồi chạy lại Equal/DBS/cold/warm/recovery.
Aiven chỉ được dùng khi đã xác định database/schema và được phép ghi; harness
hiện tại tiếp tục dùng DB test riêng. WAN cần đánh giá TLS, firewall và bảo mật
enrollment trong một nhiệm vụ riêng; Phase 2 không có bằng chứng WAN PASS.
