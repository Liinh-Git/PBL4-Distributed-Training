# Local smoke qua ba Node Agent

Hệ thống của dự án dùng **Aiven PostgreSQL**, cấu hình `DATABASE_URL` trong `.env`.
Harness dưới đây tạo PostgreSQL local riêng cho từng lượt kiểm thử, để chạy lặp và
tiêm lỗi trên dữ liệu độc lập. Không cần thay đổi `.env` của dự án.

## Môi trường

- Windows; Python 3.12 và môi trường `.venv` của PBL4 có các dependency
  `worker`, `runtime`, `management-backend`, `node-agent`, pytest và Alembic.
- PostgreSQL local có `initdb.exe`, `postgres.exe`, `psql.exe`, `createdb.exe`.
  Harness tự tìm `C:\Program Files\PostgreSQL\18\bin`; có thể truyền `--postgres-bin`.
- Checkout Dataset Manager có commit `05340cb` trên nhánh `fix/local-e2e-smoke`.
  Trên máy này: `D:\PBL4\.var\dataset-manager-local`.
- Dependency chạy Dataset Manager local: FastAPI, uvicorn, numpy, pydantic,
  python-dotenv. Chế độ local không cần `HF_TOKEN`.
- UI tùy chọn: Node.js và dependency đã có trong `web/node_modules`.

Các lệnh chạy từ `D:\PBL4`, trên nhánh `fix/local-e2e-stabilization`:

```powershell
.venv\Scripts\python.exe scripts\e2e_agents.py --dataset-manager-repo .var\dataset-manager-local
```

Harness tự chọn port còn trống, tạo database local, chạy migration, khởi động
Dataset Manager, Runtime và Backend, enroll ba Agent bằng ba mã dùng một lần,
đợi ONLINE, tạo Dataset Build, tạo Job và start FRESH. Backend dispatch
`START_WORKER`; từng Agent supervisor tạo Worker subprocess và cache riêng.
Runtime cấp worker/session ID; cả ba Worker dùng TCP DTP/1, kể cả Worker-0.
Các process PyTorch/BLAS dùng một thread CPU.

Workload: `small_cnn` / `SMALL_CNN_V1`, 162 tham số, input `3×32×32`,
192 ảnh synthetic được ghi rõ `synthetic_smoke_v1`, seed dữ liệu 42, ba shard
64 mẫu, batch 16, một epoch / bốn synchronized steps. Training seed mặc định
20260910. Nguồn synthetic đi qua pipeline Dataset Manager thật: preprocessing,
partition, batch, manifest, hash, artifact publication và registration ACK từ
Backend. Profile CIFAR-10 và ResNet-18 vẫn được giữ.

## Kiểm thử stability và recovery

```powershell
.venv\Scripts\python.exe scripts\e2e_agents.py --dataset-manager-repo .var\dataset-manager-local --scenario slow
.venv\Scripts\python.exe scripts\e2e_agents.py --dataset-manager-repo .var\dataset-manager-local --scenario disconnect
.venv\Scripts\python.exe scripts\e2e_agents.py --dataset-manager-repo .var\dataset-manager-local --scenario agent-restart
.venv\Scripts\python.exe scripts\e2e_agents.py --dataset-manager-repo .var\dataset-manager-local --scenario recovery
```

- `slow`: relay TCP chỉ làm chậm kết nối đầu tiên, thay đổi 100–300 ms mỗi lượt
  chuyển tiếp; các kết nối còn lại giữ tốc độ bình thường. Vẫn yêu cầu 3/3.
- `disconnect`: giết Worker-0 sau checkpoint đầu, yêu cầu Attempt FAILED,
  kiểm tra không có partial update, đợi allocation terminal và chạy RETRY.
- `agent-restart`: dừng riêng Agent, giữ Worker sống, khởi động Agent cùng
  identity/state, xác nhận reconcile PID cũ rồi hoàn tất training.
- `recovery`: RESUME từ checkpoint version 1, kiểm tra ba bước còn lại và
  so tham số cuối với uninterrupted run. Tiếp theo, checkpoint hỏng/thiếu
  phải làm Attempt FAILED trước update; file nguồn được phục hồi sau test.

Mỗi lượt có timeout hữu hạn và exit code khác 0 khi thất bại hoặc bị ngắt.
Nhấn Ctrl+C để hủy; `finally` dọn cây process của harness, gồm các interpreter
con trên Windows. Agent tự ngắt control channel vẫn giữ Worker sống; harness
chịu trách nhiệm cleanup các process do chính lượt test tạo.

## Kết quả và log

`artifacts/e2e/<run-id>/result.json` ghi verdict, source commit, Node/Worker PID,
Job/Attempt, model version, Step metrics thật, checkpoint verification và cleanup.
`api-evidence.jsonl` lưu bằng chứng API; enrollment credential được che.
`logs/` chứa log PostgreSQL, Dataset Manager, Runtime, Backend, Agent.
Log Worker nằm trong `.var/e2e/<run-id>/agent-*/worker-*.log`.
Có thể đặt `--run-id ten-rieng`; thư mục trùng bị từ chối.

State, cache và database còn trên đĩa để kiểm tra; process đều được dừng.
Xóa thủ công **đúng thư mục lượt chạy** khi không cần giữ evidence. Thư mục
Agent chứa identity bí mật; không commit hoặc chia sẻ nguyên `.var`.

Dataset Manager được sửa trên clone local riêng, không push. Bản bundle để
chuyển sang máy khác nằm ở `artifacts/e2e/dataset-manager-smoke.bundle`:

```powershell
git clone artifacts/e2e/dataset-manager-smoke.bundle .var/dataset-manager-copy
```

Truyền checkout đó vào `--dataset-manager-repo`. Giữ bundle cùng evidence nếu
muốn tái hiện ngoài máy này; bundle là artifact local, không nằm trong Git PBL4.

## Quan sát UI tùy chọn

```powershell
.venv\Scripts\python.exe scripts\e2e_agents.py --dataset-manager-repo .var\dataset-manager-local --backend-port 18080 --hold-seconds 300
```

Trong PowerShell khác:

```powershell
cd D:\PBL4\web
$env:VITE_API_BASE_URL='http://127.0.0.1:18080'
$env:VITE_WS_BASE_URL='ws://127.0.0.1:18080'
npm run dev -- --host 127.0.0.1 --port 18081 --strictPort
```

Mở `http://127.0.0.1:18081`. `--hold-seconds` giữ dịch vụ sau smoke tối đa
600 giây rồi cleanup. Port cố định đang bận làm harness fail ngay. Model options
lấy từ Backend catalog; thông số chưa đo hiển thị “Chưa có dữ liệu”.

## Giới hạn

Localhost với độ trễ có kiểm soát chưa chứng minh hoạt động trên WAN.
Chưa kiểm thử packet loss WAN, NAT, TLS giữa nhiều máy hoặc E2E training dùng
Aiven. Kết nối Aiven trong `.env` đã được kiểm tra riêng bằng `SELECT 1` chỉ đọc.
Không cần quyền xóa dữ liệu Aiven/Hugging Face để chạy smoke này.
