"""Unit tests for Backend Step metrics and Epoch metrics (Plan V2)."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pbl4.management_backend.api.attempts import router
from pbl4.management_backend.repositories import event_repository


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        yield client


def test_step_metrics_returns_none(client):
    """Public Step metrics stay null even when worker loss is available."""
    mock_step = {
        "step_id": 1,
        "operation_id": 1,
        "training_strategy": "strict_bsp",
        "epoch": 0,
        "batch_ordinal": 0,
        "input_model_version": 0,
        "output_model_version": 1,
        "state": "COMMITTED",
        "total_sample_count": 16,
    }
    worker = {"worker_id": 0, "session_id": 1, "shard_id": 0, "batch_id": 0,
              "sample_count": 16, "loss": 1.5, "accuracy": None}
    with (
        patch("pbl4.management_backend.db.get_connection"),
        patch("pbl4.management_backend.services.attempt_service.get_attempt"),
        patch("pbl4.management_backend.repositories.step_repository.get_step", return_value=mock_step),
        patch("pbl4.management_backend.repositories.step_repository.get_worker_steps", return_value=[worker]),
    ):
        response = client.get("/api/v1/attempts/att-1/steps/1")
        assert response.status_code == 200
        res = response.json()["data"]
        assert res["metrics"] is None
        assert res["step_id"] == 1
        assert res["worker_steps"][0]["loss"] == 1.5


def test_list_events_with_epoch_metrics_finalized_filter():
    """Verify existing event_repository.list_events filters by epoch.metrics.finalized."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    records = [
        {
            "event_id": 1,
            "attempt_id": "att-1",
            "runtime_event_seq": 10,
            "event_type": "epoch.metrics.finalized",
            "payload_jsonb": {"epoch_index": 0, "sample_count": 16, "training_loss": 2.375, "training_accuracy": 50.0},
        }
    ]
    mock_cursor.fetchall.return_value = records

    res = event_repository.list_events(mock_conn, attempt_id="att-1", event_type="epoch.metrics.finalized")
    assert len(res) == 1
    assert res[0]["event_type"] == "epoch.metrics.finalized"
    assert res[0]["payload_jsonb"]["epoch_index"] == 0
    assert res[0]["payload_jsonb"]["training_loss"] == 2.375


@pytest.mark.parametrize("limit", [1, 2, 5])
def test_pagination_cursor_does_not_skip_rows(client, limit):
    all_steps = [
        {"step_id": i, "operation_id": i, "state": "COMMITTED",
         "input_model_version": i, "output_model_version": i + 1,
         "epoch": 0, "batch_ordinal": i}
        for i in range(4, -1, -1)
    ]

    def mock_list_steps(conn, attempt_id, *, limit, cursor):
        filtered = [s for s in all_steps if cursor is None or s["step_id"] < int(cursor)]
        return filtered[:limit]

    with (
        patch("pbl4.management_backend.db.get_connection"),
        patch("pbl4.management_backend.services.attempt_service.get_attempt"),
        patch("pbl4.management_backend.repositories.step_repository.list_steps", side_effect=mock_list_steps),
    ):
        cursor, ids = None, []
        while True:
            params = {"limit": limit}
            if cursor is not None:
                params["cursor"] = cursor
            response = client.get("/api/v1/attempts/att-1/steps", params=params)
            assert response.status_code == 200
            page = response.json()
            assert len(page["data"]) <= limit
            assert all(step["metrics"] is None for step in page["data"])
            ids.extend(step["step_id"] for step in page["data"])
            cursor = page["page"]["next_cursor"]
            if cursor is None:
                break
        assert ids == [4, 3, 2, 1, 0]


def test_step_list_rejects_zero_limit(client):
    assert client.get("/api/v1/attempts/att-1/steps", params={"limit": 0}).status_code == 422


def test_empty_step_list_preserves_response(client):
    with (
        patch("pbl4.management_backend.db.get_connection"),
        patch("pbl4.management_backend.services.attempt_service.get_attempt"),
        patch("pbl4.management_backend.repositories.step_repository.list_steps", return_value=[]),
    ):
        response = client.get("/api/v1/attempts/att-1/steps").json()
        assert response["data"] == []
        assert response["page"]["next_cursor"] is None
