\# NODE\_AGENT\_IMPLEMENTATION\_PLAN.md

\> Trạng thái: Kế hoạch triển khai chuẩn cho Node Agent / WAN orchestration.  
\> Ngày đối chiếu codebase: 24/09/2026.  
\> Codebase được rà trên repository Liinh-Git/PBL4-Distributed-Training, nhánh api-review, head d33b58fc434cd9da017bcf67d2ffda5322bebde0.  
\> Tài liệu này là projection từ thiết kế xuống code. Không được dùng để tự thay đổi kiến trúc.

\#\# 0\. Quy tắc đọc trước khi implement

\#\#\# 0.1. Tài liệu phải dùng

Agent triển khai phải đọc theo thứ tự:  
1\. 02\. Mô hình miền.  
2\. 03\. Mô hình dữ liệu.  
3\. 04\. Cấu trúc mã nguồn.  
4\. NODE\_AGENT\_DESIGN.md trong thư mục Review.  
5\. docs/IMPLEMENTATION\_CONTRACT.md.  
6\. AGENTS.md và AGENTS.md lồng trong package nếu có.  
7\. Tài liệu này.  
8\. Codebase hiện tại.

\#\#\# 0.2. Tài liệu đã cũ, không dùng để quyết định implementation

Không dùng các tài liệu sau làm nguồn chuẩn nếu chúng khác tài liệu mới:  
\- 01\. Thiết kế chi tiết — Node, WAN & phân phối công việc thích ứng của tuần 14/09–20/09.  
\- 03\. Hướng triển khai — cấp mã nguồn của tuần 14/09–20/09.  
\- NODE\_AGENT\_DESIGN.md bản trước ngày 24/09/2026.  
\- NODE\_AGENT\_IMPLEMENTATION\_PLAN.md bản của An trước ngày 24/09/2026.  
\- Công thức adaptive cũ. Phần adaptive hiện chuyển sang DBS và không thuộc task Node Agent này.

Các tài liệu cũ chỉ có thể dùng để hiểu lịch sử hoặc lý do ra quyết định. Không copy enum, schema, token semantics hay file plan từ đó nếu chưa xuất hiện trong tài liệu mới.

\#\#\# 0.3. Nếu codebase đã đổi sau head được audit

Trước khi code:  
\- kiểm tra HEAD hiện tại;  
\- nếu các file được liệt kê dưới đây đã đổi, đọc diff trước;  
\- bảo toàn semantics của NODE\_AGENT\_DESIGN.md;  
\- không tự “hòa giải” xung đột bằng cách invent state/protocol mới;  
\- nếu thay đổi mới làm plan này không còn khớp, dừng ở điểm xung đột và cập nhật plan/review trước khi code tiếp.

\#\# 1\. Mục tiêu implementation

Sau khi hoàn thành, hệ thống phải hỗ trợ:  
\- Node đăng ký vào Backend bằng mã dùng một lần;  
\- Node Agent mở WSS outbound và báo heartbeat/tài nguyên;  
\- Backend chọn expected\_workers Node cho một Attempt;  
\- Backend tạo WorkerAllocation;  
\- Backend gửi START\_WORKER đến Agent;  
\- Agent spawn pbl4-worker đúng một lần cho mỗi allocation\_id;  
\- Worker kết nối DTP tới advertised Runtime endpoint;  
\- Runtime xác thực Worker trước WorkerRegistry.register();  
\- Runtime vẫn tự cấp worker\_id/session\_id;  
\- Worker/Runtime training path hiện tại không đổi;  
\- Agent restart hoặc Backend restart không tự giết Worker đang chạy.

Không implement DBS, Work Unit, adaptive scheduling, prefetch redesign trong tài liệu này.

\#\# 2\. Sự thật của codebase hiện tại phải bảo toàn

\#\#\# 2.1. Repository và package

Các process hiện tại:  
\- pbl4-runtime  
\- pbl4-worker  
\- pbl4-backend  
\- pblctl

pyproject.toml chưa có pbl4-agent.

Dependency direction hiện tại trong AGENTS.md:  
\- runtime \-\> protocol, transport, management\_protocol, common  
\- worker \-\> protocol, transport, adapter, common  
\- management\_backend \-\> management\_protocol, common  
\- all packages \-\> common

Node Agent không được import runtime, management\_backend, database libraries hoặc torch.

\#\#\# 2.2. Backend runtime config hiện tại

src/pbl4/management\_backend/config.py đã có:  
\- runtime\_host  
\- runtime\_advertised\_host  
\- runtime\_dtp\_port  
\- runtime\_management\_port  
\- property dtp\_advertised\_host

MUST KEEP:  
\- START\_WORKER phải dùng settings.dtp\_advertised\_host \+ runtime\_dtp\_port.  
\- Không tạo một nguồn cấu hình advertised host thứ hai trong Node Agent.

\#\#\# 2.3. DTP HELLO hiện tại

src/pbl4/protocol/messages.py::Hello hiện yêu cầu:  
\- node\_label  
\- client\_instance\_id  
\- role  
\- protocol\_version  
\- framework\_adapter  
\- supported\_tensor\_encoding  
\- supported\_strategy\_capabilities

src/pbl4/worker/worker\_client.py hiện tạo client\_instance\_id bằng uuid4() khi connect. TARGET: chuyển việc sinh ID này ra vòng đời Worker process để mỗi OS process chỉ có đúng một client\_instance\_id.

CHANGE:  
\- bổ sung managed admission fields dưới dạng OPTIONAL để không phá manual/dev mode:  
  \- attempt\_id  
  \- allocation\_id  
  \- node\_id  
  \- worker\_join\_token

DO NOT:  
\- bỏ các field hiện có;  
\- thêm credential vào binary/tensor header;  
\- cho Worker tự gửi worker\_id.

\#\#\# 2.4. ParameterServer hiện tại

src/pbl4/runtime/parameter\_server.py::\_serve\_connection() hiện:  
1\. đọc HELLO;  
2\. validate protocol;  
3\. gọi WorkerRegistry.register();  
4\. mới tạo connection/HELLO\_ACK.

Đây là điểm bắt buộc phải đổi.

TARGET:  
1\. đọc/validate HELLO;  
2\. nếu Runtime đang require managed admission thì verify token và claims;  
3\. reject trước khi register nếu sai;  
4\. kiểm tra allocation\_id chưa từng được admit trong Attempt hiện tại;  
5\. sau đó mới WorkerRegistry.register().

\#\#\# 2.5. Worker Session state hiện tại

src/pbl4/runtime/worker\_registry.py và migration 0001 đang dùng:  
CONNECTING, REGISTERING, PROVISIONING, SHARD\_READY, MODEL\_SYNCING, READY, DISCONNECTED, FAILED.

MUST KEEP nguyên tập state này.

Không thêm ACTIVE/CLOSED/ABORTED vào worker\_sessions.state.

\#\#\# 2.6. Training contract hiện tại

contract\_resolver.py V1 hiện freeze:  
\- dataset  
\- model  
\- training  
\- synchronization  
\- update\_policy  
\- checkpoint\_policy  
\- protocols

training.training\_seed đã tồn tại.  
synchronization.expected\_workers hiện là source of truth cho số Worker.

DO NOT:  
\- thêm join token hoặc allocation list vào resolved\_contract;  
\- thêm resource scheduling fields vào frozen contract trong task này;  
\- hardcode initialization\_seed=42.

\#\#\# 2.7. MCP START\_ATTEMPT hiện tại

