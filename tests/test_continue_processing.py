"""Tests for continue processing logic after validation callback."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from app.providers.base import OCRResult, TextBlock
from app.validation_state import PendingValidationState
from app.continue_processing import (
    process_validation_result,
    _build_image_result,
    _create_completion_and_send,
    _process_with_next_tier,
    _process_next_image,
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

    @pytest.mark.asyncio
    async def test_enqueue_failure_logs_error(self, sample_original_job, sample_results):
        """Should log error when enqueue returns False."""
        with patch('app.continue_processing.queue_client') as mock_queue:
            mock_queue.enqueue.return_value = False

            await _create_completion_and_send(
                original_job=sample_original_job,
                results=sample_results
            )

            mock_queue.enqueue.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_reply_to_does_not_enqueue(self, sample_results):
        """Should not enqueue when no reply_to queue specified."""
        job_no_reply = {
            "job_id": "ocr-123",
            "workflow_id": "wf-456",
            "source": "jarvis-recipes-server",
            "payload": {"image_count": 1},
            "trace": {"request_id": "req-123", "parent_job_id": "parent-456"}
        }

        with patch('app.continue_processing.queue_client') as mock_queue:
            await _create_completion_and_send(
                original_job=job_no_reply,
                results=sample_results
            )

            mock_queue.enqueue.assert_not_called()

    @pytest.mark.asyncio
    async def test_failed_status_includes_error(self, sample_original_job):
        """Failed status should include error in payload."""
        results = [{
            "index": 0,
            "ocr_text": "",
            "truncated": False,
            "meta": {"is_valid": False, "confidence": 0.0},
            "error": {"code": "ocr_engine_error", "message": "Provider crashed"}
        }]
        error = {"message": "All tiers exhausted", "code": "ocr_no_valid_output"}

        with patch('app.continue_processing.queue_client') as mock_queue:
            mock_queue.enqueue.return_value = True

            await _create_completion_and_send(
                original_job=sample_original_job,
                results=results,
                error=error
            )

            message = mock_queue.enqueue.call_args[0][1]
            assert message["payload"]["status"] == "failed"
            assert message["payload"]["error"]["code"] == "ocr_no_valid_output"


def _make_state(**overrides) -> PendingValidationState:
    """Helper to build a PendingValidationState with defaults."""
    defaults = {
        "original_job": {
            "job_id": "ocr-123",
            "workflow_id": "wf-456",
            "reply_to": "jarvis.recipes.jobs",
            "source": "jarvis-recipes-server",
            "payload": {
                "image_refs": [
                    {"index": 0, "kind": "s3", "value": "s3://bucket/img0.png"},
                    {"index": 1, "kind": "s3", "value": "s3://bucket/img1.png"},
                ],
                "image_count": 2,
                "options": {"language": "en"}
            },
            "trace": {"request_id": "req-1", "parent_job_id": "parent-1"}
        },
        "image_index": 0,
        "tier_name": "tesseract",
        "ocr_text": "Some text",
        "remaining_tiers": ["easyocr"],
        "processed_results": [],
        "validation_job_id": "val-001",
        "created_at": "2026-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return PendingValidationState(**defaults)


def _canned_ocr_result(text: str = "OCR output") -> OCRResult:
    return OCRResult(
        text=text,
        blocks=[TextBlock(text=text, bbox=[0, 0, 100, 20], confidence=0.95)],
        duration_ms=42.0,
    )


class TestProcessWithNextTier:
    """Tests for _process_with_next_tier tier-fallback logic."""

    @pytest.mark.asyncio
    async def test_image_ref_not_found_completes_with_error(self):
        """Complete with error when image ref is missing."""
        state = _make_state(image_index=99)  # no ref at index 99

        with patch('app.continue_processing._create_completion_and_send', new_callable=AsyncMock) as mock_send:
            await _process_with_next_tier(state, "easyocr", [])

            mock_send.assert_called_once()
            results = mock_send.call_args[0][1]
            assert results[-1]["error"]["code"] == "image_not_found"

    @pytest.mark.asyncio
    async def test_image_resolver_error_completes_with_error(self):
        """Complete with error when image resolver raises."""
        from app.image_resolver import ImageResolverError

        state = _make_state()

        with patch('app.image_resolver.resolve_image', side_effect=ImageResolverError("S3 down")):
            with patch('app.continue_processing._create_completion_and_send', new_callable=AsyncMock) as mock_send:
                await _process_with_next_tier(state, "easyocr", [])

                mock_send.assert_called_once()
                results = mock_send.call_args[0][1]
                assert results[-1]["error"]["code"] == "image_not_found"

    @pytest.mark.asyncio
    async def test_success_enqueues_validation(self):
        """Successfully process image and enqueue LLM validation."""
        state = _make_state()
        mock_pm = MagicMock()
        mock_pm.process_image = AsyncMock(return_value=(_canned_ocr_result(), "easyocr"))
        mock_state_mgr = MagicMock()
        mock_llm = MagicMock()
        mock_llm.enqueue = AsyncMock()

        with patch('app.image_resolver.resolve_image', return_value=(b"img", "image/png")):
            with patch('app.provider_manager.ProviderManager', return_value=mock_pm):
                with patch('app.validation_callback.get_state_manager', return_value=mock_state_mgr):
                    with patch('app.llm_queue_client.get_llm_queue_client', return_value=mock_llm):
                        await _process_with_next_tier(state, "easyocr", ["llm_local"])

        mock_state_mgr.save.assert_called_once()
        mock_llm.enqueue.assert_called_once()
        saved_state = mock_state_mgr.save.call_args[0][0]
        assert saved_state.tier_name == "easyocr"
        assert saved_state.remaining_tiers == ["llm_local"]

    @pytest.mark.asyncio
    async def test_tier_failure_with_remaining_retries_next(self):
        """When tier fails with remaining tiers, recurse to next tier."""
        state = _make_state()

        with patch('app.image_resolver.resolve_image', return_value=(b"img", "image/png")):
            with patch('app.provider_manager.ProviderManager', side_effect=RuntimeError("init fail")):
                with patch('app.continue_processing._create_completion_and_send', new_callable=AsyncMock) as mock_send:
                    # remaining_tiers=["llm_local"] means it will recurse
                    # The recursion will also fail (ProviderManager still raises),
                    # and with no remaining tiers, it will complete
                    await _process_with_next_tier(state, "easyocr", ["llm_local"])

                    mock_send.assert_called_once()
                    results = mock_send.call_args[0][1]
                    assert results[-1]["error"]["code"] == "ocr_engine_error"

    @pytest.mark.asyncio
    async def test_tier_failure_no_remaining_completes_failed(self):
        """When tier fails with no remaining tiers, complete with error."""
        state = _make_state(remaining_tiers=[])

        with patch('app.image_resolver.resolve_image', return_value=(b"img", "image/png")):
            with patch('app.provider_manager.ProviderManager', side_effect=RuntimeError("init fail")):
                with patch('app.continue_processing._create_completion_and_send', new_callable=AsyncMock) as mock_send:
                    await _process_with_next_tier(state, "easyocr", [])

                    mock_send.assert_called_once()
                    results = mock_send.call_args[0][1]
                    assert results[-1]["error"]["code"] == "ocr_engine_error"
                    assert results[-1]["meta"]["tier"] == "easyocr"


class TestProcessNextImage:
    """Tests for _process_next_image multi-image logic."""

    @pytest.fixture
    def current_result(self):
        return {
            "index": 0,
            "ocr_text": "First image text",
            "truncated": False,
            "meta": {"is_valid": True, "confidence": 0.9, "tier": "tesseract",
                     "language": "en", "text_len": 16, "validation_reason": "ok"},
            "error": None,
        }

    @pytest.mark.asyncio
    async def test_image_ref_not_found_completes(self, current_result):
        """Complete with existing results when next image ref not found."""
        state = _make_state(image_index=0)

        with patch('app.continue_processing._create_completion_and_send', new_callable=AsyncMock) as mock_send:
            await _process_next_image(state, current_result, next_image_index=99)

            mock_send.assert_called_once()
            results = mock_send.call_args[0][1]
            assert len(results) == 1  # just the current_result

    @pytest.mark.asyncio
    async def test_no_enabled_tiers_completes(self, current_result):
        """Complete when no tiers are enabled."""
        state = _make_state()

        from app.continue_processing import config as real_config
        with patch.object(real_config, 'get_enabled_tiers', return_value=[]):
            with patch('app.continue_processing._create_completion_and_send', new_callable=AsyncMock) as mock_send:
                await _process_next_image(state, current_result, next_image_index=1)

                mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_success_enqueues_validation_for_next_image(self, current_result):
        """Successfully process next image and enqueue validation."""
        state = _make_state()
        mock_pm = MagicMock()
        mock_pm.process_image = AsyncMock(return_value=(_canned_ocr_result(), "tesseract"))
        mock_state_mgr = MagicMock()
        mock_llm = MagicMock()
        mock_llm.enqueue = AsyncMock()

        from app.continue_processing import config as real_config
        with patch('app.image_resolver.resolve_image', return_value=(b"img", "image/png")):
            with patch('app.provider_manager.ProviderManager', return_value=mock_pm):
                with patch('app.validation_callback.get_state_manager', return_value=mock_state_mgr):
                    with patch('app.llm_queue_client.get_llm_queue_client', return_value=mock_llm):
                        with patch.object(real_config, 'get_enabled_tiers', return_value=["tesseract", "easyocr"]):
                            await _process_next_image(state, current_result, next_image_index=1)

        mock_state_mgr.save.assert_called_once()
        saved_state = mock_state_mgr.save.call_args[0][0]
        assert saved_state.image_index == 1
        assert saved_state.tier_name == "tesseract"
        mock_llm.enqueue.assert_called_once()

    @pytest.mark.asyncio
    async def test_resolver_error_with_more_images_continues(self, current_result):
        """On resolver error with more images, continue to next."""
        from app.image_resolver import ImageResolverError

        state = _make_state()
        state.original_job["payload"]["image_count"] = 3
        state.original_job["payload"]["image_refs"].append(
            {"index": 2, "kind": "s3", "value": "s3://bucket/img2.png"}
        )

        from app.continue_processing import config as real_config
        with patch('app.image_resolver.resolve_image', side_effect=ImageResolverError("S3 err")):
            with patch.object(real_config, 'get_enabled_tiers', return_value=["tesseract"]):
                with patch('app.continue_processing._create_completion_and_send', new_callable=AsyncMock) as mock_send:
                    await _process_next_image(state, current_result, next_image_index=1)

                    mock_send.assert_called_once()
                    results = mock_send.call_args[0][1]
                    error_results = [r for r in results if (r.get("error") or {}).get("code") == "image_not_found"]
                    assert len(error_results) >= 2

    @pytest.mark.asyncio
    async def test_resolver_error_last_image_completes(self, current_result):
        """On resolver error for last image, send completion."""
        from app.image_resolver import ImageResolverError

        state = _make_state()

        from app.continue_processing import config as real_config
        with patch('app.image_resolver.resolve_image', side_effect=ImageResolverError("S3 err")):
            with patch.object(real_config, 'get_enabled_tiers', return_value=["tesseract"]):
                with patch('app.continue_processing._create_completion_and_send', new_callable=AsyncMock) as mock_send:
                    await _process_next_image(state, current_result, next_image_index=1)

                    mock_send.assert_called_once()
                    results = mock_send.call_args[0][1]
                    error_results = [r for r in results if (r.get("error") or {}).get("code") == "image_not_found"]
                    assert len(error_results) >= 1

    @pytest.mark.asyncio
    async def test_provider_failure_last_image_completes(self, current_result):
        """On provider failure for last image, send completion."""
        state = _make_state()

        from app.continue_processing import config as real_config
        with patch('app.image_resolver.resolve_image', return_value=(b"img", "image/png")):
            with patch.object(real_config, 'get_enabled_tiers', return_value=["tesseract"]):
                with patch('app.provider_manager.ProviderManager', side_effect=RuntimeError("boom")):
                    with patch('app.continue_processing._create_completion_and_send', new_callable=AsyncMock) as mock_send:
                        await _process_next_image(state, current_result, next_image_index=1)

                        mock_send.assert_called_once()
                        results = mock_send.call_args[0][1]
                        error_results = [r for r in results if (r.get("error") or {}).get("code") == "ocr_engine_error"]
                        assert len(error_results) >= 1

    @pytest.mark.asyncio
    async def test_provider_failure_with_more_images_continues(self, current_result):
        """On provider failure with more images, continue to next."""
        state = _make_state()
        state.original_job["payload"]["image_count"] = 3
        state.original_job["payload"]["image_refs"].append(
            {"index": 2, "kind": "s3", "value": "s3://bucket/img2.png"}
        )

        from app.continue_processing import config as real_config
        with patch('app.image_resolver.resolve_image', return_value=(b"img", "image/png")):
            with patch.object(real_config, 'get_enabled_tiers', return_value=["tesseract"]):
                with patch('app.provider_manager.ProviderManager', side_effect=RuntimeError("boom")):
                    with patch('app.continue_processing._create_completion_and_send', new_callable=AsyncMock) as mock_send:
                        await _process_next_image(state, current_result, next_image_index=1)

                        mock_send.assert_called_once()
                        results = mock_send.call_args[0][1]
                        error_results = [r for r in results if (r.get("error") or {}).get("code") == "ocr_engine_error"]
                        assert len(error_results) >= 2
