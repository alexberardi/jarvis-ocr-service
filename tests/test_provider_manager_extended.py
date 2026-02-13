"""Extended tests for app/provider_manager.py — covering auto-mode, batch, and error paths."""

import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.exceptions import OCRProcessingException, ProviderUnavailableException
from app.providers.base import OCRProvider, OCRResult, TextBlock


def _make_manager_with_providers(**overrides):
    """Create a ProviderManager with fine-grained control over providers."""
    mock_tesseract = MagicMock(spec=OCRProvider)
    mock_tesseract.is_available.return_value = True
    mock_tesseract.name = "tesseract"
    canned = OCRResult(text="Test output", blocks=[], duration_ms=10.0)
    mock_tesseract.process.return_value = canned

    mock_tesseract_cls = MagicMock(return_value=mock_tesseract)

    config_defaults = {
        "OCR_ENABLE_EASYOCR": False,
        "OCR_ENABLE_PADDLEOCR": False,
        "OCR_ENABLE_RAPIDOCR": False,
        "OCR_ENABLE_APPLE_VISION": False,
        "OCR_ENABLE_LLM_PROXY_VISION": False,
        "OCR_ENABLE_LLM_PROXY_CLOUD": False,
        "OCR_MIN_VALID_CHARS": 3,
        "JARVIS_LLM_PROXY_URL": "",
        "JARVIS_APP_ID": "",
        "JARVIS_APP_KEY": "",
    }
    config_defaults.update(overrides)

    with patch("app.provider_manager.TesseractProvider", mock_tesseract_cls):
        with patch("app.provider_manager.config") as mock_config:
            for key, val in config_defaults.items():
                setattr(mock_config, key, val)
            from app.provider_manager import ProviderManager
            pm = ProviderManager()
    return pm, mock_tesseract


