# BÁO CÁO KIỂM TRA TÍNH ĐÚNG ĐẮN GIAO THỨC MCP/1

## Yêu Cầu Kiểm Tra
> **Mô phỏng Runtime khởi động lại (ID instance thay đổi):**
> 1. Xác minh Backend xóa ngữ cảnh cũ và áp dụng snapshot mới.
> 2. Kiểm tra `runtime_instance_id` trong `MGMT_HELLO_ACK`, nếu đổi, reset cursor sự kiện về snapshot hiện tại.

---

## 1. Kết Luận Kiểm Tra: **ĐẠT (PASSED)**

Sau khi triển khai và kiểm thử theo kế hoạch được phê duyệt:
1. **Kiểm tra `runtime_instance_id` trong `MGMT_HELLO_ACK`:** **ĐẠT**. `handle_hello_ack` so sánh `new_instance_id` với `self._runtime_instance_id`. Nếu phát hiện khác biệt (`old != new`), Backend ghi nhận sự kiện Runtime khởi động lại và kích hoạt dọn dẹp ngữ cảnh.
2. **Xóa ngữ cảnh cũ khi đổi instance ID:** **ĐẠT**. Phương thức `reset_runtime_context()` làm sạch hoàn toàn `self._attempt_snapshots` và `self._attempt_cursors`, đưa `self._cached_snapshot` về `_empty_snapshot()`, đồng thời giải phóng an toàn tất cả các lệnh đang chờ trong `self._pending_results` với `RuntimeUnavailableError`.
3. **Áp dụng snapshot mới và Reset cursor sự kiện:** **ĐẠT**. 
   - Sau khi làm sạch `_attempt_cursors`, khi `handle_state_snapshot` tiếp nhận snapshot từ instance mới, một cursor mới toanh được tạo ra và thiết lập chính xác `max_seen_seq = snap_seq` của instance hiện tại, không còn bị neo bởi giá trị cũ của instance trước.
   - Nếu instance mới ở trạng thái rảnh (`active_attempt_id: None`), toàn bộ snapshot và cursor của attempt cũ đều được dọn sạch khỏi bộ nhớ.

---

## 2. Đoạn Code Chứng Minh Kết Quả Kiểm Tra