src/pbl4/management\_protocol/messages.py::StartAttempt hiện chứa:  
\- command\_id  
\- job\_id  
\- attempt\_id  
\- execution\_mode  
\- resolved\_contract  
\- contract\_hash  
\- resume\_from\_checkpoint\_id  
\- requested\_at

Với thiết kế join token ký ngắn hạn, KHÔNG cần sửa START\_ATTEMPT để mang token/hash.

Lý do:  
\- Runtime tự verify token bằng admission secret dùng chung với Backend;  
\- token có signed claims attempt\_id/allocation\_id/node\_id/expiry;  
\- resolved\_contract tiếp tục sạch và immutable.

Không implement phương án cũ authorized\_worker\_token\_hashes trong contract\["synchronization"\].

\#\# 3\. Quyết định implementation V1 đã khóa

\#\#\# 3.1. Cluster scheduling V1

Không xây scheduler chấm điểm phức tạp.

Mỗi active Attempt:  
\- tối đa một managed Worker trên một Node;  
\- chọn đúng expected\_workers Node đang ONLINE và chưa có active Allocation;  
\- thứ tự lựa chọn deterministic, ví dụ sort theo node\_id;  
\- trên Node, ưu tiên cuda:0 khi telemetry/capability báo có GPU khả dụng; nếu không thì cpu.

CPU/RAM/VRAM vẫn được lưu để hiển thị và làm nền cho mở rộng sau; không dùng chúng để invent score trong V1.

\#\#\# 3.2. Worker admission V1

Dùng short-lived signed token.

Module thuần stdlib chung:  
src/pbl4/common/worker\_admission.py

Payload canonical:  
{  
  "v": 1,  
  "attempt\_id": "...",  
  "allocation\_id": "...",  
  "node\_id": "...",  
  "exp": \<unix\_seconds\>,  
  "nonce": "\<random\_hex\>"  
}

Encoding:  
\- canonical JSON: sort\_keys=True, separators=(",", ":"), UTF-8;  
\- payload\_b64 \= URL-safe Base64 không padding;  
\- signature \= HMAC-SHA256(secret, payload\_bytes);  
\- signature\_b64 \= URL-safe Base64 không padding;  
\- token \= payload\_b64 \+ "." \+ signature\_b64.

Issue:  
\- nonce \= secrets.token\_hex(16);  
\- TTL mặc định 600 giây;  
\- Backend không lưu plaintext token;  
\- token chỉ được tạo ngay trước START\_WORKER.

Verify:  
\- parse đúng 2 phần;  
\- decode JSON;  
\- v \== 1;  
\- compare\_digest(signature);  
\- exp \>= current time;  
\- attempt\_id/allocation\_id/node\_id trong token phải trùng HELLO;  
\- Runtime current attempt\_id phải trùng token.

Secret:  
\- env PBL4\_WORKER\_ADMISSION\_SECRET;  
\- Backend và Runtime dùng cùng secret;  
\- secret không được log;  
\- không truyền qua CLI.

Reconnect policy V1:  
\- Không implement Worker DTP reconnect trong cùng Attempt.  
\- Token phải còn hạn tại HELLO admission đầu tiên.  
\- Sau khi allocation\_id đã admit, mọi HELLO thứ hai của cùng allocation\_id đều bị reject trong Attempt đó.  
\- DTP disconnect làm Worker Session terminal và Runtime/Coordinator xử lý failure theo StrictBSP hiện có; membership không shrink.  
\- RETRY/RESUME tạo Attempt/Allocation mới và token mới.  
\- Không tạo token-refresh endpoint, reconnect lease hay rank-rebind subsystem.

\#\#\# 3.3. Manual/dev Worker compatibility

Managed fields trong DTP Hello là OPTIONAL.

Runtime có:  
\- require\_worker\_admission: bool.

Production/multi-machine Node Agent mode:  
\- require\_worker\_admission \= true;  
\- thiếu token \=\> reject.

Manual/dev mode:  
\- cho phép explicit \--allow-unmanaged-workers;  
\- khi bật flag này, HELLO cũ vẫn được chấp nhận.

Không để unmanaged mode bật ngầm trong production configuration.

\#\# 4\. File plan chính xác

\#\# 4.1. Package giao thức Agent dùng chung

\#\#\# ADD: src/pbl4/agent\_protocol/\_\_init\_\_.py

Chỉ export DTO/parser cần thiết. Không chứa network client/server.

\#\#\# ADD: src/pbl4/agent\_protocol/messages.py

Responsibility:  
\- wire schema JSON giữa Agent và Backend;  
\- không import node\_agent hoặc management\_backend;  
\- chỉ stdlib \+ common errors nếu cần.

Envelope:  
\- protocol\_version: int \= 1  
\- message\_type: str  
\- message\_id: str  
\- correlation\_id: str | None  
\- node\_id: str  
\- sent\_at: str  
\- payload: object

Message types:  
\- AGENT\_HELLO  
\- HELLO\_ACK  
\- HEARTBEAT  
\- RESOURCE\_SNAPSHOT  
\- COMMAND  
\- COMMAND\_ACK  
\- WORKER\_STATUS

MUST:  
\- reject unknown root fields;  
\- reject unknown message\_type;  
\- validate command-specific payload;  
\- không cho phép raw gradient/parameter/tensor fields.

Payload tối thiểu:

AGENT\_HELLO:  
\- agent\_version  
\- platform  
\- active\_allocations: list\[{allocation\_id, attempt\_id, local\_state, pid|null}\]  
\- active\_allocations chỉ chứa local\_state STARTING hoặc RUNNING; STOPPED/FAILED không được quảng bá là active

HELLO\_ACK:  
\- heartbeat\_interval\_seconds  
\- telemetry\_interval\_seconds

HEARTBEAT:  
\- active\_allocations\_count

RESOURCE\_SNAPSHOT:  
\- cpu\_utilization\_pct  
\- ram\_used\_bytes  
\- ram\_total\_bytes  
\- gpus: list\[{index, gpu\_utilization\_pct|null, vram\_used\_bytes|null, vram\_total\_bytes|null}\]

COMMAND / START\_WORKER:  
\- command\_id  
\- command\_type \= START\_WORKER  
\- allocation\_id  
\- attempt\_id  
\- runtime\_host  
\- runtime\_port  
\- device  
\- initialization\_seed

worker\_join\_token KHÔNG đặt trực tiếp trong JSON loggable payload nếu client logging có thể dump message.  
Cách triển khai yêu cầu:  
\- payload vẫn cần mang token qua WSS;  
\- serializer/parser phải hỗ trợ field worker\_join\_token;  
\- mọi \_\_repr\_\_/logging của COMMAND phải redact giá trị này;  
\- không log raw incoming/outgoing COMMAND.

COMMAND / STOP\_WORKER:  
\- command\_id  
\- command\_type \= STOP\_WORKER  
\- allocation\_id  
\- grace\_period\_seconds  
\- force

COMMAND\_ACK:  
\- command\_id  
\- allocation\_id  
\- status: ACCEPTED | REJECTED  
\- error\_code nullable  
\- error\_message nullable

WORKER\_STATUS:  
\- allocation\_id  
\- attempt\_id  
\- actual\_state: STARTED | ENDED | FAILED  
\- exit\_code nullable  
\- failure\_code nullable  
\- failure\_message nullable

Không thêm generic plugin/event framework.

\#\# 4.2. Shared admission token

\#\#\# ADD: src/pbl4/common/worker\_admission.py

