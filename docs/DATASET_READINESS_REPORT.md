# Dataset readiness — Aiven, Hugging Face và cache local

Kiểm tra và xử lý ngày 2026-10-13 theo yêu cầu chuẩn bị dữ liệu trước khi demo UI.
Đây là thao tác dữ liệu thật được người dùng yêu cầu, không phải mutation test
hay migration trên Aiven. Không sửa `.env`, không push/deploy code remote.

## Catalog sau xử lý

| Dataset / mục đích | Build ID | Trạng thái | Storage |
|---|---|---|---|
| CIFAR-10 50.000 mẫu, batch 256 | `1d41a685-8343-4ff0-8d1b-64146ddf792e` | READY, giữ nguyên | Hugging Face |
| CIFAR-10 bản legacy, batch 256 | `e61fa371-eedf-460e-b3d8-f0d46f04591f` | DEPRECATED | Render; artifact và lịch sử giữ nguyên |
| SmallCNN Demo - Synthetic 192 (Hugging Face), batch 16 | `13af35ef-b6c0-4edf-8ccb-109015083921` | READY, mới tạo | Hugging Face |

Hai Build CIFAR-10 ban đầu thuộc cùng dataset `ds_ab35f846`, không phải hai nguồn
dataset khác nhau. Cả hai manifest trả HTTP 200 và khớp SHA-256 trong Aiven.
Chưa có bằng chứng chúng bị hỏng; URL khác nhau phản ánh backend storage khác nhau.
Bản Render được deprecate qua Dataset Manager và Backend service hiện có nhằm
loại khỏi lựa chọn Job mới; không sửa URL/hash của một Build đã được pin trong
contract. Job cũ giữ references; RETRY/RESUME dùng Build đã DEPRECATED sẽ bị gate
READY hiện có từ chối. Không xóa checkpoint, Job, Node identity hay cache cũ.

## Dataset riêng cho demo SmallCNN

- Dataset ID: `ds_3023aa52`.
- Tên UI: **SmallCNN Demo - Synthetic 192 (Hugging Face)**.
- Source: `synthetic_smoke_v1`, dữ liệu tổng hợp deterministic, không phải CIFAR-10
  thật và không dùng để đánh giá độ chính xác mô hình.
- Profile: `CNN_IMAGE_CLASSIFICATION_V1`; tensor float ảnh `[3,32,32]`, 10 lớp.
- 192 mẫu, 3 shard, batch/Work Unit size 16, tổng 12 Work Unit.
- Partition seed: `20260910`. Equal K3 có 4 step/epoch; Equal/DBS K6 có 2 step/epoch.
- Build hash: `26224baadd7bd025547658b7674398bcb9e641ddcacc25c135e9a53b9f3408fc`.
- [Manifest trên Hugging Face](https://huggingface.co/datasets/Lilynched999/dataset-artifacts/resolve/main/dataset-builds/13af35ef-b6c0-4edf-8ccb-109015083921/dataset-manifest.json).

Build được tạo bởi Dataset Manager local tại revision `8a9a65d` với storage
`huggingface`, dùng credentials từ cấu hình Dataset Manager hiện có, không ghi
token vào evidence. Artifact upload/remote hash verification đã chạy thật.
Backend kiểm tra manifest, persist catalog vào Aiven rồi gửi registration ACK;
chỉ sau ACK mới ghi READY. Không INSERT thủ công một Build giả READY.

Dataset Manager trên Render hiện chỉ nhận nguồn CIFAR-10; chưa deploy phiên bản
synthetic. Build mới có artifact và durable metadata trên Hugging Face, nên
không cần local DM chạy để Worker đọc artifact. Backend đã có READY catalog để
validate/resolve Job. Rebuild nguồn synthetic trên Render chưa được hỗ trợ cho
đến khi triển khai revision phù hợp; hãy chọn lại Build READY này khi demo.

## Bản vật lý và kiểm chứng reuse

Artifact staging/cache của Dataset Manager:
`D:\PBL4\var\datasets-smallcnn-hf`.

Worker caches đã tải trực tiếp từ Hugging Face bằng `ShardDownloader` production:

- `D:\PBL4\var\agent\worker-cache` — tương ứng Agent mặc định `var/agent`.
- `D:\PBL4\var\demo-node-1\worker-cache`.
- `D:\PBL4\var\demo-node-2\worker-cache`.

Mỗi cache giữ cả 3 shard (`all_shards`); tên thư mục là hash của
Build ID + manifest hash + shard ID. Muốn sử dụng các cache đã chuẩn bị, Node Agent
phải chạy với var-dir tương ứng. Chạy Agent ở var-dir khác sẽ tạo cache riêng.

Kết quả: cold pass tải từ HF và xác minh bytes/hash; lượt tiếp theo tạo downloader
mới với HTTP opener luôn báo lỗi nếu bị gọi, vẫn **9/9 shard reuse, 0 request HTTP,
0 byte download**. Cùng Build ID/hash ở cả hai lượt. Kiểm tra toàn bộ 12 batch:
192 sample ID khác nhau, tensor hữu hạn đúng shape, đủ nhãn 0–9. SmallCNN thật
đọc một batch đã tải và thực hiện forward/backward, loss/gradient hữu hạn.

Đây là kiểm chứng dữ liệu và cache, không phải một lượt distributed training
E2E mới trên Build HF này. Chưa tự tạo Job training mới trong Aiven ở nhiệm vụ
chuẩn bị dữ liệu; bước kế tiếp là thao tác Job/Start trên UI với Build này.

## Chọn trên UI và evidence

UI phải trỏ Backend dùng Aiven `.env` hiện tại, không phải database của smoke
harness. Refresh danh sách, chọn dataset **SmallCNN Demo - Synthetic 192
(Hugging Face)**, chọn Build READY `13af35ef-…`, model SmallCNN. Không bấm Build
lại khi chỉ muốn train thêm hoặc đổi policy/model tương thích. Không dùng nút
Build cũ mặc định batch64 để thay thế Build batch16 đã chuẩn bị.

Các file không chứa token tại `artifacts/e2e/data-audit/`:

- `catalog-before.json`, hai root manifest cũ đã kiểm tra hash.
- `legacy-build-before-deprecation.json`: snapshot metadata/references trước thay đổi.
- `catalog-after.json`: chỉ các Build HF còn READY.
- `smallcnn-hf-build.json`: ID/hash/URL/cấu hình Build mới.
- `smallcnn-cache-cold.json`, `smallcnn-cache-warm.json`: từng cache/shard và số HTTP request.
- `smallcnn-data-verification.json`: kết quả kiểm tra dữ liệu và SmallCNN.
- `backend-read-api.json`: GET dataset list/build detail/READY filter qua Backend
  routes với catalog Aiven thật đều PASS; chưa phải browser acceptance.

Không purge artifact HF, không xóa database hay toàn bộ `var/`. Metadata cũ được
giữ để truy vết; dữ liệu của Job được chọn bằng Build ID/hash, không bằng profile
hay tên dataset chung. Đổi nội dung/URL/hash tại chỗ của Build cũ sẽ phá tính bất
biến; dùng deprecation và Build mới để tránh vấn đề đó.
