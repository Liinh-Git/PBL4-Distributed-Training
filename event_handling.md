# Phân Tích Luồng Xử Lý Event Tại Management Backend & Các Điểm Nghẽn Hiệu Năng

Tài liệu này phân tích chi tiết mã nguồn hiện tại của **Management Backend** (`src/pbl4/management_backend/`) nhằm xác định nguyên nhân và các điểm chưa tối ưu khiến luồng xử lý Event bị chậm (high latency, processing backlog).

---

## 1. Kiến Trúc Tổng Quan Luồng Xử Lý Event

Hiện tại, Management Backend hỗ trợ 2 chế độ nhận và xử lý telemetry events từ `pbl4-runtime`:

```mermaid
flowchart TD
    subgraph Runtime ["pbl4-runtime"]
        RE[EventEmitter / Coordinator]
    end

    subgraph Transport ["Event Transport Layer"]
        M1["Mode 1 (Default): MCP/1 over TCP<br/>(REDIS_URL rỗng)"]
        M2["Mode 2: Redis Stream<br/>(REDIS_URL cấu hình)"]
    end

    subgraph Backend ["Management Backend"]
        subgraph Ingestion ["Ingestion Boundary"]
            TPE["McpPort Dispatcher<br/>(ThreadPoolExecutor max_workers=1)"]
            REC["RedisEventConsumer<br/>(Thread daemon: redis-events)"]
        end

        subgraph Core ["RuntimeGateway (RLock: _projection_lock)"]
            HRE["_handle_runtime_event()<br/>(Xử lý đơn lẻ từng event)"]
            HRES["handle_runtime_events()<br/>(Xử lý batch từ Redis)"]
            PRE["_project_runtime_event()<br/>(Chiếu vào DB: steps, worker_steps, checkpoints)"]
            SNAP["_port.request_state()<br/>(Sync TCP call lấy snapshot)"]
        end

        subgraph Persistence ["PostgreSQL (Aiven Cloud Remote DB)"]
            EV_T[("events table")]
            ST_T[("steps & worker_steps")]
            AT_T[("attempts table")]
        end

        subgraph Egress ["WebSocket / UI Hub"]
            WS["AttemptBroadcastHub<br/>(asyncio.run_coroutine_threadsafe)"]
        end
    end

    RE -->|"MCP TCP Message"| M1
    RE -->|"XADD stream"| M2
    M1 --> TPE
    M2 --> REC

    TPE -->|"1 event / lần"| HRE
    REC -->|"batch 20-100 events"| HRES

    HRE -->|"Tx 1: INSERT"| EV_T
    HRE -->|"Tx 2: SELECT redundant"| EV_T
    HRE -->|"Tx 2: Project"| PRE
    PRE -->|"INSERT/UPDATE"| ST_T
    PRE -->|"UPDATE cursor"| AT_T
    HRE -.->|"Nếu attempt/worker state changed"| SNAP
    SNAP -.->|"Blocking TCP roundtrip"| Runtime

    HRES -->|"Loop INSERT"| EV_T
    HRES -->|"Loop Project"| PRE

    HRE --> WS
    HRES --> WS
```

---

## 2. Chi Tiết Các Điểm Nghẽn Nghiêm Trọng Khiến Xử Lý Event Quá Lâu

---

### Điểm Nghẽn #1: Chế Độ MCP/1 Mặc Định Bị "Double-Transaction" & Query Thừa Thãi (Critical Bottleneck)

* **Vị trí code**:
  - `src/pbl4/management_backend/gateways/runtime_gateway.py`: hàm `_handle_runtime_event()` (dòng 999–1089) và hàm `record_event_seq()` (dòng 130–248).
* **Cơ chế hiện tại**:
  Khi cấu hình `.env` không bật Redis (`REDIS_URL=` đang để trống), Backend chạy qua MCP/1. Với **mỗi một event riêng lẻ**:
  1. **Transaction 1 (Ingest)**:
     ```python
     with db.transaction() as conn:
         self._restore_event_cursor(attempt_id, conn)
         ingest_result = event_ingest.ingest_runtime_event(conn, ...)
     ```
     Thực hiện câu lệnh `INSERT INTO events (...)` và `COMMIT`. Connection được trả về pool.
  2. **Transaction 2 (Projection)**:
     Ngay lập tức, mở tiếp connection thứ 2:
     ```python
     with db.get_connection() as conn:
         self.record_event_seq(attempt_id, seq, conn)
     ```
  3. **Truy vấn ngược thừa thãi (Redundant SELECT)**:
     Bên trong `record_event_seq()`, tại dòng 185:
     ```python
     next_ev = event_repository.get_event_by_seq(conn, attempt_id, next_seq)
     ```
     Backend thực hiện:
     ```sql
     SELECT * FROM events WHERE attempt_id = %s AND runtime_event_seq = %s
     ```
     > [!WARNING]
     > **Điểm phi lý**: Event này **vừa mới được insert vào DB cách đó vài mili-giây** và payload đầy đủ đang nằm sẵn trong bộ nhớ RAM (`payload`), nhưng code lại tạo thêm 1 round-trip mạng để SELECT ngược lại từ database trước khi chiếu (project).
  4. Thực hiện các câu lệnh `INSERT`/`UPDATE` chiếu vào bảng `steps`, `worker_steps`.
  5. Gọi `conn.commit()` kết thúc transaction 2.

