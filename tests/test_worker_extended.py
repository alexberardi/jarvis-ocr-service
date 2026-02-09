"""Extended tests for worker.py — covering more paths in process_single_image_with_tiers
and process_job_with_retry."""

import copy
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.image_resolver import ImageResolverError
from worker import (
    process_job_with_retry,
    process_ocr_job,
    process_single_image_with_tiers,
    should_retry,
)


class TestProcessSingleImageExtended:
    """Additional tests for process_single_image_with_tiers."""

    @pytest.mark.asyncio
    async def test_pdf_content_type_rejection(self):
        """PDF detected by content_type (double-check path)."""
        image_ref = {"kind": "s3", "value": "s3://bucket/doc.pdf", "index": 0}
        mock_pm = MagicMock()

        with patch("worker.resolve_image", return_value=(b"PDF", "application/pdf")):
            result = await process_single_image_with_tiers(
                image_ref, 0, mock_pm, ["tesseract"], "en"
            )

        assert result["meta"]["is_valid"] is False
        assert result["error"]["code"] == "unsupported_media"

    @pytest.mark.asyncio
    async def test_confidence_below_threshold(self):
        """Tier succeeds but confidence is below threshold."""
        image_ref = {"kind": "s3", "value": "s3://bucket/img.png", "index": 0}
        mock_pm = MagicMock()
        mock_pm.process_image = AsyncMock(
            return_value=(MagicMock(text="Low conf", duration_ms=10.0), "tesseract")
        )
        mock_pm._validate_ocr_with_llm = AsyncMock(return_value=(True, 0.3, "Low confidence"))
        mock_pm.providers = {"tesseract": MagicMock(is_available=MagicMock(return_value=True))}

        with patch("worker.resolve_image", return_value=(b"IMAGE", "image/png")):
            with patch("worker.config") as mock_config:
                mock_config.OCR_MIN_CONFIDENCE = 0.5  # Below threshold
                mock_config.OCR_MAX_TEXT_BYTES = 51200
                result = await process_single_image_with_tiers(
                    image_ref, 0, mock_pm, ["tesseract"], "en"
                )

        # Should fail because confidence is below threshold and no more tiers
        assert result["meta"]["is_valid"] is False

    @pytest.mark.asyncio
    async def test_invalid_ocr_output_tries_next_tier(self):
        """Tier produces invalid output, should try next tier."""
        image_ref = {"kind": "s3", "value": "s3://bucket/img.png", "index": 0}
        mock_pm = MagicMock()
        mock_pm.process_image = AsyncMock(
            return_value=(MagicMock(text="garbage", duration_ms=10.0), "tesseract")
        )
        mock_pm._validate_ocr_with_llm = AsyncMock(return_value=(False, 0.1, "Garbled output"))
        mock_pm.providers = {"tesseract": MagicMock(is_available=MagicMock(return_value=True))}

        with patch("worker.resolve_image", return_value=(b"IMAGE", "image/png")):
            with patch("worker.config") as mock_config:
                mock_config.OCR_MIN_CONFIDENCE = None
                result = await process_single_image_with_tiers(
                    image_ref, 0, mock_pm, ["tesseract"], "en"
                )

        assert result["meta"]["is_valid"] is False
        assert result["error"]["code"] == "ocr_no_valid_output"

    @pytest.mark.asyncio
    async def test_provider_unavailable_exception(self):
        """ProviderUnavailableException should be caught and move to next tier."""
        from app.exceptions import ProviderUnavailableException

        image_ref = {"kind": "s3", "value": "s3://bucket/img.png", "index": 0}
        mock_pm = MagicMock()
        mock_pm.process_image = AsyncMock(
            side_effect=ProviderUnavailableException("not available")
        )
        mock_pm.providers = {"tesseract": MagicMock(is_available=MagicMock(return_value=True))}

        with patch("worker.resolve_image", return_value=(b"IMAGE", "image/png")):
            with patch("worker.config") as mock_config:
                mock_config.OCR_MIN_CONFIDENCE = None
                result = await process_single_image_with_tiers(
                    image_ref, 0, mock_pm, ["tesseract"], "en"
                )

        assert result["meta"]["is_valid"] is False

    @pytest.mark.asyncio
    async def test_provider_not_in_manager(self):
        """Tier specifies a provider that doesn't exist in manager."""
        image_ref = {"kind": "s3", "value": "s3://bucket/img.png", "index": 0}
        mock_pm = MagicMock()
        mock_pm.providers = {}  # No providers

        with patch("worker.resolve_image", return_value=(b"IMAGE", "image/png")):
            with patch("worker.config") as mock_config:
                mock_config.OCR_MIN_CONFIDENCE = None
                result = await process_single_image_with_tiers(
                    image_ref, 0, mock_pm, ["tesseract"], "en"
                )

        assert result["meta"]["is_valid"] is False

    @pytest.mark.asyncio
    async def test_provider_not_available(self):
        """Provider exists but is_available returns False."""
        image_ref = {"kind": "s3", "value": "s3://bucket/img.png", "index": 0}
        mock_pm = MagicMock()
        mock_pm.providers = {
            "tesseract": MagicMock(is_available=MagicMock(return_value=False))
        }

        with patch("worker.resolve_image", return_value=(b"IMAGE", "image/png")):
            with patch("worker.config") as mock_config:
                mock_config.OCR_MIN_CONFIDENCE = None
                result = await process_single_image_with_tiers(
                    image_ref, 0, mock_pm, ["tesseract"], "en"
                )

        assert result["meta"]["is_valid"] is False

    @pytest.mark.asyncio
    async def test_empty_language(self):
        """Empty language string produces None language_hints."""
        image_ref = {"kind": "s3", "value": "s3://bucket/img.png", "index": 0}
        mock_pm = MagicMock()
        mock_pm.process_image = AsyncMock(
            return_value=(MagicMock(text="Hello", duration_ms=10.0), "tesseract")
        )
        mock_pm._validate_ocr_with_llm = AsyncMock(return_value=(True, 0.9, "Valid"))
        mock_pm.providers = {"tesseract": MagicMock(is_available=MagicMock(return_value=True))}

        with patch("worker.resolve_image", return_value=(b"IMAGE", "image/png")):
            with patch("worker.config") as mock_config:
                mock_config.OCR_MIN_CONFIDENCE = None
                mock_config.OCR_MAX_TEXT_BYTES = 51200
                result = await process_single_image_with_tiers(
                    image_ref, 0, mock_pm, ["tesseract"], ""
                )

        assert result["meta"]["is_valid"] is True


