# BÁO CÁO XÁC MINH CẤU TRÚC VÀ XỬ LÝ TIN NHẮN ERROR TRONG DTP/1

**Dự án**: PBL4 Distributed Training — Parameter Server Architecture  
**Giao thức kiểm tra**: DTP/1 (Distributed Training Protocol Version 1)  
**Tiêu chí xác minh**: Cấu trúc và xử lý tin nhắn ERROR nghiêm ngặt. Tin nhắn ERROR bắt buộc có `error_code`, `scope` (`MESSAGE` | `SESSION` | `ATTEMPT`), `severity` (`INFO` | `WARNING` | `ERROR` | `CRITICAL`) và `message`. Lỗi nghiêm trọng (`SESSION`/`ATTEMPT`) bắt buộc phải đóng kết nối hoặc chuyển trạng thái rõ ràng, không chỉ ghi log.  
**Trạng thái**: **ĐẠT (PASSED)**

---

## 1. TỔNG QUAN YÊU CẦU & NGUYÊN TẮC THIẾT KẾ CHUẨN TẮC

Theo đặc tả giao thức DTP/1 và mô hình trạng thái:
1. **Cấu trúc tin nhắn `ERROR` (Message Type `0x00FF`)**:
   - `error_code` (string): Mã định danh lỗi tiêu chuẩn.
   - `scope` (enum string): Bắt buộc thuộc tập `{"MESSAGE", "SESSION", "ATTEMPT"}`.
   - `severity` (enum string): Bắt buộc thuộc tập `{"INFO", "WARNING", "ERROR", "CRITICAL"}`.
   - `message` (string): Mô tả nguyên nhân sự cố.
   - `retryable` (bool): Khả năng thử lại gói tin/thao tác.
2. **Nguyên tắc xử lý lỗi nghiêm ngặt (Strict Error Handling & State Transition)**:
   - **Lỗi cục bộ (`scope="MESSAGE"`, `severity in ("INFO", "WARNING")`)**:
     - Ghi nhận thông tin cảnh báo, thông báo handler.
     - **Không đóng kết nối**, không chuyển trạng thái session, duy trì tiến trình huấn luyện bình thường.
   - **Lỗi nghiêm trọng (`scope in ("SESSION", "ATTEMPT")` hoặc `severity in ("ERROR", "CRITICAL")`)**:
     - Không được phép chỉ ghi log đơn thuần.
     - Bắt buộc phải **đóng kết nối TCP** ngay lập tức.
     - Phía Server: Bắt buộc chuyển trạng thái phiên làm việc sang `SessionState.FAILED` với `failure_code = message.error_code`, và chuyển validator phase sang `ConnectionPhase.CLOSED`.
     - Phía Worker: Bắt buộc dừng luồng đọc, giải phóng bộ nhớ tensor (`assembler.discard()`), ngắt kết nối `transport.disconnect()`, và chuyển validator phase sang `ConnectionPhase.CLOSED`.
     - Với `scope == "ATTEMPT"`: Thông báo `error_handler` để Coordinator quản lý việc fail/abort toàn bộ đợt huấn luyện.

---

## 2. BẰNG CHỨNG MÃ NGUỒN CÀI ĐẶT (CODE PROOF)

