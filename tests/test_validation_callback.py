"""Tests for validation callback endpoint."""

import json
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from app.validation_state import PendingValidationState
from app.validation_callback import (
    ValidationCallbackPayload,
    _parse_validation_result,
    validation_callback,
    get_state_manager,
    set_state_manager
)


class TestParseValidationResult:
    """Test validation result parsing."""

    def test_parse_successful_result(self):
        """Should parse valid JSON result."""
        payload = ValidationCallbackPayload(
            job_id="llm-123",
            status="succeeded",
            result={"content": json.dumps({
                "is_valid": True,
                "confidence": 0.92,
                "reason": "Clear recipe text"
            })},
            metadata={"validation_state_key": "val-123"}
        )

        is_valid, confidence, reason = _parse_validation_result(payload)

        assert is_valid is True
        assert confidence == 0.92
        assert reason == "Clear recipe text"

    def test_parse_failed_status(self):
        """Failed status should return invalid."""
        payload = ValidationCallbackPayload(
            job_id="llm-123",
            status="failed",
            error={"code": "timeout", "message": "Model timed out"},
            metadata={"validation_state_key": "val-123"}
        )

        is_valid, confidence, reason = _parse_validation_result(payload)

        assert is_valid is False
        assert confidence == 0.0
        assert "timed out" in reason

    def test_parse_missing_result_content(self):
        """Missing result content should return invalid."""
        payload = ValidationCallbackPayload(
            job_id="llm-123",
            status="succeeded",
            result={},
            metadata={"validation_state_key": "val-123"}
        )

        is_valid, confidence, reason = _parse_validation_result(payload)

        assert is_valid is False
        assert confidence == 0.0

    def test_parse_invalid_json(self):
        """Invalid JSON should return invalid."""
        payload = ValidationCallbackPayload(
            job_id="llm-123",
            status="succeeded",
            result={"content": "not valid json"},
            metadata={"validation_state_key": "val-123"}
        )

        is_valid, confidence, reason = _parse_validation_result(payload)

        assert is_valid is False
        assert confidence == 0.0

    def test_confidence_clamped_to_valid_range(self):
        """Confidence should be clamped to 0.0-1.0."""
        payload = ValidationCallbackPayload(
            job_id="llm-123",
            status="succeeded",
            result={"content": json.dumps({
                "is_valid": True,
                "confidence": 1.5,  # Out of range
                "reason": "Test"
            })},
            metadata={"validation_state_key": "val-123"}
        )

        is_valid, confidence, reason = _parse_validation_result(payload)

        assert confidence == 1.0  # Clamped

    def test_reason_truncated(self):
        """Long reason should be truncated to 200 chars."""
        long_reason = "A" * 500
        payload = ValidationCallbackPayload(
            job_id="llm-123",
            status="succeeded",
            result={"content": json.dumps({
                "is_valid": True,
                "confidence": 0.9,
                "reason": long_reason
            })},
            metadata={"validation_state_key": "val-123"}
        )

        is_valid, confidence, reason = _parse_validation_result(payload)

        assert len(reason) == 200


