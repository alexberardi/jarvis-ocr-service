"""Tests for app/provider_manager.py."""

import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.exceptions import OCRProcessingException, ProviderUnavailableException
from app.providers.base import OCRProvider, OCRResult, TextBlock


class TestProviderManagerInit:
    """Tests for ProviderManager initialization."""

    def test_tesseract_available(self):
        mock_tesseract = MagicMock()
        mock_tesseract.return_value.is_available.return_value = True
        mock_tesseract.return_value.name = "tesseract"

        with patch("app.provider_manager.TesseractProvider", mock_tesseract):
            from app.provider_manager import ProviderManager
            pm = ProviderManager()

        assert "tesseract" in pm.providers

    def test_tesseract_not_available(self):
        mock_tesseract = MagicMock()
        mock_tesseract.return_value.is_available.return_value = False

        with patch("app.provider_manager.TesseractProvider", mock_tesseract):
            from app.provider_manager import ProviderManager
            pm = ProviderManager()

        assert "tesseract" not in pm.providers

    def test_optional_providers_not_loaded_when_disabled(self):
        mock_tesseract = MagicMock()
        mock_tesseract.return_value.is_available.return_value = True
        mock_tesseract.return_value.name = "tesseract"

        with patch("app.provider_manager.TesseractProvider", mock_tesseract):
            with patch("app.provider_manager.config") as mock_config:
                mock_config.OCR_ENABLE_EASYOCR = False
                mock_config.OCR_ENABLE_PADDLEOCR = False
                mock_config.OCR_ENABLE_APPLE_VISION = False
                mock_config.OCR_ENABLE_LLM_PROXY_VISION = False
                mock_config.OCR_ENABLE_LLM_PROXY_CLOUD = False
                from app.provider_manager import ProviderManager
                pm = ProviderManager()

        assert len(pm.providers) == 1  # Only tesseract


class TestSelectProvider:
    """Tests for ProviderManager.select_provider."""

    def _make_manager(self):
        """Create a ProviderManager with mocked providers."""
        mock_tesseract = MagicMock()
        mock_tesseract.return_value.is_available.return_value = True
        mock_tesseract.return_value.name = "tesseract"

        with patch("app.provider_manager.TesseractProvider", mock_tesseract):
            with patch("app.provider_manager.config") as mock_config:
                mock_config.OCR_ENABLE_EASYOCR = False
                mock_config.OCR_ENABLE_PADDLEOCR = False
                mock_config.OCR_ENABLE_APPLE_VISION = False
                mock_config.OCR_ENABLE_LLM_PROXY_VISION = False
                mock_config.OCR_ENABLE_LLM_PROXY_CLOUD = False
                from app.provider_manager import ProviderManager
                pm = ProviderManager()
        return pm

    def test_auto_selects_first_available(self):
        pm = self._make_manager()
        provider = pm.select_provider("auto")
        assert provider.name == "tesseract"

    def test_specific_provider_found(self):
        pm = self._make_manager()
        provider = pm.select_provider("tesseract")
        assert provider.name == "tesseract"

    def test_specific_provider_not_found_raises(self):
        pm = self._make_manager()
        with pytest.raises(ProviderUnavailableException, match="not enabled"):
            pm.select_provider("easyocr")

    def test_auto_with_no_providers_raises(self):
        pm = self._make_manager()
        # Remove all providers
        pm.providers.clear()
        with pytest.raises(RuntimeError, match="No OCR providers"):
            pm.select_provider("auto")