Symbols:  
\- class WorkerAdmissionError(PBL4Error)  
\- issue\_worker\_join\_token(...)  
\- verify\_worker\_join\_token(...)  
\- dataclass WorkerAdmissionClaims

MUST:  
\- pure stdlib: base64, hashlib, hmac, json, secrets, time;  
\- deterministic serialization của payload;  
\- compare\_digest;  
\- reject malformed Base64/JSON/field type;  
\- reject expired token;  
\- không return secret;  
\- tests bao phủ tampered payload/signature/expired/mismatched claims.

\#\# 4.3. Node Agent package

\#\#\# ADD: src/pbl4/node\_agent/\_\_init\_\_.py

Không tạo version domain riêng.  
Nếu cần version, import package version hiện có từ pbl4.\_\_init\_\_.

\#\#\# ADD: src/pbl4/node\_agent/config.py

NodeAgentConfig:  
\- backend\_url  
\- var\_dir  
\- heartbeat\_interval\_seconds  
\- telemetry\_interval\_seconds  
\- reconnect\_min\_seconds  
\- reconnect\_max\_seconds  
\- log\_level

Enrollment code không lưu trong config dài hạn.  
CLI enroll nhận code tại invocation hoặc qua env tạm thời, không ghi lại.

\#\#\# ADD: src/pbl4/node\_agent/identity.py

NodeIdentity:  
\- node\_id  
\- node\_secret

Functions:  
\- load\_identity(var\_dir)  
\- save\_identity(var\_dir, identity)  
\- identity\_path(var\_dir)

POSIX:  
\- mkdir user-only nếu có thể;  
\- chmod identity file 0600\.

Windows:  
\- dùng user-local directory;  
\- không cố viết ACL framework phức tạp trong V1;  
\- không log secret.

\#\#\# ADD: src/pbl4/node\_agent/enrollment.py

Functions:  
\- enroll(backend\_url, enrollment\_code, static\_capabilities) \-\> NodeIdentity  
\- load\_or\_fail / helper phù hợp

POST /api/v1/nodes/enroll  
Authorization: Bearer \<one-time-code\>

Response phải lấy node\_id \+ node\_secret và save identity.

Không tự enroll lại khi đã có identity trừ explicit operator command.

\#\#\# ADD: src/pbl4/node\_agent/telemetry.py

Dùng psutil.  
GPU:  
\- thử pynvml;  
\- ImportError/NVML failure \=\> gpus=\[\] hoặc partial data;  
\- không crash Agent.

Functions/class:  
\- collect\_static\_capabilities()  
\- sample\_resources()

Không chạy shell nvidia-smi loop nếu pynvml unavailable.

\#\#\# ADD: src/pbl4/node\_agent/supervisor.py

Local responsibility only.

LocalAllocationRecord tối thiểu:  
\- allocation\_id  
\- attempt\_id  
\- pid  
\- create\_time  
\- local\_state  
\- created\_at  
\- exit\_code nullable

Không đồng nhất local\_state với DB actual\_state.

WorkerProcessSupervisor:  
\- reconcile\_on\_startup()  
\- spawn\_worker(command)  
\- stop\_worker(allocation\_id, grace\_period\_seconds, force)  
\- poll()  
\- list\_records()

Duplicate START:  
\- allocation\_id là idempotency key; không cần command-history subsystem;  
\- local\_state STARTING/RUNNING \=\> ACK ACCEPTED no-op, không spawn mới;  
\- local\_state STOPPED/FAILED \=\> ACK REJECTED, không hồi sinh Allocation; Backend phải tạo Allocation mới nếu muốn chạy lại.

Spawn:  
\- spawn Worker bằng \[sys.executable, "-m", "pbl4.worker.entrypoint", ...\] để dùng đúng Python environment của Agent;  
\- truyền flags không bí mật;  
\- PBL4\_WORKER\_JOIN\_TOKEN qua env;  
\- không log env token.

POSIX:  
\- start\_new\_session=True.

Windows:  
\- CREATE\_NEW\_PROCESS\_GROUP;  
\- không bắt buộc DETACHED\_PROCESS nếu nó làm mất khả năng điều khiển/IO không cần thiết; ưu tiên cấu hình đơn giản đủ để Agent restart không kéo Worker chết.  
\- xác nhận bằng test thực tế trên Windows trước khi thêm cờ khác.

Reconcile:  
\- tối thiểu PID \+ create\_time;  
\- cmdline check nếu có;  
\- không bịa exit\_code khi Agent không phải parent và process đã mất.

Local process state được khóa đúng 4 giá trị:  
\- STARTING: intent đã ghi, chưa xác nhận process sống;  
\- RUNNING: PID \+ create\_time đã được xác minh và process còn sống;  
\- STOPPED: process kết thúc trong stop flow có chủ đích;  
\- FAILED: spawn lỗi, process thoát ngoài ý muốn, hoặc reconcile sau restart không xác minh được process cũ.

Transition tối thiểu:  
STARTING \-\> RUNNING \-\> STOPPED  
STARTING/RUNNING \-\> FAILED

Idempotency:  
\- allocation\_id là khóa idempotency của START\_WORKER;  
\- START\_WORKER khi STARTING/RUNNING \=\> ACK ACCEPTED no-op;  
\- START\_WORKER khi STOPPED/FAILED \=\> ACK REJECTED;  
\- STOP\_WORKER lặp lại khi process đã STOPPED/FAILED \=\> ACK ACCEPTED no-op và trả trạng thái hiện tại;  
\- command\_id chỉ dùng correlation/tracing, không cần command-history storage.

Reconcile không chắc chắn:  
\- không attach process nếu PID/create\_time không khớp;  
\- local\_state \= FAILED, exit\_code \= null;  
\- sau khi WSS reconnect, Agent gửi WORKER\_STATUS FAILED cho record vừa bị reconcile thành FAILED;  
\- không bịa historical exit code.

\#\#\# ADD: src/pbl4/node\_agent/client.py

NodeAgentClient:  
\- outbound WSS /ws/v1/nodes/{node\_id}/control;  
\- Authorization: Bearer \<node\_secret\>;  
\- reconnect exponential backoff bounded;  
\- send AGENT\_HELLO sau connect;  
\- heartbeat loop;  
\- telemetry loop;  
\- receive command;  
\- call supervisor;  
\- send COMMAND\_ACK / WORKER\_STATUS.

MUST:  
\- Worker tiếp tục sống khi WSS disconnect;  
\- reconnect không spawn lại worker;  
\- không retry command bằng cách tự tạo allocation mới;  
\- không truy cập DB.

\#\#\# ADD: src/pbl4/node\_agent/entrypoint.py

CLI:  
pbl4-agent enroll \--backend-url ... \--code ...  
pbl4-agent start \--backend-url ...  
pbl4-agent status

start:  
\- yêu cầu identity đã tồn tại;  
\- nếu chưa, báo rõ cần enroll trước;  
\- không tự dùng static enrollment secret.

\#\#\# MODIFY: pyproject.toml

ADD optional dependency:  
node-agent \= \[  
  "psutil\>=5.9.0",  
  "pynvml\>=11.5.0",  
  "websockets\>=12.0",  
  "httpx\>=0.27.0"  
\]

ADD script:  
pbl4-agent \= "pbl4.node\_agent.entrypoint:main"

Không đổi package version.

\#\# 4.4. Backend persistence

\#\#\# ADD migration: migrations/versions/0003\_add\_nodes\_and\_allocations.py