class TestValidationCallbackEndpoint:
    """Test POST /internal/validation/callback."""

    @pytest.fixture
    def sample_pending_state(self):
        return PendingValidationState(
            original_job={
                "job_id": "ocr-123",
                "workflow_id": "wf-456",
                "reply_to": "jarvis.recipes.jobs",
                "payload": {
                    "image_refs": [{"index": 0, "kind": "local_path", "value": "/path/to/img.jpg"}],
                    "image_count": 1
                }
            },
            image_index=0,
            tier_name="tesseract",
            ocr_text="Spicy Beef Rice Bowls...",
            remaining_tiers=["apple_vision"],
            processed_results=[],
            validation_job_id="val-789",
            created_at="2026-02-03T12:00:00Z"
        )

    @pytest.fixture
    def valid_callback_payload(self):
        return ValidationCallbackPayload(
            job_id="llm-job-123",
            status="succeeded",
            result={"content": json.dumps({
                "is_valid": True,
                "confidence": 0.92,
                "reason": "Clear recipe text"
            })},
            metadata={
                "validation_state_key": "val-789",
                "ocr_job_id": "ocr-123",
                "workflow_id": "wf-456",
                "image_index": 0,
                "tier_name": "tesseract"
            }
        )

    @pytest.mark.asyncio
    async def test_callback_returns_200_on_success(self, valid_callback_payload, sample_pending_state):
        """Callback should return 200 when state found and processed."""
        mock_manager = MagicMock()
        mock_manager.get.return_value = sample_pending_state

        with patch('app.validation_callback.get_state_manager', return_value=mock_manager), \
             patch('app.validation_callback.continue_after_validation', new_callable=AsyncMock):
            result = await validation_callback(valid_callback_payload)

            assert result["status"] == "ok"
            assert result["processed"] is True

    @pytest.mark.asyncio
    async def test_callback_loads_state_from_redis(self, valid_callback_payload, sample_pending_state):
        """Callback should load state using validation_state_key from metadata."""
        mock_manager = MagicMock()
        mock_manager.get.return_value = sample_pending_state

        with patch('app.validation_callback.get_state_manager', return_value=mock_manager), \
             patch('app.validation_callback.continue_after_validation', new_callable=AsyncMock):
            await validation_callback(valid_callback_payload)

            mock_manager.get.assert_called_with("val-789")

    @pytest.mark.asyncio
    async def test_callback_raises_404_when_state_not_found(self, valid_callback_payload):
        """Callback should raise 404 if state expired or doesn't exist."""
        from fastapi import HTTPException

        mock_manager = MagicMock()
        mock_manager.get.return_value = None

        with patch('app.validation_callback.get_state_manager', return_value=mock_manager):
            with pytest.raises(HTTPException) as exc_info:
                await validation_callback(valid_callback_payload)

            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_callback_deletes_state_after_processing(self, valid_callback_payload, sample_pending_state):
        """State should be deleted from Redis after successful processing."""
        mock_manager = MagicMock()
        mock_manager.get.return_value = sample_pending_state

        with patch('app.validation_callback.get_state_manager', return_value=mock_manager), \
             patch('app.validation_callback.continue_after_validation', new_callable=AsyncMock):
            await validation_callback(valid_callback_payload)

            mock_manager.delete.assert_called_with("val-789")

    @pytest.mark.asyncio
    async def test_callback_parses_validation_result_from_content(self, valid_callback_payload, sample_pending_state):
        """Should extract is_valid, confidence, reason from result.content JSON."""
        mock_manager = MagicMock()
        mock_manager.get.return_value = sample_pending_state

        with patch('app.validation_callback.get_state_manager', return_value=mock_manager), \
             patch('app.validation_callback.continue_after_validation', new_callable=AsyncMock) as mock_continue:
            await validation_callback(valid_callback_payload)

            mock_continue.assert_called_once()
            call_kwargs = mock_continue.call_args[1]
            assert call_kwargs["is_valid"] is True
            assert call_kwargs["confidence"] == 0.92
            assert call_kwargs["reason"] == "Clear recipe text"

    @pytest.mark.asyncio
    async def test_callback_handles_failed_status(self, sample_pending_state):
        """Failed status from LLM should trigger next tier or failure."""
        payload = ValidationCallbackPayload(
            job_id="llm-job-123",
            status="failed",
            error={"code": "timeout", "message": "Model timed out"},
            metadata={
                "validation_state_key": "val-789",
                "ocr_job_id": "ocr-123",
                "workflow_id": "wf-456",
                "image_index": 0,
                "tier_name": "tesseract"
            }
        )

        mock_manager = MagicMock()
        mock_manager.get.return_value = sample_pending_state

        with patch('app.validation_callback.get_state_manager', return_value=mock_manager), \
             patch('app.validation_callback.continue_after_validation', new_callable=AsyncMock) as mock_continue:
            await validation_callback(payload)

            call_kwargs = mock_continue.call_args[1]
            assert call_kwargs["is_valid"] is False

    @pytest.mark.asyncio
    async def test_callback_handles_malformed_result_content(self, sample_pending_state):
        """Should handle non-JSON content gracefully."""
        payload = ValidationCallbackPayload(
            job_id="llm-job-123",
            status="succeeded",
            result={"content": "not valid json"},
            metadata={
                "validation_state_key": "val-789",
                "ocr_job_id": "ocr-123",
                "workflow_id": "wf-456",
                "image_index": 0,
                "tier_name": "tesseract"
            }
        )

        mock_manager = MagicMock()
        mock_manager.get.return_value = sample_pending_state

        with patch('app.validation_callback.get_state_manager', return_value=mock_manager), \
             patch('app.validation_callback.continue_after_validation', new_callable=AsyncMock) as mock_continue:
            result = await validation_callback(payload)

            assert result["status"] == "ok"
            call_kwargs = mock_continue.call_args[1]
            assert call_kwargs["is_valid"] is False

    @pytest.mark.asyncio
    async def test_callback_raises_400_for_missing_metadata(self):
        """Should raise 400 if metadata is missing."""
        from fastapi import HTTPException

        payload = ValidationCallbackPayload(
            job_id="llm-job-123",
            status="succeeded",
            result={"content": '{"is_valid": true}'},
            metadata=None
        )

        with pytest.raises(HTTPException) as exc_info:
            await validation_callback(payload)

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_callback_raises_400_for_missing_validation_state_key(self):
        """Should raise 400 if validation_state_key is missing from metadata."""
        from fastapi import HTTPException

        payload = ValidationCallbackPayload(
            job_id="llm-job-123",
            status="succeeded",
            result={"content": '{"is_valid": true}'},
            metadata={"ocr_job_id": "ocr-123"}  # Missing validation_state_key
        )

        with pytest.raises(HTTPException) as exc_info:
            await validation_callback(payload)

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_callback_passes_state_to_continue_function(self, valid_callback_payload, sample_pending_state):
        """Callback should pass the loaded state to continue_after_validation."""
        mock_manager = MagicMock()
        mock_manager.get.return_value = sample_pending_state

        with patch('app.validation_callback.get_state_manager', return_value=mock_manager), \
             patch('app.validation_callback.continue_after_validation', new_callable=AsyncMock) as mock_continue:
            await validation_callback(valid_callback_payload)

            call_kwargs = mock_continue.call_args[1]
            assert call_kwargs["state"] == sample_pending_state
