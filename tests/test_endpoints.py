"""Tests for app/main.py API endpoints."""

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth import verify_app_auth
from app.exceptions import OCRProcessingException, ProviderUnavailableException
from app.providers.base import OCRResult, TextBlock


class TestHealthEndpoint:
    """Tests for GET /health."""

    def test_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_no_auth_required(self):
        """Health endpoint should not require auth."""
        import app.main as main_module

        with TestClient(main_module.app) as tc:
            resp = tc.get("/health")
        assert resp.status_code == 200


class TestProvidersEndpoint:
    """Tests for GET /v1/providers."""

    def test_returns_providers(self, client):
        resp = client.get("/v1/providers")
        assert resp.status_code == 200
        assert "providers" in resp.json()

    def test_401_without_auth(self):
        """Should fail without auth headers."""
        import app.main as main_module

        # Don't override auth
        with TestClient(main_module.app) as tc:
            resp = tc.get("/v1/providers")
        # Will fail because no auth and no provider_manager
        assert resp.status_code in (401, 503)

    def test_503_when_not_initialized(self, mock_auth):
        """Should return 503 when provider_manager is None."""
        import app.main as main_module
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _noop_lifespan(app):
            yield

        original_lifespan = main_module.app.router.lifespan_context
        main_module.app.router.lifespan_context = _noop_lifespan
        main_module.provider_manager = None
        main_module.app.dependency_overrides[verify_app_auth] = mock_auth

        try:
            with TestClient(main_module.app) as tc:
                resp = tc.get("/v1/providers")
            assert resp.status_code == 503
        finally:
            main_module.app.dependency_overrides.clear()
            main_module.provider_manager = None
            main_module.app.router.lifespan_context = original_lifespan


class TestQueueStatusEndpoint:
    """Tests for GET /v1/queue/status."""

    def test_connected(self, client, mock_queue_client):
        resp = client.get("/v1/queue/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["redis_connected"] is True

    def test_disconnected(self, client, mock_queue_client):
        mock_queue_client.get_status.return_value = {
            "redis_connected": False,
            "error": "Not available",
        }
        resp = client.get("/v1/queue/status")
        assert resp.status_code == 503


class TestOCREndpoint:
    """Tests for POST /v1/ocr."""

    def test_success(self, client, mock_queue_client, sample_base64_image):
        resp = client.post("/v1/ocr", json={
            "provider": "auto",
            "image": {
                "content_type": "image/png",
                "base64": sample_base64_image,
            },
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == "test-job-123"
        assert data["status"] == "pending"

    def test_runtime_error_returns_503(self, client, mock_queue_client, sample_base64_image):
        mock_queue_client.enqueue_job.side_effect = RuntimeError("Redis down")
        resp = client.post("/v1/ocr", json={
            "provider": "auto",
            "image": {
                "content_type": "image/png",
                "base64": sample_base64_image,
            },
        })
        assert resp.status_code == 503

    def test_unexpected_error_returns_500(self, client, mock_queue_client, sample_base64_image):
        mock_queue_client.enqueue_job.side_effect = Exception("unexpected")
        resp = client.post("/v1/ocr", json={
            "provider": "auto",
            "image": {
                "content_type": "image/png",
                "base64": sample_base64_image,
            },
        })
        assert resp.status_code == 500


class TestJobStatusEndpoint:
    """Tests for GET /v1/ocr/jobs/{job_id}."""

    def test_pending_job(self, client, mock_queue_client):
        resp = client.get("/v1/ocr/jobs/test-job-123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"
        assert data["job_id"] == "test-job-123"

    def test_completed_job(self, client, mock_queue_client):
        mock_queue_client.get_job_status.return_value = {
            "job_id": "j1",
            "status": "completed",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:01:00Z",
            "result": {
                "provider_used": "tesseract",
                "text": "Hello",
                "blocks": [{"text": "Hello", "bbox": [0, 0, 100, 20], "confidence": 0.95}],
                "meta": {"duration_ms": 42.0},
            },
        }
        resp = client.get("/v1/ocr/jobs/j1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["result"]["text"] == "Hello"

    def test_failed_job(self, client, mock_queue_client):
        mock_queue_client.get_job_status.return_value = {
            "job_id": "j2",
            "status": "failed",
            "created_at": "2024-01-01T00:00:00Z",
            "error": "Provider failed",
        }
        resp = client.get("/v1/ocr/jobs/j2")
        assert resp.status_code == 200
        assert resp.json()["error"] == "Provider failed"

    def test_not_found(self, client, mock_queue_client):
        mock_queue_client.get_job_status.return_value = None
        resp = client.get("/v1/ocr/jobs/nonexistent")
        assert resp.status_code == 404


class TestBatchEndpoint:
    """Tests for POST /v1/ocr/batch."""

    def test_success(self, client, mock_provider_manager, sample_base64_image):
        resp = client.post("/v1/ocr/batch", json={
            "provider": "auto",
            "images": [
                {"content_type": "image/png", "base64": sample_base64_image},
            ],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) == 1
        assert data["meta"]["total_images"] == 1

    def test_provider_unavailable_returns_400(self, client, mock_provider_manager, sample_base64_image):
        mock_provider_manager.process_batch.side_effect = ProviderUnavailableException("not available")
        resp = client.post("/v1/ocr/batch", json={
            "provider": "easyocr",
            "images": [{"content_type": "image/png", "base64": sample_base64_image}],
        })
        assert resp.status_code == 400

    def test_processing_error_returns_422(self, client, mock_provider_manager, sample_base64_image):
        mock_provider_manager.process_batch.side_effect = OCRProcessingException("corrupt image")
        resp = client.post("/v1/ocr/batch", json={
            "provider": "tesseract",
            "images": [{"content_type": "image/png", "base64": sample_base64_image}],
        })
        assert resp.status_code == 422

    def test_value_error_returns_400(self, client, mock_provider_manager, sample_base64_image):
        mock_provider_manager.process_batch.side_effect = ValueError("bad input")
        resp = client.post("/v1/ocr/batch", json={
            "provider": "tesseract",
            "images": [{"content_type": "image/png", "base64": sample_base64_image}],
        })
        assert resp.status_code == 400

    def test_unexpected_error_returns_500(self, client, mock_provider_manager, sample_base64_image):
        mock_provider_manager.process_batch.side_effect = Exception("unexpected")
        resp = client.post("/v1/ocr/batch", json={
            "provider": "tesseract",
            "images": [{"content_type": "image/png", "base64": sample_base64_image}],
        })
        assert resp.status_code == 500

    def test_503_when_not_initialized(self, mock_auth, sample_base64_image):
        import app.main as main_module
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _noop_lifespan(app):
            yield

        original_lifespan = main_module.app.router.lifespan_context
        main_module.app.router.lifespan_context = _noop_lifespan
        main_module.provider_manager = None
        main_module.app.dependency_overrides[verify_app_auth] = mock_auth

        try:
            with TestClient(main_module.app) as tc:
                resp = tc.post("/v1/ocr/batch", json={
                    "provider": "auto",
                    "images": [{"content_type": "image/png", "base64": sample_base64_image}],
                })
            assert resp.status_code == 503
        finally:
            main_module.app.dependency_overrides.clear()
            main_module.provider_manager = None
            main_module.app.router.lifespan_context = original_lifespan
