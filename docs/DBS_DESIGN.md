\# DBS\_DESIGN.md

\> Trạng thái: Thiết kế chuẩn cho phạm vi phân phối khối lượng huấn luyện thích ứng bằng DBS.  
\> Mục tiêu: Cài đặt thuật toán DBS từ paper arXiv:2007.11831, nhưng giữ nguyên kiến trúc huấn luyện cốt lõi của PBL4.  
\> Phạm vi: Runtime, Worker, Dataset provisioning cần thiết cho Work Unit và dữ liệu quan sát phục vụ DBS.

Các ý tưởng có giá trị được giữ lại:  
\- Work Unit là đơn vị nhỏ, cố định để Runtime chia việc.  
\- Runtime sở hữu việc chia khối lượng huấn luyện; Node Agent không tham gia.  
\- StrictBSP vẫn yêu cầu đủ N/N Worker.  
\- Tổng lượng dữ liệu của một bước toàn cục giữ cố định.  
\- Worker có thể xử lý nhiều Work Unit rồi gửi một gradient duy nhất.  
\- Gradient toàn cục tiếp tục tổng hợp theo sample\_count.  
\- Thứ tự dữ liệu phải xác định được từ seed \+ epoch.  
\- Dữ liệu phải được chuẩn bị/cached trước khi bước huấn luyện dùng đến.  
\- Checkpoint chỉ cần giữ trạng thái ảnh hưởng correctness; trạng thái ước lượng hiệu năng có thể đo lại.

\#\# 2\. Mục tiêu

DBS giải quyết tình trạng Worker nhanh phải chờ Worker chậm trong huấn luyện đồng bộ.

Hệ thống cần:  
\- đo hiệu năng thực tế của từng Worker trong epoch trước;  
\- giao nhiều Work Unit hơn cho Worker xử lý nhanh, ít hơn cho Worker xử lý chậm;  
\- giữ tổng số mẫu của mỗi bước toàn cục không đổi;  
\- giữ StrictBSP, Parameter Server và cập nhật mô hình phía Runtime không đổi semantics;  
\- không dự đoán hiệu năng từ tên CPU/GPU;  
\- không đưa Database, Backend hoặc Dataset Manager vào vòng gradient \-\> barrier \-\> update.

\#\# 3\. Kiến trúc tổng thể

Dataset Manager  
  \-\> tạo Dataset Build bất biến  
  \-\> physical batch hiện có được dùng làm Work Unit

Worker  
  \-\> cache dữ liệu đã xác minh  
  \-\> nhận danh sách Work Unit của bước  
  \-\> tính từng Work Unit  
  \-\> gộp gradient cục bộ theo số mẫu  
  \-\> gửi đúng một contribution

Runtime  
  \-\> BatchScheduler chọn tập Work Unit toàn cục  
  \-\> WorkloadScheduler quyết định mỗi Worker nhận bao nhiêu Work Unit  
  \-\> StrictBSP chờ N/N contribution  
  \-\> GradientAggregator tổng hợp theo sample\_count  
  \-\> UpdateEngine cập nhật mô hình chuẩn  
  \-\> checkpoint  
  \-\> cuối epoch tính kế hoạch DBS cho epoch sau

DBS chỉ thay đổi "mỗi Worker làm bao nhiêu dữ liệu". DBS không thay đổi "khi nào một bước được phép cập nhật mô hình".

\#\# 4\. Những phần bắt buộc giữ nguyên

1\. training\_strategy vẫn là strict\_bsp.  
2\. Tập Worker cố định trong một Attempt.  
3\. Runtime cấp worker\_id/session\_id.  
4\. Mỗi synchronized step dùng cùng input model version.  
5\. Mỗi Worker gửi đúng một logical gradient contribution cho một step.  
6\. Runtime chỉ update khi nhận đủ N/N contribution hợp lệ.  
7\. GradientAggregator tiếp tục weighted average theo sample\_count.  
8\. Worker không gọi optimizer.step() cho canonical model.  
9\. PARAMETER\_APPLIED N/N và checkpoint gate hiện tại tiếp tục giữ nguyên.  
10\. Gradient/parameter chỉ đi qua DTP/1.