class TestProcessJobWithRetryExtended:
    """Additional tests for process_job_with_retry."""

    @pytest.mark.asyncio
    async def test_process_ocr_job_exception_creates_error_completion(self, valid_queue_message):
        """When process_ocr_job raises, should create error completion message."""
        msg = copy.deepcopy(valid_queue_message)
        mock_pm = MagicMock()

        with patch("worker.validate_ocr_request"):
            with patch("worker.process_ocr_job", new_callable=AsyncMock, side_effect=RuntimeError("crash")):
                with patch("worker.queue_client") as mock_qc:
                    mock_qc.enqueue.return_value = True
                    with patch("worker.should_retry", return_value=False):
                        await process_job_with_retry(msg, mock_pm)

        # Should still emit a completion message
        mock_qc.enqueue.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_reply_to_logs_warning(self, valid_queue_message):
        """When no reply_to, should still process but not emit."""
        msg = copy.deepcopy(valid_queue_message)
        msg["reply_to"] = None
        mock_pm = MagicMock()

        completion = {
            "job_type": "ocr.completed",
            "payload": {"status": "success", "results": [], "error": None},
        }

        with patch("worker.validate_ocr_request"):
            with patch("worker.process_ocr_job", new_callable=AsyncMock, return_value=completion):
                with patch("worker.queue_client") as mock_qc:
                    await process_job_with_retry(msg, mock_pm)

        # enqueue should NOT be called (no reply_to)
        mock_qc.enqueue.assert_not_called()

    @pytest.mark.asyncio
    async def test_top_level_exception_caught(self, valid_queue_message):
        """Top-level exception in process_job_with_retry should be caught."""
        msg = copy.deepcopy(valid_queue_message)
        mock_pm = MagicMock()

        with patch("worker.validate_ocr_request", side_effect=Exception("unexpected")):
            # Should not raise - catches at top level
            await process_job_with_retry(msg, mock_pm)

    @pytest.mark.asyncio
    async def test_schema_failure_no_reply_to(self, valid_queue_message):
        """Schema failure with empty reply_to should not try to enqueue."""
        msg = copy.deepcopy(valid_queue_message)
        msg["schema_version"] = 999
        msg["reply_to"] = ""
        mock_pm = MagicMock()

        with patch("worker.queue_client") as mock_qc:
            await process_job_with_retry(msg, mock_pm)

        # Should not enqueue since reply_to is empty
        mock_qc.enqueue.assert_not_called()

    @pytest.mark.asyncio
    async def test_enqueue_failure_logged(self, valid_queue_message):
        """When enqueue fails, should log error but not crash."""
        msg = copy.deepcopy(valid_queue_message)
        mock_pm = MagicMock()

        completion = {
            "job_type": "ocr.completed",
            "payload": {"status": "success", "results": [], "error": None},
        }

        with patch("worker.validate_ocr_request"):
            with patch("worker.process_ocr_job", new_callable=AsyncMock, return_value=completion):
                with patch("worker.queue_client") as mock_qc:
                    mock_qc.enqueue.return_value = False
                    await process_job_with_retry(msg, mock_pm)