* **Hậu quả**:
  Một event đơn lẻ tiêu tốn tối thiểu **2 lần mượn connection**, **2 lần COMMIT**, và **4–8 round-trips mạng tới PostgreSQL**.

---

### Điểm Nghẽn #2: Tác Động Khuếch Đại Của Remote Cloud Database (Aiven Cloud)

* **Vị trí cấu hình**: `.env` dòng 25:
  ```env
  DATABASE_URL=postgres://avnadmin:...@distributed-learning-nguyenlinh33662222-9396.g.aivencloud.com:11073/defaultdb?sslmode=require
  ```
* **Chi phí thực tế**:
  - Kết nối tới database cloud qua Internet có độ trễ Round-Trip Time (RTT) mạng trung bình từ **40ms đến 120ms** mỗi câu lệnh/commit.
  - Phân tích chi phí thời gian cho **MỘT Step huấn luyện** (trung bình 5–7 events: `step.started`, `gradient.accepted`, `model.updated`, `parameter.applied`, `step.committed`):

| Thao tác xử lý trong 1 step | Số lượng truy vấn mạng tới DB | Thời gian ước tính (RTT = 60ms) |
| :--- | :---: | :---: |
| `step.started` (Tx1 Ingest + Tx2 Readback + Step Insert + Step Update) | 5 round-trips | ~300 ms |
| `gradient.accepted` (Tx1 Ingest) | 2 round-trips | ~120 ms |
| `model.updated` (Tx1 Ingest + Tx2 Readback + 3x WorkerStep + Step Update) | 7 round-trips | ~420 ms |
| `parameter.applied` (Tx1 Ingest) | 2 round-trips | ~120 ms |
| `step.committed` (Tx1 Ingest + Tx2 Readback + Step Update) | 4 round-trips | ~240 ms |
| **Tổng cộng 1 Step** | **~20 round-trips SQL** | **~1.2 – 2.0 Giây** |

> [!CAUTION]
> Trong khi Workers và Runtime hoàn thành tính toán một batch chỉ trong **30ms – 100ms**, Backend lại mất **1,200ms – 2,000ms** chỉ để ghi telemetry vào PostgreSQL.
> Backend bị tụt lại phía sau (lag) hơn 1 giây cho mỗi step! Sau 100 steps, Backend sẽ chậm hơn Runtime từ **2 đến 3 phút**.

---

### Điểm Nghẽn #3: Dispatcher Đơn Luồng (`max_workers=1`) & Nghẽn Khóa Toàn Cục `_projection_lock`

* **Vị trí code**:
  - `src/pbl4/management_backend/gateways/mcp_port.py` (dòng 276–278):
    ```python
    self._dispatch_executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="pbl4-mcp-projection"
    )
    ```
  - `src/pbl4/management_backend/gateways/runtime_gateway.py` (dòng 83, 832, 847, 1425):
    ```python
    self._projection_lock = threading.RLock()
    ```
* **Cơ chế**:
  - `_dispatch_executor` chỉ có **duy nhất 1 worker thread**. Mọi MCP inbound messages (`RUNTIME_EVENT`, `STATE_SNAPSHOT`, `COMMAND_RESULT`) đều phải xếp hàng tuần tự vào hàng đợi của executor này.
  - Khi xử lý event, thread này giữ `_projection_lock` trong suốt thời gian thực hiện các transaction DB chậm chạp.
  - Đồng thời, tác vụ nền `_runtime_snapshot_loop` trong `app.py` chạy mỗi 2 giây một lần:
    ```python
    gateway.refresh_pretraining_snapshot()
    ```
    cũng yêu cầu chiếm giữ `_projection_lock`, gây tranh chấp tài nguyên (lock contention) với luồng event ingestion.

---

### Điểm Nghẽn #4: Blocking Synchronous Snapshot Request Qua Socket Ngay Trong Luồng Event

