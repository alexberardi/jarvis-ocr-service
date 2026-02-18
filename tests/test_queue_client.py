"""Tests for app/queue_client.py."""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.queue_client import QueueClient


class TestGetClient:
    """Tests for QueueClient._get_client."""

    def test_redis_not_available(self):
        qc = QueueClient()
        with patch("app.queue_client.REDIS_AVAILABLE", False):
            qc._client = None
            assert qc._get_client() is None

    def test_redis_connection_success(self):
        qc = QueueClient()
        qc._client = None
        mock_redis_cls = MagicMock()
        mock_instance = MagicMock()
        mock_redis_cls.return_value = mock_instance
        mock_instance.ping.return_value = True

        with patch("app.queue_client.REDIS_AVAILABLE", True):
            with patch("app.queue_client.redis") as mock_redis_mod:
                mock_redis_mod.Redis = mock_redis_cls
                client = qc._get_client()

        assert client is mock_instance

    def test_redis_connection_failure(self):
        qc = QueueClient()
        qc._client = None
        mock_redis_cls = MagicMock()
        mock_redis_cls.return_value.ping.side_effect = Exception("Connection refused")

        with patch("app.queue_client.REDIS_AVAILABLE", True):
            with patch("app.queue_client.redis") as mock_redis_mod:
                mock_redis_mod.Redis = mock_redis_cls
                assert qc._get_client() is None

    def test_reuses_existing_client(self):
        qc = QueueClient()
        mock_client = MagicMock()
        qc._client = mock_client
        assert qc._get_client() is mock_client


class TestGetStatus:
    """Tests for QueueClient.get_status."""

    def test_redis_unavailable(self):
        qc = QueueClient()
        qc._client = None
        with patch.object(qc, "_get_client", return_value=None):
            status = qc.get_status()
        assert status["redis_connected"] is False

    def test_redis_connected(self):
        qc = QueueClient()
        mock_client = MagicMock()
        mock_client.llen.return_value = 5
        mock_client.info.return_value = {b"redis_version": b"7.0.0"}

        with patch.object(qc, "_get_client", return_value=mock_client):
            status = qc.get_status()

        assert status["redis_connected"] is True
        assert status["queue_length"] == 5

    def test_redis_error(self):
        qc = QueueClient()
        mock_client = MagicMock()
        mock_client.llen.side_effect = Exception("Redis error")

        with patch.object(qc, "_get_client", return_value=mock_client):
            status = qc.get_status()

        assert status["redis_connected"] is False
        assert "error" in status


class TestEnqueueJob:
    """Tests for QueueClient.enqueue_job."""

    def test_success(self):
        qc = QueueClient()
        mock_client = MagicMock()
        with patch.object(qc, "_get_client", return_value=mock_client):
            job_id = qc.enqueue_job({"image": "base64data"})

        assert isinstance(job_id, str)
        assert len(job_id) == 36  # UUID format
        mock_client.setex.assert_called_once()
        mock_client.lpush.assert_called_once()

    def test_redis_unavailable_raises(self):
        qc = QueueClient()
        with patch.object(qc, "_get_client", return_value=None):
            with pytest.raises(RuntimeError, match="Redis not available"):
                qc.enqueue_job({"image": "data"})

    def test_redis_error_raises(self):
        qc = QueueClient()
        mock_client = MagicMock()
        mock_client.setex.side_effect = Exception("write error")
        with patch.object(qc, "_get_client", return_value=mock_client):
            with pytest.raises(RuntimeError, match="Failed to enqueue"):
                qc.enqueue_job({"image": "data"})


class TestGetJobStatus:
    """Tests for QueueClient.get_job_status."""

    def test_success(self):
        qc = QueueClient()
        mock_client = MagicMock()
        job_data = json.dumps({"job_id": "j1", "status": "completed"}).encode()
        mock_client.get.return_value = job_data
        with patch.object(qc, "_get_client", return_value=mock_client):
            result = qc.get_job_status("j1")
        assert result["status"] == "completed"

    def test_not_found(self):
        qc = QueueClient()
        mock_client = MagicMock()
        mock_client.get.return_value = None
        with patch.object(qc, "_get_client", return_value=mock_client):
            assert qc.get_job_status("missing") is None

    def test_redis_unavailable(self):
        qc = QueueClient()
        with patch.object(qc, "_get_client", return_value=None):
            assert qc.get_job_status("j1") is None

    def test_redis_error(self):
        qc = QueueClient()
        mock_client = MagicMock()
        mock_client.get.side_effect = Exception("read error")
        with patch.object(qc, "_get_client", return_value=mock_client):
            assert qc.get_job_status("j1") is None