Không tạo dbs\_bsp và không tạo DbsStrictBSP.  
\#\#\# 4.1. Trạng thái hiện có — DBS không tạo state mới  
DBS không thêm state mới vào Database, Attempt, WorkerSession hoặc StrictBSP. Giữ nguyên state machine hiện có trong codebase:  
\- Attempt/Coordinator: CREATED → WAITING\_WORKERS → PROVISIONING → INITIALIZING → RUNNING → COMPLETING → COMPLETED. FAILED và ABORTED là trạng thái kết thúc.  
\- WorkerSession: CONNECTING → REGISTERING → PROVISIONING → SHARD\_READY → MODEL\_SYNCING → READY. DISCONNECTED và FAILED là trạng thái kết thúc.  
\- Step: COLLECTING\_GRADIENTS → AGGREGATING → UPDATING → WAITING\_PARAMETER\_APPLIED → CHECKPOINTING → COMMITTED.  
WorkloadPlan và thống kê theo epoch chỉ là state nội bộ trong bộ nhớ Runtime; không tạo enum/state mới trong Database và không đưa vào WorkerSession lifecycle.  
\#\#\# 4.2. Luồng chuẩn  
Khởi động Attempt:  
Worker đủ N/N → PROVISIONING → Runtime gửi DatasetAssignment → mỗi Worker cache và verify dữ liệu theo cache\_scope → N/N SHARD\_READY → MODEL\_SYNCING → N/N READY → freeze membership → RUNNING.  
Mỗi synchronized step:  
1\. WorkloadScheduler trả active plan đã được cố định cho epoch hiện tại.  
2\. BatchScheduler lấy đúng K Work Unit toàn cục tại RecoveryCursor hiện tại; tập K unit này chỉ phụ thuộc dataset, seed, epoch và batch ordinal, không phụ thuộc policy equal hay dbs.  
3\. BatchScheduler chia K Work Unit theo số lượng k\_i trong active plan và Runtime gửi STEP\_START(work\_units\[\]) cho từng Worker.  
4\. Worker chỉ load đúng work\_units\[\] đã nhận, tính gradient từng Work Unit và gộp theo sample\_count thành đúng một contribution.  
5\. StrictBSP nhận đủ N/N contribution hợp lệ → GradientAggregator tổng hợp có trọng số → UpdateEngine cập nhật canonical model đúng một lần.  
6\. Runtime broadcast parameter mới → nhận đủ N/N PARAMETER\_APPLIED → ghi checkpoint blocking.  
7\. Chỉ khi checkpoint thành công thì step chuyển COMMITTED, RecoveryCursor mới được advance và statistics của step mới được ghi cho DBS.  
Tại ranh giới epoch, nếu policy là dbs và epoch vừa hoàn tất có statistics đầy đủ, Runtime tính WorkloadPlan cho epoch kế tiếp. WorkloadPlan được cố định suốt một epoch và không thay đổi giữa các step.  
Khi schedule hết và step cuối đã COMMITTED, Attempt chuyển COMPLETING → COMPLETED.

\#\# 5\. Work Unit

\#\#\# 5.1. Định nghĩa V1

Để tránh xây thêm định dạng dữ liệu không cần thiết, V1 dùng chính physical batch đã materialize trong Dataset Build làm Work Unit.

Một Work Unit được nhận diện bởi:

WorkUnitRef {  
  shard\_id  
  batch\_id  
  sample\_count  
}

Work Unit phải bất biến và đã được kiểm tra hash theo Dataset Build hiện có.

Không tạo thêm storage chunk format, chunk index database hoặc một Dataset Manager pipeline mới chỉ để chạy DBS.

\#\#\# 5.2. Kích thước Work Unit

Gọi:  
\- N: số Worker cố định của Attempt.  
\- U: số mẫu của một Work Unit; V1 lấy từ dataset.batch\_size của Dataset Build.  
\- K: số Work Unit của một bước toàn cục.  
\- B \= U x K: số mẫu mục tiêu của một bước toàn cục.

Điều kiện:  
\- với policy \= equal: K \>= N;  
\- với policy \= dbs: K \> N; nếu K \= N thì ràng buộc mỗi Worker có ít nhất một Work Unit buộc k\_i \= 1 cho mọi Worker, nên DBS không còn khả năng thích ứng;  
\- Dataset Build phải có đủ Work Unit đầy đủ cho ít nhất một bước;  
\- Work Unit cuối có sample\_count khác U không tham gia tập Work Unit thích ứng V1.