* **Vị trí code**:
  - `src/pbl4/management_backend/gateways/runtime_gateway.py` (dòng 1064–1082 và 1133–1142):
    ```python
    if (ingest_result.inserted or self._redis_events) and (
        (
            event_type == "attempt.state_changed"
            and event_payload.get("state") in {"RUNNING", "COMPLETED", "FAILED", "ABORTED"}
        )
        or event_type in {"worker.reconnected", "worker.disconnected"}
    ):
        snapshot = self._port.request_state()
        if snapshot and snapshot.get("active_attempt_id") == attempt_id:
            self.handle_state_snapshot(snapshot)
    ```
* **Cơ chế**:
  - Khi nhận được các event thay đổi trạng thái attempt hoặc worker, ngay giữa luồng event processing, Backend gửi một request TCP `GET_STATE` đồng bộ tới Runtime (`self._port.request_state()`) và **block chờ đợi câu trả lời**.
  - Sau khi nhận được snapshot, Backend lại mở thêm một transaction DB lớn (`handle_state_snapshot`), duyệt từng worker trong mảng, query `node_repository.get_node`, cập nhật session,...
  - Toàn bộ thao tác này diễn ra chặn đứng luồng xử lý event duy nhất (`_dispatch_executor`). Nếu Runtime đang bận xử lý tensor hoặc mạng bị nghẽn, event ingestion sẽ bị dừng hoàn toàn.

---

### Điểm Nghẽn #5: Thiếu Batch/Bulk SQL Trong Projection & N+1 Query Loop

* **Vị trí code**:
  - `src/pbl4/management_backend/gateways/runtime_gateway.py`:
    1. **`step.started` thừa 1 câu query**:
       ```python
       # Dòng 1243: insert step với state = 'CREATED'
       step_repository.create_step(...)
       # Dòng 1256: ngay lập tức update step sang 'COLLECTING_GRADIENTS'
       step_repository.update_step(conn, attempt_id, step_id, state="COLLECTING_GRADIENTS")
       ```
       Thay vì insert trực tiếp `state = 'COLLECTING_GRADIENTS'`, code lại thực hiện 2 câu lệnh SQL riêng biệt.
    2. **`model.updated` vòng lặp N+1 query**:
       ```python
       # Dòng 1260
       for item in details.get("contributions", []):
           step_repository.upsert_worker_step(...)
       ```
       Với $N$ workers (ví dụ 3 đến 8 workers), Backend thực hiện $N$ câu lệnh `INSERT ... ON CONFLICT DO UPDATE` tuần tự riêng biệt thay vì gom thành 1 lệnh batch/bulk insert duy nhất (`executemany` hoặc multi-row VALUES).
    3. **Redis Batch Mode vẫn insert tuần tự**:
       Trong `handle_runtime_events()` (khi bật Redis), dù đã nhận batch `payloads` danh sách 50–100 events, code vẫn dùng vòng lặp `for payload in payloads:` để gọi từng hàm `ingest_runtime_event` đơn lẻ (từng lệnh INSERT riêng).

---

### Điểm Nghẽn #6: Delay Cưỡng Bức 25ms Trong Redis Consumer (`max_wait`)

* **Vị trí code**:
  - `src/pbl4/management_backend/gateways/redis_events.py` (dòng 68–79):
    ```python
    if (
        not pending
        and 0 < len(entries) < self._batch_size
        and not self._stopping.wait(self._max_wait)
    ):
        more = self._client.xreadgroup(...)
    ```
* **Cơ chế**:
  - Nếu số event lấy ra từ Redis nhỏ hơn `batch_size` (100), consumer luôn dừng lại `max_wait = 0.025` (25ms) để chờ gom thêm event trước khi đưa vào ingest.
  - Khi luồng huấn luyện chạy ở tốc độ bình thường và phát sinh 1–2 event mỗi đợt, độ trễ 25ms này bị cộng dồn liên tục vào chu kỳ xử lý của từng batch.

---

### Điểm Nghẽn #7: Overhead WebSocket Broadcast Đồng Bộ Từng Event (`asyncio.run_coroutine_threadsafe`)

* **Vị trí code**:
  - `src/pbl4/management_backend/websocket.py` (dòng 78–90):
    ```python
    def broadcast_sync(self, attempt_id: str, message: dict[str, Any]) -> None:
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self.broadcast(attempt_id, message), self._loop)
    ```
* **Cơ chế**:
  - Sau mỗi event hoặc mỗi batch, Backend lặp qua từng event được project và gọi `broadcast_sync()`.
  - Mỗi cuộc gọi `run_coroutine_threadsafe` phải schedule một task vào asyncio event loop, cấp phát đối tượng Future và kích hoạt context switch giữa worker thread và main thread.
  - Hàng đợi của mỗi client WebSocket chỉ có kích thước `maxsize=256` (`websocket.py:47`). Khi Backend xử lý dồn một loạt events, hàng đợi client dễ bị tràn (`asyncio.QueueFull`), kích hoạt `OVERFLOW_INVALIDATE` làm đứt kết nối WebSocket. Sau đó client buộc phải kết nối lại và query lại DB (`list_events_after_seq`), gây thêm tải nặng cho PostgreSQL.