class TestDequeueJob:
    """Tests for QueueClient.dequeue_job."""

    def test_non_blocking_success(self):
        qc = QueueClient()
        mock_client = MagicMock()
        mock_client.rpop.return_value = json.dumps({"job_id": "j1"}).encode()
        with patch.object(qc, "_get_client", return_value=mock_client):
            result = qc.dequeue_job(timeout=0)
        assert result["job_id"] == "j1"

    def test_non_blocking_empty(self):
        qc = QueueClient()
        mock_client = MagicMock()
        mock_client.rpop.return_value = None
        with patch.object(qc, "_get_client", return_value=mock_client):
            assert qc.dequeue_job(timeout=0) is None

    def test_blocking_success(self):
        qc = QueueClient()
        mock_client = MagicMock()
        mock_client.brpop.return_value = (b"jarvis.ocr.jobs", json.dumps({"job_id": "j2"}).encode())
        with patch.object(qc, "_get_client", return_value=mock_client):
            result = qc.dequeue_job(timeout=5)
        assert result["job_id"] == "j2"

    def test_blocking_timeout(self):
        qc = QueueClient()
        mock_client = MagicMock()
        mock_client.brpop.return_value = None
        with patch.object(qc, "_get_client", return_value=mock_client):
            assert qc.dequeue_job(timeout=5) is None

    def test_redis_unavailable(self):
        qc = QueueClient()
        with patch.object(qc, "_get_client", return_value=None):
            assert qc.dequeue_job() is None


class TestEnqueue:
    """Tests for QueueClient.enqueue (generic)."""

    def test_lpush_by_default(self):
        qc = QueueClient()
        mock_client = MagicMock()
        with patch.object(qc, "_get_client", return_value=mock_client):
            result = qc.enqueue("test.queue", {"data": "value"})
        assert result is True
        mock_client.lpush.assert_called_once()

    def test_rpush_to_back(self):
        qc = QueueClient()
        mock_client = MagicMock()
        with patch.object(qc, "_get_client", return_value=mock_client):
            result = qc.enqueue("test.queue", {"data": "value"}, to_back=True)
        assert result is True
        mock_client.rpush.assert_called_once()

    def test_redis_unavailable_returns_false(self):
        qc = QueueClient()
        with patch.object(qc, "_get_client", return_value=None):
            assert qc.enqueue("test.queue", {"data": "value"}) is False

    def test_redis_error_returns_false(self):
        qc = QueueClient()
        mock_client = MagicMock()
        mock_client.lpush.side_effect = Exception("write error")
        with patch.object(qc, "_get_client", return_value=mock_client):
            assert qc.enqueue("test.queue", {"data": "value"}) is False

    def test_rq_dispatch_for_recipes_queue(self):
        qc = QueueClient()
        with patch.object(qc, "_enqueue_with_rq", return_value=True) as mock_rq:
            with patch("app.queue_client.RQ_AVAILABLE", True):
                result = qc.enqueue(
                    "jarvis.recipes.jobs",
                    {"job_type": "ocr.completed", "job_id": "j1"},
                )
        assert result is True
        mock_rq.assert_called_once()


class TestUpdateJobStatus:
    """Tests for QueueClient.update_job_status."""

    def test_success(self):
        qc = QueueClient()
        mock_client = MagicMock()
        existing = json.dumps({"job_id": "j1", "status": "pending"}).encode()
        mock_client.get.return_value = existing

        with patch.object(qc, "_get_client", return_value=mock_client):
            result = qc.update_job_status("j1", "completed", result={"text": "hi"})

        assert result is True
        mock_client.setex.assert_called_once()

    def test_job_not_found(self):
        qc = QueueClient()
        mock_client = MagicMock()
        mock_client.get.return_value = None
        with patch.object(qc, "_get_client", return_value=mock_client):
            assert qc.update_job_status("missing", "completed") is False

    def test_with_error(self):
        qc = QueueClient()
        mock_client = MagicMock()
        existing = json.dumps({"job_id": "j1", "status": "pending"}).encode()
        mock_client.get.return_value = existing

        with patch.object(qc, "_get_client", return_value=mock_client):
            result = qc.update_job_status("j1", "failed", error="Provider crashed")

        assert result is True
        # Verify the stored data includes the error
        stored = json.loads(mock_client.setex.call_args[0][2])
        assert stored["error"] == "Provider crashed"
        assert stored["status"] == "failed"

    def test_redis_error_returns_false(self):
        qc = QueueClient()
        mock_client = MagicMock()
        existing = json.dumps({"job_id": "j1", "status": "pending"}).encode()
        mock_client.get.return_value = existing
        mock_client.setex.side_effect = Exception("write failed")

        with patch.object(qc, "_get_client", return_value=mock_client):
            assert qc.update_job_status("j1", "completed") is False

    def test_redis_unavailable(self):
        qc = QueueClient()
        with patch.object(qc, "_get_client", return_value=None):
            assert qc.update_job_status("j1", "completed") is False


