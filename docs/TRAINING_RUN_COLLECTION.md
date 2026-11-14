# Thu kết quả một phiên training

Chạy collector trên **máy Runtime** để ưu tiên file local. Collector dùng Python
standard library, không cần cài thêm package và không launch/abort/thay đổi training.

```powershell
python scripts/collect_training_run.py
```

Sau đó partner thao tác Start training bình thường trên WebUI. Collector tự gắn vào
Attempt đang active, hoặc đợi Attempt mới được tạo sau khi mở collector. Mỗi lần
chạy script theo dõi một Attempt rồi kết thúc; chạy lại cho lần test kế tiếp.
Không tự chọn lại một Attempt cũ đã kết thúc. Nếu có nhiều Attempt mới trong lúc
collector mất kết nối, ưu tiên theo thứ tự API (mới nhất trước); dùng `--attempt-id`
để chọn chính xác. Có thể giới hạn discovery bằng `--job-id`.

Khi terminal, collector đợi lịch sử/artifact ổn định 20 giây, tối đa 120 giây từ
lần đầu quan sát terminal. Nó tạo folder và ZIP trong `output/training-runs/`;
dòng `Send this archive:` chỉ đúng file partner cần gửi. Exit 0: thu đủ lịch sử
quan sát được, có model export mới nhất và không còn lỗi thu thập; **không có
nghĩa training đạt chất lượng**. Exit 2: thiếu dữ liệu/artifact sau timeout; gửi
cả gói này và đọc `summary.json`. Ctrl+C lưu gói dở dang, exit 130.

## Local trước, API sau

- `var/checkpoints/<attempt_id>/<hash>/`: đọc checkpoint đã publish; bỏ directory
  tạm. Mỗi checkpoint chỉ copy trọng số một lần, xác minh hash/size trước khi nhận.
- `var/manifests/`: tìm parameter manifest trùng hash; cùng resolved contract tạo
  model ZIP gồm `model.bin`, `checkpoint.json`, `parameter-manifest.json`,
  `resolved-contract.json`. Hai file đầu chính là dữ liệu checkpoint vật lý,
  giữ nguyên bytes; không phải `.pt`/pickle. Không copy thêm một bộ trọng số trùng.
- `var/logs/*.log`: lấy tối đa 2 MiB cuối mỗi log lúc bắt đầu, sau đó đọc nối tiếp
  tối đa 1 MiB/file/poll. Có thể mất log do rotation hoặc collector không theo kịp;
  log service dùng chung có thể chứa ngữ cảnh của lần chạy khác. Không đọc `.env`,
  Node identity, allocations hay credential files. Không tự lấy log máy Worker khác.
- Job/resolved contract lấy một lần qua API và cache. Event metrics chưa có file
  local đầy đủ nên lấy lịch sử PostgreSQL qua Backend, đọc tăng dần theo contiguous
  event sequence. Nếu có gap, đọc lại từ trước gap, deduplicate khi ghi.
- Nếu không có folder checkpoint local, dùng inventory/export API hiện có. Nếu
  thiếu local manifest, dùng export API cho checkpoint đó. API trả lỗi được ghi
  lại và retry; không đánh dấu model đã lấy thành công khi hash sai.
- Node resource là snapshot Agent mà Backend đang có; collector lưu timestamp
  của lần lấy và timestamp freshness gốc trong response. Không phải bộ profiler
  toàn cụm, không giả định snapshot luôn fresh.

Nếu dùng state directory khác hoặc Backend ở máy khác:

```powershell
python scripts/collect_training_run.py --state-dir D:/PBL4/var --backend-url http://192.168.1.10:8000
```

`--state-dir` mặc định `PBL4_STATE_DIR` trong process environment hoặc `var/` của
checkout; collector không nạp `.env`. Backend mặc định `BACKEND_URL` trong process
environment hoặc `http://127.0.0.1:8000`. Dùng `--poll-seconds 10` để giảm polling.
Nếu Runtime dùng checkpoint root riêng ngoài launcher convention, chỉ định state
directory có `checkpoints/` và `manifests/` tương ứng; nếu không script dùng API.

Thu một Attempt đã hoàn tất, hoặc tiếp tục collector bị dừng:

```powershell
python scripts/collect_training_run.py --attempt-id <ATTEMPT_ID>
```

Giữ cùng `--output` để dùng lại events/model đã lưu. Tránh chạy hai collector cho
cùng Attempt và cùng output đồng thời. Không tắt Runtime trước khi thu xong nếu
cần API export. Training chưa tạo checkpoint thì collector không thể tạo thay;
báo thiếu model. Checkpoint đã bị retention xóa trước khi thu cũng không thể lấy lại.

## Nội dung gói

- `summary.json`: trạng thái, lỗi/chỗ thiếu, training span, throughput, step p50/p95,
  epoch metrics cuối, async progress cuối và danh sách model export.
- `job.json`, `attempt.json`, `workers.json`: cấu hình và danh tính phiên.
- `events.jsonl`: event thô, sequence gốc; `epochs.csv`, `steps.csv`,
  `contributions.csv`, `async-progress.json`: bảng để phân tích.
- `checkpoints/<hash>/model.zip`, `detail.json`: checkpoint và manifest phục vụ
  inference; `checkpoints.json` ghi inventory local hoặc API.
- `node-resources.jsonl`, `logs/`, `log-capture.json`: resource snapshots và log local.
- `collector-environment.json`: Python/OS/commit của **máy collector**, không chứng
  minh commit hay dependency của Worker trên máy khác.
- `sha256.json`: checksum các file trong gói (ngoại trừ chính checksum manifest).

Timing StrictBSP lấy từ Runtime timestamps: từ start của committed step đầu đến
commit/checkpoint event cuối. Bao gồm checkpoint cuối và khoảng chờ giữa các bước;
không bao gồm provisioning trước step đầu. Step latency chỉ start → commit; p95
dùng nearest rank. Khi lịch sử có gap hoặc chưa bắt kịp Runtime cursor, để null
cho throughput/timing tổng hợp, không suy đoán. Async giữ progress thật, không
tạo Step hoặc tính sync throughput giả. Không tính validation, test, F1 hay
confusion matrix; không thu dataset/test images, source code hay dependency lockfile.

## Inference thủ công

Dùng checkout PBL4 tương ứng, đã cài worker dependencies:

```python
import torch
from pbl4.adapter.model_export import load_exported_model

model = load_exported_model("path/to/checkpoints/<hash>/model.zip", device="cpu")
with torch.inference_mode():
    logits = model(images)  # Tensor đã preprocessing theo resolved-contract.json.
```

Chọn model theo `model_version` trong `summary.json`, không theo tên hash folder.
Không gọi model cuối là model tốt nhất nếu chưa có validation để chọn. Đọc
`checkpoint.json` để đối chiếu recovery cursor và schema trước khi dùng lại dữ liệu
cho công cụ resume; collector không đăng ký/import checkpoint sang một hệ thống mới.