### 2.1. Phát hiện thay đổi `runtime_instance_id` trong `MGMT_HELLO_ACK`
Tại file [`src/pbl4/management_backend/gateways/runtime_gateway.py`](file:///d:/HKI%2026-27/PBL4/demo/src/pbl4/management_backend/gateways/runtime_gateway.py#L281-L299):
```python
# src/pbl4/management_backend/gateways/runtime_gateway.py (dòng 281-299)
def handle_hello_ack(self, payload: dict[str, Any]) -> None:
    """MGMT_HELLO_ACK -> ALWAYS request GET_STATE."""
    logger.info("Received MGMT_HELLO_ACK: %s", payload)
    new_instance_id = payload.get("runtime_instance_id")
    if (
        self._runtime_instance_id is not None
        and new_instance_id is not None
        and self._runtime_instance_id != new_instance_id
    ):
        logger.warning(
            "Runtime instance changed from %s to %s; clearing old attempt contexts",
            self._runtime_instance_id,
            new_instance_id,
        )
        self.reset_runtime_context()

    if new_instance_id is not None:
        self._runtime_instance_id = new_instance_id
    # Always request authoritative runtime state immediately
    state = self._port.request_state()
    if state:
        self.handle_state_snapshot(state)
```

### 2.2. Xóa ngữ cảnh cũ và hủy an toàn các lệnh đang chờ
Tại file [`src/pbl4/management_backend/gateways/runtime_gateway.py`](file:///d:/HKI%2026-27/PBL4/demo/src/pbl4/management_backend/gateways/runtime_gateway.py#L238-L253):
```python
# src/pbl4/management_backend/gateways/runtime_gateway.py (dòng 238-253)
def reset_runtime_context(self) -> None:
    """Clear in-memory snapshots, cursors, and abort pending waiters on instance change."""
    self._attempt_snapshots.clear()
    self._attempt_cursors.clear()
    self._cached_snapshot = self._empty_snapshot()
    for cmd_id, future in list(self._pending_results.items()):
        if not future.done():
            future.set_exception(
                RuntimeUnavailableError(
                    f"Runtime restarted with new instance ID; command {cmd_id} aborted",
                    command_id=cmd_id,
                )
            )
    self._pending_results.clear()
    logger.info("Runtime context and cursors reset due to runtime instance change.")
```

### 2.3. Reset cursor sự kiện chuẩn xác về snapshot hiện tại
Nhờ `_attempt_cursors.clear()` được gọi khi đổi instance ID, hàm `handle_state_snapshot` ([`runtime_gateway.py:395-402`](file:///d:/HKI%2026-27/PBL4/demo/src/pbl4/management_backend/gateways/runtime_gateway.py#L395-L402)) khởi tạo cursor sạch và gán:
```python
cursor = self.get_cursor(attempt_id)
cursor.authoritative_snapshot_seq = snap_seq
cursor.highest_contiguous_seq = snap_seq
cursor.max_seen_seq = max(cursor.max_seen_seq, snap_seq)  # max(0, snap_seq) == snap_seq
```
Giá trị `max_seen_seq` được reset chuẩn xác về đúng mốc `snap_seq` của snapshot hiện hành, không còn bị ảnh hưởng bởi phiên chạy cũ.

---

## 3. Bằng Chứng Thực Nghiệm & Kiểm Thử Tự Động

Bộ kiểm thử đơn vị tự động tại [`src/pbl4/management_backend/tests/test_runtime_gateway_restart.py`](file:///d:/HKI%2026-27/PBL4/demo/src/pbl4/management_backend/tests/test_runtime_gateway_restart.py) kiểm tra toàn diện 3 kịch bản:
1. **`test_runtime_instance_change_clears_old_context_and_resets_cursor`**: Khi `runtime_instance_id` đổi từ `runtime-1` sang `runtime-2`, các lệnh đang chờ bị hủy an toàn với `RuntimeUnavailableError`, cursor `attempt-1` được reset về sequence 0 theo snapshot mới (không giữ giá trị cũ 25).
2. **`test_runtime_instance_change_with_idle_snapshot`**: Khi Runtime mới khởi động lại ở trạng thái rảnh (`active_attempt_id: None`), toàn bộ `_attempt_snapshots` và `_attempt_cursors` cũ bị xóa sạch.
3. **`test_runtime_instance_unchanged_preserves_context_on_reconnect`**: Khi ngắt kết nối mạng tạm thời và kết nối lại cùng một instance ID (`runtime-1`), ngữ cảnh và cursor được bảo toàn chuẩn xác.

### Kết Quả Chạy Kiểm Thử:
```powershell
uv run pytest src/pbl4/management_backend/tests/test_runtime_gateway_restart.py -v
============================= test session starts =============================
collected 3 items

src/pbl4/management_backend/tests/test_runtime_gateway_restart.py::test_runtime_instance_change_clears_old_context_and_resets_cursor PASSED [ 33%]
src/pbl4/management_backend/tests/test_runtime_gateway_restart.py::test_runtime_instance_change_with_idle_snapshot PASSED [ 66%]
src/pbl4/management_backend/tests/test_runtime_gateway_restart.py::test_runtime_instance_unchanged_preserves_context_on_reconnect PASSED [100%]

============================== 3 passed in 0.63s ==============================
```

Kiểm tra ranh giới kiến trúc & lint:
```powershell
uv run python scripts/check_architecture.py
# Architecture import-boundary check PASSED: all configured package import rules passed.

uv run ruff check src/pbl4/management_backend/gateways/runtime_gateway.py
# All checks passed!
```

---

## 4. Bảng Đối Chiếu Tiêu Chí

| Tiêu chí kiểm tra | Kết quả | Đoạn code chứng minh |
| :--- | :---: | :--- |
| Áp dụng snapshot mới từ Runtime sau khi kết nối lại | **ĐẠT** | `runtime_gateway.py:297-299`, `handle_state_snapshot` |
| Kiểm tra `runtime_instance_id` trong `MGMT_HELLO_ACK` xem có đổi hay không | **ĐẠT** | `runtime_gateway.py:284-295` (`self._runtime_instance_id != new_instance_id`) |
| Xóa ngữ cảnh cũ (`_attempt_snapshots`, `_attempt_cursors`) khi đổi instance ID | **ĐẠT** | `runtime_gateway.py:238-253` (`reset_runtime_context`) |
| Reset cursor sự kiện về snapshot hiện tại khi đổi instance ID | **ĐẠT** | `runtime_gateway.py:241`, `395-402` (Cursor mới bắt đầu từ `snap_seq`) |
| Giải phóng an toàn các lệnh đang chờ (`_pending_results`) khi instance đổi | **ĐẠT** | `runtime_gateway.py:243-251` (báo lỗi `RuntimeUnavailableError`) |
| Bảo tồn ngữ cảnh cũ khi kết nối lại cùng một instance ID | **ĐẠT** | `test_runtime_gateway_restart.py::test_runtime_instance_unchanged...` (PASSED) |
