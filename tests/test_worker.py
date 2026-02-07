"""Tests for worker.py."""

import copy
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.image_resolver import ImageResolverError
from worker import process_job_with_retry, process_ocr_job, process_single_image_with_tiers, should_retry


class TestShouldRetry:
    """Tests for should_retry function."""

    def test_max_attempts_reached(self):
        with patch("worker.config") as mock_config:
            mock_config.OCR_MAX_ATTEMPTS = 3
            assert should_retry("internal_error", 3) is False

    def test_non_retryable_bad_request(self):
        with patch("worker.config") as mock_config:
            mock_config.OCR_MAX_ATTEMPTS = 3
            assert should_retry("bad_request", 1) is False

    def test_non_retryable_image_not_found(self):
        with patch("worker.config") as mock_config:
            mock_config.OCR_MAX_ATTEMPTS = 3
            assert should_retry("image_not_found", 1) is False

    def test_non_retryable_schema_invalid(self):
        with patch("worker.config") as mock_config:
            mock_config.OCR_MAX_ATTEMPTS = 3
            assert should_retry("schema_invalid", 1) is False

    def test_non_retryable_unsupported_media(self):
        with patch("worker.config") as mock_config:
            mock_config.OCR_MAX_ATTEMPTS = 3
            assert should_retry("unsupported_media", 1) is False

    def test_retryable_ocr_engine_error(self):
        with patch("worker.config") as mock_config:
            mock_config.OCR_MAX_ATTEMPTS = 3
            assert should_retry("ocr_engine_error", 1) is True

    def test_retryable_internal_error(self):
        with patch("worker.config") as mock_config:
            mock_config.OCR_MAX_ATTEMPTS = 3
            assert should_retry("internal_error", 2) is True

    def test_retryable_file_read_error(self):
        with patch("worker.config") as mock_config:
            mock_config.OCR_MAX_ATTEMPTS = 3
            assert should_retry("file_read_error", 1) is True

    def test_unknown_code_not_retried(self):
        with patch("worker.config") as mock_config:
            mock_config.OCR_MAX_ATTEMPTS = 3
            assert should_retry("unknown_error_code", 1) is False


class TestProcessSingleImageWithTiers:
    """Tests for process_single_image_with_tiers."""

    @pytest.mark.asyncio
    async def test_success_on_first_tier(self):
        image_ref = {"kind": "s3", "value": "s3://bucket/img.png", "index": 0}
        mock_pm = MagicMock()
        mock_pm.process_image = AsyncMock(return_value=(
            MagicMock(text="Hello World", duration_ms=10.0),
            "tesseract",
        ))
        mock_pm._validate_ocr_with_llm = AsyncMock(return_value=(True, 0.9, "Valid text"))
        mock_pm.providers = {"tesseract": MagicMock(is_available=MagicMock(return_value=True))}

        with patch("worker.resolve_image", return_value=(b"IMAGE", "image/png")):
            with patch("worker.config") as mock_config:
                mock_config.OCR_MIN_CONFIDENCE = None
                mock_config.OCR_MAX_TEXT_BYTES = 51200
                result = await process_single_image_with_tiers(
                    image_ref, 0, mock_pm, ["tesseract"], "en"
                )

        assert result["meta"]["is_valid"] is True
        assert result["meta"]["tier"] == "tesseract"
        assert result["index"] == 0

    @pytest.mark.asyncio
    async def test_pdf_rejection(self):
        image_ref = {"kind": "local_path", "value": "/data/images/doc.pdf", "index": 0}
        mock_pm = MagicMock()

        with patch("worker.resolve_image", side_effect=ImageResolverError("PDF files are not supported in v1 (error code: unsupported_media)")):
            result = await process_single_image_with_tiers(
                image_ref, 0, mock_pm, ["tesseract"], "en"
            )

        assert result["meta"]["is_valid"] is False
        assert result["error"]["code"] == "unsupported_media"

    @pytest.mark.asyncio
    async def test_image_not_found(self):
        image_ref = {"kind": "local_path", "value": "/data/images/missing.png", "index": 0}
        mock_pm = MagicMock()

        with patch("worker.resolve_image", side_effect=ImageResolverError("Image file not found")):
            result = await process_single_image_with_tiers(
                image_ref, 0, mock_pm, ["tesseract"], "en"
            )

        assert result["meta"]["is_valid"] is False
        assert result["error"]["code"] == "image_not_found"

    @pytest.mark.asyncio
    async def test_all_tiers_fail(self):
        image_ref = {"kind": "s3", "value": "s3://bucket/img.png", "index": 0}
        mock_pm = MagicMock()
        mock_pm.process_image = AsyncMock(side_effect=Exception("OCR failed"))
        mock_pm.providers = {"tesseract": MagicMock(is_available=MagicMock(return_value=True))}

        with patch("worker.resolve_image", return_value=(b"IMAGE", "image/png")):
            with patch("worker.config") as mock_config:
                mock_config.OCR_MIN_CONFIDENCE = None
                result = await process_single_image_with_tiers(
                    image_ref, 0, mock_pm, ["tesseract"], "en"
                )

        assert result["meta"]["is_valid"] is False
        assert result["error"]["code"] == "ocr_no_valid_output"


