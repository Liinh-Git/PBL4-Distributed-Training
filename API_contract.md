# API Contract

Định dạng Markdown được chuyển đổi từ bảng `API contract.xlsx`. Nội dung request, response và quy tắc được giữ nguyên theo dữ liệu nguồn.

| STT | Nhóm | Chức năng | Method | Endpoint |
|---:|---|---|---|---|
| 1.0 | System | Health tổng hợp | `GET` | `/api/v1/health` |
| 2.0 | System / Runtime | Capabilities hệ thống | `GET` | `/api/v1/system/capabilities` |
| 3.0 | Runtime | Runtime snapshot | `GET` | `/api/v1/runtime/snapshot` |
| 4.0 | Dataset | Tạo Dataset logic | `POST` | `/api/v1/datasets` |
| 5.0 | Dataset | Danh sách Dataset | `GET` | `/api/v1/datasets` |
| 6.0 | Dataset | Chi tiết Dataset | `GET` | `/api/v1/datasets/{dataset_id}` |
| 7.0 | Dataset Build | Tạo Dataset Build | `POST` | `/api/v1/dataset-builds` |
| 8.0 | Dataset Build | Danh sách Dataset Build | `GET` | `/api/v1/dataset-builds` |
| 9.0 | Dataset Build | Chi tiết Dataset Build | `GET` | `/api/v1/dataset-builds/{dataset_build_id}` |
| 10.0 | Dataset Build | Rebuild Dataset Build | `POST` | `/api/v1/dataset-builds/{dataset_build_id}/rebuild` |
| 11.0 | Dataset Build | Deprecate Dataset Build | `POST` | `/api/v1/dataset-builds/{dataset_build_id}/deprecate` |
| 12.0 | Dataset Build | Delete Dataset Build (business workflow) | `POST` | `/api/v1/dataset-builds/{dataset_build_id}/delete` |
| 13.0 | Job | Tạo Job DRAFT | `POST` | `/api/v1/jobs` |
| 14.0 | Job | Danh sách Job | `GET` | `/api/v1/jobs` |
| 15.0 | Job | Chi tiết Job | `GET` | `/api/v1/jobs/{job_id}` |
| 16.0 | Job | Sửa Job | `PATCH` | `/api/v1/jobs/{job_id}` |
| 17.0 | Job / Training | Validate/preview Job contract | `POST` | `/api/v1/jobs/{job_id}/validate` |
| 18.0 | Job | Clone Job | `POST` | `/api/v1/jobs/{job_id}/clone` |
| 19.0 | Job | Archive Job | `POST` | `/api/v1/jobs/{job_id}/archive` |
| 20.0 | Training / Attempt | Start Job - FRESH | `POST` | `/api/v1/jobs/{job_id}/start` |
| 21.0 | Training / Attempt | Retry from start | `POST` | `/api/v1/jobs/{job_id}/retry` |
| 22.0 | Training / Attempt | Resume từ checkpoint | `POST` | `/api/v1/jobs/{job_id}/resume` |
| 23.0 | Attempt | Danh sách Attempt | `GET` | `/api/v1/attempts` |
| 24.0 | Attempt | Chi tiết Attempt | `GET` | `/api/v1/attempts/{attempt_id}` |
| 25.0 | Runtime / Attempt | Abort Attempt | `POST` | `/api/v1/attempts/{attempt_id}/abort` |
| 26.0 | Runtime / Worker Bootstrap | Lấy Worker join spec | `GET` | `/api/v1/attempts/{attempt_id}/join-spec` |
| 27.0 | Runtime | Attempt snapshot | `GET` | `/api/v1/attempts/{attempt_id}/snapshot` |
| 28.0 | Runtime / Worker | Danh sách Worker Session | `GET` | `/api/v1/attempts/{attempt_id}/workers` |
| 29.0 | Runtime / Worker | Chi tiết Worker/session | `GET` | `/api/v1/attempts/{attempt_id}/workers/{worker_id}` |
| 30.0 | Training / StrictBSP | Danh sách Step | `GET` | `/api/v1/attempts/{attempt_id}/steps` |
| 31.0 | Training / StrictBSP | Chi tiết Step | `GET` | `/api/v1/attempts/{attempt_id}/steps/{step_id}` |
| 32.0 | Training / Checkpoint | Danh sách Checkpoint | `GET` | `/api/v1/checkpoints` |
| 33.0 | Training / Checkpoint | Chi tiết Checkpoint | `GET` | `/api/v1/checkpoints/{checkpoint_id}` |
| 34.0 | Training / Checkpoint | Yêu cầu checkpoint thủ công | `POST` | `/api/v1/attempts/{attempt_id}/checkpoint-requests` |
| 35.0 | BE Event History | Catch-up Runtime Event | `GET` | `/api/v1/attempts/{attempt_id}/events` |
| 36.0 | BE Audit | Audit events tổng quát | `GET` | `/api/v1/events` |
| 37.0 | BE Command | Chi tiết command | `GET` | `/api/v1/commands/{command_id}` |
| 38.0 | BE Command | Danh sách command | `GET` | `/api/v1/commands` |
| 39.0 | Runtime / WebSocket | Realtime Attempt stream | `GET / Upgrade` | `/ws/v1/attempts/{attempt_id}` |
| 40.0 | Training / Metrics | Truy vấn chuỗi số liệu đo lường (Training Metrics Time-series) | `GET` | `/api/v1/attempts/{attempt_id}/metrics` |

---

## 1.0 — Health tổng hợp

**Nhóm:** System  
**Method:** `GET`  
**Endpoint:** `/api/v1/health`

### Headers / Quyền truy cập

Quyền operator theo cấu hình bảo mật theo security profile; X-Request-Id tùy chọn

### Request (Body / Query)

```text
Không có body.

Ví dụ request:
GET /api/v1/health
```

### Response

```text
HTTP 200
{
  "data": {
    "backend": "ok",
    "postgres": "ok",
    "runtime_mcp": "ok",
    "dataset_manager": "ok",
    "timestamp": "2026-09-07T03:24:18.527Z"
  },
  "meta": {
    "request_id": "req_health_001"
  }
}
```

### Quy tắc cần nhớ

API chỉ phản ánh health của Backend và các dependency; không thay đổi training state. runtime_mcp hoặc dataset_manager degraded/unavailable không tự làm Attempt chuyển FAILED.

---

## 2.0 — Capabilities hệ thống

**Nhóm:** System / Runtime  
**Method:** `GET`  
**Endpoint:** `/api/v1/system/capabilities`

### Headers / Quyền truy cập

Quyền operator theo cấu hình bảo mật

### Request (Body / Query)

```text
Không có body.

Ví dụ request:
GET /api/v1/system/capabilities
```

### Response

```text
HTTP 200
{
  "data": {
    "api_version": "v1",
    "dtp_versions": [1],
    "mcp_versions": [1],
    "runtime_connected": true,
    "runtime_instance_id": "runtime_machine_a_001",
    "supported_training_strategies": ["strict_bsp"],
    "feature_flags": {
      "attempt_websocket_stream": true,
      "manual_checkpoint_request": true
    }
    "supported_models": [
      {
        "model_id": "resnet18_groupnorm",
        "display_name": "ResNet-18 (GroupNorm)",
        "task_type": "image_classification"
      }
    ]
  },
  "meta": {
    "request_id": "req_cap_001"
  }
}
```

### Quy tắc cần nhớ

WebUI/CLI phải đọc capability trước khi bật tính năng. V1 chỉ cho strict_bsp; không hiện strategy chưa được Runtime hỗ trợ.

---

## 3.0 — Runtime snapshot

**Nhóm:** Runtime  
**Method:** `GET`  
**Endpoint:** `/api/v1/runtime/snapshot`

### Headers / Quyền truy cập

Quyền operator theo cấu hình bảo mật

### Request (Body / Query)

```text
Không có body.

Ví dụ request:
GET /api/v1/runtime/snapshot
```

### Response

```text
HTTP 200
{
  "data": {
    "runtime_instance_id": "runtime_machine_a_001",
    "active_job_id": "job_demo_001",
    "active_attempt_id": "attempt_demo_001",
    "attempt_state": "RUNNING",
    "training_strategy": "strict_bsp",
    "checkpoint_policy": "after_each_model_update_blocking",
    "epoch": 2,
    "current_operation_id": 17,
    "current_batch_ordinal": 5,
    "model_version": 42,
    "workers": [
      {
        "worker_id": 0,
        "session_id": "10000",
        "node_label": "machine-a",
        "state": "READY",
        "local_model_version": 42
      },
      {
        "worker_id": 1,
        "session_id": "10001",
        "node_label": "machine-b",
        "state": "READY",
        "local_model_version": 42
      },
      {
        "worker_id": 2,
        "session_id": "10002",
        "node_label": "machine-c",
        "state": "READY",
        "local_model_version": 42
      }
    ],
    "strategy_state": {
      "type": "strict_bsp",
      "current_step_id": 17,
      "state": "COLLECTING_GRADIENTS",
      "accepted_contribution_count": 1,
      "expected_contribution_count": 3,
      "parameter_applied_count": 0,
      "barrier_wait_ms": 8.4,
      "synchronization_complete": false
    },
    "checkpoint_state": "COMPLETE",
    "latest_checkpoint_id": "ckpt_1e83f540c66f4feaa389a527d932c411",
    "recovery_cursor": {
      "epoch": 2,
      "next_batch_ordinal": 5
    },
    "dataset_build_id": "dsb_cifar10_20260907_001",
    "dataset_manifest_hash": "6674068eedd93d78de3c72c218d1f2bcbf2a1b02cbd9378e110b3c88f377306d",
    "management_event_gap_count": 0,
    "stale": false,
    "observed_at": "2026-09-07T03:24:18.527Z",
    "runtime_event_seq": 123
  },
  "meta": {
    "request_id": "req_runtime_snapshot_001"
  }
}
```