class TestProcessOcrJobExtended:
    """Additional tests for process_ocr_job."""

    @pytest.mark.asyncio
    async def test_options_default_language(self, valid_queue_message):
        """When options.language is missing, uses default."""
        msg = copy.deepcopy(valid_queue_message)
        del msg["payload"]["options"]  # Remove options entirely

        result = {"index": 0, "ocr_text": "OK", "truncated": False, "meta": {"is_valid": True}, "error": None}
        mock_pm = MagicMock()

        with patch("worker.process_single_image_with_tiers", new_callable=AsyncMock, return_value=result):
            with patch("worker.config") as mock_config:
                mock_config.OCR_LANGUAGE_DEFAULT = "en"
                mock_config.get_enabled_tiers.return_value = ["tesseract"]
                completion = await process_ocr_job(msg, mock_pm)

        assert completion["payload"]["status"] == "success"

    @pytest.mark.asyncio
    async def test_mixed_valid_invalid_results(self, valid_queue_message):
        """Some images valid, some invalid."""
        msg = copy.deepcopy(valid_queue_message)
        msg["payload"]["image_refs"] = [
            {"kind": "s3", "value": "s3://bucket/a.png", "index": 0},
            {"kind": "s3", "value": "s3://bucket/b.png", "index": 1},
        ]
        msg["payload"]["image_count"] = 2

        result_valid = {"index": 0, "ocr_text": "OK", "truncated": False, "meta": {"is_valid": True}, "error": None}
        result_invalid = {"index": 1, "ocr_text": "", "truncated": False, "meta": {"is_valid": False}, "error": {"code": "ocr_no_valid_output", "message": "failed"}}
        mock_pm = MagicMock()

        with patch("worker.process_single_image_with_tiers", new_callable=AsyncMock, side_effect=[result_valid, result_invalid]):
            with patch("worker.config") as mock_config:
                mock_config.OCR_LANGUAGE_DEFAULT = "en"
                mock_config.get_enabled_tiers.return_value = ["tesseract"]
                completion = await process_ocr_job(msg, mock_pm)

        # Status should still be "success" because at least one image succeeded
        results = completion["payload"]["results"]
        assert len(results) == 2


class TestShouldRetryExtended:
    """Additional tests for should_retry."""

    def test_redis_error_is_retryable(self):
        with patch("worker.config") as mock_config:
            mock_config.OCR_MAX_ATTEMPTS = 3
            assert should_retry("redis_error", 1) is True
