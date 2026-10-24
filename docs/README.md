# Tài liệu dự án

| Tài liệu | Mục đích |
|---|---|
| [DISTRIBUTED_DEMO_GUIDE.md](DISTRIBUTED_DEMO_GUIDE.md) | Khởi chạy dịch vụ và thao tác qua WebUI |
| [API.md](API.md) | Tra cứu REST/WebSocket implementation và contract tests hiện tại |
| [IMPLEMENTATION_CONTRACT.md](IMPLEMENTATION_CONTRACT.md) | Projection kiến trúc và ràng buộc triển khai |
| [OPEN_ISSUES.md](OPEN_ISSUES.md) | Câu hỏi thiết kế còn mở, cần đối chiếu canonical trước khi xử lý |
| [DBS_DESIGN.md](DBS_DESIGN.md) | Thiết kế DBS/Work Unit |

Nguồn canonical và phạm vi sở hữu được đăng ký tại
[.agents/SOURCE_REGISTRY.md](../.agents/SOURCE_REGISTRY.md).
Các bản kế hoạch triển khai và báo cáo smoke cũ đã được xóa khỏi
checkout; tài liệu từng được commit vẫn có thể tra cứu trong lịch sử Git.

[archive/](archive/) chỉ còn bản API contract cũ và báo cáo kiểm tra dataset,
không phải tài liệu hướng dẫn API hoặc trạng thái dữ liệu hiện tại.

## Dữ liệu local

- `var/`: checkpoint, Node identity, manifest, log và Worker cache mà launcher sử dụng.
- `.var/`: workspace Dataset Manager local, môi trường và dữ liệu thử nghiệm.
- `artifacts/e2e/`: evidence của các lần kiểm thử.

Các thư mục trên chứa dữ liệu local được Git bỏ qua. Không xóa toàn bộ `var/`
hoặc `.var/` để dọn cache: cần giữ checkpoint, identity, backup và checkout phụ.
Các thư mục `var/pytest-*`, `.pytest_cache/`, `.ruff_cache/` và `__pycache__/`
là đầu ra có thể tái tạo khi không có tiến trình kiểm thử đang chạy.
