"""Shared fixtures and environment setup for OCR service tests."""

import base64
import io
import os
import struct
import zlib

# Set environment variables BEFORE any app imports
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JARVIS_AUTH_BASE_URL", "http://localhost:8007")
os.environ.setdefault("OCR_LOG_LEVEL", "WARNING")
os.environ.setdefault("OCR_ENABLE_EASYOCR", "false")
os.environ.setdefault("OCR_ENABLE_PADDLEOCR", "false")
os.environ.setdefault("OCR_ENABLE_RAPIDOCR", "false")
os.environ.setdefault("OCR_ENABLE_APPLE_VISION", "false")
os.environ.setdefault("OCR_ENABLE_LLM_PROXY_VISION", "false")
os.environ.setdefault("OCR_ENABLE_LLM_PROXY_CLOUD", "false")
os.environ.setdefault("JARVIS_LLM_PROXY_URL", "")
os.environ.setdefault("JARVIS_APP_ID", "")
os.environ.setdefault("JARVIS_APP_KEY", "")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6379")

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth import verify_app_auth
from app.auth_cache import AuthCache, set_auth_cache
from app.providers.base import OCRResult, TextBlock


def _make_minimal_png() -> bytes:
    """Create a minimal valid 1x1 white PNG image."""
    # PNG signature
    signature = b"\x89PNG\r\n\x1a\n"

    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        chunk_data = chunk_type + data
        crc = struct.pack(">I", zlib.crc32(chunk_data) & 0xFFFFFFFF)
        length = struct.pack(">I", len(data))
        return length + chunk_data + crc

    # IHDR: 1x1, 8-bit RGB
    ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    ihdr = _chunk(b"IHDR", ihdr_data)

    # IDAT: single white pixel (filter byte 0 + RGB 255,255,255)
    raw_data = b"\x00\xff\xff\xff"
    compressed = zlib.compress(raw_data)
    idat = _chunk(b"IDAT", compressed)

    # IEND
    iend = _chunk(b"IEND", b"")

    return signature + ihdr + idat + iend


@pytest.fixture
def auth_headers() -> dict:
    """Standard auth headers for testing."""
    return {
        "X-Jarvis-App-Id": "test-app",
        "X-Jarvis-App-Key": "test-key",
    }


@pytest.fixture
def mock_auth():
    """Override verify_app_auth to always succeed."""
    async def _override():
        return {"app_id": "test-app", "name": "Test App"}

    return _override


@pytest.fixture
def mock_provider_manager():
    """Mock ProviderManager with tesseract returning canned OCRResult."""
    manager = MagicMock()
    canned_result = OCRResult(
        text="Hello World",
        blocks=[TextBlock(text="Hello World", bbox=[0.0, 0.0, 100.0, 20.0], confidence=0.95)],
        duration_ms=42.0,
    )
    manager.get_available_providers.return_value = {"tesseract": True}
    manager.process_image = AsyncMock(return_value=(canned_result, "tesseract"))
    manager.process_batch = AsyncMock(return_value=([canned_result], "tesseract"))
    manager.providers = {"tesseract": MagicMock(is_available=MagicMock(return_value=True), name="tesseract")}
    return manager


@pytest.fixture
def mock_queue_client():
    """Mock QueueClient with controlled returns."""
    qc = MagicMock()
    qc.get_status.return_value = {
        "redis_connected": True,
        "queue_length": 0,
        "workers_active": 0,
        "queue_name": "jarvis.ocr.jobs",
        "redis_info": {"host": "localhost", "port": 6379, "version": "7.0.0"},
    }
    qc.enqueue_job.return_value = "test-job-123"
    qc.get_job_status.return_value = {
        "job_id": "test-job-123",
        "status": "pending",
        "created_at": "2024-01-01T00:00:00Z",
    }
    qc.enqueue.return_value = True
    qc.dequeue_job.return_value = None
    return qc


@pytest.fixture
def client(mock_auth, mock_provider_manager, mock_queue_client):
    """TestClient with auth overridden and provider_manager/queue_client mocked."""
    import app.main as main_module
    from contextlib import asynccontextmanager

    # Replace lifespan to avoid real provider init / sys.exit
    @asynccontextmanager
    async def _test_lifespan(app):
        yield

    original_lifespan = main_module.app.router.lifespan_context
    main_module.app.router.lifespan_context = _test_lifespan
    main_module.provider_manager = mock_provider_manager
    main_module.app.dependency_overrides[verify_app_auth] = mock_auth

    with patch.object(main_module, "queue_client", mock_queue_client):
        with TestClient(main_module.app) as tc:
            yield tc

    main_module.app.dependency_overrides.clear()
    main_module.provider_manager = None
    main_module.app.router.lifespan_context = original_lifespan


@pytest.fixture
def sample_png_bytes() -> bytes:
    """Minimal valid 1x1 PNG as raw bytes."""
    return _make_minimal_png()


@pytest.fixture
def sample_base64_image() -> str:
    """Minimal valid 1x1 PNG as base64 string."""
    return base64.b64encode(_make_minimal_png()).decode("utf-8")


@pytest.fixture
def valid_queue_message() -> dict:
    """A complete valid v1 OCR request message dict."""
    return {
        "schema_version": 1,
        "job_id": "job-001",
        "workflow_id": "wf-001",
        "job_type": "ocr.extract_text.requested",
        "source": "jarvis-recipes-server",
        "target": "jarvis-ocr-service",
        "created_at": "2024-06-01T12:00:00Z",
        "attempt": 1,
        "reply_to": "jarvis.recipes.jobs",
        "payload": {
            "image_refs": [
                {"kind": "s3", "value": "s3://bucket/image.png", "index": 0},
            ],
            "image_count": 1,
            "options": {"language": "en"},
        },
        "trace": {
            "request_id": "req-001",
            "parent_job_id": "parent-001",
        },
    }


@pytest.fixture
def auth_cache():
    """Fresh AuthCache instance installed globally."""
    cache = AuthCache(success_ttl=60, failure_ttl=10)
    set_auth_cache(cache)
    return cache
