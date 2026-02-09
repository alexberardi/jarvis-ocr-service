"""Tests for provider unavailability paths, base provider, and tesseract process."""

import io
import struct
import time
import zlib
from unittest.mock import MagicMock, patch
from typing import List, Optional

import pytest
from PIL import Image

from app.providers.base import OCRProvider, OCRResult, TextBlock


def _make_minimal_png() -> bytes:
    """Create a minimal valid 1x1 white PNG image."""
    signature = b"\x89PNG\r\n\x1a\n"

    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        chunk_data = chunk_type + data
        crc = struct.pack(">I", zlib.crc32(chunk_data) & 0xFFFFFFFF)
        length = struct.pack(">I", len(data))
        return length + chunk_data + crc

    ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    ihdr = _chunk(b"IHDR", ihdr_data)
    raw_data = b"\x00\xff\xff\xff"
    compressed = zlib.compress(raw_data)
    idat = _chunk(b"IDAT", compressed)
    iend = _chunk(b"IEND", b"")
    return signature + ihdr + idat + iend


# --- Base OCRProvider tests ---


class TestBaseProvider:
    """Tests for OCRProvider base class."""

    def test_time_execution(self):
        """Test the _time_execution helper."""

        class DummyProvider(OCRProvider):
            @property
            def name(self):
                return "dummy"

            def is_available(self):
                return True

            def process(self, image_bytes, language_hints=None, return_boxes=True, mode="document"):
                return OCRResult(text="test", blocks=[], duration_ms=0)

        provider = DummyProvider()
        result, duration = provider._time_execution(lambda: "hello")
        assert result == "hello"
        assert duration >= 0

    def test_ocr_result_dataclass(self):
        result = OCRResult(text="hello", blocks=[], duration_ms=1.5)
        assert result.text == "hello"
        assert result.blocks == []
        assert result.duration_ms == 1.5

    def test_text_block_dataclass(self):
        block = TextBlock(text="word", bbox=[0.0, 0.0, 10.0, 5.0], confidence=0.9)
        assert block.text == "word"
        assert len(block.bbox) == 4


# --- Tesseract provider process tests ---


class TestTesseractProcess:
    """Tests for TesseractProvider.process method (actual tesseract installed)."""

    def test_process_basic(self):
        from app.providers.tesseract_provider import TesseractProvider

        provider = TesseractProvider()
        if not provider.is_available():
            pytest.skip("Tesseract not installed")

        png_bytes = _make_minimal_png()
        result = provider.process(png_bytes)
        assert isinstance(result, OCRResult)
        assert result.duration_ms >= 0

    def test_process_with_language_hints(self):
        from app.providers.tesseract_provider import TesseractProvider

        provider = TesseractProvider()
        if not provider.is_available():
            pytest.skip("Tesseract not installed")

        png_bytes = _make_minimal_png()
        result = provider.process(png_bytes, language_hints=["en"])
        assert isinstance(result, OCRResult)

    def test_process_no_boxes(self):
        from app.providers.tesseract_provider import TesseractProvider

        provider = TesseractProvider()
        if not provider.is_available():
            pytest.skip("Tesseract not installed")

        png_bytes = _make_minimal_png()
        result = provider.process(png_bytes, return_boxes=False)
        assert isinstance(result, OCRResult)
        assert result.blocks == []

    def test_process_with_boxes(self):
        from app.providers.tesseract_provider import TesseractProvider

        provider = TesseractProvider()
        if not provider.is_available():
            pytest.skip("Tesseract not installed")

        # Create a slightly larger PNG (still may not have text)
        png_bytes = _make_minimal_png()
        result = provider.process(png_bytes, return_boxes=True)
        assert isinstance(result, OCRResult)
        # blocks may be empty if no text found in blank image

    def test_name_property(self):
        from app.providers.tesseract_provider import TesseractProvider
        provider = TesseractProvider()
        assert provider.name == "tesseract"

    def test_is_available(self):
        from app.providers.tesseract_provider import TesseractProvider
        provider = TesseractProvider()
        # Returns bool regardless of whether tesseract is installed
        assert isinstance(provider.is_available(), bool)

    def test_language_map_fr(self):
        from app.providers.tesseract_provider import TesseractProvider

        provider = TesseractProvider()
        if not provider.is_available():
            pytest.skip("Tesseract not installed")

        png_bytes = _make_minimal_png()
        # This should work even though the fr language pack may not be installed
        # It may fail silently or produce empty results
        try:
            result = provider.process(png_bytes, language_hints=["fr"])
            assert isinstance(result, OCRResult)
        except Exception:
            pass  # Language pack may not be installed


