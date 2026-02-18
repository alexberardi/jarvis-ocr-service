"""Tests for LLM Queue Client."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
import httpx

from app.llm_queue_client import LLMQueueClient
from app.validation_state import PendingValidationState


class TestLLMQueueClient:
    """Test enqueueing validation jobs to LLM proxy."""

    @pytest.fixture
    def client(self):
        return LLMQueueClient(
            llm_proxy_url="http://10.0.0.122:8000",
            app_id="ocr-service",
            app_key="test-key"
        )

    @pytest.fixture
    def sample_state(self):
        return PendingValidationState(
            original_job={
                "job_id": "ocr-123",
                "workflow_id": "wf-456",
                "reply_to": "jarvis.recipes.jobs"
            },
            image_index=0,
            tier_name="tesseract",
            ocr_text="Recipe text here...",
            remaining_tiers=["apple_vision"],
            processed_results=[],
            validation_job_id="val-789",
            created_at="2026-02-03T12:00:00Z"
        )

    def test_build_enqueue_payload_has_required_fields(self, client, sample_state):
        """Payload should have job_id, job_type, request, callback, metadata."""
        callback_url = "http://10.0.0.71:7031/internal/validation/callback"
        payload = client._build_payload(sample_state, callback_url)

        assert payload["job_type"] == "chat_completion"
        assert "job_id" in payload
        assert "request" in payload
        assert "callback" in payload
        assert "metadata" in payload

    def test_build_enqueue_payload_callback_url(self, client, sample_state):
        """Callback URL should point to OCR service."""
        callback_url = "http://10.0.0.71:7031/internal/validation/callback"
        payload = client._build_payload(sample_state, callback_url)

        assert payload["callback"]["url"] == callback_url

    def test_build_enqueue_payload_metadata_for_roundtrip(self, client, sample_state):
        """Metadata should contain fields needed to restore context on callback."""
        payload = client._build_payload(sample_state, "http://...")

        metadata = payload["metadata"]
        assert metadata["validation_state_key"] == "val-789"
        assert metadata["ocr_job_id"] == "ocr-123"
        assert metadata["workflow_id"] == "wf-456"
        assert metadata["image_index"] == 0
        assert metadata["tier_name"] == "tesseract"

    def test_build_enqueue_payload_request_has_validation_prompt(self, client, sample_state):
        """Request should contain messages with validation prompt."""
        payload = client._build_payload(sample_state, "http://...")

        messages = payload["request"]["messages"]
        assert len(messages) == 1
        assert "is_valid" in messages[0]["content"]
        assert "Recipe text here" in messages[0]["content"]

    def test_build_enqueue_payload_uses_json_response_format(self, client, sample_state):
        """Request should specify JSON response format."""
        payload = client._build_payload(sample_state, "http://...")

        assert payload["request"]["response_format"]["type"] == "json_object"

    def test_build_enqueue_payload_includes_model(self, client, sample_state):
        """Request should include the model name."""
        payload = client._build_payload(sample_state, "http://...")

        assert "model" in payload["request"]

    def test_build_enqueue_payload_truncates_long_text(self, client):
        """Long OCR text should be truncated in the prompt."""
        long_text = "A" * 1000
        state = PendingValidationState(
            original_job={"job_id": "ocr-123", "workflow_id": "wf-456"},
            image_index=0,
            tier_name="tesseract",
            ocr_text=long_text,
            remaining_tiers=[],
            processed_results=[],
            validation_job_id="val-789",
            created_at="2026-02-03T12:00:00Z"
        )
        payload = client._build_payload(state, "http://...")

        # Text should be truncated to 500 chars
        messages = payload["request"]["messages"]
        # Check that the full 1000-char text is NOT in the prompt
        assert long_text not in messages[0]["content"]
        # But the truncated version should be
        assert "A" * 500 in messages[0]["content"]

    @pytest.mark.asyncio
    async def test_enqueue_validation_posts_to_llm_proxy(self, client, sample_state):
        """enqueue() should POST to /internal/queue/enqueue."""
        with patch('httpx.AsyncClient.post', new_callable=AsyncMock) as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {"accepted": True, "job_id": "val-789"}
            )

            callback_url = "http://10.0.0.71:7031/internal/validation/callback"
            job_id = await client.enqueue(sample_state, callback_url)

            mock_post.assert_called_once()
            call_args = mock_post.call_args
            call_url = call_args[0][0]
            assert call_url == "http://10.0.0.122:8000/internal/queue/enqueue"

    @pytest.mark.asyncio
    async def test_enqueue_validation_includes_auth_headers(self, client, sample_state):
        """Request should include X-Jarvis-App-Id and X-Jarvis-App-Key."""
        with patch('httpx.AsyncClient.post', new_callable=AsyncMock) as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {"accepted": True, "job_id": "val-789"}
            )

            await client.enqueue(sample_state, "http://...")

            call_args = mock_post.call_args
            headers = call_args[1]["headers"]
            assert headers["X-Jarvis-App-Id"] == "ocr-service"
            assert headers["X-Jarvis-App-Key"] == "test-key"

    @pytest.mark.asyncio
    async def test_enqueue_validation_returns_job_id(self, client, sample_state):
        """enqueue() should return the job_id from response."""
        with patch('httpx.AsyncClient.post', new_callable=AsyncMock) as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {"accepted": True, "job_id": "returned-id"}
            )

            job_id = await client.enqueue(sample_state, "http://...")

            assert job_id == "returned-id"

    @pytest.mark.asyncio
    async def test_enqueue_raises_on_http_error(self, client, sample_state):
        """enqueue() should raise exception on non-200 response."""
        with patch('httpx.AsyncClient.post', new_callable=AsyncMock) as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.text = "Internal error"
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "Internal error", request=MagicMock(), response=mock_response
            )
            mock_post.return_value = mock_response

            with pytest.raises(httpx.HTTPStatusError):
                await client.enqueue(sample_state, "http://...")

    @pytest.mark.asyncio
    async def test_enqueue_raises_on_timeout(self, client, sample_state):
        """enqueue() should raise exception on timeout."""
        with patch('httpx.AsyncClient.post', new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = httpx.TimeoutException("timeout")

            with pytest.raises(httpx.TimeoutException):
                await client.enqueue(sample_state, "http://...")

    def test_get_validation_prompt_includes_instructions(self, client, sample_state):
        """Validation prompt should include clear instructions."""
        prompt = client._get_validation_prompt(sample_state.ocr_text)

        assert "OCR" in prompt or "ocr" in prompt.lower()
        assert "is_valid" in prompt
        assert "confidence" in prompt
        assert "reason" in prompt

    def test_client_stores_configuration(self, client):
        """Client should store configuration values."""
        assert client.llm_proxy_url == "http://10.0.0.122:8000"
        assert client.app_id == "ocr-service"
        assert client.app_key == "test-key"