MUST:  
revision \= "0003\_add\_nodes\_and\_allocations"  
down\_revision \= "0002\_fix\_dsb\_null\_and\_idemp"

Không sửa migration 0001/0002.

\#\#\#\# Table node\_enrollment\_codes

Fields:  
\- code\_hash CHAR(64) PRIMARY KEY  
\- created\_at TIMESTAMPTZ NOT NULL  
\- expires\_at TIMESTAMPTZ NOT NULL  
\- used\_at TIMESTAMPTZ NULL

Invariant:  
\- code usable iff used\_at IS NULL and now \< expires\_at.

Không lưu plaintext code.

\#\#\#\# Table nodes

Fields:  
\- node\_id TEXT PK  
\- display\_name TEXT NOT NULL  
\- credential\_hash CHAR(64) NOT NULL  
\- credential\_created\_at TIMESTAMPTZ NOT NULL  
\- credential\_revoked\_at TIMESTAMPTZ NULL  
\- agent\_version TEXT NULL  
\- platform TEXT NULL  
\- capabilities\_jsonb JSONB NOT NULL  
\- latest\_resources\_jsonb JSONB NULL  
\- state TEXT NOT NULL  
\- enrolled\_at TIMESTAMPTZ NOT NULL  
\- last\_seen\_at TIMESTAMPTZ NULL

Node states V1:  
\- ONLINE  
\- OFFLINE  
\- REVOKED

Không tạo ENROLLED/DRAINED/DECOMMISSIONED trong V1.

Node lifecycle V1:  
\- create\_node sau enrollment thành công phải ghi state=OFFLINE;  
\- WSS auth \+ AGENT\_HELLO hợp lệ \-\> ONLINE;  
\- WSS disconnect không đổi state ngay;  
\- quá node\_heartbeat\_timeout\_seconds kể từ last\_seen\_at \-\> OFFLINE;  
\- ONLINE \-\> OFFLINE chỉ phản ánh control-plane liveness, không tự đổi active Allocation/Attempt;  
\- reconnect \+ AGENT\_HELLO hợp lệ \-\> ONLINE;  
\- thao tác revoke rõ ràng \-\> REVOKED;  
\- REVOKED là terminal cho node\_id hiện tại và mọi lần WSS auth sau đó bị từ chối;  
\- muốn dùng lại máy sau revoke phải enroll thành Node mới;  
\- revoke không tự đổi Attempt/Allocation và không tự phát STOP\_WORKER/ABORT\_ATTEMPT.

\#\#\#\# Table worker\_allocations

Fields:  
\- allocation\_id TEXT PK  
\- attempt\_id TEXT NOT NULL FK attempts(attempt\_id)  
\- node\_id TEXT NOT NULL FK nodes(node\_id)  
\- desired\_state TEXT NOT NULL  
\- actual\_state TEXT NOT NULL  
\- device TEXT NOT NULL  
\- resource\_allocation\_jsonb JSONB NOT NULL DEFAULT '{}'  
\- runtime\_endpoint TEXT NOT NULL  
\- created\_at TIMESTAMPTZ NOT NULL  
\- dispatched\_at TIMESTAMPTZ NULL  
\- started\_at TIMESTAMPTZ NULL  
\- ended\_at TIMESTAMPTZ NULL  
\- failure\_code TEXT NULL  
\- failure\_message TEXT NULL

desired\_state:  
\- RUNNING  
\- STOPPED

actual\_state:  
\- REQUESTED  
\- DISPATCHED  
\- STARTED  
\- ENDED  
\- FAILED

Partial unique index:  
\- một active allocation trên mỗi node trong V1;  
\- WHERE actual\_state IN ('REQUESTED','DISPATCHED','STARTED').

Không cần pid column; PID thuộc Agent local state.

\#\#\#\# Extend worker\_sessions

ADD nullable:  
\- node\_id TEXT FK nodes(node\_id)  
\- allocation\_id TEXT FK worker\_allocations(allocation\_id)

Không sửa worker\_sessions.state constraint.

\#\#\# ADD: src/pbl4/management\_backend/repositories/node\_repository.py

Functions tối thiểu:  
\- create\_node(...)  
\- get\_node(...)  
\- list\_nodes(...)  
\- update\_heartbeat(...)  
\- update\_resources(...)  
\- update\_state(...)

Repository chỉ SQL, không auth logic.

\#\#\# ADD: src/pbl4/management\_backend/repositories/node\_enrollment\_repository.py

Functions:  
\- create\_code\_hash(...)  
\- consume\_code\_if\_valid(...)  
\- get/cleanup nếu cần test

consume phải atomic:  
UPDATE ... SET used\_at=now  
WHERE code\_hash=? AND used\_at IS NULL AND expires\_at \> now  
RETURNING ...

Không SELECT rồi UPDATE tách rời.

\#\#\# ADD: src/pbl4/management\_backend/repositories/allocation\_repository.py

Functions:  
\- create\_allocation(...)  
\- get\_allocation(...)  
\- list\_for\_attempt(...)  
\- list\_active(...)  
\- update\_actual\_state(...)  
\- update\_desired\_state(...)  
\- release/terminal update helper

Không import service.

\#\# 4.5. Backend service layer

\#\#\# ADD: src/pbl4/management\_backend/services/node\_enrollment\_service.py

Responsibilities:  
\- issue one-time enrollment code;  
\- hash code;  
\- consume code atomically;  
\- create node\_id;  
\- issue node\_secret;  
\- store SHA-256(node\_secret);  
\- return plaintext node\_secret đúng một lần.

Use:  
\- secrets.token\_urlsafe(32) cho node\_secret;  
\- enrollment code cũng dùng CSPRNG đủ entropy;  
\- compare/hash rõ ràng.

\#\#\# ADD: src/pbl4/management\_backend/services/node\_service.py

Responsibilities:  
\- authenticate node\_secret;  
\- heartbeat;  
\- mark stale ONLINE \-\> OFFLINE;  
\- revoke\_node(node\_id);  
\- reject REVOKED node.

Không tạo WorkerAllocation trong NodeService.

NodeService MUST thực hiện đúng Node lifecycle đã khóa ở migration section:  
\- authenticate/reconnect không được tự đưa REVOKED về ONLINE;  
\- heartbeat chỉ cập nhật last\_seen\_at cho Node hợp lệ;  
\- stale-node check chỉ chuyển ONLINE \-\> OFFLINE;  
\- revoke chỉ chuyển ONLINE/OFFLINE \-\> REVOKED và yêu cầu NodeControlGateway đóng WSS đang active của node\_id đó;

Không có transition REVOKED \-\> ONLINE trong V1.

\#\#\# ADD: src/pbl4/management\_backend/services/cluster\_scheduler.py

Input:  
\- expected\_workers  
\- ONLINE nodes  
\- active allocations  
\- latest capabilities/resources

V1 algorithm:  
1\. lấy Node ONLINE;  
2\. bỏ node có active allocation;  
3\. sort ổn định theo node\_id;  
4\. yêu cầu len(candidates) \>= expected\_workers;  
5\. chọn N đầu;  
6\. device \= "cuda:0" nếu capabilities báo ít nhất một GPU; ngược lại "cpu".

Output:  
WorkerPlacementSpec\[\]:  
\- node\_id  
\- device

Không persistence trong ClusterScheduler.  
Không send WSS.  
Không dùng training throughput.

\#\#\# ADD: src/pbl4/management\_backend/services/allocation\_service.py