### Quy tắc cần nhớ

Đây là ảnh chụp trạng thái Runtime gần nhất. Nếu mất MCP thì stale=true; không được tự kết luận Attempt đã FAILED.

---

## 4.0 — Tạo Dataset logic

**Nhóm:** Dataset  
**Method:** `POST`  
**Endpoint:** `/api/v1/datasets`

### Headers / Quyền truy cập

Quyền operator theo cấu hình bảo mật; Idempotency-Key

### Request (Body / Query)

```text
Body JSON — DatasetSourceV1
{
  "name": "CIFAR-10",
  "task_type": "image_classification",
  "source_type": "builtin",
  "source_reference": "cifar10"
}

Required V1: cả 4 field.
```

### Response

```text
HTTP 201
{
  "data": {
    "dataset_id": "cifar10",
    "name": "CIFAR-10",
    "task_type": "image_classification",
    "source_type": "builtin",
    "source_reference": "cifar10",
    "created_at": "2026-09-07T02:00:00.000Z"
  },
  "meta": {
    "request_id": "req_dataset_create_001"
  }
}
```

### Quy tắc cần nhớ

Dataset ở đây chỉ là nguồn dữ liệu logic. batch_size, preprocessing và shard_count chưa thuộc Dataset; chúng thuộc Dataset Build.

---

## 5.0 — Danh sách Dataset

**Nhóm:** Dataset  
**Method:** `GET`  
**Endpoint:** `/api/v1/datasets`

### Headers / Quyền truy cập

Quyền operator theo cấu hình bảo mật

### Request (Body / Query)

```text
Query params (đều optional):
- task_type: enum; V1=image_classification. Ví dụ: image_classification
- q: string; tìm case-insensitive trên dataset_id + name. Ví dụ: cifar
- cursor: opaque string từ page.next_cursor. Ví dụ: eyJjcmVhdGVkX2F0IjoiMjAyNi0wOS0wN1QwMjowMDowMFoifQ
- limit: integer 1..200, default 50. Ví dụ: 50

Ví dụ:
GET /api/v1/datasets?task_type=image_classification&q=cifar&limit=50
```

### Response

```text
HTTP 200
{
  "data": [
    {
      "dataset_id": "cifar10",
      "name": "CIFAR-10",
      "task_type": "image_classification",
      "source_type": "builtin",
      "source_reference": "cifar10",
      "created_at": "2026-09-07T02:00:00.000Z"
    }
  ],
  "page": {
    "next_cursor": null
  }
}
```

### Quy tắc cần nhớ

Dùng để tìm Dataset trong catalog. Đây là API đọc có phân trang; không tạo hay thay đổi Build.

---

## 6.0 — Chi tiết Dataset

**Nhóm:** Dataset  
**Method:** `GET`  
**Endpoint:** `/api/v1/datasets/{dataset_id}`

### Headers / Quyền truy cập

Quyền operator theo cấu hình bảo mật

### Request (Body / Query)

```text
Path param:
- dataset_id: string opaque. Ví dụ: cifar10

Ví dụ:
GET /api/v1/datasets/cifar10
```

### Response

```text
HTTP 200
{
  "data": {
    "dataset_id": "cifar10",
    "name": "CIFAR-10",
    "task_type": "image_classification",
    "source_type": "builtin",
    "source_reference": "cifar10",
    "created_at": "2026-09-07T02:00:00.000Z",
    "build_counts": {
      "CREATED": 0,
      "QUEUED": 0,
      "IMPORTING": 0,
      "VALIDATING": 0,
      "PREPROCESSING": 0,
      "MATERIALIZING": 0,
      "VERIFYING": 0,
      "REGISTERING": 0,
      "READY": 2,
      "FAILED": 1,
      "DEPRECATED": 0,
      "DELETING": 0,
      "DELETED": 0
    }
  },
  "meta": {
    "request_id": "req_dataset_show_001"
  }
}
```

### Quy tắc cần nhớ

Trả thông tin Dataset và thống kê các Build của nó. Dataset và Dataset Build là hai identity khác nhau.

---

## 7.0 — Tạo Dataset Build

**Nhóm:** Dataset Build  
**Method:** `POST`  
**Endpoint:** `/api/v1/dataset-builds`

### Headers / Quyền truy cập

Quyền operator theo cấu hình bảo mật; Idempotency-Key

### Request (Body / Query)

```text
Body JSON — DatasetBuildCreateV1
{
  "dataset_id": "cifar10",
  "profile": "CNN_IMAGE_CLASSIFICATION_V1",
  "batch_size": 32,
  "partition_seed": 2026,
  "preprocessing": {
    "input_shape": [3, 32, 32],
    "normalization": {
      "mean": [0.4914, 0.4822, 0.4465],
      "std": [0.2470, 0.2435, 0.2616]
    }
  }
}

Required V1: tất cả field trên. batch_size > 0; partition_seed integer >= 0; normalization mean/std có 3 phần tử và std > 0.
```

### Response

```text
HTTP 202
{
  "data": {
    "command_id": "1c53a2b0-6f13-4f8d-b1cd-4203a7c5e901",
    "command_type": "CREATE_DATASET_BUILD",
    "command_state": "ACCEPTED",
    "target_type": "DATASET_BUILD",
    "target_id": "dsb_cifar10_20260907_001",
    "dataset_build_id": "dsb_cifar10_20260907_001",
    "dataset_build_state": "CREATED"
  },
  "meta": {
    "request_id": "req_build_create_001"
  }
}
```

### Quy tắc cần nhớ

Tạo Command CREATE_DATASET_BUILD và Build mới. command_state=ACCEPTED chỉ nói workflow đã được nhận; dataset_build_state mới là state của Build và phải theo dõi tới READY/FAILED.

---

## 8.0 — Danh sách Dataset Build

**Nhóm:** Dataset Build  
**Method:** `GET`  
**Endpoint:** `/api/v1/dataset-builds`

### Headers / Quyền truy cập

Quyền operator theo cấu hình bảo mật

### Request (Body / Query)

```text
Query params (optional):
- dataset_id: string. Ví dụ: cifar10
- state: DatasetBuildState. Ví dụ: READY
- profile: enum capability; V1=CNN_IMAGE_CLASSIFICATION_V1
- cursor: opaque string từ page.next_cursor
- limit: integer 1..200, default 50

Ví dụ:
GET /api/v1/dataset-builds?dataset_id=cifar10&state=READY&profile=CNN_IMAGE_CLASSIFICATION_V1&limit=50
```

### Response

```text
HTTP 200
{
  "data": [
    {
      "dataset_build_id": "dsb_cifar10_20260907_001",
      "dataset_id": "cifar10",
      "state": "READY",
      "profile": "CNN_IMAGE_CLASSIFICATION_V1",
      "batch_size": 32,
      "shard_count": 3,
      "sample_count": 50000,
      "created_at": "2026-09-07T02:01:00.000Z",
      "ready_at": "2026-09-07T02:04:30.000Z"
    }
  ],
  "page": {
    "next_cursor": null
  }
}
```

### Quy tắc cần nhớ

Danh sách Build lấy state do Dataset Manager quản lý. Backend không tự đoán READY từ progress.

---

## 9.0 — Chi tiết Dataset Build

**Nhóm:** Dataset Build  
**Method:** `GET`  
**Endpoint:** `/api/v1/dataset-builds/{dataset_build_id}`

### Headers / Quyền truy cập

Quyền operator theo cấu hình bảo mật

### Request (Body / Query)

```text
Path param:
- dataset_build_id: string opaque. Ví dụ: dsb_cifar10_20260907_001

Ví dụ:
GET /api/v1/dataset-builds/dsb_cifar10_20260907_001
```

### Response

```text
HTTP 200
{
  "data": {
    "dataset_build_id": "dsb_cifar10_20260907_001",
    "dataset_id": "cifar10",
    "state": "READY",
    "current_stage": "READY",
    "progress": 1.0,
    "profile": "CNN_IMAGE_CLASSIFICATION_V1",
    "batch_size": 32,
    "shard_count": 3,
    "partition_seed": 2026,
    "sample_count": 50000,
    "manifest_summary": {
      "dataset_manifest_hash": "6674068eedd93d78de3c72c218d1f2bcbf2a1b02cbd9378e110b3c88f377306d",
      "manifest_uri": "/artifacts/v1/dataset-builds/dsb_cifar10_20260907_001/manifest.json",
      "artifact_base_url": "http://192.168.1.10:8100/artifacts/v1/dataset-builds/dsb_cifar10_20260907_001"
    },
    "references": [
      {
        "type": "JOB",
        "id": "job_demo_001"
      },
      {
        "type": "CHECKPOINT",
        "id": "ckpt_7f54d56ea1314daaa68870bc28bd77ab"
      }
    ],
    "error": null,
    "created_at": "2026-09-07T02:01:00.000Z",
    "ready_at": "2026-09-07T02:04:30.000Z"
  },
  "meta": {
    "request_id": "req_build_show_001"
  }
}
```