class TestProcessOcrJob:
    """Tests for process_ocr_job."""

    @pytest.mark.asyncio
    async def test_results_sorted_by_index(self, valid_queue_message):
        msg = copy.deepcopy(valid_queue_message)
        msg["payload"]["image_refs"] = [
            {"kind": "s3", "value": "s3://bucket/b.png", "index": 1},
            {"kind": "s3", "value": "s3://bucket/a.png", "index": 0},
        ]
        msg["payload"]["image_count"] = 2

        result_0 = {"index": 0, "ocr_text": "A", "truncated": False, "meta": {"is_valid": True}, "error": None}
        result_1 = {"index": 1, "ocr_text": "B", "truncated": False, "meta": {"is_valid": True}, "error": None}

        mock_pm = MagicMock()

        with patch("worker.process_single_image_with_tiers", new_callable=AsyncMock, side_effect=[result_1, result_0]):
            with patch("worker.config") as mock_config:
                mock_config.OCR_LANGUAGE_DEFAULT = "en"
                mock_config.get_enabled_tiers.return_value = ["tesseract"]
                completion = await process_ocr_job(msg, mock_pm)

        results = completion["payload"]["results"]
        assert results[0]["index"] == 0
        assert results[1]["index"] == 1

    @pytest.mark.asyncio
    async def test_completion_message_structure(self, valid_queue_message):
        result = {"index": 0, "ocr_text": "OK", "truncated": False, "meta": {"is_valid": True}, "error": None}
        mock_pm = MagicMock()

        with patch("worker.process_single_image_with_tiers", new_callable=AsyncMock, return_value=result):
            with patch("worker.config") as mock_config:
                mock_config.OCR_LANGUAGE_DEFAULT = "en"
                mock_config.get_enabled_tiers.return_value = ["tesseract"]
                completion = await process_ocr_job(valid_queue_message, mock_pm)

        assert completion["job_type"] == "ocr.completed"
        assert completion["payload"]["status"] == "success"


class TestProcessJobWithRetry:
    """Tests for process_job_with_retry."""

    @pytest.mark.asyncio
    async def test_schema_failure_sends_error(self, valid_queue_message):
        msg = copy.deepcopy(valid_queue_message)
        msg["schema_version"] = 999  # Invalid

        mock_pm = MagicMock()
        with patch("worker.queue_client") as mock_qc:
            mock_qc.enqueue.return_value = True
            await process_job_with_retry(msg, mock_pm)

        # Should have enqueued error message to reply_to
        mock_qc.enqueue.assert_called_once()
        call_args = mock_qc.enqueue.call_args
        assert call_args[0][0] == "jarvis.recipes.jobs"

    @pytest.mark.asyncio
    async def test_success_emits_completion(self, valid_queue_message):
        msg = copy.deepcopy(valid_queue_message)
        mock_pm = MagicMock()

        completion = {
            "job_type": "ocr.completed",
            "payload": {"status": "success", "results": [], "error": {"message": None, "code": None}},
        }

        with patch("worker.validate_ocr_request"):
            with patch("worker.process_ocr_job", new_callable=AsyncMock, return_value=completion):
                with patch("worker.queue_client") as mock_qc:
                    mock_qc.enqueue.return_value = True
                    await process_job_with_retry(msg, mock_pm)

        mock_qc.enqueue.assert_called_once()

    @pytest.mark.asyncio
    async def test_retryable_failure_requeues(self, valid_queue_message):
        msg = copy.deepcopy(valid_queue_message)
        mock_pm = MagicMock()

        completion = {
            "job_type": "ocr.completed",
            "payload": {
                "status": "failed",
                "results": [],
                "error": {"message": "engine error", "code": "internal_error"},
            },
        }

        with patch("worker.validate_ocr_request"):
            with patch("worker.process_ocr_job", new_callable=AsyncMock, return_value=completion):
                with patch("worker.queue_client") as mock_qc:
                    mock_qc.enqueue.return_value = True
                    mock_qc.queue_name = "jarvis.ocr.jobs"
                    with patch("worker.should_retry", return_value=True):
                        await process_job_with_retry(msg, mock_pm)

        # Called twice: once for reply_to, once for requeue
        assert mock_qc.enqueue.call_count == 2

    @pytest.mark.asyncio
    async def test_non_retryable_failure_no_requeue(self, valid_queue_message):
        msg = copy.deepcopy(valid_queue_message)
        mock_pm = MagicMock()

        completion = {
            "job_type": "ocr.completed",
            "payload": {
                "status": "failed",
                "results": [],
                "error": {"message": "bad image", "code": "bad_request"},
            },
        }

        with patch("worker.validate_ocr_request"):
            with patch("worker.process_ocr_job", new_callable=AsyncMock, return_value=completion):
                with patch("worker.queue_client") as mock_qc:
                    mock_qc.enqueue.return_value = True
                    with patch("worker.should_retry", return_value=False):
                        await process_job_with_retry(msg, mock_pm)

        # Called once for reply_to, NOT requeued
        assert mock_qc.enqueue.call_count == 1