class TestProcessImage:
    """Tests for ProviderManager.process_image."""

    def _make_manager_with_mock_provider(self):
        mock_tesseract = MagicMock()
        mock_tesseract.return_value.is_available.return_value = True
        mock_tesseract.return_value.name = "tesseract"
        canned = OCRResult(
            text="Test output",
            blocks=[TextBlock(text="Test output", bbox=[0, 0, 100, 20], confidence=0.9)],
            duration_ms=10.0,
        )
        mock_tesseract.return_value.process.return_value = canned

        with patch("app.provider_manager.TesseractProvider", mock_tesseract):
            with patch("app.provider_manager.config") as mock_config:
                mock_config.OCR_ENABLE_EASYOCR = False
                mock_config.OCR_ENABLE_PADDLEOCR = False
                mock_config.OCR_ENABLE_APPLE_VISION = False
                mock_config.OCR_ENABLE_LLM_PROXY_VISION = False
                mock_config.OCR_ENABLE_LLM_PROXY_CLOUD = False
                mock_config.OCR_MIN_VALID_CHARS = 3
                mock_config.JARVIS_LLM_PROXY_URL = ""
                mock_config.JARVIS_APP_ID = ""
                mock_config.JARVIS_APP_KEY = ""
                from app.provider_manager import ProviderManager
                pm = ProviderManager()
        return pm

    @pytest.mark.asyncio
    async def test_specific_provider(self, sample_base64_image):
        pm = self._make_manager_with_mock_provider()
        result, provider_name = await pm.process_image(
            image_base64=sample_base64_image,
            provider_name="tesseract",
        )
        assert provider_name == "tesseract"
        assert result.text == "Test output"

    @pytest.mark.asyncio
    async def test_invalid_base64_raises(self):
        pm = self._make_manager_with_mock_provider()
        with pytest.raises(ValueError, match="Invalid base64"):
            await pm.process_image(image_base64="!!not-base64!!", provider_name="tesseract")

    @pytest.mark.asyncio
    async def test_auto_mode_tries_providers(self, sample_base64_image):
        pm = self._make_manager_with_mock_provider()
        # Auto mode with LLM validation unavailable -> assumes valid
        result, provider_name = await pm.process_image(
            image_base64=sample_base64_image,
            provider_name="auto",
        )
        assert provider_name == "tesseract"


class TestProcessBatch:
    """Tests for ProviderManager.process_batch."""

    def _make_manager(self):
        from app.providers.base import OCRProvider

        mock_provider = MagicMock(spec=OCRProvider)
        mock_provider.is_available.return_value = True
        mock_provider.name = "tesseract"
        canned = OCRResult(text="Batch", blocks=[], duration_ms=5.0)
        mock_provider.process.return_value = canned

        mock_tesseract_cls = MagicMock(return_value=mock_provider)

        with patch("app.provider_manager.TesseractProvider", mock_tesseract_cls):
            with patch("app.provider_manager.config") as mock_config:
                mock_config.OCR_ENABLE_EASYOCR = False
                mock_config.OCR_ENABLE_PADDLEOCR = False
                mock_config.OCR_ENABLE_APPLE_VISION = False
                mock_config.OCR_ENABLE_LLM_PROXY_VISION = False
                mock_config.OCR_ENABLE_LLM_PROXY_CLOUD = False
                mock_config.OCR_MIN_VALID_CHARS = 3
                mock_config.JARVIS_LLM_PROXY_URL = ""
                mock_config.JARVIS_APP_ID = ""
                mock_config.JARVIS_APP_KEY = ""
                from app.provider_manager import ProviderManager
                pm = ProviderManager()
        return pm

    @pytest.mark.asyncio
    async def test_empty_batch_raises(self, sample_base64_image):
        pm = self._make_manager()
        with pytest.raises(ValueError, match="At least one image"):
            await pm.process_batch([], [], provider_name="tesseract")

    @pytest.mark.asyncio
    async def test_too_large_batch_raises(self, sample_base64_image):
        pm = self._make_manager()
        images = [sample_base64_image] * 101
        types = ["image/png"] * 101
        with pytest.raises(ValueError, match="Maximum 100"):
            await pm.process_batch(images, types, provider_name="tesseract")

    @pytest.mark.asyncio
    async def test_mismatched_lengths_raises(self, sample_base64_image):
        pm = self._make_manager()
        with pytest.raises(ValueError, match="must match"):
            await pm.process_batch(
                [sample_base64_image, sample_base64_image],
                ["image/png"],
                provider_name="tesseract",
            )

    @pytest.mark.asyncio
    async def test_batch_specific_provider_success(self, sample_base64_image):
        pm = self._make_manager()
        results, provider_name = await pm.process_batch(
            [sample_base64_image],
            ["image/png"],
            provider_name="tesseract",
        )
        assert isinstance(results, list)
        assert len(results) == 1
        assert results[0].text == "Batch"
        assert provider_name == "tesseract"

    @pytest.mark.asyncio
    async def test_batch_auto_mode_success(self, sample_base64_image):
        pm = self._make_manager()
        # Auto mode with no LLM proxy -> validation returns True/0.5
        with patch("app.provider_manager.config") as mock_config:
            mock_config.OCR_MIN_VALID_CHARS = 3
            mock_config.JARVIS_LLM_PROXY_URL = ""
            mock_config.JARVIS_APP_ID = ""
            mock_config.JARVIS_APP_KEY = ""
            results, provider_name = await pm.process_batch(
                [sample_base64_image],
                ["image/png"],
                provider_name="auto",
            )
        assert isinstance(results, list)
        assert provider_name == "tesseract"


