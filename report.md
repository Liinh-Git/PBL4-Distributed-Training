# BÁO CÁO XÁC MINH QUẢN LÝ THỜI GIAN SỐNG VÀ HOẠT ĐỘNG (LAST_SEEN) TRONG DTP/1

**Dự án**: PBL4 Distributed Training — Parameter Server Architecture  
**Giao thức kiểm tra**: DTP/1 (Distributed Training Protocol Version 1)  
**Tiêu chí xác minh**: Quản lý thời gian sống và hoạt động (`last_seen`). `last_seen` được cập nhật khi nhận `HEARTBEAT` hoặc bất kỳ tin nhắn DTP hợp lệ nào từ connection.  
**Trạng thái**: **ĐẠT (PASSED)**

---

## 1. TỔNG QUAN THIẾT KẾ & ĐẶC TẢ KIẾN TRÚC

Theo tài liệu thiết kế chuẩn tắc DTP/1 và quyết định kiến trúc:
1. **Bản chất của quản lý thời gian sống (Liveness Management)**:
   - Trong huấn luyện phân tán, các tensor tham số và gradient có dung lượng lớn được phân mảnh thành nhiều chunk (`PARAMETER_CHUNK`, `GRADIENT_CHUNK`).
   - Giao thức DTP/1 nghiêm cấm việc xen kẽ tin nhắn `HEARTBEAT` vào giữa luồng truyền tải tensor trên cùng một kết nối (`transfer_lock` / No Interleaving Rule).
   - Do đó, để tránh việc một Worker đang tích cực truyền dữ liệu tensor lớn bị coi là đã chết (false positive timeout), **mọi khung truyền DTP hợp lệ (DTP Frame) nhận được từ kết nối đều là bằng chứng về hoạt động sống (activity progress)**.
2. **Quy tắc cập nhật `last_seen` và `last_heartbeat_at`**:
   - Khi Parameter Server nhận được tin nhắn `HEARTBEAT` (`0x0030`) hoặc **bất kỳ tin nhắn DTP hợp lệ nào** (`SHARD_READY`, `MODEL_MANIFEST`, `READY`, `GRADIENT_META`, `GRADIENT_CHUNK`, `GRADIENT_END`, `PARAMETER_APPLIED`):
     1. Ghi nhận mốc thời gian hoạt động cục bộ trên kết nối: `connection.last_seen = time.monotonic()`.
     2. Cập nhật mốc liveness vào bảng đăng ký phiên làm việc: `self.registry.heartbeat(worker_id, session_id, now)` để làm mới `WorkerSession.last_heartbeat_at`.
   - **Tối giản hóa phạm vi theo yêu cầu người dùng**:
     - Server không cần phản hồi `HEARTBEAT` (luồng liveness đi 1 chiều từ worker đến server).
     - Chưa cần cài đặt `worker.last_seen`, đảm bảo tuân thủ nguyên tắc "Simplicity First" (không sinh mã thừa).

---

## 2. BẰNG CHỨNG MÃ NGUỒN CÀI ĐẶT (CODE PROOF)