### Bằng chứng 1: Định nghĩa cấu trúc `Error` nghiêm ngặt theo schema
Trong file [src/pbl4/protocol/messages.py:449-469](file:///d:/HKI%2026-27/PBL4/demo/src/pbl4/protocol/messages.py#L449-L469):
```python
# Trích xuất từ src/pbl4/protocol/messages.py:
class Error(DtpControlMessage):
    MESSAGE_TYPE = MESSAGE_TYPE_ERROR
    REQUIRED = {
        "error_code": "string",
        "scope": "string",
        "severity": "string",
        "message": "string",
        "retryable": "bool",
    }
    OPTIONAL = {
        "related_message_type": "string",
        "operation_id": "nonnegative_int",
        "model_version": "nonnegative_int",
        "tensor_id": "nonnegative_int",
        "step_id": "nonnegative_int",
    }
    ENUMS = {
        "scope": frozenset({"MESSAGE", "SESSION", "ATTEMPT"}),
        "severity": frozenset({"INFO", "WARNING", "ERROR", "CRITICAL"}),
    }
```

---

### Bằng chứng 2: Parameter Server xử lý `ERROR`, chuyển trạng thái `FAILED` và ngắt kết nối
Trong file [src/pbl4/runtime/parameter_server.py:288-316](file:///d:/HKI%2026-27/PBL4/demo/src/pbl4/runtime/parameter_server.py#L288-L316):
```python
# Trích xuất từ src/pbl4/runtime/parameter_server.py (_read_bound):
            elif frame.header.message_type == MESSAGE_TYPE_ERROR:
                assert isinstance(message, Error)
                if self._error_handler is not None:
                    self._error_handler(connection.worker_id, connection.session_id, message)
                if message.scope in {"SESSION", "ATTEMPT"} or message.severity in {
                    "ERROR",
                    "CRITICAL",
                }:
                    now = time.monotonic()
                    with contextlib.suppress(ValueError):
                        self.registry.transition(
                            connection.worker_id,
                            connection.session_id,
                            SessionState.FAILED,
                            now,
                            failure_code=message.error_code,
                        )
                    connection.validator.set_phase(ConnectionPhase.CLOSED)
                    raise ProtocolError(
                        f"Fatal worker error (scope={message.scope}, "
                        f"code={message.error_code}): {message.message}"
                    )
```

**Phân tích**:
- Khi nhận lỗi `MESSAGE` với severity `INFO`/`WARNING`: Server kích hoạt `_error_handler` (nếu có), không raise exception, giữ nguyên trạng thái kết nối và session.
- Khi nhận lỗi `SESSION` hoặc `ATTEMPT`, hoặc severity `ERROR`/`CRITICAL`:
  1. `self.registry.transition` được gọi để chuyển Worker Session sang trạng thái `SessionState.FAILED` kèm `failure_code`.
  2. `connection.validator.set_phase(ConnectionPhase.CLOSED)` đánh dấu phase đóng.
  3. `raise ProtocolError` làm thoát khỏi vòng lặp `_read_bound`, giải phóng bộ đệm tensor, đóng socket và dọn dẹp kết nối trong khối `finally`.

Đồng thời, Parameter Server cung cấp API gửi tin nhắn `send_error` [src/pbl4/runtime/parameter_server.py:429-436](file:///d:/HKI%2026-27/PBL4/demo/src/pbl4/runtime/parameter_server.py#L429-L436):
```python
    def send_error(
        self,
        worker_id: int,
        error: Error,
        *,
        operation_id: int = NO_OPERATION,
    ) -> None:
        self._send_control(self._connection(worker_id), error, operation_id=operation_id)
```

---

### Bằng chứng 3: Worker Client xử lý lỗi nghiêm trọng từ Server và cung cấp `send_error`
Trong file [src/pbl4/worker/worker_client.py:328-343](file:///d:/HKI%2026-27/PBL4/demo/src/pbl4/worker/worker_client.py#L328-L343):
```python
# Trích xuất từ src/pbl4/worker/worker_client.py (_read_loop):
                elif isinstance(message, Error):
                    if self._message_handler is not None:
                        self._message_handler(message, frame.header.operation_id)
                    if message.scope in {"SESSION", "ATTEMPT"} or message.severity in {
                        "ERROR",
                        "CRITICAL",
                    }:
                        self._closing.set()
                        self._validator.set_phase(ConnectionPhase.CLOSED)
                        raise TransportError(
                            f"Fatal error from runtime (scope={message.scope}, "
                            f"code={message.error_code}): {message.message}"
                        )
```

Và phương thức gửi lỗi của Worker [src/pbl4/worker/worker_client.py:284-286](file:///d:/HKI%2026-27/PBL4/demo/src/pbl4/worker/worker_client.py#L284-L286):
```python
    def send_error(self, error: Error, *, operation_id: int = NO_OPERATION) -> None:
        self._send_control(error, operation_id=operation_id)
```

**Phân tích**:
- Khi Server báo lỗi nghiêm trọng (`SESSION`/`ATTEMPT` hoặc `ERROR`/`CRITICAL`), WorkerClient đặt cờ `_closing.set()`, chuyển validator sang `ConnectionPhase.CLOSED` và ném `TransportError`, dẫn tới ngắt kết nối TCP và giải phóng tài nguyên trong khối `finally`.

---

## 3. KẾT QUẢ KIỂM THỬ TỰ ĐỘNG (TEST PROOF)

Đã bổ sung 4 test case chuyên biệt trong [tests/unit/test_dtp_messages.py](file:///d:/HKI%2026-27/PBL4/demo/tests/unit/test_dtp_messages.py):
1. `test_runtime_handles_message_scope_error_without_disconnecting`: Xác minh lỗi scope `MESSAGE` không làm đứt kết nối, không chuyển `FAILED`.
2. `test_runtime_handles_session_and_attempt_scope_fatal_errors`: Xác minh lỗi scope `SESSION`/`ATTEMPT` làm chuyển `SessionState.FAILED`, lưu `failure_code`, và đóng kết nối.
3. `test_worker_client_handles_fatal_error_from_server`: Xác minh WorkerClient tự động ngắt kết nối, chuyển phase `CLOSED`, và kiểm tra `client.send_error()`.
4. `test_parameter_server_send_error`: Xác minh `server.send_error()` tạo frame chuẩn xác trên đường truyền.

### Bằng chứng thực thi:
```bash
uv run pytest tests/unit/test_dtp_messages.py -v
```
**Kết quả**:
```
tests/unit/test_dtp_messages.py::RuntimeSeamTest::test_parameter_server_send_error PASSED [ 87%]
tests/unit/test_dtp_messages.py::RuntimeSeamTest::test_runtime_handles_message_scope_error_without_disconnecting PASSED [ 90%]
tests/unit/test_dtp_messages.py::RuntimeSeamTest::test_runtime_handles_session_and_attempt_scope_fatal_errors PASSED [ 93%]
tests/unit/test_dtp_messages.py::RuntimeSeamTest::test_worker_client_handles_fatal_error_from_server PASSED [100%]

=================== 31 passed, 97 subtests passed in 0.27s ====================
```

Chạy toàn bộ 212 test case trong `tests/`:
```bash
uv run pytest tests/
```
**Kết quả**:
```
====================== 212 passed, 2 warnings in 10.77s =======================
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

| Tiêu chuẩn yêu cầu | Hiện trạng mã nguồn | Đánh giá | Chi tiết phân tích |
|---|---|:---:|---|
| **Bắt buộc có `error_code`** | `Error.REQUIRED["error_code"] = "string"`. | **ĐẠT (PASSED)** | Thiếu trường bị từ chối ngay. |
| **Bắt buộc có `scope` (`MESSAGE` \| `SESSION` \| `ATTEMPT`)** | `Error.ENUMS["scope"] = frozenset(...)`. | **ĐẠT (PASSED)** | Enum kiểm tra chặt chẽ 3 giá trị cho phép. |
| **Bắt buộc có `severity` (`INFO` \| `WARNING` \| `ERROR` \| `CRITICAL`)** | `Error.ENUMS["severity"] = frozenset(...)`. | **ĐẠT (PASSED)** | Enum kiểm tra chặt chẽ 4 mức nghiêm trọng. |
| **Bắt buộc có `message`** | `Error.REQUIRED["message"] = "string"`. | **ĐẠT (PASSED)** | Chuỗi mô tả lỗi bắt buộc. |
| **Bắt buộc có `retryable`** | `Error.REQUIRED["retryable"] = "bool"`. | **ĐẠT (PASSED)** | Cờ boolean theo chuẩn wire schema. |
| **Xử lý lỗi `SESSION`/`ATTEMPT` trên Runtime** | `_read_bound` chuyển `SessionState.FAILED`, đóng kết nối TCP. | **ĐẠT (PASSED)** | Lưu `failure_code`, chuyển phase `CLOSED`, đóng socket. |
| **Xử lý lỗi `SESSION`/`ATTEMPT` trên Worker** | `_read_loop` ngắt transport, chuyển phase `CLOSED`, dừng worker. | **ĐẠT (PASSED)** | Giải phóng assembler, ngắt kết nối dứt điểm. |
| **Cấm việc chỉ ghi log đối với lỗi nghiêm trọng** | Mã nguồn cưỡng chế đóng kết nối TCP và chuyển đổi trạng thái rõ ràng. | **ĐẠT (PASSED)** | Tuân thủ triệt để nguyên tắc Fail-Fast. |

---

## 5. KẾT LUẬN

Yêu cầu: **"Cấu trúc và xử lý tin nhắn ERROR nghiêm ngặt. Tin nhắn ERROR bắt buộc có error_code, scope (MESSAGE | SESSION | ATTEMPT), severity (INFO | WARNING | ERROR | CRITICAL) và message. Lỗi nghiêm trọng (SESSION/ATTEMPT) bắt buộc phải đóng kết nối hoặc chuyển trạng thái rõ ràng, không chỉ ghi log"** đã được thực hiện và kiểm thử hoàn chỉnh, chính thức đạt trạng thái **ĐẠT (PASSED)**.