### Quy tắc cần nhớ

READY Build là bất biến. Muốn đổi batch/preprocessing/seed thì phải rebuild để có dataset_build_id mới.

---

## 10.0 — Rebuild Dataset Build

**Nhóm:** Dataset Build  
**Method:** `POST`  
**Endpoint:** `/api/v1/dataset-builds/{dataset_build_id}/rebuild`

### Headers / Quyền truy cập

Quyền operator theo cấu hình bảo mật; Idempotency-Key

### Request (Body / Query)

```text
Path param:
- dataset_build_id: string. Ví dụ: dsb_cifar10_20260907_001

Body JSON — mọi field optional; field không gửi thì kế thừa Build nguồn:
{
  "batch_size": 64,
  "partition_seed": 2027,
  "preprocessing": {
    "input_shape": [3, 32, 32],
    "normalization": {
      "mean": [0.4914, 0.4822, 0.4465],
      "std": [0.2470, 0.2435, 0.2616]
    }
  }
}
```

### Response

```text
HTTP 202
{
  "data": {
    "command_id": "2d64b3c1-7024-4a9e-a2de-5314b8d6f012",
    "command_type": "REBUILD_DATASET_BUILD",
    "command_state": "ACCEPTED",
    "target_type": "DATASET_BUILD",
    "target_id": "dsb_cifar10_20260907_002",
    "source_dataset_build_id": "dsb_cifar10_20260907_001",
    "new_dataset_build_id": "dsb_cifar10_20260907_002",
    "dataset_build_state": "CREATED"
  },
  "meta": {
    "request_id": "req_build_rebuild_001"
  }
}
```

### Quy tắc cần nhớ

Tạo Command REBUILD_DATASET_BUILD. Build nguồn không bị sửa; target của command là Build mới. command_state và DatasetBuildState là hai lifecycle khác nhau.

---

## 11.0 — Deprecate Dataset Build

**Nhóm:** Dataset Build  
**Method:** `POST`  
**Endpoint:** `/api/v1/dataset-builds/{dataset_build_id}/deprecate`

### Headers / Quyền truy cập

Quyền operator theo cấu hình bảo mật; Idempotency-Key

### Request (Body / Query)

```text
Path param:
- dataset_build_id: string. Ví dụ: dsb_cifar10_20260907_001

Body JSON:
{
  "reason": "Không dùng Build này cho Job mới"
}

reason: optional string, ví dụ trên.
```

### Response

```text
HTTP 200
{
  "data": {
    "dataset_build_id": "dsb_cifar10_20260907_001",
    "state": "DEPRECATED",
    "deprecated_at": "2026-09-07T03:30:00.000Z"
  },
  "meta": {
    "request_id": "req_build_deprecate_001"
  }
}
```

### Quy tắc cần nhớ

DEPRECATED = không cho Job mới chọn, nhưng artifact vẫn phải giữ cho Job/checkpoint cũ còn dùng.

---

## 12.0 — Delete Dataset Build (business workflow)

**Nhóm:** Dataset Build  
**Method:** `POST`  
**Endpoint:** `/api/v1/dataset-builds/{dataset_build_id}/delete`

### Headers / Quyền truy cập

Quyền operator theo cấu hình bảo mật; Idempotency-Key

### Request (Body / Query)

```text
Path param:
- dataset_build_id: string. Ví dụ: dsb_cifar10_20260907_001

Body JSON:
{
  "reason": "Dọn Build đã ngừng sử dụng"
}

reason: optional string.
```

### Response

```text
HTTP 202
{
  "data": {
    "command_id": "3e75c4d2-8135-4bae-b3ef-6425c9e70123",
    "command_type": "DELETE_DATASET_BUILD",
    "command_state": "ACCEPTED",
    "target_type": "DATASET_BUILD",
    "target_id": "dsb_cifar10_20260907_001",
    "dataset_build_id": "dsb_cifar10_20260907_001",
    "dataset_build_state": "DELETING"
  },
  "meta": {
    "request_id": "req_build_delete_001"
  }
}

HTTP 409
{
  "error": {
    "code": "DATASET_BUILD_IN_USE",
    "message": "Dataset Build vẫn còn được tham chiếu",
    "details": {
      "references": [
        {
          "type": "JOB",
          "id": "job_demo_001"
        },
        {
          "type": "CHECKPOINT",
          "id": "ckpt_7f54d56ea1314daaa68870bc28bd77ab"
        }
      ]
    },
    "request_id": "req_build_delete_002"
  }
}
```

### Quy tắc cần nhớ

Tạo Command DELETE_DATASET_BUILD sau khi Backend kiểm tra durable references. Cùng command_id được dùng khi Backend gọi purge nội bộ; Dataset Manager không tự query PostgreSQL để kiểm tra reference.

---

## 13.0 — Tạo Job DRAFT

**Nhóm:** Job  
**Method:** `POST`  
**Endpoint:** `/api/v1/jobs`

### Headers / Quyền truy cập

Quyền operator theo cấu hình bảo mật; Idempotency-Key

### Request (Body / Query)

```text
Body JSON — required: display_name + requested_contract; description optional:

{
  "display_name": "ResNet18 GroupNorm - CIFAR-10",
  "description": "Baseline Strict BSP cho demo 3 máy",
  "requested_contract": {
    "dataset_build_id": "dsb_cifar10_20260907_001",
    "model_id": "resnet18_groupnorm",
    "epochs": 20,
    "learning_rate": 0.01,
    "training_seed": 2026,
    "training_strategy": "strict_bsp"
  }
}

RequestedContractV1 chỉ có đúng 6 key trên. Validation tối thiểu: dataset_build_id phải trỏ Build READY/selectable; model_id phải được Backend hỗ trợ; epochs là integer >= 1; learning_rate hữu hạn > 0; training_seed là integer; training_strategy thuộc capability và V1 chỉ nhận strict_bsp.
```

### Response

```text
HTTP 201
{
  "data": {
    "job_id": "job_demo_001",
    "display_name": "ResNet18 GroupNorm - CIFAR-10",
    "description": "Baseline Strict BSP cho demo 3 máy",
    "state": "DRAFT",
    "requested_contract": {
      "dataset_build_id": "dsb_cifar10_20260907_001",
      "model_id": "resnet18_groupnorm",
      "epochs": 20,
      "learning_rate": 0.01,
      "training_seed": 2026,
      "training_strategy": "strict_bsp"
    },
    "created_at": "2026-09-07T02:10:00.000Z"
  },
  "meta": {
    "request_id": "req_job_create_001"
  }
}
```

### Quy tắc cần nhớ

Job mới luôn DRAFT. requested_contract chỉ chứa 6 field người dùng được chọn; chưa phải cấu hình cuối cùng để Runtime chạy.

---

## 14.0 — Danh sách Job

**Nhóm:** Job  
**Method:** `GET`  
**Endpoint:** `/api/v1/jobs`

### Headers / Quyền truy cập

Quyền operator theo cấu hình bảo mật

### Request (Body / Query)

```text
Query params (optional):
- state: DRAFT | READY | ARCHIVED.
- dataset_build_id: string. Ví dụ: dsb_cifar10_20260907_001
- q: string; case-insensitive trên display_name + description. Ví dụ: resnet18
- cursor: opaque string từ page.next_cursor
- limit: integer 1..200, default 50

Ví dụ:
GET /api/v1/jobs?state=READY&dataset_build_id=dsb_cifar10_20260907_001&q=resnet18&limit=50
```

### Response

```text
HTTP 200
{
  "data": [
    {
      "job_id": "job_demo_001",
      "display_name": "ResNet18 GroupNorm - CIFAR-10",
      "state": "READY",
      "dataset_build_id": "dsb_cifar10_20260907_001",
      "model_id": "resnet18_groupnorm",
      "training_strategy": "strict_bsp",
      "contract_hash": "2c398acd67b2e3607abb19b7e889d931d0e6576b9461e9487042568ad8a69304",
      "attempt_count": 3,
      "latest_attempt": {
        "attempt_id": "attempt_demo_003",
        "state": "COMPLETED"
      },
      "created_at": "2026-09-07T02:10:00.000Z",
      "frozen_at": "2026-09-07T02:12:05.000Z"
    }
  ],
  "page": {
    "next_cursor": null
  }
}
```

### Quy tắc cần nhớ

Job state chỉ có DRAFT/READY/ARCHIVED. RUNNING/FAILED/COMPLETED là trạng thái của Attempt, được hiển thị riêng ở latest_attempt. Danh sách sắp xếp ổn định theo created_at DESC, job_id DESC; cursor là opaque.

---

## 15.0 — Chi tiết Job

**Nhóm:** Job  
**Method:** `GET`  
**Endpoint:** `/api/v1/jobs/{job_id}`

### Headers / Quyền truy cập

Quyền operator theo cấu hình bảo mật

### Request (Body / Query)

```text
Path param:
- job_id: string opaque. Ví dụ: job_demo_001

Ví dụ:
GET /api/v1/jobs/job_demo_001
```

### Response