Responsibilities:  
\- create allocations from scheduler placements;  
\- build START\_WORKER command;  
\- issue short-lived join token;  
\- dispatch command through node gateway;  
\- state transitions;  
\- fail DISPATCHED allocations that exceed settings.worker\_start\_timeout\_seconds;  
\- stop allocations;  
\- release terminal allocations.

START\_WORKER values:  
\- allocation\_id  
\- attempt\_id  
\- runtime\_host \= settings.dtp\_advertised\_host  
\- runtime\_port \= settings.runtime\_dtp\_port  
\- device  
\- initialization\_seed \= job.resolved\_contract\["training"\]\["training\_seed"\]  
\- worker\_join\_token \= issue\_worker\_join\_token(...)

MUST assert:  
\- attempt\_id matches allocation;  
\- selected node is ONLINE;  
\- initialization\_seed exists and is int;  
\- token claim node\_id \== target node.

Do not accept seed from Agent or arbitrary client.

\#\# 4.6. Backend API / WSS gateway

\#\#\# ADD: src/pbl4/management\_backend/schemas/node.py

Schemas:  
\- NodeItem / NodeDetail  
\- EnrollmentCodeCreateRequest/Response  
\- NodeEnrollRequest/Response

Keep response envelope pattern consistent with existing API.

\#\#\# ADD: src/pbl4/management\_backend/api/nodes.py

Minimal endpoints:  
\- POST /api/v1/nodes/enrollment-codes  
\- POST /api/v1/nodes/enroll  
\- GET /api/v1/nodes  
\- GET /api/v1/nodes/{node\_id}  
\- POST /api/v1/nodes/{node\_id}/revoke

Full account/IAM authorization is out of scope; endpoint follows the current Management API trust model.  
Document clearly that production hardening would require operator auth.

\#\#\# ADD: src/pbl4/management\_backend/gateways/node\_control\_gateway.py

Responsibilities:  
\- accept WSS /ws/v1/nodes/{node\_id}/control;  
\- authenticate Bearer node\_secret before accepting logical session;  
\- maintain node\_id \-\> active websocket map;  
\- enforce one current control connection per node;  
\- handle AGENT\_HELLO/HEARTBEAT/RESOURCE\_SNAPSHOT/COMMAND\_ACK/WORKER\_STATUS;  
\- send START/STOP commands;  
\- update service/repository through service boundary, không SQL trực tiếp nếu tránh được.

Connection drop:  
\- mark connection absent;  
\- node becomes OFFLINE only by heartbeat timeout, không ngay lập tức kill allocations.

Revoke:  
\- khi NodeService chuyển Node sang REVOKED, gateway đóng WSS control hiện tại của node\_id nếu có;  
\- việc đóng WSS không tự STOP\_WORKER hoặc ABORT\_ATTEMPT.

Gateway does not touch Runtime/DTP.

\#\#\# MODIFY: src/pbl4/management\_backend/app.py

\- register nodes router;  
\- mount WSS route;  
\- initialize NodeControlGateway singleton/service during app lifespan nếu cần;  
\- start một asyncio maintenance task trong app lifespan, chạy mỗi node\_heartbeat\_interval\_seconds; mỗi vòng gọi NodeService mark stale ONLINE \-\> OFFLINE và AllocationService fail DISPATCHED allocations quá worker\_start\_timeout\_seconds; không thêm background framework riêng.

Không để WSS message bị HTTP response middleware can thiệp.

\#\#\# MODIFY: src/pbl4/management\_backend/config.py

ADD:  
\- worker\_admission\_secret: str | None \= env PBL4\_WORKER\_ADMISSION\_SECRET  
\- worker\_join\_token\_ttl\_seconds: int \= 600  
\- node\_heartbeat\_timeout\_seconds: float \= 15  
\- node\_heartbeat\_interval\_seconds: float \= 5  
\- node\_telemetry\_interval\_seconds: float \= 5  
\- worker\_start\_timeout\_seconds: float \= 60

MUST:  
\- không hardcode secret;  
\- Node-managed start phải fail rõ nếu worker\_admission\_secret thiếu.

KEEP:  
\- runtime\_advertised\_host / dtp\_advertised\_host hiện có.

\#\# 4.7. Tích hợp Attempt \-\> Allocation \-\> Agent

\#\#\# MODIFY: src/pbl4/management\_backend/services/attempt\_service.py

Không viết lại lifecycle hiện tại.

Chèn orchestration tại đường start/retry/resume theo nguyên tắc:

A. Trong transaction tạo Attempt/command:  
1\. Job phải READY/freeze đúng logic hiện tại.  
2\. Lấy expected\_workers từ resolved\_contract\["synchronization"\]\["expected\_workers"\].  
3\. ClusterScheduler.select(expected\_workers).  
4\. AllocationService.create allocations ở REQUESTED.  
5\. Tạo/persist START\_ATTEMPT control command theo flow hiện có.  
6\. Commit.

Nếu không đủ Node:  
\- raise NODE\_CAPACITY\_UNAVAILABLE;  
\- transaction rollback;  
\- không để Attempt/Allocation nửa chừng.

B. Dispatch Runtime:  
\- giữ nguyên durable-command-before-dispatch hiện tại;  
\- gửi START\_ATTEMPT bằng MCP hiện có;  
\- không thêm allocation/token vào resolved\_contract.

C. Chỉ sau khi Runtime chấp nhận START\_ATTEMPT:  
\- dispatch START\_WORKER cho tất cả Allocation.

D. Nếu một hoặc nhiều START\_WORKER dispatch fail:  
\- mark allocation FAILED;  
\- strict membership không shrink;  
\- gửi ABORT\_ATTEMPT tới Runtime theo service/gateway hiện có;  
\- các Allocation đã STARTED/dispatch thành công phải nhận STOP\_WORKER best-effort;  
\- không tự sửa Attempt state trực tiếp ở Backend; Runtime vẫn owner transition.

E. Retry/Resume:  
\- tạo Allocation mới;  
\- tạo join token mới;  
\- không reuse allocation\_id/token từ Attempt cũ.

Không copy orchestration logic vào API router.

\#\# 4.8. DTP protocol và Runtime admission

\#\#\# MODIFY: src/pbl4/protocol/messages.py

Hello.OPTIONAL:  
\- attempt\_id: string  
\- allocation\_id: string  
\- node\_id: string  
\- worker\_join\_token: string

Validation:  
\- hoặc không có cả 4 field;  
\- hoặc có đủ cả 4 field;  
\- không chấp nhận partial managed identity.

Không đổi HELLO\_ACK schema.

\#\#\# MODIFY: src/pbl4/runtime/entrypoint.py

ADD:  
\- \--allow-unmanaged-workers action=store\_true  
\- đọc env PBL4\_WORKER\_ADMISSION\_SECRET

Rules:  
\- nếu allow\_unmanaged\_workers=false và secret thiếu \-\> startup error rõ ràng;  
\- secret không xuất hiện trong argparse/ps output.

Pass:  
\- worker\_admission\_secret  
\- require\_worker\_admission \= not allow\_unmanaged\_workers  
vào RuntimeProcess.

\#\#\# MODIFY: src/pbl4/runtime/process.py

RuntimeProcess lưu:  
\- worker\_admission\_secret  
\- require\_worker\_admission

Khi tạo ParameterServer, truyền hai giá trị này.

Không thêm admission data vào \_payload\["resolved\_contract"\].

\#\#\# MODIFY: src/pbl4/runtime/parameter\_server.py