class TestDequeueJobErrors:
    """Additional error-path tests for QueueClient.dequeue_job."""

    def test_redis_error_returns_none(self):
        qc = QueueClient()
        mock_client = MagicMock()
        mock_client.rpop.side_effect = Exception("connection lost")
        with patch.object(qc, "_get_client", return_value=mock_client):
            assert qc.dequeue_job(timeout=0) is None

    def test_blocking_redis_error_returns_none(self):
        qc = QueueClient()
        mock_client = MagicMock()
        mock_client.brpop.side_effect = Exception("timeout error")
        with patch.object(qc, "_get_client", return_value=mock_client):
            assert qc.dequeue_job(timeout=5) is None


class TestEnqueueWithRQ:
    """Tests for QueueClient._enqueue_with_rq."""

    def test_rq_not_available_returns_false(self):
        qc = QueueClient()
        with patch("app.queue_client.RQ_AVAILABLE", False):
            assert qc._enqueue_with_rq("jarvis.recipes.jobs", {"job_id": "j1"}) is False

    def test_redis_unavailable_returns_false(self):
        qc = QueueClient()
        with patch("app.queue_client.RQ_AVAILABLE", True):
            with patch.object(qc, "_get_client", return_value=None):
                assert qc._enqueue_with_rq("jarvis.recipes.jobs", {"job_id": "j1"}) is False

    def test_missing_job_id_returns_false(self):
        qc = QueueClient()
        mock_client = MagicMock()
        mock_redis_cls = MagicMock()
        with patch("app.queue_client.RQ_AVAILABLE", True):
            with patch.object(qc, "_get_client", return_value=mock_client):
                with patch("app.queue_client.redis") as mock_redis_mod:
                    mock_redis_mod.Redis = mock_redis_cls
                    assert qc._enqueue_with_rq("jarvis.recipes.jobs", {"no_id": True}) is False

    def test_success(self):
        qc = QueueClient()
        mock_client = MagicMock()
        mock_redis_cls = MagicMock()
        mock_queue_cls = MagicMock()
        mock_queue_instance = MagicMock()
        mock_queue_cls.return_value = mock_queue_instance

        with patch("app.queue_client.RQ_AVAILABLE", True):
            with patch.object(qc, "_get_client", return_value=mock_client):
                with patch("app.queue_client.redis") as mock_redis_mod:
                    mock_redis_mod.Redis = mock_redis_cls
                    with patch("app.queue_client.Queue", mock_queue_cls):
                        result = qc._enqueue_with_rq(
                            "jarvis.recipes.jobs",
                            {"job_id": "j1", "job_type": "ocr.completed"},
                        )

        assert result is True
        mock_queue_instance.enqueue.assert_called_once()

    def test_exception_returns_false(self):
        qc = QueueClient()
        mock_client = MagicMock()
        mock_redis_cls = MagicMock()
        mock_queue_cls = MagicMock()
        mock_queue_cls.return_value.enqueue.side_effect = Exception("RQ error")

        with patch("app.queue_client.RQ_AVAILABLE", True):
            with patch.object(qc, "_get_client", return_value=mock_client):
                with patch("app.queue_client.redis") as mock_redis_mod:
                    mock_redis_mod.Redis = mock_redis_cls
                    with patch("app.queue_client.Queue", mock_queue_cls):
                        result = qc._enqueue_with_rq(
                            "jarvis.recipes.jobs",
                            {"job_id": "j1", "job_type": "ocr.completed"},
                        )

        assert result is False


class TestPublishMessage:
    """Tests for QueueClient.publish_message (deprecated wrapper)."""

    def test_delegates_to_enqueue(self):
        qc = QueueClient()
        with patch.object(qc, "enqueue", return_value=True) as mock_enqueue:
            result = qc.publish_message("test.queue", {"data": 1}, to_back=True)
        assert result is True
        mock_enqueue.assert_called_once_with("test.queue", {"data": 1}, True)