```text
HTTP 200
{
  "data": {
    "job_id": "job_demo_001",
    "display_name": "ResNet18 GroupNorm - CIFAR-10",
    "description": "Baseline Strict BSP cho demo 3 máy",
    "state": "READY",
    "requested_contract": {
      "dataset_build_id": "dsb_cifar10_20260907_001",
      "model_id": "resnet18_groupnorm",
      "epochs": 20,
      "learning_rate": 0.01,
      "training_seed": 2026,
      "training_strategy": "strict_bsp"
    },
    "resolved_contract": {
      "dataset": {
        "dataset_build_id": "dsb_cifar10_20260907_001",
        "dataset_manifest_hash": "6674068eedd93d78de3c72c218d1f2bcbf2a1b02cbd9378e110b3c88f377306d",
        "task_type": "image_classification",
        "input_shape": [3, 32, 32],
        "dtype": "float32",
        "num_classes": 10,
        "batch_size": 32,
        "shard_count": 3,
        "preprocessing": {
          "normalization": {
            "mean": [0.4914, 0.4822, 0.4465],
            "std": [0.2470, 0.2435, 0.2616]
          }
        }
      },
      "model": {
        "model_id": "resnet18_groupnorm",
        "profile": "RESNET18_GROUPNORM_V1",
        "parameter_manifest_hash": "9a77fd7e1542f92f8329626d333b73524ac420a093aea412f1aaf78af5ef4960"
      },
      "training": {
        "epochs": 20,
        "learning_rate": 0.01,
        "training_seed": 2026
      },
      "synchronization": {
        "training_strategy": "strict_bsp",
        "expected_workers": 3
      },
      "update_policy": {
        "type": "plain_sgd_without_momentum"
      },
      "checkpoint_policy": {
        "type": "after_each_model_update_blocking",
        "schema_version": 1
      },
      "protocols": {
        "dtp_version": 1,
        "mcp_version": 1
      }
    },
    "contract_hash": "2c398acd67b2e3607abb19b7e889d931d0e6576b9461e9487042568ad8a69304",
    "attempt_summary": {
      "total": 3,
      "latest_attempt_id": "attempt_demo_003",
      "latest_attempt_state": "COMPLETED"
    },
    "links": {
      "attempts": "/api/v1/attempts?job_id=job_demo_001"
    },
    "created_at": "2026-09-07T02:10:00.000Z",
    "frozen_at": "2026-09-07T02:12:05.000Z",
    "archived_at": null
  },
  "meta": {
    "request_id": "req_job_show_001"
  }
}
```

### Quy tắc cần nhớ

DRAFT chưa có resolved_contract. Sau freeze, resolved_contract và contract_hash là bất biến; contract_hash là SHA-256 của canonical bytes của resolved_contract. Lịch sử chạy lấy qua Attempt API riêng.

---

## 16.0 — Sửa Job

**Nhóm:** Job  
**Method:** `PATCH`  
**Endpoint:** `/api/v1/jobs/{job_id}`

### Headers / Quyền truy cập

Quyền operator theo cấu hình bảo mật

### Request (Body / Query)

```text
Path param:
- job_id: string. Ví dụ: job_demo_001

PATCH partial merge. Ví dụ DRAFT:
{
  "description": "Giảm learning rate cho lần chạy thử",
  "requested_contract": {
    "learning_rate": 0.005
  }
}

DRAFT writable: display_name, description, requested_contract.dataset_build_id/model_id/epochs/learning_rate/training_seed/training_strategy.
READY writable: display_name, description.
ARCHIVED: không writable.
```

### Response

```text
HTTP 200 (DRAFT example)
{
  "data": {
    "job_id": "job_demo_001",
    "state": "DRAFT",
    "display_name": "ResNet18 GroupNorm - CIFAR-10",
    "description": "Giảm learning rate cho lần chạy thử",
    "requested_contract": {
      "dataset_build_id": "dsb_cifar10_20260907_001",
      "model_id": "resnet18_groupnorm",
      "epochs": 20,
      "learning_rate": 0.005,
      "training_seed": 2026,
      "training_strategy": "strict_bsp"
    }
  },
  "meta": {
    "request_id": "req_job_patch_001"
  }
}

HTTP 409 nếu sửa contract của READY
{
  "error": {
    "code": "JOB_FROZEN",
    "message": "Job contract đã được freeze",
    "details": {
      "field": "requested_contract.learning_rate"
    },
    "request_id": "req_job_patch_002"
  }
}
```

### Quy tắc cần nhớ

PATCH là partial shallow-merge theo field. DRAFT sửa metadata + 6 key requested_contract và giá trị mới phải thỏa validation của POST create; READY chỉ sửa tên/mô tả; ARCHIVED không sửa. Field không gửi giữ nguyên; requested_contract={} không reset contract; field lạ trả 422.

---

## 17.0 — Validate/preview Job contract

**Nhóm:** Job / Training  
**Method:** `POST`  
**Endpoint:** `/api/v1/jobs/{job_id}/validate`

### Headers / Quyền truy cập

Quyền operator theo cấu hình bảo mật

### Request (Body / Query)

```text
Path param:
- job_id: string. Ví dụ: job_demo_001

Không có body.

Ví dụ:
POST /api/v1/jobs/job_demo_001/validate
```

### Response

```text
HTTP 200
{
  "data": {
    "requested_contract": {
      "dataset_build_id": "dsb_cifar10_20260907_001",
      "model_id": "resnet18_groupnorm",
      "epochs": 20,
      "learning_rate": 0.01,
      "training_seed": 2026,
      "training_strategy": "strict_bsp"
    },
    "resolved_preview": {
      "dataset": {
        "dataset_build_id": "dsb_cifar10_20260907_001",
        "dataset_manifest_hash": "6674068eedd93d78de3c72c218d1f2bcbf2a1b02cbd9378e110b3c88f377306d",
        "task_type": "image_classification",
        "input_shape": [3, 32, 32],
        "dtype": "float32",
        "num_classes": 10,
        "batch_size": 32,
        "shard_count": 3,
        "preprocessing": {
          "normalization": {
            "mean": [0.4914, 0.4822, 0.4465],
            "std": [0.2470, 0.2435, 0.2616]
          }
        }
      },
      "model": {
        "model_id": "resnet18_groupnorm",
        "profile": "RESNET18_GROUPNORM_V1",
        "parameter_manifest_hash": "9a77fd7e1542f92f8329626d333b73524ac420a093aea412f1aaf78af5ef4960"
      },
      "training": {
        "epochs": 20,
        "learning_rate": 0.01,
        "training_seed": 2026
      },
      "synchronization": {
        "training_strategy": "strict_bsp",
        "expected_workers": 3
      },
      "update_policy": {
        "type": "plain_sgd_without_momentum"
      },
      "checkpoint_policy": {
        "type": "after_each_model_update_blocking",
        "schema_version": 1
      },
      "protocols": {
        "dtp_version": 1,
        "mcp_version": 1
      }
    },
    "warnings": [],
    "errors": []
  },
  "meta": {
    "request_id": "req_job_validate_001"
  }
}
```

### Quy tắc cần nhớ

Validate chỉ thử resolve và báo lỗi/cảnh báo. Nó không freeze Job, không tạo Attempt và không tạo contract_hash authoritative.

---

## 18.0 — Clone Job

**Nhóm:** Job  
**Method:** `POST`  
**Endpoint:** `/api/v1/jobs/{job_id}/clone`

### Headers / Quyền truy cập

Quyền operator theo cấu hình bảo mật; Idempotency-Key

### Request (Body / Query)

```text
Path param:
- job_id: string. Ví dụ: job_demo_001

Không có body.
```

### Response

```text
HTTP 201
{
  "data": {
    "job_id": "job_demo_clone_001",
    "state": "DRAFT",
    "cloned_from_job_id": "job_demo_001",
    "display_name": "ResNet18 GroupNorm - CIFAR-10 (copy)",
    "description": "Baseline Strict BSP cho demo 3 máy",
    "requested_contract": {
      "dataset_build_id": "dsb_cifar10_20260907_001",
      "model_id": "resnet18_groupnorm",
      "epochs": 20,
      "learning_rate": 0.01,
      "training_seed": 2026,
      "training_strategy": "strict_bsp"
    },
    "resolved_contract": null,
    "contract_hash": null
  },
  "meta": {
    "request_id": "req_job_clone_001"
  }
}
```

### Quy tắc cần nhớ

Clone tạo một Job DRAFT mới để chỉnh tiếp. Không sửa Job READY cũ và không copy mù contract_hash.

---

## 19.0 — Archive Job

**Nhóm:** Job  
**Method:** `POST`  
**Endpoint:** `/api/v1/jobs/{job_id}/archive`

### Headers / Quyền truy cập

Quyền operator theo cấu hình bảo mật; Idempotency-Key

### Request (Body / Query)

```text
Path param:
- job_id: string. Ví dụ: job_demo_001

Không có body.
```

### Response

```text
HTTP 200
{
  "data": {
    "job_id": "job_demo_001",
    "state": "ARCHIVED",
    "archived_at": "2026-09-07T04:00:00.000Z"
  },
  "meta": {
    "request_id": "req_job_archive_001"
  }
}
```

### Quy tắc cần nhớ

Archive chỉ đổi trạng thái quản trị của Job. Nó không tự abort Attempt đang chạy.

---

## 20.0 — Start Job - FRESH

**Nhóm:** Training / Attempt  
**Method:** `POST`  
**Endpoint:** `/api/v1/jobs/{job_id}/start`

### Headers / Quyền truy cập

Quyền operator theo cấu hình bảo mật; Idempotency-Key

### Request (Body / Query)