ADD internal map:  
\- admitted\_allocation\_ids: set\[str\] giữ trong suốt vòng đời Attempt; allocation\_id đã admit một lần thì không được admit lần hai trong V1

\_Connection bổ sung:  
\- node\_id nullable  
\- allocation\_id nullable

Handshake:  
1\. first frame HELLO as hiện tại.  
2\. protocol validator.  
3\. nếu require admission:  
   \- require managed fields;  
   \- verify\_worker\_join\_token();  
   \- attempt claim \== self.attempt\_id;  
   \- payload fields \== claims;  
   \- allocation\_id chưa active;  
4\. nếu allow unmanaged:  
   \- managed HELLO luôn verify token còn hạn ở lần admission đầu;  
   \- allocation\_id đã có trong admitted\_allocation\_ids bị reject kể cả session cũ đã disconnect;  
   \- unmanaged HELLO được phép khi explicit dev mode.  
5\. chỉ sau verify mới tăng session\_id/register rank.  
6\. thêm allocation\_id vào admitted\_allocation\_ids khi registration thành công.  
7\. KHÔNG remove allocation\_id khỏi admitted\_allocation\_ids khi disconnect; DTP reconnect trong cùng Attempt không được hỗ trợ ở V1.

Error:  
\- gửi canonical DTP ERROR nếu current protocol có helper; nếu không thể an toàn trước session bind, đóng socket và log mã lỗi không chứa token.  
\- không log raw HELLO khi có token.

worker\_snapshots bổ sung:  
\- node\_id  
\- allocation\_id  
nhưng node\_label/protocol\_version/connected\_at hiện có vẫn giữ.

Runtime admission/disconnect rules V1:  
1\. Managed HELLO phải có đủ attempt\_id/allocation\_id/node\_id/worker\_join\_token.  
2\. Token phải còn hạn và claims phải khớp ở admission đầu tiên.  
3\. allocation\_id đã tồn tại trong admitted\_allocation\_ids \-\> reject trước WorkerRegistry.register().  
4\. Admission hợp lệ \-\> WorkerRegistry.register() \-\> add allocation\_id vào admitted\_allocation\_ids.  
5\. Khi DTP connection mất, chuyển Worker Session sang DISCONNECTED/FAILED theo owner hiện có và báo Coordinator.  
6\. Không xóa allocation\_id khỏi admitted\_allocation\_ids; không cho reconnect/rebind rank trong cùng Attempt.  
7\. Attempt failure/cancel tiếp tục do Coordinator/StrictBSP xử lý; Node Agent không can thiệp.

\#\# 4.9. Worker managed identity

\#\#\# MODIFY: src/pbl4/worker/config.py

ADD optional:  
\- attempt\_id: str | None  
\- allocation\_id: str | None  
\- node\_id: str | None  
\- worker\_join\_token: str | None

Validation:  
\- managed identity phải all-or-none.  
\- worker\_join\_token dùng field(repr=False) và không được xuất hiện trong log/repr.

\#\#\# MODIFY: src/pbl4/worker/entrypoint.py

ADD:  
\- \--attempt-id  
\- \--allocation-id  
\- \--node-id

KEEP:  
\- \--initialization-seed required.  
Không đặt default 42\.

Read:  
\- PBL4\_WORKER\_JOIN\_TOKEN from env.

Managed invocation do Agent:  
\- tất cả managed flags \+ token env phải có.

Manual invocation:  
\- có thể không có managed fields khi Runtime chạy \--allow-unmanaged-workers.

\#\#\# MODIFY: src/pbl4/worker/worker\_client.py

Constructor nhận managed identity từ WorkerConfig/process.  
HELLO:  
\- giữ node\_label/client\_instance\_id/etc.;  
\- nếu managed \=\> thêm attempt\_id/allocation\_id/node\_id/worker\_join\_token.

Không gửi worker\_id.  
Không đổi gradient/parameter path.

\#\#\# MODIFY: src/pbl4/worker/process.py

Chỉ truyền identity config xuống WorkerClient.  
Không thêm Backend HTTP client.

Managed Worker identity:  
\- WorkerProcess/entrypoint sinh client\_instance\_id \= uuid4() đúng một lần khi OS process khởi động;  
\- truyền client\_instance\_id vào WorkerClient;  
\- WorkerClient.connect() không được tự sinh UUID mới;  
\- process Worker mới \=\> client\_instance\_id mới;  
\- V1 không thêm DTP reconnect loop. DTP connection mất được coi là lỗi terminal của Worker process để Agent quan sát và báo FAILED.

\#\# 4.10. Snapshot và durable trace Worker \-\> Node/Allocation

\#\#\# MODIFY: src/pbl4/management\_protocol/messages.py

StateSnapshot worker projection hiện yêu cầu worker\_id/session\_id/node\_label/state/...  
Bổ sung OPTIONAL:  
\- node\_id nullable/string  
\- allocation\_id nullable/string

Không đổi START\_ATTEMPT.

Nếu validator hiện dùng fixed required\_worker map, mở rộng validator để cho phép hai field mới nhưng không bắt buộc cho unmanaged session.

\#\#\# MODIFY: src/pbl4/runtime/parameter\_server.py

worker\_snapshots() emit node\_id/allocation\_id cho managed connections.

\#\#\# MODIFY: src/pbl4/management\_backend/gateways/runtime\_gateway.py

Khi reconcile worker snapshot:  
\- truyền node\_id/allocation\_id vào worker\_session\_repository;  
\- unmanaged/legacy snapshot có thể null;  
\- không invent value từ node\_label.

\#\#\# MODIFY: src/pbl4/management\_backend/repositories/worker\_session\_repository.py

upsert\_session thêm optional node\_id/allocation\_id.  
update\_snapshot\_projection cập nhật hai field bằng COALESCE phù hợp.

Không đổi session state semantics.

\#\#\# MODIFY: src/pbl4/management\_backend/schemas/attempt.py

WorkerSessionItem thêm:  
\- node\_id: str | None \= None  
\- allocation\_id: str | None \= None

Không làm protocol\_version/connected\_at optional.

\#\# 4.11. Architecture guard

\#\#\# MODIFY: scripts/check\_architecture.py

ADD rules:  
\- node\_agent không import runtime, worker internals, management\_backend, database libs, torch/torchvision;  
\- agent\_protocol không import node\_agent/management\_backend/runtime/worker;  
\- common.worker\_admission không import process packages.

Không sửa AGENTS.md trong feature task.

\#\# 4.12. Quyền sở hữu error code

Không tạo một registry lỗi dùng chung trong src/pbl4/common/errors.py cho các lỗi Node/Allocation/Admission.

src/pbl4/common/errors.py tiếp tục chỉ giữ các exception nền tảng dùng chung như PBL4Error, ProtocolError và TransportError. Các mã lỗi nghiệp vụ phải nằm ở đúng protocol/subsystem sở hữu chúng:

\- src/pbl4/agent\_protocol/messages.py:  
  \- validate/cho phép các error\_code và failure\_code xuất hiện trong COMMAND\_ACK và WORKER\_STATUS;  
  \- gồm tối thiểu ALLOCATION\_NOT\_FOUND, ALLOCATION\_ALREADY\_ACTIVE, WORKER\_SPAWN\_FAILED khi các mã này đi trên kênh Agent.

