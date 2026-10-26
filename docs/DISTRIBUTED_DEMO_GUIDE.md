# Chạy PBL4 qua WebUI

## Chuẩn bị một lần trên máy mới

Python 3.12 và Node.js cần có sẵn. Trong thư mục repository:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[worker,runtime,management-backend,node-agent]"
npm --prefix web ci
```

Linux/macOS dùng `source .venv/bin/activate`. Cấu hình `.env` theo `.env.example`, gồm `DATABASE_URL` của Aiven, `DATASET_MANAGER_URL` và `PBL4_WORKER_ADMISSION_SECRET`. Không thay connection string đang có. Với database mới hoàn toàn, chạy `python -m alembic upgrade head` một lần; database Aiven hiện tại đã migrate.

## Mỗi lần chạy trên một máy

```powershell
# Bước 1: Khởi động hạ tầng dịch vụ (Runtime, Backend, WebUI)
python services/start.py

# Bước 2: Khởi động các Node Agent (mỗi agent chạy trong một terminal riêng)
# Terminal 1:
python services/node-agent.py
# Terminal 2:
python services/node-agent.py
# Terminal 3:
python services/node-agent.py
```

Mở http://127.0.0.1:3000. Launcher `python services/start.py` chạy Runtime, Backend và Vite. Các Node Agent được chạy độc lập trên từng terminal bằng `python services/node-agent.py` (hệ thống tự động cấp phát demo-node-0, demo-node-1, demo-node-2 và khóa chống trùng lặp). Các cổng lấy từ `.env`; địa chỉ nội bộ tự dùng loopback để không phụ thuộc IP máy. Nếu cổng đang được dùng, dừng phiên service cũ trước; launcher không tự giết process khác.

Trên UI:

1. Kiểm tra Nodes có ba Node ONLINE; chỉ chọn Node của phiên đang dùng.
2. Tạo Job mới, chọn SmallCNN hoặc ResNet-18 GroupNorm và Dataset Build READY tương thích.
3. Để chạy nhanh, chọn **SmallCNN Demo - Synthetic 192 (Hugging Face)**, batch 16, một epoch, Equal K3 (hoặc DBS K6). Đây là dữ liệu tổng hợp kiểm tra pipeline, không phải CIFAR-10 thật.
4. Validate, chọn ba Node rồi Start. Theo dõi Steps, metrics và checkpoints trong Live Training.
5. Tạo Job tiếp theo với cùng Build để kiểm tra cache reuse; có thể đổi model mà không restart Runtime. Runtime chạy từng Attempt, không chạy hai Job đồng thời.

Không cần CLI tạo Job hoặc lệnh bật Worker. Manifest các model được suy ra từ model thật lúc bật service. Log ở `var/logs`; Ctrl+C dừng các process của launcher, giữ identity, artifact và cache. Không bấm dừng launcher khi muốn một Attempt tiếp tục chạy.

## Chạy service riêng hoặc nhiều máy

```powershell
python services/runtime.py --host 0.0.0.0
python services/backend.py --host 0.0.0.0
python services/node-agent.py --backend-url http://BACKEND_HOST:8000 --var-dir var/demo-node-0
# Hoặc chạy không cần --var-dir để tự động nhận slot khả dụng (demo-node-0, demo-node-1, ...)
```

Chạy mỗi lệnh trong terminal riêng. Cấu hình `RUNTIME_HOST`, `RUNTIME_ADVERTISED_HOST`, `RUNTIME_PORT`, `RUNTIME_MANAGEMENT_PORT` theo địa chỉ Runtime mà Backend/Workers truy cập được. Node máy khác chỉ cần dependencies Worker/Agent và URL Backend; không cần connection string Aiven. Dùng thư mục `--var-dir` riêng cho từng Agent để giữ cache/identity ổn định. WebUI riêng cần `VITE_API_BASE_URL` và `VITE_WS_BASE_URL` là origin Backend (không thêm `/api/v1` hoặc `/ws/v1`). CORS Backend phải cho phép origin WebUI.

Dataset Manager dùng service đã cấu hình; launcher không nhân bản hoặc xóa kho Hugging Face. Build READY đã có được dùng lại. Remote Dataset Manager hiện không hỗ trợ tạo nguồn synthetic mới; chọn Build synthetic READY đã đăng ký.

Các hướng dẫn harness/network cũ nằm trong `archive/`; không dùng harness để demo tương tác người dùng. Không chạy integration test bằng DATABASE_URL Aiven. Tests chỉ nhận TEST_DATABASE_URL trỏ PostgreSQL loopback cô lập.