---

## 3. Bảng Tổng Hợp So Sánh Các Điểm Nghẽn

| STT | Vấn đề / Điểm nghẽn | Mức độ nghiêm trọng | Nguyên nhân gốc rễ | Hậu quả trực tiếp |
| :---: | :--- | :---: | :--- | :--- |
| **1** | Double-Transaction & Re-SELECT thừa | **CRITICAL** | Phân mảnh transaction giữa `_handle_runtime_event` và `record_event_seq`; SELECT lại event vừa insert. | Tăng gấp đôi số round-trip DB cho mỗi event (thêm 100–300ms/event). |
| **2** | Remote Cloud DB qua SSL | **CRITICAL** | Sử dụng Aiven Cloud PostgreSQL qua Internet (ping ~60–100ms) thay vì local DB hoặc low-latency pool. | Mọi thao tác tuần tự nhiều bước bị khuếch đại độ trễ gấp hàng chục lần. |
| **3** | Single-worker Executor | **HIGH** | `_dispatch_executor` giới hạn `max_workers=1` cho toàn bộ MCP inbound messages. | Tắc nghẽn hàng đợi (queue starvation); không có khả năng xử lý song song. |
| **4** | Blocking `request_state()` | **HIGH** | Gọi synchronous MCP socket call ngay giữa luồng event processing khi state thay đổi. | Đóng băng pipeline xử lý event trong khi chờ network socket I/O từ Runtime. |
| **5** | Thiếu Bulk/Batch Insert & N+1 Loop | **MEDIUM** | Dùng vòng lặp `for` insert từng worker contribution và từng event thay vì multi-row INSERT. | Thêm nhiều round-trips không cần thiết trong cùng 1 transaction. |
| **6** | `create_step` + `update_step` kép | **LOW** | `step.started` gọi `create_step` ('CREATED') rồi ngay lập tức gọi `update_step` ('COLLECTING_GRADIENTS'). | Tốn 2 câu lệnh SQL thay vì 1 câu duy nhất. |
| **7** | `broadcast_sync` từng event | **LOW** | Gọi `run_coroutine_threadsafe` lẻ tẻ cho từng event thay vì broadcast batch frame. | Tăng overhead context switch giữa thread và event loop. |

---

## 4. Các Giải Pháp Tối Ưu Hóa Đề Xuất

### Giải Pháp 1: Hợp nhất Transaction & Loại bỏ Re-SELECT trong `_handle_runtime_event` (Ưu tiên cao nhất)
- Gộp việc Ingest và Project vào **cùng 1 Database Transaction duy nhất**.
- Truyền trực tiếp `payload` đã có sẵn trong RAM vào `_project_runtime_event()` khi `seq == expected`, tuyệt đối **không thực hiện `SELECT * FROM events WHERE seq = ...`**.
- Tiết kiệm ngay lập tức 50% số round-trips DB và 50% chi phí kết nối pool.

### Giải Pháp 2: Bật Redis Streams hoặc chạy Local PostgreSQL cho Development/Demo
- Bật Redis Streams (`REDIS_URL=redis://...`) theo quy định của `AGENTS.md` (Redis Streams chỉ buffer event, không can thiệp critical path). Nhờ đó Backend có thể tận dụng consumer batch processing (`handle_runtime_events`).
- Hoặc chuyển `DATABASE_URL` về PostgreSQL nội bộ (localhost / docker) để giảm RTT mạng từ ~80ms xuống < 1ms.

### Giải Pháp 3: Tối ưu hóa SQL Projection (Bulk Insert)
- Trong `step.started`: Cho phép `create_step` nhận trực tiếp `state="COLLECTING_GRADIENTS"`, loại bỏ lệnh `update_step` ngay sau đó.
- Trong `model.updated`: Gom tất cả worker contributions vào 1 câu lệnh bulk upsert duy nhất:
  ```sql
  INSERT INTO worker_steps (...) VALUES (...), (...), (...)
  ON CONFLICT (...) DO UPDATE ...
  ```

### Giải Pháp 4: Tách `request_state()` khỏi luồng Event Critical Path
- Không gọi đồng bộ `snapshot = self._port.request_state()` chặn đứng luồng `_handle_runtime_event`.
- Đẩy yêu cầu làm mới snapshot sang một background task hoặc chỉ cập nhật trực tiếp snapshot in-memory dựa trên thông tin payload của event vừa nhận.