\- src/pbl4/protocol/messages.py và src/pbl4/runtime/parameter\_server.py:  
  \- DTP ERROR cho WORKER\_ADMISSION\_REQUIRED, WORKER\_ADMISSION\_INVALID, WORKER\_ADMISSION\_EXPIRED, WORKER\_ADMISSION\_SCOPE\_MISMATCH;  
  \- Runtime quyết định khi nào phát lỗi; protocol package chỉ sở hữu wire schema/mã giao thức, không chứa admission policy.

\- Management Backend service/API layer:  
  \- NODE\_ENROLLMENT\_CODE\_INVALID, NODE\_ENROLLMENT\_CODE\_EXPIRED, NODE\_UNAUTHORIZED, NODE\_REVOKED, NODE\_CAPACITY\_UNAVAILABLE, NODE\_OFFLINE;  
  \- map sang HTTP error envelope hiện có ở API boundary;  
  \- không đẩy các lỗi nghiệp vụ này xuống common.

Nếu implementation cần constant để tránh string lặp lại, constant phải nằm trong package sở hữu protocol/domain tương ứng, không tạo dependency ngược giữa Backend, Runtime và Agent.

\#\# 5\. Trạng thái Allocation và mapping sự kiện

DB actual\_state không phải process-internal state.

Mapping:  
\- create Allocation \-\> REQUESTED;  
\- NodeControlGateway ghi START\_WORKER thành công lên active WSS \-\> DISPATCHED;  
\- COMMAND\_ACK ACCEPTED \-\> giữ nguyên DISPATCHED;  
\- COMMAND\_ACK REJECTED, WSS send failure, spawn failure hoặc quá worker\_start\_timeout\_seconds chưa STARTED \-\> FAILED;  
\- WORKER\_STATUS STARTED \-\> STARTED;  
\- process kết thúc trong stop flow có desired\_state=STOPPED \-\> ENDED;  
\- process thoát/mất ngoài stop flow \-\> FAILED.

STOP:  
\- nhận yêu cầu dừng \-\> desired\_state=STOPPED;  
\- gửi STOP\_WORKER tới Agent;  
\- Agent graceful stop, sau grace\_period mới force nếu command cho phép;  
\- WORKER\_STATUS ENDED \-\> actual\_state=ENDED;  
\- không xác minh được process sau Agent restart \-\> actual\_state=FAILED, exit\_code=null.

DTP WorkerSession độc lập:  
\- Allocation STARTED không có nghĩa session READY;  
\- DTP Session DISCONNECTED/FAILED không trực tiếp sửa Allocation trong DB;  
\- V1 không reconnect DTP: Worker process kết thúc lỗi, Agent báo WORKER\_STATUS FAILED và Allocation sau đó \-\> FAILED;  
\- Backend có thể gửi STOP\_WORKER sau Attempt terminal để thu hồi các process còn lại.

\#\# 6\. Luồng end-to-end phải implement đúng

\#\#\# 6.1. Enrollment

Operator \-\> Backend: tạo one-time code  
Backend DB: hash \+ expiry

Agent \-\> Backend POST /nodes/enroll:  
  code \+ capabilities

Backend:  
  atomic consume code  
  create node  
  return node\_id \+ node\_secret once

Agent:  
  save identity

\#\#\# 6.2. Agent connect

Agent \-\> Backend WSS:  
  Authorization Bearer node\_secret

Backend:  
  SHA256(secret) \== credential\_hash  
  node not REVOKED  
  accept

Agent \-\> AGENT\_HELLO  
Backend \-\> HELLO\_ACK  
Agent \-\> heartbeat / resource snapshots

\#\#\# 6.3. Start Attempt

API \-\> attempt\_service  
  \-\> freeze/read job as current logic  
  \-\> expected\_workers  
  \-\> ClusterScheduler  
  \-\> create N allocations  
  \-\> persist START\_ATTEMPT command  
commit

Backend \-\> Runtime START\_ATTEMPT  
Runtime \-\> ACCEPTED

for each allocation:  
  Backend issue short-lived token  
  Backend \-\> Agent START\_WORKER  
  Agent ACK  
  Agent spawn pbl4-worker  
  Agent \-\> WORKER\_STATUS STARTED

Worker \-\> Runtime HELLO  
Runtime verify token BEFORE register  
Runtime \-\> HELLO\_ACK(worker\_id, session\_id)

Từ đây provisioning/training tiếp tục code hiện tại.

\#\#\# 6.4. Duplicate START\_WORKER

allocation\_id là idempotency key:  
\- chưa có local record \-\> ghi intent và spawn;  
\- local\_state STARTING/RUNNING \-\> ACK ACCEPTED no-op, không spawn lần hai;  
\- local\_state STOPPED/FAILED \-\> ACK REJECTED, không reuse allocation\_id;  
\- command\_id chỉ dùng correlation/tracing, không có command-history subsystem.

\#\#\# 6.5. Agent reconnect

WSS mất:  
\- Worker không bị kill;  
\- Agent reconnect backoff;  
\- AGENT\_HELLO gửi active allocations;  
\- Backend reconcile node/allocations.

\#\#\# 6.6. Backend restart

\- Agent reconnect;  
\- Runtime DTP không phụ thuộc Backend;  
\- Backend dùng Agent report \+ Runtime snapshot để phục hồi projection;  
\- không resend START\_WORKER cho Allocation đã STARTED nếu Agent báo process còn sống.

\#\#\# 6.7. Worker crash và STOP\_WORKER

Worker crash:  
\- Agent supervisor phát hiện process đã kết thúc ngoài ý muốn;  
\- Agent gửi WORKER\_STATUS với actual\_state=FAILED, exit\_code nếu biết, failure\_code/failure\_message phù hợp;  
\- AllocationService chuyển Allocation sang FAILED;  
\- Agent không tự khởi chạy lại cùng allocation\_id;  
\- Runtime xử lý DTP disconnect/heartbeat timeout theo StrictBSP hiện có; membership không shrink;  
\- khi Attempt được Runtime đưa về terminal hoặc Backend đã gửi ABORT\_ATTEMPT, Backend gửi STOP\_WORKER best-effort tới các Allocation còn đang chạy để thu hồi process.

STOP\_WORKER có chủ đích:  
1\. AllocationService đặt desired\_state=STOPPED.  
2\. Backend gửi COMMAND STOP\_WORKER tới đúng Node Agent.  
3\. Agent thử dừng êm trong grace\_period\_seconds.  
4\. Nếu process chưa dừng và force=true, Agent mới cưỡng bức kết thúc.  
5\. Agent gửi WORKER\_STATUS actual\_state=ENDED khi dừng theo chủ đích; nếu không thể dừng hoặc process lỗi bất thường thì dùng FAILED.

MUST:  
\- STOP\_WORKER chỉ quản lý process; không tự thay đổi Attempt lifecycle trong Runtime.  
\- Việc hủy một Attempt phải đi qua MCP ABORT\_ATTEMPT theo flow hiện có.  
\- Agent shutdown/restart không được tự phát sinh STOP\_WORKER cho các Worker đang sống.

\#\# 7\. Error semantics tối thiểu

Dùng error codes rõ, không invent quá nhiều.

Cần có tối thiểu:  
\- NODE\_ENROLLMENT\_CODE\_INVALID  
\- NODE\_ENROLLMENT\_CODE\_EXPIRED  
\- NODE\_UNAUTHORIZED  
\- NODE\_REVOKED  
\- NODE\_CAPACITY\_UNAVAILABLE  
\- NODE\_OFFLINE  
\- ALLOCATION\_NOT\_FOUND  
\- ALLOCATION\_ALREADY\_ACTIVE  
\- WORKER\_SPAWN\_FAILED  
\- WORKER\_ADMISSION\_REQUIRED  
\- WORKER\_ADMISSION\_INVALID  
\- WORKER\_ADMISSION\_EXPIRED  
\- WORKER\_ADMISSION\_SCOPE\_MISMATCH