Nếu muốn giữ global batch tương đương cấu hình cũ nhưng có granularity nhỏ hơn, tạo Dataset Build với U nhỏ hơn và chọn K sao cho B không đổi.

\#\# 6\. Dataset provisioning V1

Thiết kế trước có hướng cache/prefetch theo khối. V1 chọn cách đơn giản hơn để tránh xây hệ thống prefetch nền phức tạp:

\- trong PROVISIONING, Runtime gửi DatasetAssignment với cache\_scope \= "all\_shards" cho Work Unit mode; mỗi Worker tải và xác minh toàn bộ shard của pinned Dataset Build trước khi báo SHARD\_READY;  
\- ShardCache hiện có vẫn dùng để lưu/verify từng shard;  
\- thêm lớp DatasetCache để quản lý nhiều CachedShard;  
\- SHARD\_READY giữ nguyên message/state hiện có; trong cache\_scope \= "all\_shards", SHARD\_READY có nghĩa toàn bộ artifact cần cho Dataset Build đã được cache và verify; không thêm state mới chỉ cho DBS;  
\- sau N/N SHARD\_READY và model synchronization, các step chỉ đọc local cache;  
\- Dataset Manager không được gọi trong synchronized step.

Cách này tốn dung lượng hơn nhưng phù hợp quy mô demo, đơn giản và bảo toàn ranh giới training path. Selective prefetch là tối ưu hóa về sau, không thuộc V1.

shard\_id từ đây là định danh phân vùng lưu trữ, không còn đồng nghĩa worker\_id trong lúc chia Work Unit.

\#\# 7\. Thuật toán DBS

Nguồn: Q. Ye et al., "DBS: Dynamic Batch Size for Distributed Deep Neural Network Training", arXiv:2007.11831.

\#\#\# 7.1. Epoch đầu

Epoch đầu chia gần đều vì chưa có số đo lịch sử.

Kế hoạch Equal:  
\- mọi Worker có ít nhất 1 Work Unit;  
\- K Work Unit được chia cân bằng, tie-break theo worker\_id.

\#\#\# 7.2. Đo hiệu năng

Với Worker i ở epoch j:

d\_i^j \= samples\_i^j / total\_samples^j

t\_i^j \= tổng compute\_ms của các step đã COMMITTED trong epoch

p\_i^j \= d\_i^j / t\_i^j

Chỉ dùng step đã vượt qua StrictBSP \+ PARAMETER\_APPLIED \+ checkpoint và được COMMITTED.

compute\_ms gồm:  
\- đọc Work Unit từ local verified cache;  
\- forward/loss/backward;  
\- gộp gradient cục bộ.

compute\_ms không gồm:  
\- upload gradient;  
\- chờ barrier;  
\- nhận/apply parameter;  
\- HTTP tải dataset.

\#\#\# 7.3. Tỉ lệ cho epoch sau

p\_sum \= sum(p\_i)

r\_i \= p\_i / p\_sum

q\_i \= r\_i x K

q\_i là số Work Unit lý tưởng trước khi chuyển sang số nguyên.

\#\#\# 7.4. Chuyển tỉ lệ DBS sang số Work Unit

Việc chuyển q\_i sang số nguyên chỉ là bước lượng tử hóa do kiến trúc Work Unit, không phải một heuristic adaptive khác.

Ràng buộc:  
\- sum(k\_i) \= K;  
\- k\_i \>= 1;  
\- cố gắng gần q\_i nhất;  
\- kết quả xác định được.

V1 dùng projection theo sai số bình phương:  
1\. khởi tạo mỗi Worker 1 Work Unit;  
2\. còn K-N Work Unit;  
3\. mỗi lần thêm 1 Work Unit cho Worker làm tăng tổng sai số (k\_i \- q\_i)^2 ít nhất;  
4\. nếu bằng nhau, worker\_id nhỏ hơn được chọn.

DBS quyết định q\_i. Projection chỉ chuyển q\_i thành nghiệm nguyên hợp lệ cho PBL4.

\#\#\# 7.5. Ví dụ kiểm thử paper

Với U=1, K=B=64 và ideal batch sizes:

\[13.7, 16.5, 19.6, 14.2\]

kết quả phải là:

