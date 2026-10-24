# Tra cứu API đang triển khai

Tài liệu này chỉ dẫn đến implementation hiện tại, không thay thế đặc tả canonical
trong [source registry](../.agents/SOURCE_REGISTRY.md).

Khi Backend đang chạy, mở `/api/docs` để xem REST API và `/api/openapi.json`
để lấy OpenAPI trên chính Backend đó. Các đường dẫn này được cấu hình trong
[app.py](../src/pbl4/management_backend/app.py).

| Nội dung | Nơi đối chiếu |
|---|---|
| REST endpoints | [api/](../src/pbl4/management_backend/api/) |
| Request/response models | [schemas/](../src/pbl4/management_backend/schemas/) |
| HTTP envelopes, middleware, WebSocket routes | [app.py](../src/pbl4/management_backend/app.py) |
| WebUI API client | [web/src/api/](../web/src/api/) |
| WebUI types và stream consumer | [types/api.ts](../web/src/types/api.ts), [useAttemptStream.ts](../web/src/hooks/useAttemptStream.ts) |
| Backend contract tests | [management_backend/tests/](../src/pbl4/management_backend/tests/) |

OpenAPI mô tả REST; khi kiểm tra WebSocket cần đọc cả route và consumer.

Khi thay đổi semantics API, đối chiếu canonical owner trước; không coi
implementation là nguồn phê duyệt semantics mới. Bản
[API_contract.md cũ](archive/API_contract.md) chỉ còn dùng để tra cứu lịch sử,
không dùng làm contract hiện hành.