Không dùng cùng một code cho lỗi process và lỗi DTP session.

\#\# 8\. Test bắt buộc

\#\#\# 8.1. Unit

agent\_protocol:  
\- valid/invalid envelope;  
\- unknown fields;  
\- START/STOP payload validation;  
\- token redaction path.

worker\_admission:  
\- issue/verify success;  
\- altered payload;  
\- altered signature;  
\- expired;  
\- wrong attempt/allocation/node;  
\- malformed Base64/JSON.

node enrollment:  
\- one-time code success;  
\- expired;  
\- second use rejected;  
\- node secret only returned once.

cluster scheduler:  
\- exact expected\_workers;  
\- OFFLINE excluded;  
\- active allocation excluded;  
\- deterministic selection;  
\- not enough nodes \-\> capacity error;  
\- GPU capability \-\> cuda:0, otherwise cpu.

supervisor:  
\- local\_state chỉ STARTING/RUNNING/STOPPED/FAILED;  
\- duplicate START khi STARTING/RUNNING là no-op, khi STOPPED/FAILED bị reject;  
\- duplicate STOP trên terminal state là accepted no-op;  
\- spawn failure \-\> FAILED;  
\- reconcile live process;  
\- stale PID/create\_time mismatch \-\> FAILED, exit\_code=null và không reattach.

ParameterServer:  
\- admission check happens before registry count changes;  
\- invalid/expired token does not consume worker slot;  
\- valid token gets rank;  
\- allocation\_id đã từng admit bị reject kể cả session cũ đã disconnect;  
\- DTP disconnect không reconnect trong cùng Attempt và membership không shrink;  
\- unmanaged HELLO accepted only with explicit dev mode.

\#\#\# 8.2. Integration

Backend:  
\- migration 0003 upgrade/downgrade;  
\- enrollment API;  
\- WSS auth;  
\- heartbeat \-\> ONLINE/last\_seen;  
\- timeout \-\> OFFLINE nhưng không tự đổi active Allocation/Attempt;  
\- revoke \-\> REVOKED và WSS auth sau đó bị từ chối;  
\- resource snapshot persistence;  
\- START\_WORKER WSS write thành công \-\> DISPATCHED;  
\- ACK ACCEPTED không đổi state;  
\- ACK REJECTED/spawn failure/worker\_start\_timeout \-\> FAILED;  
\- WORKER\_STATUS STARTED \-\> STARTED.

Attempt orchestration:  
\- enough nodes \-\> allocations \+ START\_ATTEMPT \+ START\_WORKER;  
\- not enough nodes \-\> no half-created Attempt/Allocation;  
\- partial agent dispatch \-\> abort Runtime and stop already dispatched Workers;  
\- DISPATCHED quá worker\_start\_timeout\_seconds mà chưa STARTED \-\> mark FAILED, abort Runtime và stop best-effort các Worker đã chạy.

Snapshot:  
\- node\_id/allocation\_id Runtime \-\> MCP snapshot \-\> worker\_sessions DB.

\#\#\# 8.3. E2E gate

Bắt buộc có:  
1\. Backend \+ Runtime trên máy A.  
2\. Agent/Worker trên ít nhất máy B và C hoặc 3 máy theo demo target.  
3\. Agent connect qua địa chỉ mạng thực, không localhost giả lập.  
4\. Backend tạo Attempt.  
5\. Worker nhận advertised DTP host, kết nối được.  
6\. invalid random client bị reject trước worker slot.  
7\. đủ N Worker \-\> StrictBSP chạy.  
8\. gradient weighted aggregation/checkpoint test hiện có vẫn pass.  
9\. restart một Agent trong khi Worker đang chạy: Worker không chết do Agent.  
10\. duplicate START\_WORKER không tạo process thứ hai.

\#\# 9\. Definition of Done

Feature chỉ hoàn thành khi tất cả đúng:

\- Node lifecycle đúng OFFLINE \-\> ONLINE \-\> OFFLINE và ONLINE/OFFLINE \-\> REVOKED; REVOKED không quay lại ONLINE.  
\- Allocation transition có trigger duy nhất: WSS write \-\> DISPATCHED, WORKER\_STATUS STARTED \-\> STARTED, requested stop \-\> ENDED, unexpected exit/launch timeout \-\> FAILED.  
\- local\_state của Agent chỉ STARTING/RUNNING/STOPPED/FAILED; không dùng thay cho DB state.  
\- DTP disconnect không reconnect/rebind rank trong cùng Attempt; RETRY/RESUME dùng Allocation/token mới.  
\- client\_instance\_id sinh một lần cho mỗi Worker process, không sinh lại trong WorkerClient.connect().

\- NODE\_AGENT\_DESIGN.md không bị vi phạm.  
\- Migration 0003 không sửa migration cũ.  
\- Node Agent không import DB/runtime/training internals.  
\- Backend không cấp worker\_id.  
\- DTP HELLO managed identity là optional ở schema nhưng required trong managed Runtime mode.  
\- Runtime verify admission trước WorkerRegistry.register().  
\- Token không nằm trong resolved\_contract/contract\_hash.  
\- initialization\_seed lấy từ frozen contract, không hardcode.  
\- START\_WORKER dùng settings.dtp\_advertised\_host.  
\- worker\_sessions giữ nguyên state enum canonical.  
\- node\_id/allocation\_id trace được từ Runtime snapshot về DB.  
\- duplicate command idempotent.  
\- Agent/Backend disconnect không tự cắt DTP.  
\- scripts/check\_architecture.py pass.  
\- ruff format/check pass.  
\- unit \+ integration \+ E2E tests tương ứng pass.  
\- không thêm DBS/Work Unit/prefetch vào PR Node Agent.  
\- không sửa AGENTS.md để “hợp thức hóa” implementation.

\#\# 10\. Những thay đổi tuyệt đối không được tái đưa vào

1\. NODE\_ENROLLMENT\_SECRET tĩnh dùng chung làm enrollment chính.  
2\. worker\_join\_token \= HMAC(secret, attempt\_id:allocation\_id) deterministic không expiry.  
3\. authorized\_worker\_token\_hashes trong resolved\_contract\["synchronization"\].  
4\. worker\_sessions.state \= ACTIVE/CLOSED/ABORTED.  
5\. initialization\_seed mặc định 42\.  
6\. Backend truyền worker\_id cho Worker.  
7\. Agent proxy DTP/tensor.  
8\. Agent truy cập PostgreSQL.  
9\. ClusterScheduler dùng adaptive throughput/DBS.  
10\. Bất kỳ enum/protocol field mới nào không có trong DESIGN/PLAN này.

\#\# 11\. Ghi chú cho reviewer

Reviewer nên kiểm tra theo thứ tự:  
1\. boundary giữa Backend / Agent / Runtime / Worker;  
2\. contract và state machine có giữ canonical không;  
3\. current code path đã được sửa ở đúng owner chưa;  
4\. auth diễn ra trước registration;  
5\. failure có để lại partial allocation/process không;  
6\. restart behavior có bảo toàn training path không;  
7\. test chứng minh invariant, không chỉ test happy path.  