\[14, 16, 20, 14\]

Đây là golden test bắt buộc.

\#\# 8\. Lập lịch dữ liệu

Gọi M là số Work Unit hợp lệ của Dataset Build. BatchScheduler tạo một thứ tự toàn cục trên M Work Unit theo:

training\_seed \+ epoch \+ shard\_id \+ batch\_id

V1 dùng cơ chế drop\_last ở mức bước toàn cục: steps\_per\_epoch \= floor(M / K). Mỗi bước lấy đúng K Work Unit; M mod K Work Unit cuối trong thứ tự của epoch đó không được lập lịch. Không tạo bước cuối nhỏ hơn K và không chuyển phần dư sang epoch sau.

WorkloadScheduler chỉ cho biết:

worker\_id \-\> số Work Unit

BatchScheduler mới ánh xạ số lượng đó vào K Work Unit cụ thể.

Hai policy equal và dbs với cùng dataset, seed, epoch, step phải xử lý cùng một tập Work Unit toàn cục. Chúng chỉ khác cách chia tập đó cho Worker.

Điều này giúp so sánh công bằng và giữ training semantics.

\#\# 9\. Tính gradient trên Worker

ModelAdapter hiện trả gradient trung bình của một batch và sample\_count.

Không cần thêm API mới vào PyTorchAdapter.

Nếu Worker nhận nhiều Work Unit u:

g\_local \= sum(n\_u x g\_u) / sum(n\_u)

loss\_local cũng gộp theo sample\_count.

Worker gửi:  
\- một gradient duy nhất;  
\- sample\_count \= tổng số mẫu của mọi Work Unit đã xử lý;

\- compute\_ms.

Runtime tiếp tục tính:

g\_global \= sum(n\_i x g\_local\_i) / sum(n\_i)

Vì vậy cách chia Work Unit không làm thay đổi gradient trung bình của cùng tập mẫu toàn cục, ngoài sai khác số học dấu chấm động do thứ tự cộng.

\#\# 10\. Giao thức DTP/1

Không tạo DTP/2 chỉ cho feature này.

Giữ:  
\- 48-byte framing hiện tại;  
\- message catalogue hiện tại;  
\- tensor transfer META/CHUNK/END;  
\- protocol\_version \= 1\.

Chỉ mở rộng payload ở nơi cần để Worker biết chính xác Work Unit phải xử lý. Không thêm field định danh/hash mới nếu Runtime đã giữ assignment canonical của step.

DatasetAssignment:  
\- giữ field hiện có;  
\- cache\_scope là field OPTIONAL để tương thích wire cũ: vắng mặt được hiểu là "assigned\_shard"; Work Unit mode MUST gửi "all\_shards". Field này chỉ phục vụ provisioning, không thuộc thuật toán DBS.

ShardReady:  
\- giữ nguyên message/state SHARD\_READY và không thêm field đếm mới;  
\- với cache\_scope \= "all\_shards", Worker chỉ gửi SHARD\_READY sau khi toàn bộ shard cần thiết đã cache và verify thành công.

StepStart:  
\- thêm work\_units\[\];  
\- giữ shard\_id/batch\_id hiện có bằng Work Unit đầu tiên trong giai đoạn migration để tương thích với code cũ;

GradientMeta:  
\- không thêm trường định danh assignment mới; Runtime dùng OperationContext và BatchAssignment canonical đang mở;  
\- sample\_count là tổng sample thực tế;  
\- compute\_ms phải được gửi thật, không chỉ tồn tại trong schema.

Các field shard\_id/batch\_id cũ được giữ tạm và mang identity của Work Unit đầu tiên để tương thích/logging. Runtime tiếp tục validate attempt/session/operation/model version, batch\_ordinal và sample\_count theo assignment canonical; Worker phải load đúng toàn bộ work\_units\[\] trước khi compute. Không dùng một hash do Worker echo lại để chứng minh Worker đã xử lý đúng dữ liệu.

\#\# 11\. Workload policy trong training contract

training\_strategy vẫn strict\_bsp.

Resolved contract thêm phần workload tối thiểu:

workload {  
  policy: "equal" | "dbs"  
  work\_units\_per\_step: K  
}

Operator chỉ nhập:  
\- workload\_policy;  
\- work\_units\_per\_step.