```text
Path param:
- job_id: string. Ví dụ: job_demo_001

Body optional:
{
  "note": "Fresh run cho demo"
}

Có thể omit body hoàn toàn.
```

### Response

```text
HTTP 202
{
  "data": {
    "command_id": "4f86d5e3-9246-4cbf-a4f0-7536daf81234",
    "command_type": "START_ATTEMPT",
    "command_state": "ACCEPTED",
    "target_type": "ATTEMPT",
    "target_id": "attempt_demo_001",
    "job_id": "job_demo_001",
    "attempt_id": "attempt_demo_001",
    "execution_mode": "FRESH"
  },
  "meta": {
    "request_id": "req_job_start_001"
  }
}
```

### Quy tắc cần nhớ

Tạo Attempt mới và Command START_ATTEMPT với execution_mode=FRESH. ACCEPTED là CommandState; Attempt có lifecycle riêng và chưa nhất thiết RUNNING.

---

## 21.0 — Retry from start

**Nhóm:** Training / Attempt  
**Method:** `POST`  
**Endpoint:** `/api/v1/jobs/{job_id}/retry`

### Headers / Quyền truy cập

Quyền operator theo cấu hình bảo mật; Idempotency-Key

### Request (Body / Query)

```text
Path param:
- job_id: string. Ví dụ: job_demo_001

Body optional:
{
  "note": "Chạy lại từ đầu sau khi Worker lỗi"
}

Không cho phép bất kỳ hyperparameter override nào.
```

### Response

```text
HTTP 202
{
  "data": {
    "command_id": "5097e6f4-a357-4dc0-b501-8647eb092345",
    "command_type": "START_ATTEMPT",
    "command_state": "ACCEPTED",
    "target_type": "ATTEMPT",
    "target_id": "attempt_demo_retry_001",
    "job_id": "job_demo_001",
    "attempt_id": "attempt_demo_retry_001",
    "execution_mode": "RETRY_FROM_START"
  },
  "meta": {
    "request_id": "req_job_retry_001"
  }
}
```

### Quy tắc cần nhớ

Retry vẫn dùng Command START_ATTEMPT, nhưng Attempt mới có execution_mode=RETRY_FROM_START. Không có command type START_RETRY riêng.

---

## 22.0 — Resume từ checkpoint

**Nhóm:** Training / Attempt  
**Method:** `POST`  
**Endpoint:** `/api/v1/jobs/{job_id}/resume`

### Headers / Quyền truy cập

Quyền operator theo cấu hình bảo mật; Idempotency-Key

### Request (Body / Query)

```text
Path param:
- job_id: string. Ví dụ: job_demo_001

Body required:
{
  "checkpoint_id": "ckpt_7f54d56ea1314daaa68870bc28bd77ab"
}

checkpoint_id: string opaque, bắt buộc.
```

### Response

```text
HTTP 202
{
  "data": {
    "command_id": "61a8f705-b468-4ed1-a612-9758fc1a3456",
    "command_type": "START_ATTEMPT",
    "command_state": "ACCEPTED",
    "target_type": "ATTEMPT",
    "target_id": "attempt_demo_resume_001",
    "job_id": "job_demo_001",
    "attempt_id": "attempt_demo_resume_001",
    "execution_mode": "RESUME",
    "resume_from_checkpoint_id": "ckpt_7f54d56ea1314daaa68870bc28bd77ab"
  },
  "meta": {
    "request_id": "req_job_resume_001"
  }
}
```

### Quy tắc cần nhớ

Resume cũng dùng Command START_ATTEMPT, nhưng Attempt mới có execution_mode=RESUME và pin checkpoint COMPLETE tương thích. Checkpoint ID là opaque; không parse ID để suy model_version.

---

## 23.0 — Danh sách Attempt

**Nhóm:** Attempt  
**Method:** `GET`  
**Endpoint:** `/api/v1/attempts`

### Headers / Quyền truy cập

Quyền operator theo cấu hình bảo mật

### Request (Body / Query)

```text
Query params (optional):
- job_id: string. Ví dụ: job_demo_001
- state: CREATED | WAITING_WORKERS | PROVISIONING | INITIALIZING | RUNNING | COMPLETING | COMPLETED | FAILED | ABORTED. Ví dụ: FAILED
- execution_mode: FRESH | RETRY_FROM_START | RESUME. Ví dụ: FRESH
- cursor: opaque string từ page.next_cursor
- limit: integer 1..200, default 50

Ví dụ:
GET /api/v1/attempts?job_id=job_demo_001&state=FAILED&limit=50
```

### Response

```text
HTTP 200
{
  "data": [
    {
      "attempt_id": "attempt_demo_failed_001",
      "job_id": "job_demo_001",
      "state": "FAILED",
      "execution_mode": "FRESH",
      "training_strategy": "strict_bsp",
      "created_at": "2026-09-07T02:20:00.000Z",
      "started_at": "2026-09-07T02:21:00.000Z",
      "ended_at": "2026-09-07T02:28:14.000Z",
      "failure_code": "WORKER_DISCONNECTED"
    }
  ],
  "page": {
    "next_cursor": null
  }
}
```

### Quy tắc cần nhớ

Attempt là một lần chạy cụ thể của Job. FRESH, RETRY_FROM_START và RESUME đều có attempt_id riêng.

---

## 24.0 — Chi tiết Attempt

**Nhóm:** Attempt  
**Method:** `GET`  
**Endpoint:** `/api/v1/attempts/{attempt_id}`

### Headers / Quyền truy cập

Quyền operator theo cấu hình bảo mật

### Request (Body / Query)

```text
Path param:
- attempt_id: string opaque. Ví dụ: attempt_demo_001

Ví dụ:
GET /api/v1/attempts/attempt_demo_001
```

### Response

```text
HTTP 200
{
  "data": {
    "attempt_id": "attempt_demo_001",
    "job_id": "job_demo_001",
    "contract_hash": "2c398acd67b2e3607abb19b7e889d931d0e6576b9461e9487042568ad8a69304",
    "state": "RUNNING",
    "execution_mode": "FRESH",
    "training_strategy": "strict_bsp",
    "expected_workers": 3,
    "membership": {
      "active_workers": 3,
      "expected_workers": 3
    },
    "epoch": 2,
    "progress_cursor": {
      "epoch": 2,
      "next_batch_ordinal": 6
    },
    "model_version": 42,
    "checkpoint": {
      "state": "COMPLETE",
      "latest_checkpoint_id": "ckpt_7f54d56ea1314daaa68870bc28bd77ab"
    },
    "runtime": {
      "stale": false,
      "observed_at": "2026-09-07T03:24:18.527Z",
      "runtime_event_seq": 123
    },
    "strategy_state": {
      "type": "strict_bsp",
      "current_step_id": 18,
      "state": "COLLECTING_GRADIENTS",
      "accepted_contribution_count": 1,
      "expected_contribution_count": 3,
      "parameter_applied_count": 0,
      "barrier_wait_ms": 8.4,
      "synchronization_complete": false
    },
    "failure": null,
    "links": {
      "job": "/api/v1/jobs/job_demo_001",
      "workers": "/api/v1/attempts/attempt_demo_001/workers",
      "steps": "/api/v1/attempts/attempt_demo_001/steps",
      "events": "/api/v1/attempts/attempt_demo_001/events"
    }
  },
  "meta": {
    "request_id": "req_attempt_show_001"
  }
}
```

### Quy tắc cần nhớ

Top-level chỉ giữ thông tin dùng chung. Chi tiết barrier/contribution của StrictBSP nằm trong strategy_state để sau này strategy khác không bị ép theo BSP.

---

## 25.0 — Abort Attempt

**Nhóm:** Runtime / Attempt  
**Method:** `POST`  
**Endpoint:** `/api/v1/attempts/{attempt_id}/abort`

### Headers / Quyền truy cập

Quyền operator theo cấu hình bảo mật; Idempotency-Key

### Request (Body / Query)

```text
Path param:
- attempt_id: string. Ví dụ: attempt_demo_001

Body JSON:
{
  "reason": "Operator dừng demo"
}

reason: optional string.
```

### Response

```text
HTTP 202
{
  "data": {
    "command_id": "72b90716-c579-4fe2-b723-a8690d2b4567",
    "command_type": "ABORT_ATTEMPT",
    "command_state": "ACCEPTED",
    "target_type": "ATTEMPT",
    "target_id": "attempt_demo_001",
    "attempt_id": "attempt_demo_001"
  },
  "meta": {
    "request_id": "req_attempt_abort_001"
  }
}

HTTP 409
{
  "error": {
    "code": "ATTEMPT_NOT_ABORTABLE",
    "message": "Attempt không còn ở trạng thái cho phép abort",
    "details": {
      "state": "COMPLETED"
    },
    "request_id": "req_attempt_abort_002"
  }
}
```

### Quy tắc cần nhớ

Tạo Command ABORT_ATTEMPT. Backend không tự set Attempt=ABORTED khi command được ACCEPTED; Runtime sở hữu transition và phản ánh kết quả qua state/event.

---

## 26.0 — Lấy Worker join spec

**Nhóm:** Runtime / Worker Bootstrap  
**Method:** `GET`  
**Endpoint:** `/api/v1/attempts/{attempt_id}/join-spec`

### Headers / Quyền truy cập

Quyền bootstrap Worker theo cấu hình bảo mật

### Request (Body / Query)