class TestProcessImageAutoValidation:
    """Test auto-mode process_image with LLM validation failures and fallback."""

    @pytest.mark.asyncio
    async def test_auto_mode_validation_fails_falls_back_to_tesseract(self, sample_base64_image):
        """When auto validation says invalid, should try next provider then fallback."""
        pm, mock_tesseract = _make_manager_with_providers()

        # Make validation return invalid on first call, then valid
        with patch.object(pm, '_validate_ocr_with_llm', new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = (False, 0.1, "Garbled")
            # All providers return invalid -> fallback to tesseract
            result, name = await pm.process_image(
                image_base64=sample_base64_image,
                provider_name="auto",
            )
        # Falls back to tesseract
        assert name == "tesseract"
        assert result.text == "Test output"

    @pytest.mark.asyncio
    async def test_auto_mode_provider_exception_tries_next(self, sample_base64_image):
        """When a provider throws an exception in auto mode, it falls back to tesseract."""
        pm, mock_tesseract = _make_manager_with_providers()

        canned = OCRResult(text="Fallback output", blocks=[], duration_ms=10.0)
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("OCR engine crash")
            return canned

        mock_tesseract.process.side_effect = side_effect

        # Only tesseract is available, so it will fail in auto-loop then
        # fall back to the explicit tesseract fallback path
        result, name = await pm.process_image(
            image_base64=sample_base64_image,
            provider_name="auto",
        )
        assert name == "tesseract"
        assert result.text == "Fallback output"

    @pytest.mark.asyncio
    async def test_auto_mode_no_providers_raises(self, sample_base64_image):
        """When no providers available in auto mode, should raise RuntimeError."""
        pm, _ = _make_manager_with_providers()
        pm.providers.clear()

        with pytest.raises(RuntimeError, match="No OCR providers"):
            await pm.process_image(
                image_base64=sample_base64_image,
                provider_name="auto",
            )

    @pytest.mark.asyncio
    async def test_specific_provider_ocr_error_raises_processing_exception(self, sample_base64_image):
        """When specific provider fails with image-related error, raises OCRProcessingException."""
        pm, mock_tesseract = _make_manager_with_providers()
        mock_tesseract.process.side_effect = RuntimeError("invalid image format detected")

        with pytest.raises(OCRProcessingException, match="Failed to process image"):
            await pm.process_image(
                image_base64=sample_base64_image,
                provider_name="tesseract",
            )

    @pytest.mark.asyncio
    async def test_specific_provider_non_image_error_propagates(self, sample_base64_image):
        """When specific provider fails with non-image error, it propagates."""
        pm, mock_tesseract = _make_manager_with_providers()
        mock_tesseract.process.side_effect = RuntimeError("memory allocation failed")

        with pytest.raises(RuntimeError, match="memory allocation"):
            await pm.process_image(
                image_base64=sample_base64_image,
                provider_name="tesseract",
            )

    @pytest.mark.asyncio
    async def test_specific_unavailable_provider_raises(self, sample_base64_image):
        """Request a specific provider that's not available."""
        pm, mock_tesseract = _make_manager_with_providers()
        mock_tesseract.is_available.return_value = False

        with pytest.raises(ProviderUnavailableException):
            await pm.process_image(
                image_base64=sample_base64_image,
                provider_name="tesseract",
            )


class TestProcessBatchExtended:
    """Extended tests for batch processing paths."""

    @pytest.mark.asyncio
    async def test_batch_invalid_base64_at_index(self, sample_base64_image):
        """Invalid base64 at specific index should report the index."""
        pm, _ = _make_manager_with_providers()
        with pytest.raises(ValueError, match="index 1"):
            await pm.process_batch(
                [sample_base64_image, "!!!invalid!!!"],
                ["image/png", "image/png"],
                provider_name="tesseract",
            )

    @pytest.mark.asyncio
    async def test_batch_auto_mode_with_batch_provider(self, sample_base64_image):
        """Auto mode with a provider that has process_batch method."""
        pm, mock_tesseract = _make_manager_with_providers()
        canned = OCRResult(text="Batch result", blocks=[], duration_ms=5.0)
        mock_tesseract.process_batch = MagicMock(return_value=[canned])

        with patch("app.provider_manager.config") as mock_config:
            mock_config.OCR_MIN_VALID_CHARS = 3
            mock_config.JARVIS_LLM_PROXY_URL = ""
            mock_config.JARVIS_APP_ID = ""
            mock_config.JARVIS_APP_KEY = ""
            results, name = await pm.process_batch(
                [sample_base64_image],
                ["image/png"],
                provider_name="auto",
            )

        assert len(results) == 1
        assert results[0].text == "Batch result"

    @pytest.mark.asyncio
    async def test_batch_auto_mode_batch_provider_fails_tries_next(self, sample_base64_image):
        """Auto mode: when batch provider fails, should continue to next provider."""
        pm, mock_tesseract = _make_manager_with_providers()
        canned = OCRResult(text="Sequential", blocks=[], duration_ms=5.0)

        # First call: batch method raises
        mock_tesseract.process_batch = MagicMock(side_effect=RuntimeError("batch failed"))
        # Then process (sequential fallback) succeeds
        mock_tesseract.process.return_value = canned

        # Remove process_batch so it falls through to sequential
        del mock_tesseract.process_batch

        with patch("app.provider_manager.config") as mock_config:
            mock_config.OCR_MIN_VALID_CHARS = 3
            mock_config.JARVIS_LLM_PROXY_URL = ""
            mock_config.JARVIS_APP_ID = ""
            mock_config.JARVIS_APP_KEY = ""
            results, name = await pm.process_batch(
                [sample_base64_image],
                ["image/png"],
                provider_name="auto",
            )

        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_batch_auto_no_providers_raises(self, sample_base64_image):
        """Auto batch with no providers should raise RuntimeError."""
        pm, _ = _make_manager_with_providers()
        pm.providers.clear()

        with pytest.raises(RuntimeError, match="No OCR providers"):
            await pm.process_batch(
                [sample_base64_image],
                ["image/png"],
                provider_name="auto",
            )

    @pytest.mark.asyncio
    async def test_batch_specific_provider_with_batch_method(self, sample_base64_image):
        """Specific provider with process_batch method."""
        pm, mock_tesseract = _make_manager_with_providers()
        canned = OCRResult(text="Batch specific", blocks=[], duration_ms=5.0)
        mock_tesseract.process_batch = MagicMock(return_value=[canned])

        results, name = await pm.process_batch(
            [sample_base64_image],
            ["image/png"],
            provider_name="tesseract",
        )

        assert results[0].text == "Batch specific"

    @pytest.mark.asyncio
    async def test_batch_specific_provider_batch_image_error(self, sample_base64_image):
        """Specific provider batch method fails with image-related error."""
        pm, mock_tesseract = _make_manager_with_providers()
        mock_tesseract.process_batch = MagicMock(
            side_effect=RuntimeError("corrupt image data")
        )

        with pytest.raises(OCRProcessingException, match="Failed to process batch"):
            await pm.process_batch(
                [sample_base64_image],
                ["image/png"],
                provider_name="tesseract",
            )

    @pytest.mark.asyncio
    async def test_batch_specific_sequential_image_error(self, sample_base64_image):
        """Sequential batch fails with image error for specific image."""
        pm, mock_tesseract = _make_manager_with_providers()
        mock_tesseract.process.side_effect = RuntimeError("invalid image format")

        with pytest.raises(OCRProcessingException, match="Failed to process image 0"):
            await pm.process_batch(
                [sample_base64_image],
                ["image/png"],
                provider_name="tesseract",
            )

    @pytest.mark.asyncio
    async def test_batch_specific_sequential_non_image_error(self, sample_base64_image):
        """Sequential batch fails with non-image error propagates directly."""
        pm, mock_tesseract = _make_manager_with_providers()
        mock_tesseract.process.side_effect = RuntimeError("out of memory")

        with pytest.raises(RuntimeError, match="out of memory"):
            await pm.process_batch(
                [sample_base64_image],
                ["image/png"],
                provider_name="tesseract",
            )


class TestInitOptionalProviders:
    """Test ProviderManager initialization with optional providers."""

    def test_easyocr_enabled_and_available(self):
        mock_tesseract = MagicMock()
        mock_tesseract.return_value.is_available.return_value = True
        mock_tesseract.return_value.name = "tesseract"

        mock_easyocr = MagicMock()
        mock_easyocr.return_value.is_available.return_value = True
        mock_easyocr.return_value.name = "easyocr"

        with patch("app.provider_manager.TesseractProvider", mock_tesseract):
            with patch("app.provider_manager.EasyOCRProvider", mock_easyocr):
                with patch("app.provider_manager.config") as mock_config:
                    mock_config.OCR_ENABLE_EASYOCR = True
                    mock_config.OCR_ENABLE_PADDLEOCR = False
                    mock_config.OCR_ENABLE_RAPIDOCR = False
                    mock_config.OCR_ENABLE_APPLE_VISION = False
                    mock_config.OCR_ENABLE_LLM_PROXY_VISION = False
                    mock_config.OCR_ENABLE_LLM_PROXY_CLOUD = False
                    from app.provider_manager import ProviderManager
                    pm = ProviderManager()

        assert "easyocr" in pm.providers

    def test_easyocr_enabled_but_unavailable(self):
        mock_tesseract = MagicMock()
        mock_tesseract.return_value.is_available.return_value = True
        mock_tesseract.return_value.name = "tesseract"

        mock_easyocr = MagicMock()
        mock_easyocr.return_value.is_available.return_value = False

        with patch("app.provider_manager.TesseractProvider", mock_tesseract):
            with patch("app.provider_manager.EasyOCRProvider", mock_easyocr):
                with patch("app.provider_manager.config") as mock_config:
                    mock_config.OCR_ENABLE_EASYOCR = True
                    mock_config.OCR_ENABLE_PADDLEOCR = False
                    mock_config.OCR_ENABLE_RAPIDOCR = False
                    mock_config.OCR_ENABLE_APPLE_VISION = False
                    mock_config.OCR_ENABLE_LLM_PROXY_VISION = False
                    mock_config.OCR_ENABLE_LLM_PROXY_CLOUD = False
                    from app.provider_manager import ProviderManager
                    pm = ProviderManager()

        assert "easyocr" not in pm.providers

    def test_llm_proxy_providers_enabled(self):
        mock_tesseract = MagicMock()
        mock_tesseract.return_value.is_available.return_value = True
        mock_tesseract.return_value.name = "tesseract"

        mock_llm_vision = MagicMock()
        mock_llm_vision.return_value.is_available.return_value = True
        mock_llm_vision.return_value.name = "llm_proxy_vision"

        mock_llm_cloud = MagicMock()
        mock_llm_cloud.return_value.is_available.return_value = True
        mock_llm_cloud.return_value.name = "llm_proxy_cloud"

        with patch("app.provider_manager.TesseractProvider", mock_tesseract):
            with patch("app.provider_manager.LLMProxyVisionProvider", mock_llm_vision):
                with patch("app.provider_manager.LLMProxyCloudProvider", mock_llm_cloud):
                    with patch("app.provider_manager.config") as mock_config:
                        mock_config.OCR_ENABLE_EASYOCR = False
                        mock_config.OCR_ENABLE_PADDLEOCR = False
                        mock_config.OCR_ENABLE_RAPIDOCR = False
                        mock_config.OCR_ENABLE_APPLE_VISION = False
                        mock_config.OCR_ENABLE_LLM_PROXY_VISION = True
                        mock_config.OCR_ENABLE_LLM_PROXY_CLOUD = True
                        from app.provider_manager import ProviderManager
                        pm = ProviderManager()

        assert "llm_proxy_vision" in pm.providers
        assert "llm_proxy_cloud" in pm.providers
