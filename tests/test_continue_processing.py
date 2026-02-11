"""Tests for continue processing logic after validation callback."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from app.validation_state import PendingValidationState
from app.continue_processing import (
    process_validation_result,
    _build_image_result,
    _create_completion_and_send
)


class TestBuildImageResult:
    """Test building image result dict."""

    def test_build_valid_image_result(self):
        """Should build result dict with all required fields."""
        result = _build_image_result(
            image_index=0,
            ocr_text="Recipe text here...",
            tier_name="tesseract",
            is_valid=True,
            confidence=0.92,
            reason="Clear recipe text",
            language="en"
        )

        assert result["index"] == 0
        assert result["ocr_text"] == "Recipe text here..."
        assert result["truncated"] is False
        assert result["meta"]["tier"] == "tesseract"
        assert result["meta"]["is_valid"] is True
        assert result["meta"]["confidence"] == 0.92
        assert result["meta"]["validation_reason"] == "Clear recipe text"
        assert result["meta"]["language"] == "en"
        assert result["error"] is None

    def test_build_invalid_image_result(self):
        """Should build result dict for invalid OCR."""
        result = _build_image_result(
            image_index=1,
            ocr_text="garbled text",
            tier_name="apple_vision",
            is_valid=False,
            confidence=0.2,
            reason="Text appears garbled",
            language="en"
        )

        assert result["index"] == 1
        assert result["meta"]["is_valid"] is False
        assert result["meta"]["confidence"] == 0.2

    def test_build_result_truncates_long_text(self):
        """Should truncate text exceeding max bytes."""
        long_text = "A" * 60000  # Exceeds 50KB
        result = _build_image_result(
            image_index=0,
            ocr_text=long_text,
            tier_name="tesseract",
            is_valid=True,
            confidence=0.9,
            reason="Valid",
            language="en"
        )

        assert result["truncated"] is True
        assert len(result["ocr_text"].encode("utf-8")) <= 51200  # 50KB limit

    def test_build_result_with_empty_text(self):
        """Should handle empty OCR text."""
        result = _build_image_result(
            image_index=0,
            ocr_text="",
            tier_name="tesseract",
            is_valid=False,
            confidence=0.0,
            reason="No text extracted",
            language="en"
        )

        assert result["ocr_text"] == ""
        assert result["meta"]["text_len"] == 0


class TestProcessValidationResult:
    """Test the main validation result processing logic."""

    @pytest.fixture
    def state_single_image_valid(self):
        """State where validation passed, single image, should complete."""
        return PendingValidationState(
            original_job={
                "job_id": "ocr-123",
                "workflow_id": "wf-456",
                "reply_to": "jarvis.recipes.jobs",
                "source": "jarvis-recipes-server",
                "payload": {
                    "image_refs": [{"index": 0, "kind": "local_path", "value": "/path/img.jpg"}],
                    "image_count": 1,
                    "options": {"language": "en"}
                },
                "trace": {"request_id": "req-123", "parent_job_id": "parent-456"}
            },
            image_index=0,
            tier_name="tesseract",
            ocr_text="Valid recipe text...",
            remaining_tiers=[],
            processed_results=[],
            validation_job_id="val-789",
            created_at="2026-02-03T12:00:00Z"
        )

    @pytest.fixture
    def state_with_remaining_tiers(self):
        """State with remaining tiers to try on failure."""
        return PendingValidationState(
            original_job={
                "job_id": "ocr-123",
                "workflow_id": "wf-456",
                "reply_to": "jarvis.recipes.jobs",
                "source": "jarvis-recipes-server",
                "payload": {
                    "image_refs": [{"index": 0, "kind": "local_path", "value": "/path/img.jpg"}],
                    "image_count": 1,
                    "options": {"language": "en"}
                },
                "trace": {"request_id": "req-123", "parent_job_id": "parent-456"}
            },
            image_index=0,
            tier_name="tesseract",
            ocr_text="Garbled text...",
            remaining_tiers=["apple_vision", "llm_local"],
            processed_results=[],
            validation_job_id="val-789",
            created_at="2026-02-03T12:00:00Z"
        )

    @pytest.fixture
    def state_multi_image(self):
        """State with multiple images, first image done."""
        return PendingValidationState(
            original_job={
                "job_id": "ocr-123",
                "workflow_id": "wf-456",
                "reply_to": "jarvis.recipes.jobs",
                "source": "jarvis-recipes-server",
                "payload": {
                    "image_refs": [
                        {"index": 0, "kind": "local_path", "value": "/path/img1.jpg"},
                        {"index": 1, "kind": "local_path", "value": "/path/img2.jpg"}
                    ],
                    "image_count": 2,
                    "options": {"language": "en"}
                },
                "trace": {"request_id": "req-123", "parent_job_id": "parent-456"}
            },
            image_index=0,
            tier_name="tesseract",
            ocr_text="First image text...",
            remaining_tiers=[],
            processed_results=[],
            validation_job_id="val-789",
            created_at="2026-02-03T12:00:00Z"
        )

    @pytest.mark.asyncio
    async def test_valid_result_single_image_sends_completion(self, state_single_image_valid):
        """Valid result for single image should send completion message."""
        with patch('app.continue_processing._create_completion_and_send', new_callable=AsyncMock) as mock_send:
            await process_validation_result(
                state=state_single_image_valid,
                is_valid=True,
                confidence=0.9,
                reason="Clear text"
            )

            mock_send.assert_called_once()
            # Access positional args
            call_args = mock_send.call_args[0]
            results = call_args[1]  # second positional arg is results
            assert len(results) == 1
            assert results[0]["meta"]["is_valid"] is True

    @pytest.mark.asyncio
    async def test_invalid_result_with_remaining_tiers_tries_next(self, state_with_remaining_tiers):
        """Invalid result with remaining tiers should try next tier."""
        with patch('app.continue_processing._process_with_next_tier', new_callable=AsyncMock) as mock_next_tier:
            await process_validation_result(
                state=state_with_remaining_tiers,
                is_valid=False,
                confidence=0.2,
                reason="Garbled text"
            )

            mock_next_tier.assert_called_once()
            # Access positional args: (state, next_tier, remaining_tiers)
            call_args = mock_next_tier.call_args[0]
            assert call_args[1] == "apple_vision"  # next_tier is second arg

    @pytest.mark.asyncio
    async def test_invalid_result_no_remaining_tiers_marks_failed(self):
        """Invalid result with no remaining tiers should mark image as failed."""
        state = PendingValidationState(
            original_job={
                "job_id": "ocr-123",
                "workflow_id": "wf-456",
                "reply_to": "jarvis.recipes.jobs",
                "source": "jarvis-recipes-server",
                "payload": {
                    "image_refs": [{"index": 0}],
                    "image_count": 1,
                    "options": {"language": "en"}
                },
                "trace": {"request_id": "req-123", "parent_job_id": "parent-456"}
            },
            image_index=0,
            tier_name="llm_cloud",
            ocr_text="Still garbled",
            remaining_tiers=[],  # No more tiers
            processed_results=[],
            validation_job_id="val-789",
            created_at="2026-02-03T12:00:00Z"
        )

        with patch('app.continue_processing._create_completion_and_send', new_callable=AsyncMock) as mock_send:
            await process_validation_result(
                state=state,
                is_valid=False,
                confidence=0.1,
                reason="All tiers failed"
            )

            mock_send.assert_called_once()
            results = mock_send.call_args[0][1]  # second positional arg
            assert results[0]["meta"]["is_valid"] is False

    @pytest.mark.asyncio
    async def test_multi_image_continues_to_next_image(self, state_multi_image):
        """With multiple images, should continue to next image after one completes."""
        with patch('app.continue_processing._process_next_image', new_callable=AsyncMock) as mock_next:
            await process_validation_result(
                state=state_multi_image,
                is_valid=True,
                confidence=0.9,
                reason="Valid"
            )

            mock_next.assert_called_once()
            # Access positional args: (state, current_result, next_image_index)
            call_args = mock_next.call_args[0]
            assert call_args[2] == 1  # next_image_index is third arg

    @pytest.mark.asyncio
    async def test_last_image_sends_completion(self):
        """Last image in multi-image job should send completion."""
        state = PendingValidationState(
            original_job={
                "job_id": "ocr-123",
                "workflow_id": "wf-456",
                "reply_to": "jarvis.recipes.jobs",
                "source": "jarvis-recipes-server",
                "payload": {
                    "image_refs": [{"index": 0}, {"index": 1}],
                    "image_count": 2,
                    "options": {"language": "en"}
                },
                "trace": {"request_id": "req-123", "parent_job_id": "parent-456"}
            },
            image_index=1,  # Last image
            tier_name="tesseract",
            ocr_text="Second image text",
            remaining_tiers=[],
            processed_results=[{  # First image already done
                "index": 0,
                "ocr_text": "First image text",
                "truncated": False,
                "meta": {"is_valid": True, "confidence": 0.9, "tier": "tesseract"}
            }],
            validation_job_id="val-789",
            created_at="2026-02-03T12:00:00Z"
        )

        with patch('app.continue_processing._create_completion_and_send', new_callable=AsyncMock) as mock_send:
            await process_validation_result(
                state=state,
                is_valid=True,
                confidence=0.85,
                reason="Valid"
            )

            mock_send.assert_called_once()
            results = mock_send.call_args[0][1]  # second positional arg
            assert len(results) == 2


class TestCreateCompletionAndSend:
    """Test completion message creation and sending."""

    @pytest.fixture
    def sample_original_job(self):
        return {
            "job_id": "ocr-123",
            "workflow_id": "wf-456",
            "reply_to": "jarvis.recipes.jobs",
            "source": "jarvis-recipes-server",
            "payload": {"image_count": 1},
            "trace": {"request_id": "req-123", "parent_job_id": "parent-456"}
        }

    @pytest.fixture
    def sample_results(self):
        return [{
            "index": 0,
            "ocr_text": "Recipe text",
            "truncated": False,
            "meta": {
                "is_valid": True,
                "confidence": 0.9,
                "tier": "tesseract",
                "language": "en",
                "text_len": 11
            },
            "error": None
        }]

    @pytest.mark.asyncio
    async def test_sends_to_reply_queue(self, sample_original_job, sample_results):
        """Should send completion message to reply_to queue."""
        with patch('app.continue_processing.queue_client') as mock_queue:
            mock_queue.enqueue.return_value = True

            await _create_completion_and_send(
                original_job=sample_original_job,
                results=sample_results
            )

            mock_queue.enqueue.assert_called_once()
            queue_name = mock_queue.enqueue.call_args[0][0]
            assert queue_name == "jarvis.recipes.jobs"

    @pytest.mark.asyncio
    async def test_completion_message_has_correct_structure(self, sample_original_job, sample_results):
        """Completion message should match queue-flow schema."""
        with patch('app.continue_processing.queue_client') as mock_queue:
            mock_queue.enqueue.return_value = True

            await _create_completion_and_send(
                original_job=sample_original_job,
                results=sample_results
            )

            message = mock_queue.enqueue.call_args[0][1]

            assert message["schema_version"] == 1
            assert message["job_type"] == "ocr.completed"
            assert message["source"] == "jarvis-ocr-service"
            assert "results" in message["payload"]
            assert message["trace"]["parent_job_id"] == "ocr-123"
            assert message["workflow_id"] == "wf-456"

    @pytest.mark.asyncio
    async def test_status_success_when_any_valid(self, sample_original_job, sample_results):
        """Status should be success if at least one image is valid."""
        with patch('app.continue_processing.queue_client') as mock_queue:
            mock_queue.enqueue.return_value = True

            await _create_completion_and_send(
                original_job=sample_original_job,
                results=sample_results
            )

            message = mock_queue.enqueue.call_args[0][1]
            assert message["payload"]["status"] == "success"

    @pytest.mark.asyncio
    async def test_status_failed_when_none_valid(self, sample_original_job):
        """Status should be failed if no images are valid."""
        results = [{
            "index": 0,
            "ocr_text": "",
            "truncated": False,
            "meta": {"is_valid": False, "confidence": 0.1},
            "error": {"code": "ocr_no_valid_output", "message": "All tiers failed"}
        }]

        with patch('app.continue_processing.queue_client') as mock_queue:
            mock_queue.enqueue.return_value = True

            await _create_completion_and_send(
                original_job=sample_original_job,
                results=results
            )

            message = mock_queue.enqueue.call_args[0][1]
            assert message["payload"]["status"] == "failed"
