# Kế Hoạch Kỹ Thuật: Tối Ưu Hóa Tốc Độ Ingestion Tại Management Backend

> **Mục tiêu**: Nâng thông lượng xử lý sự kiện (Event Ingestion) tại Management Backend từ **2–5 events/giây** lên **500+ events/giây**, triệt tiêu độ trễ hàng đợi trong RAM, chống mất dữ liệu khi Backend bị tắt đột ngột.
>
> **Quyết định kiến trúc chốt**:
> 1. **Thống nhất một hàm xử lý duy nhất (Single Source of Truth)**: 
>    - `handle_runtime_event(self, payload: dict[str, Any] | list[dict[str, Any]])` là nơi duy nhất tiếp nhận sự kiện (cả đơn lẻ lẫn danh sách batch), thực thi gom lô và chiếu dữ liệu trong đúng 1 transaction. Xóa bỏ hoàn toàn hàm wrapper trung gian.
> 2. **TCP đã đảm bảo thứ tự (FIFO) trên kết nối**: Xóa bỏ hoàn toàn logic kiểm tra tuần tự thừa thãi (như coi event đến out-of-order, vòng lặp query lại DB `get_event_by_seq` và việc chia 2 lần commit độc lập).
> 3. **Giữ nguyên logic kiểm tra Lỗ hổng (Gap Detection)**: Khi `seq > expected` (do Runtime drop vì đầy buffer 1024 hoặc rớt đoạn giữa khi reconnect), bật cờ `gap_fenced = True` và bắn WebSocket frame `GAP` để yêu cầu snapshot recovery.
> 4. **Giữ nguyên logic kiểm tra Lặp lại (Duplicate Detection)**: Khi `seq <= highest_contiguous_seq`, xác định là event gửi lặp lại (re-delivery sau reconnect), bỏ qua không chiếu lại vào bảng `steps` (đảm bảo tính Idempotency).
> 5. **Fast Path (Single Transaction Commit)**: Sử dụng trực tiếp `payload` trong RAM để ghi `events` và chiếu `steps` trong cùng 1 transaction, chỉ commit 1 lần duy nhất ra đĩa cho cả batch (1 đến 100 events).
> 6. **Gom lô thích ứng (Micro-batching Ingestion)**: `RealMcpClientPort` gom lô 50–100 events hoặc sau 20ms timeout để commit 1 lần duy nhất, tăng tốc độ ghi đĩa gấp 100 lần.

---

## 1. Bối Cảnh & Vấn Đề Kỹ Thuật

Trong quá trình huấn luyện phân tán (ví dụ 100 epochs mô hình `small_cnn` hoàn thành trong 5.6 giây), Runtime phát ra **845 telemetry events** qua socket MCP/1 tới Management Backend.

Tuy nhiên:
- Trên hệ điều hành Windows với PostgreSQL `fsync=on`, mỗi thao tác xác nhận giao dịch (`conn.commit()`) tiêu tốn khoảng **150ms – 250ms** để flush dữ liệu vật lý xuống đĩa.
- Kiến trúc cũ của Backend xử lý **từng sự kiện đơn lẻ (1-by-1)** và thực hiện **2 lần commit riêng biệt** cho mỗi sự kiện (1 commit vào `events`, 1 commit vào `steps`).
- Ngoài ra còn có câu lệnh query lại DB (`get_event_by_seq`) vốn hoàn toàn thừa thãi trong điều kiện bình thường vì dữ liệu đã có sẵn trong RAM và TCP luôn đảm bảo thứ tự gói tin.
- **Hậu quả**:
  - Backend phải thực hiện $845 \times 2 = 1.690$ lần commit, mất gần **4 phút** để xử lý xong.
  - Hàng trăm sự kiện bị kẹt lại trong hàng đợi RAM của Backend (`_dispatch_executor`).
  - Khi người dùng tắt Backend đột ngột, toàn bộ hàng đợi RAM này biến mất, dẫn đến mất dữ liệu hiển thị (ví dụ chỉ hiển thị đến Epoch 21).

---

## 2. Kiến Trúc Luồng Xử Lý Mới