Hệ thống đã triển khai đầy đủ và chuẩn xác theo kế hoạch trong [src/pbl4/runtime/parameter_server.py](file:///d:/HKI%2026-27/PBL4/demo/src/pbl4/runtime/parameter_server.py):

---

### Bằng chứng 1: Đối tượng kết nối `_Connection` lưu trữ mốc thời gian `last_seen`

Trong file [src/pbl4/runtime/parameter_server.py:66-75](file:///d:/HKI%2026-27/PBL4/demo/src/pbl4/runtime/parameter_server.py#L66-L75):

```python
# Trích xuất từ src/pbl4/runtime/parameter_server.py:
@dataclass(slots=True)
class _Connection:
    sock: socket.socket
    session_id: int
    worker_id: int
    validator: ConnectionProtocolValidator
    assembler: TensorTransferAssembler
    sender: LogicalTransferSender
    last_seen: float = 0.0
```

Tại thời điểm kết nối TCP được xác thực qua bắt tay `HELLO` thành công, trường `last_seen` được khởi tạo bằng đồng hồ monotonic chuẩn tắc ([src/pbl4/runtime/parameter_server.py:182-195](file:///d:/HKI%2026-27/PBL4/demo/src/pbl4/runtime/parameter_server.py#L182-L195)):

```python
                connection = _Connection(
                    sock=sock,
                    session_id=session_id,
                    worker_id=registered.worker_id,
                    validator=validator,
                    assembler=TensorTransferAssembler(
                        self.manifest,
                        max_model_bytes=self.manifest.total_bytes,
                        max_tensor_chunk_bytes=self._max_chunk,
                    ),
                    sender=LogicalTransferSender(self._write_frame),
                    last_seen=time.monotonic(),
                )
```

---

### Bằng chứng 2: Vòng lặp `_read_bound` cập nhật `last_seen` và `registry.heartbeat()` trên mọi frame DTP hợp lệ

Trong file [src/pbl4/runtime/parameter_server.py:230-252](file:///d:/HKI%2026-27/PBL4/demo/src/pbl4/runtime/parameter_server.py#L230-L252):

```python
# Trích xuất từ src/pbl4/runtime/parameter_server.py:
    def _read_bound(self, connection: _Connection) -> None:
        while True:
            frame = DTPFrame.read_from(
                connection.sock,
                recv_exact,
                bound_identity=(connection.session_id, connection.worker_id),
            )
            message: DtpControlMessage | None = None
            if frame.header.message_type not in {
                MESSAGE_TYPE_GRADIENT_CHUNK,
                MESSAGE_TYPE_PARAMETER_CHUNK,
            }:
                message = decode_control_message(frame.header.message_type, frame.payload)
            connection.validator.validate(frame.header, message)
            now = time.monotonic()
            connection.last_seen = now
            with contextlib.suppress(ValueError):
                self.registry.heartbeat(connection.worker_id, connection.session_id, now)
```

**Phân tích kỹ thuật**:
1. `connection.validator.validate(frame.header, message)` đảm bảo frame đúng cấu trúc, đúng pha trạng thái của session và không vi phạm ràng buộc DTP/1.
2. Ngay sau khi validate thành công, `connection.last_seen` được gán mốc `now = time.monotonic()`.
3. Đồng thời gọi `self.registry.heartbeat(connection.worker_id, connection.session_id, now)` để cập nhật trường `session.last_heartbeat_at` trong `WorkerRegistry`.
4. Cơ chế này áp dụng nhất quán cho:
   - Tin nhắn `HEARTBEAT` (`0x0030`).
   - Các gói nhị phân chunk dữ liệu (`GRADIENT_CHUNK`, `PARAMETER_CHUNK`).
   - Mọi tin nhắn điều khiển hợp lệ khác (`SHARD_READY`, `READY`, `GRADIENT_META`, `GRADIENT_END`, `PARAMETER_APPLIED`).
5. Nếu frame là `HEARTBEAT`, gói tin rơi xuống cuối vòng lặp và tiếp tục lắng nghe mà không cần phản hồi dư thừa (đúng yêu cầu *"server ko cần phản hồi heartbeat"*).

---

### Bằng chứng 3: Bổ sung phương thức truy xuất `ParameterServer.last_seen(worker_id)`

Trong file [src/pbl4/runtime/parameter_server.py:367-373](file:///d:/HKI%2026-27/PBL4/demo/src/pbl4/runtime/parameter_server.py#L367-L373):

```python
# Trích xuất từ src/pbl4/runtime/parameter_server.py:
    def last_seen(self, worker_id: int) -> float:
        with self._lock:
            try:
                return self._connections[worker_id].last_seen
            except KeyError as exc:
                raise ValueError(f"Worker {worker_id} is not connected") from exc
```

Cung cấp API an toàn theo thread (`self._lock`) để các subsystem khác (hoặc test harness) truy vấn trạng thái hoạt động thực tế của từng Worker.

---

## 3. KẾT QUẢ KIỂM THỬ TỰ ĐỘNG (AUTOMATED TEST PROOF)

Đã bổ sung unit test chuyên biệt `test_last_seen_updated_on_heartbeat_and_any_valid_dtp_message` trong [tests/unit/test_dtp_messages.py:775-871](file:///d:/HKI%2026-27/PBL4/demo/tests/unit/test_dtp_messages.py#L775-L871) để xác minh:
1. Giá trị ban đầu của `last_seen` khi worker kết nối.
2. Khi server nhận `SHARD_READY` (một tin nhắn DTP thông thường không phải heartbeat), `server.last_seen(0)` và `registry.snapshot()[0].last_heartbeat_at` được cập nhật tức thì.
3. Khi server nhận tin nhắn `HEARTBEAT`, `server.last_seen(0)` và `registry.snapshot()[0].last_heartbeat_at` tiếp tục được cập nhật.
4. `HeartbeatMonitor` không bị kích hoạt timeout giả sau khi nhận tin nhắn hợp lệ.
5. Truy vấn `server.last_seen(99)` cho worker không tồn tại raise `ValueError`.

### Bằng chứng thực thi kiểm thử:

```bash
uv run pytest tests/unit/test_dtp_messages.py -v
```
**Kết quả**:
```
tests/unit/test_dtp_messages.py::RuntimeSeamTest::test_last_seen_updated_on_heartbeat_and_any_valid_dtp_message PASSED [ 88%]
=================== 27 passed, 97 subtests passed in 0.25s ====================
```

Chạy toàn bộ 208 test case thuộc phạm vi core distributed training:
```bash
uv run pytest tests/
```
**Kết quả**:
```
======================= 208 passed, 2 warnings in 6.63s =======================
```

Kiểm tra ranh giới kiến trúc và quy chuẩn định dạng:
```bash
uv run python scripts/check_architecture.py
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
```
**Kết quả**:
```
Architecture import-boundary check PASSED: all configured package import rules passed.
All checks passed!
171 files already formatted
```

---

## 4. BẢNG ĐỐI CHIẾU TIÊU CHÍ XÁC MINH

| Tiêu chuẩn yêu cầu | Hiện trạng mã nguồn | Đánh giá | Ghi chú |
|---|---|:---:|---|
| **Theo dõi `last_seen` trên kết nối DTP** | `_Connection` có thuộc tính `last_seen`, `ParameterServer` có hàm `last_seen(worker_id)`. | **ĐẠT (PASSED)** | Khởi tạo khi bắt tay thành công, thread-safe. |
| **Cập nhật khi nhận tin nhắn `HEARTBEAT`** | Được validate và cập nhật cả `connection.last_seen` lẫn `registry.heartbeat()`. | **ĐẠT (PASSED)** | Không gửi phản hồi dư thừa theo chỉ đạo thiết kế. |
| **Cập nhật khi nhận bất kỳ tin nhắn DTP hợp lệ nào** | Trong `_read_bound`, mọi frame qua `validator.validate` đều cập nhật `last_seen`. | **ĐẠT (PASSED)** | Đáp ứng quy tắc Validated Progress, tránh timeout giả khi truyền chunk lớn. |
| **Đồng bộ với bảng đăng ký phiên (`WorkerRegistry`)** | `self.registry.heartbeat()` được kích hoạt ngay trong `_read_bound`. | **ĐẠT (PASSED)** | `HeartbeatMonitor` đồng bộ trực tiếp với luồng DTP transport. |
| **Tuân thủ giới hạn phạm vi người dùng yêu cầu** | Không bổ sung echo heartbeat trên server; không bổ sung `worker.last_seen`. | **ĐẠT (PASSED)** | Giữ mã nguồn đơn giản, chuẩn xác theo yêu cầu. |

---

## 5. KẾT LUẬN

Yêu cầu: **"Quản lý thời gian sống và hoạt động (last_seen). last_seen được cập nhật khi nhận HEARTBEAT hoặc bất kỳ tin nhắn DTP hợp lệ nào từ connection"** đã được triển khai hoàn chỉnh, kiểm thử toàn diện, và chính thức đạt trạng thái **ĐẠT (PASSED)**.