U luôn lấy từ dataset.batch\_size đã có trong resolved contract; B \= U × K được Runtime tính ra khi cần. Không lưu lặp work\_unit\_size hoặc global\_batch\_size trong workload contract.

Mặc định để giữ hành vi cũ:  
\- policy \= equal;  
\- K \= expected\_workers.

Với dbs:  
\- K phải được khai báo;  
\- K \> expected\_workers.

\#\# 12\. Checkpoint và resume

Không tạo Checkpoint V2 chỉ để lưu số đo DBS.

Checkpoint V1 hiện đã giữ:  
\- model;  
\- model\_version;  
\- contract\_hash;  
\- dataset identity;  
\- RecoveryCursor(epoch, next\_batch\_ordinal).

workload policy và K nằm trong frozen contract nên đã được contract\_hash bảo vệ.

Các số đo p\_i, compute\_ms tích lũy và phân phối hiện tại chỉ ảnh hưởng hiệu năng, không ảnh hưởng correctness của tập Work Unit toàn cục.

Quy tắc resume:  
\- không persist WorkloadPlan hoặc statistics DBS vào checkpoint;  
\- nếu RecoveryCursor ở đầu epoch (next\_batch\_ordinal \= 0), epoch đó dùng Equal và thu statistics đầy đủ; epoch kế tiếp mới dùng DBS;  
\- nếu resume giữa epoch, phần còn lại của epoch hiện tại dùng Equal nhưng không thu statistics cho DBS; epoch đầy đủ kế tiếp tiếp tục dùng Equal để đo lại; DBS chỉ bật từ epoch sau đó;  
\- policy \= equal luôn dùng Equal và không cần statistics DBS.

Nhờ đó không phải thay checkpoint schema và không dùng số đo thiếu nửa epoch.

\#\# 13\. Trạng thái và lỗi

Worker disconnect hoặc heartbeat timeout:  
\- giữ semantics StrictBSP hiện tại;  
\- Attempt fail; không tự redistribute giữa step.

DBS stats không hợp lệ khi Runtime cần tính plan cho epoch kế tiếp:  
\- compute\_ms \<= 0, NaN/inf hoặc thiếu Worker \-\> Attempt FAILED trước khi mở epoch kế tiếp;  
\- không silent fallback sang Equal hoặc một công thức khác.

Dataset cache lỗi:  
\- lỗi trong provisioning \-\> Worker không được vào SHARD\_READY và Attempt không được RUNNING;  
\- cache miss/corrupt sau khi đã RUNNING \-\> Worker FAILED; StrictBSP fixed membership mất thành viên nên Attempt FAILED.

K không hợp lệ hoặc không đủ Work Unit:  
\- equal yêu cầu K \>= N; dbs yêu cầu K \> N;  
\- nếu M \< K hoặc steps\_per\_epoch \= 0 thì validation fail trước RUNNING.

\#\# 14\. Những gì cố ý không làm

V1 không xây:  
\- dbs\_bsp;  
\- DbsStrictBSP;  
\- DTP/2;  
\- Checkpoint V2;  
\- bảng DB riêng cho DBS;  
\- EMA/smoothing;  
\- db\_min\_batch;  
\- rebalance mỗi vài step;  
\- threshold gain;  
\- hardware score;  
\- network-aware cost formula;  
\- dynamic Work Unit size;  
\- storage chunk format mới;  
\- prefetch daemon phức tạp;  
\- auto elastic membership;  
\- WebUI dashboard mới như điều kiện bắt buộc;  
\- thay optimizer hoặc update policy.

\#\# 15\. Tiêu chí thiết kế hoàn thành

Thiết kế đạt khi:  
\- DBS nằm ở workload scheduling, không nằm trong synchronization strategy;  
\- Work Unit dùng được với artifact hiện tại;  
\- tổng K và global batch được giữ cố định;  
\- Worker nhiều Work Unit vẫn gửi một contribution;  
\- weighted local \+ global aggregation đúng toán học;  
\- StrictBSP N/N không đổi;  
\- Dataset Manager ra khỏi synchronized step;  
\- checkpoint V1 vẫn dùng được;  
\- resume có quy tắc đo lại rõ ràng;  
\- code có thể triển khai mà không phải tự phát minh thêm state, protocol version hoặc thuật toán.  