```text
Path param:
- attempt_id: string. Ví dụ: attempt_demo_001

Ví dụ:
GET /api/v1/attempts/attempt_demo_001/join-spec
```

### Response

```text
HTTP 200
{
  "data": {
    "ps_host": "192.168.1.10",
    "ps_port": 5000,
    "job_id": "job_demo_001",
    "attempt_id": "attempt_demo_001",
    "contract_hash": "2c398acd67b2e3607abb19b7e889d931d0e6576b9461e9487042568ad8a69304",
    "protocol": {
      "dtp_version": 1
    },
    "expires_at": "2026-09-07T03:40:00.000Z"
  },
  "meta": {
    "request_id": "req_join_spec_001"
  }
}
```

### Quy tắc cần nhớ

join-spec chỉ cung cấp thông tin để Worker kết nối Parameter Server. worker_id cuối cùng vẫn do DTP HELLO_ACK cấp.

---

## 27.0 — Attempt snapshot

**Nhóm:** Runtime  
**Method:** `GET`  
**Endpoint:** `/api/v1/attempts/{attempt_id}/snapshot`

### Headers / Quyền truy cập

Quyền operator theo cấu hình bảo mật

### Request (Body / Query)

```text
Path param:
- attempt_id: string. Ví dụ: attempt_demo_001

Ví dụ:
GET /api/v1/attempts/attempt_demo_001/snapshot
```

### Response

```text
HTTP 200
{
  "data": {
    "attempt_id": "attempt_demo_001",
    "state": "RUNNING",
    "training_strategy": "strict_bsp",
    "epoch": 2,
    "current_operation_id": 18,
    "current_batch_ordinal": 6,
    "model_version": 42,
    "workers": [
      {
        "worker_id": 0,
        "session_id": "10000",
        "state": "READY",
        "local_model_version": 42
      },
      {
        "worker_id": 1,
        "session_id": "10001",
        "state": "READY",
        "local_model_version": 42
      },
      {
        "worker_id": 2,
        "session_id": "10002",
        "state": "READY",
        "local_model_version": 42
      }
    ],
    "strategy_state": {
      "type": "strict_bsp",
      "current_step_id": 18,
      "state": "COLLECTING_GRADIENTS",
      "accepted_contribution_count": 1,
      "expected_contribution_count": 3,
      "parameter_applied_count": 0,
      "barrier_wait_ms": 8.4,
      "synchronization_complete": false
    },
    "checkpoint_state": "COMPLETE",
    "latest_checkpoint_id": "ckpt_7f54d56ea1314daaa68870bc28bd77ab",
    "stale": false,
    "observed_at": "2026-09-07T03:24:18.527Z",
    "runtime_event_seq": 123
  },
  "meta": {
    "request_id": "req_attempt_snapshot_001"
  }
}
```

### Quy tắc cần nhớ

Snapshot là live projection cho đúng Attempt. stale=true nghĩa dữ liệu cũ; client vẫn hiển thị nhưng phải báo người dùng biết.

---

## 28.0 — Danh sách Worker Session

**Nhóm:** Runtime / Worker  
**Method:** `GET`  
**Endpoint:** `/api/v1/attempts/{attempt_id}/workers`

### Headers / Quyền truy cập

Quyền operator theo cấu hình bảo mật

### Request (Body / Query)

```text
Path param:
- attempt_id: string. Ví dụ: attempt_demo_001

Ví dụ:
GET /api/v1/attempts/attempt_demo_001/workers
```

### Response

```text
HTTP 200
{
  "data": [
    {
      "worker_id": 0,
      "session_id": "10000",
      "node_label": "machine-a",
      "state": "READY",
      "shard_id": 0,
      "local_model_version": 42,
      "protocol_version": 1,
      "connected_at": "2026-09-07T02:20:00.000Z",
      "last_heartbeat_at": "2026-09-07T03:24:17.000Z",
      "disconnected_at": null,
      "failure_code": null
    },
    {
      "worker_id": 1,
      "session_id": "10001",
      "node_label": "machine-b",
      "state": "READY",
      "shard_id": 1,
      "local_model_version": 42,
      "protocol_version": 1,
      "connected_at": "2026-09-07T02:20:01.000Z",
      "last_heartbeat_at": "2026-09-07T03:24:17.100Z",
      "disconnected_at": null,
      "failure_code": null
    },
    {
      "worker_id": 2,
      "session_id": "10002",
      "node_label": "machine-c",
      "state": "READY",
      "shard_id": 2,
      "local_model_version": 42,
      "protocol_version": 1,
      "connected_at": "2026-09-07T02:20:02.000Z",
      "last_heartbeat_at": "2026-09-07T03:24:17.200Z",
      "disconnected_at": null,
      "failure_code": null
    }
  ]
}
```

### Quy tắc cần nhớ

Danh sách Worker Session chỉ để quan sát. Client không được tự gán worker_id, sửa heartbeat hay đánh dấu SHARD_READY.

---

## 29.0 — Chi tiết Worker/session

**Nhóm:** Runtime / Worker  
**Method:** `GET`  
**Endpoint:** `/api/v1/attempts/{attempt_id}/workers/{worker_id}`

### Headers / Quyền truy cập

Quyền operator theo cấu hình bảo mật

### Request (Body / Query)

```text
Path params:
- attempt_id: string. Ví dụ: attempt_demo_001
- worker_id: integer rank, V1 0..2. Ví dụ: 1

Query optional:
- include_history: boolean, default false. Ví dụ: true

Ví dụ:
GET /api/v1/attempts/attempt_demo_001/workers/1?include_history=true
```

### Response

```text
HTTP 200
{
  "data": {
    "worker_id": 1,
    "active_session": {
      "worker_id": 1,
      "session_id": "10001",
      "node_label": "machine-b",
      "state": "READY",
      "shard_id": 1,
      "local_model_version": 42,
      "protocol_version": 1,
      "connected_at": "2026-09-07T02:20:01.000Z",
      "last_heartbeat_at": "2026-09-07T03:24:17.100Z",
      "disconnected_at": null,
      "failure_code": null
    },
    "historical_sessions": [
      {
        "worker_id": 1,
        "session_id": "9901",
        "node_label": "machine-b",
        "state": "DISCONNECTED",
        "shard_id": 1,
        "local_model_version": 12,
        "protocol_version": 1,
        "connected_at": "2026-09-07T02:05:00.000Z",
        "last_heartbeat_at": "2026-09-07T02:09:59.000Z",
        "disconnected_at": "2026-09-07T02:10:04.000Z",
        "failure_code": "CONNECTION_LOST"
      }
    ]
  },
  "meta": {
    "request_id": "req_worker_show_001"
  }
}
```

### Quy tắc cần nhớ

Mỗi reconnect tạo session_id mới. include_history=true dùng để xem session cũ thay vì ghi đè lịch sử của cùng worker_id.

---

## 30.0 — Danh sách Step

**Nhóm:** Training / StrictBSP  
**Method:** `GET`  
**Endpoint:** `/api/v1/attempts/{attempt_id}/steps`

### Headers / Quyền truy cập

Quyền operator theo cấu hình bảo mật

### Request (Body / Query)

```text
Path param:
- attempt_id: string. Ví dụ: attempt_demo_001

Query optional:
- cursor: opaque string từ page.next_cursor
- limit: integer 1..200, default 50

Ví dụ:
GET /api/v1/attempts/attempt_demo_001/steps?limit=50
```

### Response

```text
HTTP 200
{
  "data": [
    {
      "step_id": 17,
      "operation_id": 17,
      "state": "COMMITTED",
      "input_model_version": 41,
      "output_model_version": 42,
      "epoch": 2,
      "batch_ordinal": 5,
      "total_sample_count": 96,
      "committed_at": "2026-09-07T03:24:18.000Z"
    }
  ],
  "page": {
    "next_cursor": null
  }
}
```

### Quy tắc cần nhớ

Step API chỉ tồn tại vì V1 dùng strict_bsp. step_id chỉ có nghĩa trong Attempt và không đồng nhất với model_version.

---

## 31.0 — Chi tiết Step

**Nhóm:** Training / StrictBSP  
**Method:** `GET`  
**Endpoint:** `/api/v1/attempts/{attempt_id}/steps/{step_id}`

### Headers / Quyền truy cập

Quyền operator theo cấu hình bảo mật

### Request (Body / Query)

```text
Path params:
- attempt_id: string. Ví dụ: attempt_demo_001
- step_id: integer >= 0 trong scope Attempt. Ví dụ: 17

Ví dụ:
GET /api/v1/attempts/attempt_demo_001/steps/17
```

### Response