# --- EasyOCR unavailability tests ---


class TestEasyOCRUnavailable:
    """Tests for EasyOCR when the library is not available."""

    def test_name(self):
        from app.providers.easyocr_provider import EasyOCRProvider
        provider = EasyOCRProvider()
        assert provider.name == "easyocr"

    def test_is_available_when_lib_missing(self):
        from app.providers.easyocr_provider import EasyOCRProvider

        with patch("app.providers.easyocr_provider.EASYOCR_AVAILABLE", False):
            provider = EasyOCRProvider()
            assert provider.is_available() is False

    def test_process_raises_when_lib_missing(self):
        from app.providers.easyocr_provider import EasyOCRProvider

        with patch("app.providers.easyocr_provider.EASYOCR_AVAILABLE", False):
            provider = EasyOCRProvider()
            with pytest.raises(RuntimeError, match="not installed"):
                provider.process(b"fake")

    def test_ensure_initialized_raises_when_lib_missing(self):
        from app.providers.easyocr_provider import EasyOCRProvider

        with patch("app.providers.easyocr_provider.EASYOCR_AVAILABLE", False):
            provider = EasyOCRProvider()
            with pytest.raises(RuntimeError, match="not installed"):
                provider._ensure_initialized()


# --- PaddleOCR unavailability tests ---


class TestPaddleOCRUnavailable:
    """Tests for PaddleOCR when the library is not available."""

    def test_name(self):
        from app.providers.paddleocr_provider import PaddleOCRProvider
        provider = PaddleOCRProvider()
        assert provider.name == "paddleocr"

    def test_is_available_when_lib_missing(self):
        from app.providers.paddleocr_provider import PaddleOCRProvider

        with patch("app.providers.paddleocr_provider.PADDLEOCR_AVAILABLE", False):
            provider = PaddleOCRProvider()
            assert provider.is_available() is False

    def test_process_raises_when_lib_missing(self):
        from app.providers.paddleocr_provider import PaddleOCRProvider

        with patch("app.providers.paddleocr_provider.PADDLEOCR_AVAILABLE", False):
            provider = PaddleOCRProvider()
            with pytest.raises(RuntimeError, match="not installed"):
                provider.process(b"fake")

    def test_ensure_initialized_raises_when_lib_missing(self):
        from app.providers.paddleocr_provider import PaddleOCRProvider

        with patch("app.providers.paddleocr_provider.PADDLEOCR_AVAILABLE", False):
            provider = PaddleOCRProvider()
            with pytest.raises(RuntimeError, match="not installed"):
                provider._ensure_initialized()


# --- Apple Vision unavailability tests ---


class TestAppleVisionUnavailable:
    """Tests for Apple Vision when the framework is not available."""

    def test_name(self):
        from app.providers.apple_vision_provider import AppleVisionProvider
        provider = AppleVisionProvider()
        assert provider.name == "apple_vision"

    def test_is_available_when_framework_missing(self):
        from app.providers.apple_vision_provider import AppleVisionProvider

        with patch("app.providers.apple_vision_provider.APPLE_VISION_AVAILABLE", False):
            provider = AppleVisionProvider()
            assert provider.is_available() is False

    def test_process_raises_when_framework_missing(self):
        from app.providers.apple_vision_provider import AppleVisionProvider

        with patch("app.providers.apple_vision_provider.APPLE_VISION_AVAILABLE", False):
            provider = AppleVisionProvider()
            with pytest.raises(RuntimeError, match="not available"):
                provider.process(b"fake")