class TestValidateOcrWithLlm:
    """Tests for ProviderManager._validate_ocr_with_llm."""

    def _make_manager(self):
        mock_provider = MagicMock(spec=OCRProvider)
        mock_provider.is_available.return_value = True
        mock_provider.name = "tesseract"
        mock_tesseract_cls = MagicMock(return_value=mock_provider)

        with patch("app.provider_manager.TesseractProvider", mock_tesseract_cls):
            with patch("app.provider_manager.config") as mock_config:
                mock_config.OCR_ENABLE_EASYOCR = False
                mock_config.OCR_ENABLE_PADDLEOCR = False
                mock_config.OCR_ENABLE_APPLE_VISION = False
                mock_config.OCR_ENABLE_LLM_PROXY_VISION = False
                mock_config.OCR_ENABLE_LLM_PROXY_CLOUD = False
                from app.provider_manager import ProviderManager
                pm = ProviderManager()
        return pm

    @pytest.mark.asyncio
    async def test_empty_text_returns_invalid(self):
        pm = self._make_manager()
        with patch("app.provider_manager.config") as mock_config:
            mock_config.OCR_MIN_VALID_CHARS = 3
            is_valid, conf, reason = await pm._validate_ocr_with_llm("")
        assert is_valid is False
        assert conf == 0.0

    @pytest.mark.asyncio
    async def test_short_text_returns_invalid(self):
        pm = self._make_manager()
        with patch("app.provider_manager.config") as mock_config:
            mock_config.OCR_MIN_VALID_CHARS = 3
            is_valid, conf, reason = await pm._validate_ocr_with_llm("ab")
        assert is_valid is False

    @pytest.mark.asyncio
    async def test_no_llm_proxy_url_assumes_valid(self):
        pm = self._make_manager()
        with patch("app.provider_manager.config") as mock_config:
            mock_config.OCR_MIN_VALID_CHARS = 3
            mock_config.JARVIS_LLM_PROXY_URL = ""
            mock_config.JARVIS_APP_ID = ""
            mock_config.JARVIS_APP_KEY = ""
            is_valid, conf, reason = await pm._validate_ocr_with_llm("Hello World")
        assert is_valid is True
        assert conf == 0.5

    @pytest.mark.asyncio
    async def test_llm_returns_valid_response(self):
        pm = self._make_manager()
        llm_response = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "is_valid": True,
                        "confidence": 0.95,
                        "reason": "Clear text"
                    })
                }
            }]
        }
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = llm_response

        with patch("app.provider_manager.config") as mock_config:
            mock_config.OCR_MIN_VALID_CHARS = 3
            mock_config.JARVIS_LLM_PROXY_URL = "http://localhost:8000"
            mock_config.JARVIS_APP_ID = "app"
            mock_config.JARVIS_APP_KEY = "key"
            mock_config.OCR_VALIDATION_MODEL = "lightweight"
            with patch("httpx.AsyncClient") as MockClient:
                mock_client_instance = AsyncMock()
                mock_client_instance.post.return_value = mock_resp
                mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
                mock_client_instance.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = mock_client_instance

                is_valid, conf, reason = await pm._validate_ocr_with_llm("Hello World Test")

        assert is_valid is True
        assert conf == 0.95
        assert reason == "Clear text"

    @pytest.mark.asyncio
    async def test_llm_returns_invalid_response(self):
        pm = self._make_manager()
        llm_response = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "is_valid": False,
                        "confidence": 0.1,
                        "reason": "Garbled text"
                    })
                }
            }]
        }
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = llm_response

        with patch("app.provider_manager.config") as mock_config:
            mock_config.OCR_MIN_VALID_CHARS = 3
            mock_config.JARVIS_LLM_PROXY_URL = "http://localhost:8000"
            mock_config.JARVIS_APP_ID = "app"
            mock_config.JARVIS_APP_KEY = "key"
            mock_config.OCR_VALIDATION_MODEL = "lightweight"
            with patch("httpx.AsyncClient") as MockClient:
                mock_client_instance = AsyncMock()
                mock_client_instance.post.return_value = mock_resp
                mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
                mock_client_instance.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = mock_client_instance

                is_valid, conf, reason = await pm._validate_ocr_with_llm("asdfghjkl")

        assert is_valid is False
        assert conf == 0.1

    @pytest.mark.asyncio
    async def test_llm_no_choices_returns_valid(self):
        pm = self._make_manager()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"choices": []}

        with patch("app.provider_manager.config") as mock_config:
            mock_config.OCR_MIN_VALID_CHARS = 3
            mock_config.JARVIS_LLM_PROXY_URL = "http://localhost:8000"
            mock_config.JARVIS_APP_ID = "app"
            mock_config.JARVIS_APP_KEY = "key"
            mock_config.OCR_VALIDATION_MODEL = "lightweight"
            with patch("httpx.AsyncClient") as MockClient:
                mock_client_instance = AsyncMock()
                mock_client_instance.post.return_value = mock_resp
                mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
                mock_client_instance.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = mock_client_instance

                is_valid, conf, reason = await pm._validate_ocr_with_llm("Some text here")

        assert is_valid is True
        assert reason == "No validation response"

    @pytest.mark.asyncio
    async def test_llm_exception_returns_valid(self):
        pm = self._make_manager()
        with patch("app.provider_manager.config") as mock_config:
            mock_config.OCR_MIN_VALID_CHARS = 3
            mock_config.JARVIS_LLM_PROXY_URL = "http://localhost:8000"
            mock_config.JARVIS_APP_ID = "app"
            mock_config.JARVIS_APP_KEY = "key"
            mock_config.OCR_VALIDATION_MODEL = "lightweight"
            with patch("httpx.AsyncClient") as MockClient:
                mock_client_instance = AsyncMock()
                mock_client_instance.post.side_effect = Exception("connection refused")
                mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
                mock_client_instance.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = mock_client_instance

                is_valid, conf, reason = await pm._validate_ocr_with_llm("Some text")

        assert is_valid is True
        assert "Validation error" in reason

    @pytest.mark.asyncio
    async def test_llm_clamps_confidence(self):
        pm = self._make_manager()
        llm_response = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "is_valid": True,
                        "confidence": 5.0,  # Out of range
                        "reason": "Over-confident"
                    })
                }
            }]
        }
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = llm_response

        with patch("app.provider_manager.config") as mock_config:
            mock_config.OCR_MIN_VALID_CHARS = 3
            mock_config.JARVIS_LLM_PROXY_URL = "http://localhost:8000"
            mock_config.JARVIS_APP_ID = "app"
            mock_config.JARVIS_APP_KEY = "key"
            mock_config.OCR_VALIDATION_MODEL = "lightweight"
            with patch("httpx.AsyncClient") as MockClient:
                mock_client_instance = AsyncMock()
                mock_client_instance.post.return_value = mock_resp
                mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
                mock_client_instance.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = mock_client_instance

                is_valid, conf, reason = await pm._validate_ocr_with_llm("Valid text content")

        assert conf == 1.0  # Clamped to max

    @pytest.mark.asyncio
    async def test_llm_truncates_long_reason(self):
        pm = self._make_manager()
        long_reason = "A" * 300
        llm_response = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "is_valid": True,
                        "confidence": 0.8,
                        "reason": long_reason,
                    })
                }
            }]
        }
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = llm_response

        with patch("app.provider_manager.config") as mock_config:
            mock_config.OCR_MIN_VALID_CHARS = 3
            mock_config.JARVIS_LLM_PROXY_URL = "http://localhost:8000"
            mock_config.JARVIS_APP_ID = "app"
            mock_config.JARVIS_APP_KEY = "key"
            mock_config.OCR_VALIDATION_MODEL = "lightweight"
            with patch("httpx.AsyncClient") as MockClient:
                mock_client_instance = AsyncMock()
                mock_client_instance.post.return_value = mock_resp
                mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
                mock_client_instance.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = mock_client_instance

                _, _, reason = await pm._validate_ocr_with_llm("Valid text here")

        assert len(reason) == 200


class TestGetAvailableProviders:
    """Tests for ProviderManager.get_available_providers."""

    def test_returns_provider_map(self):
        mock_provider = MagicMock(spec=OCRProvider)
        mock_provider.is_available.return_value = True
        mock_provider.name = "tesseract"
        mock_tesseract_cls = MagicMock(return_value=mock_provider)

        with patch("app.provider_manager.TesseractProvider", mock_tesseract_cls):
            with patch("app.provider_manager.config") as mock_config:
                mock_config.OCR_ENABLE_EASYOCR = False
                mock_config.OCR_ENABLE_PADDLEOCR = False
                mock_config.OCR_ENABLE_APPLE_VISION = False
                mock_config.OCR_ENABLE_LLM_PROXY_VISION = False
                mock_config.OCR_ENABLE_LLM_PROXY_CLOUD = False
                mock_config.get_provider_config.return_value = {
                    "tesseract": True,
                    "easyocr": False,
                }
                from app.provider_manager import ProviderManager
                pm = ProviderManager()

        available = pm.get_available_providers()
        assert available["tesseract"] is True
        assert available["easyocr"] is False