```
[MCP/1 TCP Reader Thread]
           │ Nhận McpEnvelope (RUNTIME_EVENT)
           ▼
[Adaptive Queue (maxsize=10000)]
           │
           ▼ Draining theo lô: MIN(100 events, 20ms timeout)
[Batch Ingestion Worker Thread]
           │
           ▼ Gọi handle_runtime_event_batch(events)
┌────────────────────────────────────────────────────────────────────────┐
│ DUY NHẤT 1 POSTGRESQL TRANSACTION (conn)                              │
│                                                                        │
│   for event in events:                                                 │
│     if seq <= highest_contiguous_seq:                                  │
│         # 1. DUPLICATE CHECK -> Bỏ qua không chiếu lại vào steps       │
│         continue                                                       │
│                                                                        │
│     if seq > expected:                                                 │
│         # 2. GAP CHECK -> Rào chắn, đánh dấu snapshot_required         │
│         cursor.gap_fenced = True                                       │
│         mark_gap(expected, seq)                                        │
│         break                                                          │
│                                                                        │
│     if seq == expected:                                                │
│         # 3. FAST PATH (Liền mạch, dùng payload RAM):                  │
│         insert_event(conn, event)                                      │
│         project_runtime_event(conn, event_in_memory)                   │
│         cursor.highest_contiguous_seq = seq                            │
│                                                                        │
│   conn.commit()  <── 1 LẦN FLUSH ĐĨA DUY NHẤT CHO CẢ BATCH (1-100)    │
└────────────────────────────────────────────────────────────────────────┘
           │
           ▼ Sau khi commit bền vững:
[Broadcast WebSocket Hàng Loạt Ra WebUI]
```

---

## 3. Chi Tiết Các Thay Đổi Mã Nguồn

### 3.1. Phía Cổng Kết Nối MCP/1 (`src/pbl4/management_backend/gateways/mcp_port.py`)
- Thay thế `ThreadPoolExecutor(max_workers=1)` bằng `queue.Queue(maxsize=10000)` và luồng `_batch_drain_loop`.
- Gom tối đa `MAX_BATCH_SIZE = 100` sự kiện hoặc sau `FLUSH_INTERVAL = 20ms`.
- Chuyển tiếp cả lô sự kiện tới `RuntimeGateway.handle_runtime_event_batch`.

### 3.2. Phía Xử Lý Ingestion (`src/pbl4/management_backend/gateways/runtime_gateway.py`)
- **Hàm `handle_runtime_event(self, payload: dict[str, Any] | list[dict[str, Any]])` là Single Source of Truth**:
  - Tự động nhận diện `list` (batch) hoặc `dict` (đơn lẻ).
  - Mở 1 `with db.transaction() as conn:`.
  - Duyệt qua từng event trong lô:
    - Bỏ qua nếu `seq <= highest_contiguous_seq` (Duplicate).
    - Ngừng chiếu nếu `seq > expected` (Gap Detected $\rightarrow$ `gap_fenced = True`).
    - Thực hiện Fast Path: `ingest_runtime_event` + `_project_runtime_event` (bằng payload RAM) nếu `seq == expected`.
  - Commit 1 lần duy nhất cho toàn bộ lô.
  - Broadcast WebSocket sau khi commit DB thành công.
- **Xóa bỏ**: Vòng lặp `while True:` trong `record_event_seq` cùng các câu lệnh truy vấn ngược `event_repository.get_event_by_seq`.

---

## 4. Bảng So Sánh Hiệu Năng Trước & Sau Khi Tối Ưu

| Chỉ số | Trước khi tối ưu (Hiện tại) | Sau khi tối ưu (Đề xuất) | Cải thiện |
| :--- | :--- | :--- | :--- |
| **Số lần DB Commit cho 845 events** | 1.690 lần commit | ~9 – 17 lần commit | **Giảm ~99%** |
| **Thời gian nuốt 845 events** | ~240 – 260 giây (4 phút) | ~1.5 – 2.0 giây | **Nhanh hơn 130 lần** |
| **Tốc độ Ingestion trung bình** | ~2 – 4 events/giây | **500 – 1.000+ events/giây** | **Đạt mục tiêu đề ra** |
| **Số lượng event ứ đọng trong RAM** | 600 – 700 events khi train nhanh | Gần như 0 (tối đa < 50 events) | **Triệt tiêu nghẽn RAM** |
| **Rủi ro mất event khi tắt Backend** | **Rất cao** (mất toàn bộ hàng đợi RAM) | **Rất thấp** (chỉ mất tối đa 1 batch đang flush) | **An toàn dữ liệu** |
| **Tính nhất quán giữa `events` & `steps`** | Rời rạc (có thể lệch nếu crash giữa chừng) | Nguyên tử (Atomic) trong 1 Transaction | **Đảm bảo 100%** |