```text
HTTP 200
{
  "data": {
    "training_strategy": "strict_bsp",
    "step_id": 17,
    "operation_id": 17,
    "input_model_version": 41,
    "output_model_version": 42,
    "state": "COMMITTED",
    "epoch": 2,
    "batch_ordinal": 5,
    "total_sample_count": 96,
    "timing": {
      "started_at": "2026-09-07T03:24:10.000Z",
      "update_completed_at": "2026-09-07T03:24:15.600Z",
      "synchronization_completed_at": "2026-09-07T03:24:16.700Z",
      "checkpoint_completed_at": "2026-09-07T03:24:17.800Z",
      "committed_at": "2026-09-07T03:24:18.000Z"
    },
    "metrics": {
      "loss": 0.21,
      "accuracy": 89.0
    },
    "worker_steps": [
      {
        "worker_id": 0,
        "session_id": "10000",
        "shard_id": 0,
        "batch_id": 105,
        "sample_count": 32,
        "contribution_accepted": true,
        "parameter_applied": true,
        "loss": 0.22,
        "accuracy": 88.5,
        "compute_ms": 65.4,      // -> Training Time
        "upload_ms": 28.1,       // -> Pushing Time
        "parameter_apply_ms": 12.0,
        "bytes_sent": 18240000,
        "bytes_received": 18240000
      },
      {
        "worker_id": 1,
        "session_id": "10001",
        "shard_id": 1,
        "batch_id": 105,
        "sample_count": 32,
        "contribution_accepted": true,
        "parameter_applied": true,
        "loss": 0.22,
        "accuracy": 88.5,
        "compute_ms": 65.4,      // -> Training Time
        "upload_ms": 28.1,       // -> Pushing Time
        "parameter_apply_ms": 12.0,
        "bytes_sent": 18240000,
        "bytes_received": 18240000
      },
      {
        "worker_id": 2,
        "session_id": "10002",
        "shard_id": 2,
        "batch_id": 105,
        "sample_count": 32,
        "contribution_accepted": true,
        "parameter_applied": true,
        "loss": 0.22,
        "accuracy": 88.5,
        "compute_ms": 65.4,      // -> Training Time
        "upload_ms": 28.1,       // -> Pushing Time
        "parameter_apply_ms": 12.0,
        "bytes_sent": 18240000,
        "bytes_received": 18240000
      }
    ]
  },
  "meta": {
    "request_id": "req_step_show_001"
  }
}
```

### Quy tắc cần nhớ

Một Step có nhiều mốc khác nhau: update xong, Worker apply xong, checkpoint xong, rồi mới COMMITTED. Không gộp các mốc này.

---

## 32.0 — Danh sách Checkpoint

**Nhóm:** Training / Checkpoint  
**Method:** `GET`  
**Endpoint:** `/api/v1/checkpoints`

### Headers / Quyền truy cập

Quyền operator theo cấu hình bảo mật

### Request (Body / Query)

```text
Query params (optional):
- job_id: string. Ví dụ: job_demo_001
- attempt_id: string. Ví dụ: attempt_demo_001
- state: WRITING | COMPLETE | FAILED. Ví dụ: COMPLETE
- cursor: opaque string từ page.next_cursor
- limit: integer 1..200, default 50

Ví dụ:
GET /api/v1/checkpoints?job_id=job_demo_001&state=COMPLETE&limit=50
```

### Response

```text
HTTP 200
{
  "data": [
    {
      "checkpoint_id": "ckpt_7f54d56ea1314daaa68870bc28bd77ab",
      "job_id": "job_demo_001",
      "created_by_attempt_id": "attempt_demo_001",
      "state": "COMPLETE",
      "model_version": 42,
      "source_step_id": 17,
      "created_at": "2026-09-07T03:24:17.800Z",
      "completed_at": "2026-09-07T03:24:17.950Z"
    }
  ],
  "page": {
    "next_cursor": null
  }
}
```

### Quy tắc cần nhớ

Checkpoint list chỉ trả metadata/index để quản trị. Không tải model binary qua Backend REST.

---

## 33.0 — Chi tiết Checkpoint

**Nhóm:** Training / Checkpoint  
**Method:** `GET`  
**Endpoint:** `/api/v1/checkpoints/{checkpoint_id}`

### Headers / Quyền truy cập

Quyền operator theo cấu hình bảo mật

### Request (Body / Query)

```text
Path param:
- checkpoint_id: string opaque. Ví dụ: ckpt_7f54d56ea1314daaa68870bc28bd77ab

Ví dụ:
GET /api/v1/checkpoints/ckpt_7f54d56ea1314daaa68870bc28bd77ab
```

### Response

```text
HTTP 200
{
  "data": {
    "checkpoint_id": "ckpt_7f54d56ea1314daaa68870bc28bd77ab",
    "state": "COMPLETE",
    "job_id": "job_demo_001",
    "created_by_attempt_id": "attempt_demo_001",
    "contract_hash": "2c398acd67b2e3607abb19b7e889d931d0e6576b9461e9487042568ad8a69304",
    "dataset_build_id": "dsb_cifar10_20260907_001",
    "dataset_manifest_hash": "6674068eedd93d78de3c72c218d1f2bcbf2a1b02cbd9378e110b3c88f377306d",
    "parameter_manifest_hash": "9a77fd7e1542f92f8329626d333b73524ac420a093aea412f1aaf78af5ef4960",
    "training_strategy": "strict_bsp",
    "source_operation_id": 17,
    "source_step_id": 17,
    "model_version": 42,
    "recovery_cursor": {
      "epoch": 2,
      "next_batch_ordinal": 6
    },
    "integrity": {
      "model_sha256": "b1c09a817d23e4540fb83a0ccb7f69a54c4a32096c09e3d42b1e4bd18847b086",
      "metadata_sha256": "084043331a1092609a49c3ba82b5219b76407431d44ec85c4811d9caabcbeefc",
      "artifact_size_bytes": 46821376
    },
    "created_at": "2026-09-07T03:24:17.800Z",
    "completed_at": "2026-09-07T03:24:17.950Z"
  },
  "meta": {
    "request_id": "req_checkpoint_show_001"
  }
}
```

### Quy tắc cần nhớ

Checkpoint binary nằm trên filesystem Runtime. Backend/DB chỉ biết identity, version, hash và trạng thái.

---

## 34.0 — Yêu cầu checkpoint thủ công

**Nhóm:** Training / Checkpoint  
**Method:** `POST`  
**Endpoint:** `/api/v1/attempts/{attempt_id}/checkpoint-requests`

### Headers / Quyền truy cập

Quyền operator theo cấu hình bảo mật; Idempotency-Key

### Request (Body / Query)

```text
Path param:
- attempt_id: string. Ví dụ: attempt_demo_001

Body JSON:
{
  "reason": "manual"
}

reason: optional string operator note; ví dụ "manual". Không phải enum.
```

### Response

```text
HTTP 202
{
  "data": {
    "command_id": "83ca1827-d68a-4af3-a834-b97a1e3c5678",
    "command_type": "REQUEST_CHECKPOINT",
    "command_state": "ACCEPTED",
    "target_type": "ATTEMPT",
    "target_id": "attempt_demo_001",
    "attempt_id": "attempt_demo_001"
  },
  "meta": {
    "request_id": "req_checkpoint_request_001"
  }
}
```

### Quy tắc cần nhớ

Tạo Command REQUEST_CHECKPOINT. ACCEPTED chỉ nghĩa Runtime nhận yêu cầu; Runtime có thể DEFERRED tới safe boundary hoặc SUCCEEDED với result.code=NO_OP nếu recovery point tương ứng đã durable/đang được tạo.

---

## 35.0 — Catch-up Runtime Event

**Nhóm:** BE Event History  
**Method:** `GET`  
**Endpoint:** `/api/v1/attempts/{attempt_id}/events`

### Headers / Quyền truy cập

Quyền operator theo cấu hình bảo mật

### Request (Body / Query)

```text
Path param:
- attempt_id: string. Ví dụ: attempt_demo_001

Query:
- after_seq: optional integer >= 0; default 0. Ví dụ: 123
- limit: optional integer 1..200, default 50. Ví dụ: 50

Ví dụ:
GET /api/v1/attempts/attempt_demo_001/events?after_seq=123&limit=50
```

### Response

```text
HTTP 200
{
  "data": [
    {
      "attempt_id": "attempt_demo_001",
      "job_id": "job_demo_001",
      "runtime_event_seq": 124,
      "event_type": "model.updated",
      "event_schema_version": 1,
      "occurred_at": "2026-09-07T03:24:18.527Z",
      "source_component": "Coordinator",
      "severity": "INFO",
      "details": {
        "input_model_version": 41,
        "output_model_version": 42
      }
    }
  ],
  "meta": {
    "complete": true,
    "gap_detected": false,
    "snapshot_required": false
  }
}
```

### Quy tắc cần nhớ

Dùng after_seq để lấy phần event bị lỡ. Thứ tự chuẩn là runtime_event_seq tăng dần, không phải timestamp.

---

## 36.0 — Audit events tổng quát

**Nhóm:** BE Audit  
**Method:** `GET`  
**Endpoint:** `/api/v1/events`

### Headers / Quyền truy cập

Quyền operator theo cấu hình bảo mật

### Request (Body / Query)

```text
Query params (optional):
- scope_type: SYSTEM | DATASET_BUILD | JOB | ATTEMPT | CHECKPOINT | COMMAND. Ví dụ: ATTEMPT
- scope_id: string; dùng cùng scope_type. Ví dụ: attempt_demo_001
- event_type: exact event type. Ví dụ: model.updated
- severity: INFO | WARNING | ERROR | CRITICAL. Ví dụ: INFO
- from: ISO-8601 UTC. Ví dụ: 2026-09-07T00:00:00Z
- to: ISO-8601 UTC. Ví dụ: 2026-09-08T00:00:00Z
- cursor: opaque string
- limit: integer 1..200, default 50

Ví dụ:
GET /api/v1/events?scope_type=ATTEMPT&scope_id=attempt_demo_001&severity=INFO&limit=50
```

### Response

```text
HTTP 200
{
  "data": [
    {
      "event_id": "124",
      "scope": {
        "type": "ATTEMPT",
        "id": "attempt_demo_001"
      },
      "event_type": "model.updated",
      "severity": "INFO",
      "occurred_at": "2026-09-07T03:24:18.527Z",
      "summary": "Canonical model advanced from version 41 to 42"
    }
  ],
  "page": {
    "next_cursor": null
  }
}
```

### Quy tắc cần nhớ

EventSeverity chỉ có INFO/WARNING/ERROR/CRITICAL. event_id là BIGSERIAL của DB nhưng public API serialize thành JSON string dạng số; runtime_event_seq mới là cursor semantic của Runtime Event.

---

## 37.0 — Chi tiết command

**Nhóm:** BE Command  
**Method:** `GET`  
**Endpoint:** `/api/v1/commands/{command_id}`

### Headers / Quyền truy cập

Quyền operator theo cấu hình bảo mật

### Request (Body / Query)

```text
Path param:
- command_id: UUID public dưới dạng string opaque. Ví dụ: 83ca1827-d68a-4af3-a834-b97a1e3c5678

Ví dụ:
GET /api/v1/commands/83ca1827-d68a-4af3-a834-b97a1e3c5678
```

### Response

```text
HTTP 200
{
  "data": {
    "command_id": "83ca1827-d68a-4af3-a834-b97a1e3c5678",
    "command_type": "REQUEST_CHECKPOINT",
    "state": "SUCCEEDED",
    "target_type": "ATTEMPT",
    "target_id": "attempt_demo_001",
    "request": {
      "reason": "manual"
    },
    "result": {
      "code": "NO_OP",
      "message": "Recovery point hiện tại đã durable"
    },
    "requested_at": "2026-09-07T03:20:00.000Z",
    "dispatched_at": "2026-09-07T03:20:00.020Z",
    "completed_at": "2026-09-07T03:20:00.120Z"
  },
  "meta": {
    "request_id": "req_command_show_001"
  }
}
```

### Quy tắc cần nhớ

Đây là resource Command nên field state là CommandState. PENDING xảy ra trước dispatch; ACCEPTED chưa có nghĩa target hoàn tất; NO_OP chỉ là result.code của SUCCEEDED. Muốn biết Attempt/Build hiện ở state nào phải query resource đích.

---

## 38.0 — Danh sách command

**Nhóm:** BE Command  
**Method:** `GET`  
**Endpoint:** `/api/v1/commands`

### Headers / Quyền truy cập

Quyền operator theo cấu hình bảo mật

### Request (Body / Query)

```text
Query params (optional):
- target_type: DATASET_BUILD | ATTEMPT. Ví dụ: ATTEMPT
- target_id: string opaque. Ví dụ: attempt_demo_001
- state: PENDING | ACCEPTED | DEFERRED | SUCCEEDED | REJECTED | FAILED. Ví dụ: SUCCEEDED
- from: ISO-8601 UTC. Ví dụ: 2026-09-07T00:00:00Z
- to: ISO-8601 UTC. Ví dụ: 2026-09-08T00:00:00Z
- cursor: opaque string
- limit: integer 1..200, default 50

Ví dụ:
GET /api/v1/commands?target_type=ATTEMPT&target_id=attempt_demo_001&state=SUCCEEDED&limit=50
```

### Response

```text
HTTP 200
{
  "data": [
    {
      "command_id": "83ca1827-d68a-4af3-a834-b97a1e3c5678",
      "command_type": "REQUEST_CHECKPOINT",
      "state": "SUCCEEDED",
      "target_type": "ATTEMPT",
      "target_id": "attempt_demo_001",
      "requested_at": "2026-09-07T03:20:00.000Z",
      "dispatched_at": "2026-09-07T03:20:00.020Z",
      "completed_at": "2026-09-07T03:20:00.120Z"
    }
  ],
  "page": {
    "next_cursor": null
  }
}
```

### Quy tắc cần nhớ

Danh sách Command phục vụ audit/monitor workflow bất đồng bộ. command_type cho biết hành động gì; state cho biết vòng đời Command; target_type/target_id cho biết resource bị tác động.

---

## 39.0 — Realtime Attempt stream

**Nhóm:** Runtime / WebSocket  
**Method:** `GET / Upgrade`  
**Endpoint:** `/ws/v1/attempts/{attempt_id}`

### Headers / Quyền truy cập

Dùng cùng cơ chế đăng nhập/quyền truy cập như REST

### Request (Body / Query)

```text
Path param:
- attempt_id: string. Ví dụ: attempt_demo_001

Query optional:
- after_seq: integer >= 0. Ví dụ: 123

Ví dụ upgrade URL:
/ws/v1/attempts/attempt_demo_001?after_seq=123
```

### Response

```text
EVENT
{
  "kind": "EVENT",
  "attempt_id": "attempt_demo_001",
  "runtime_event_seq": 124,
  "occurred_at": "2026-09-07T03:24:18.527Z",
  "payload": {
    "event_type": "model.updated",
    "event_schema_version": 1,
    "source_component": "Coordinator",
    "severity": "INFO",
    "details": {
      "input_model_version": 41,
      "output_model_version": 42
    }
  }
}

SNAPSHOT
{
  "kind": "SNAPSHOT",
  "attempt_id": "attempt_demo_001",
  "runtime_event_seq": null,
  "occurred_at": "2026-09-07T03:24:18.600Z",
  "payload": {
    "snapshot_seq": 123,
    "state": {
      "state": "RUNNING",
      "epoch": 2,
      "model_version": 42,
      "training_strategy": "strict_bsp",
      "stale": false
    }
  }
}

GAP
{
  "kind": "GAP",
  "attempt_id": "attempt_demo_001",
  "runtime_event_seq": null,
  "occurred_at": "2026-09-07T03:24:18.601Z",
  "payload": {
    "snapshot_required": true
  }
}
```

### Quy tắc cần nhớ

WebSocket chỉ stream live state/event, không nhận lệnh side-effect. Reconnect bằng after_seq; nếu có GAP thì lấy snapshot rồi tiếp tục từ cursor mới.

---

## 40.0 — Truy vấn chuỗi số liệu đo lường (Training Metrics Time-series)

**Nhóm:** Training / Metrics  
**Method:** `GET`  
**Endpoint:** `/api/v1/attempts/{attempt_id}/metrics`

### Headers / Quyền truy cập

Quyền operator theo cấu hình bảo mật theo security profile; X-Request-Id tùy chọn

### Request (Body / Query)

```text
Path param:

attempt_id: string opaque. Ví dụ: attempt_demo_001

Query optional:

name: string. Lọc tên metric cụ thể (loss, accuracy, throughput, latency_ms). Nếu không truyền thì trả về tất cả metrics của Attempt. Ví dụ: loss

worker_id: integer rank (0, 1, 2). Nếu để trống hoặc null thì chỉ lấy metric tổng hợp mức toàn Attempt.

from_step: integer >= 0. Lọc từ step_id này trở đi. Ví dụ: 0

to_step: integer >= 0. Lọc đến step_id này.

from: ISO-8601 UTC. Ví dụ: 2026-09-07T03:00:00.000Z

to: ISO-8601 UTC. Ví dụ: 2026-09-07T04:00:00.000Z

cursor: opaque string từ page.next_cursor

limit: integer 1..500, default 100.

Ví dụ request:
GET /api/v1/attempts/attempt_demo_001/metrics?name=loss&from_step=0&limit=100
```

### Response

```text
HTTP 200
{
        "data": [
                {
                        "metric_id": "1001",
                        "attempt_id": "attempt_demo_001",
                        "worker_id": null,
                        "step_id": 1,
                        "operation_id": 1,
                        "name": "loss",
                        "value": 0.45,
                        "unit": null,
                        "labels": {
                                "strategy": "strict_bsp",
                                "split": "train"
                        },
                        "observed_at": "2026-09-07T03:24:05.120Z"
                },
                {
                        "metric_id": "1002",
                        "attempt_id": "attempt_demo_001",
                        "worker_id": null,
                        "step_id": 2,
                        "operation_id": 2,
                        "name": "loss",
                        "value": 0.21,
                        "unit": null,
                        "labels": {
                                "strategy": "strict_bsp",
                                "split": "train"
                        },
                        "observed_at": "2026-09-07T03:24:18.527Z"
                },
                {
                        "metric_id": "1003",
                        "attempt_id": "attempt_demo_001",
                        "worker_id": null,
                        "step_id": 2,
                        "operation_id": 2,
                        "name": "accuracy",
                        "value": 89.0,
                        "unit": "%",
                        "labels": {
                                "strategy": "strict_bsp",
                                "split": "eval"
                        },
                        "observed_at": "2026-09-07T03:24:18.527Z"
                },
                {
                        "metric_id": "1004",
                        "attempt_id": "attempt_demo_001",
                        "worker_id": null,
                        "step_id": 2,
                        "operation_id": 2,
                        "name": "throughput",
                        "value": 5000.0,
                        "unit": "samples/sec",
                        "labels": {
                                "scope": "cluster"
                        },
                        "observed_at": "2026-09-07T03:24:18.527Z"
                }
        ],
        "page": {
                "next_cursor": null
        },
        "meta": {
                "request_id": "req_metrics_query_001"
        }
}
```

### Quy tắc cần nhớ

WebSocket chỉ stream live state/event, không nhận lệnh side-effect. Reconnect bằng after_seq; nếu có GAP thì lấy snapshot rồi tiếp tục từ cursor mới.

---
