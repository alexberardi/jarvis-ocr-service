"""Tests for app/providers/llm_proxy_provider.py."""

import asyncio
import base64
import io
import json
import struct
import time
import zlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.providers.base import OCRResult, TextBlock


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


# --- run_async tests ---


class TestRunAsync:
    """Tests for the run_async helper."""

    def test_run_async_no_running_loop(self):
        """run_async should work when no event loop is running."""
        from app.providers.llm_proxy_provider import run_async

        async def coro():
            return 42

        result = run_async(coro())
        assert result == 42

    def test_run_async_with_running_loop(self):
        """run_async should work from within a running event loop via thread."""
        from app.providers.llm_proxy_provider import run_async

        async def inner():
            return "hello"

        async def outer():
            return run_async(inner())

        result = asyncio.run(outer())
        assert result == "hello"

    def test_run_async_propagates_exception(self):
        """run_async should propagate exceptions from the coroutine."""
        from app.providers.llm_proxy_provider import run_async

        async def failing():
            raise ValueError("test error")

        with pytest.raises(ValueError, match="test error"):
            run_async(failing())

    def test_run_async_propagates_exception_in_loop(self):
        """run_async should propagate exceptions when called from within a loop."""
        from app.providers.llm_proxy_provider import run_async

        async def failing():
            raise ValueError("inner error")

        async def outer():
            return run_async(failing())

        with pytest.raises(ValueError, match="inner error"):
            asyncio.run(outer())


# --- LLMProxyProvider tests ---


class TestLLMProxyProvider:
    """Tests for LLMProxyProvider base class."""

    def _make_provider(self, model="vision", base_url="http://llm:8000", app_id="app1", app_key="key1"):
        with patch("app.providers.llm_proxy_provider.config") as mock_config:
            mock_config.JARVIS_APP_ID = app_id
            mock_config.JARVIS_APP_KEY = app_key
            with patch("app.providers.llm_proxy_provider.service_config") as mock_sc:
                mock_sc.get_llm_proxy_url.return_value = base_url
                from app.providers.llm_proxy_provider import LLMProxyProvider

                class ConcreteProvider(LLMProxyProvider):
                    pass

                provider = ConcreteProvider(model)
        # Patch base_url property for later use
        provider._base_url_override = base_url
        return provider

    def test_init_sets_fields(self):
        with patch("app.providers.llm_proxy_provider.config") as mock_config:
            mock_config.JARVIS_APP_ID = "myapp"
            mock_config.JARVIS_APP_KEY = "mykey"
            from app.providers.llm_proxy_provider import LLMProxyProvider

            class Concrete(LLMProxyProvider):
                pass

            p = Concrete("vision")
        assert p.model_name == "vision"
        assert p.app_id == "myapp"
        assert p.app_key == "mykey"
        assert p.timeout == 60.0

    def test_name_property(self):
        provider = self._make_provider("cloud")
        assert provider.name == "llm_proxy_cloud"

    def test_is_available_true(self):
        with patch("app.providers.llm_proxy_provider.service_config") as mock_sc:
            mock_sc.get_llm_proxy_url.return_value = "http://llm:8000"
            provider = self._make_provider()
            assert provider.is_available() is True

    def test_is_available_false_no_url(self):
        with patch("app.providers.llm_proxy_provider.service_config") as mock_sc:
            mock_sc.get_llm_proxy_url.return_value = ""
            provider = self._make_provider(base_url="")
            provider.app_id = "app"
            provider.app_key = "key"
            assert provider.is_available() is False

    def test_is_available_false_no_app_id(self):
        with patch("app.providers.llm_proxy_provider.service_config") as mock_sc:
            mock_sc.get_llm_proxy_url.return_value = "http://llm:8000"
            provider = self._make_provider()
            provider.app_id = ""
            assert provider.is_available() is False

    def test_is_available_false_no_app_key(self):
        with patch("app.providers.llm_proxy_provider.service_config") as mock_sc:
            mock_sc.get_llm_proxy_url.return_value = "http://llm:8000"
            provider = self._make_provider()
            provider.app_key = ""
            assert provider.is_available() is False

    def test_create_image_message(self):
        provider = self._make_provider()
        image_bytes = b"fake-image-data"
        msg = provider._create_image_message(image_bytes, "image/png")
        assert msg["type"] == "image_url"
        assert "data:image/png;base64," in msg["image_url"]["url"]
        # Verify base64 round-trip
        b64_part = msg["image_url"]["url"].split(",")[1]
        assert base64.b64decode(b64_part) == image_bytes


class TestCallLlmProxy:
    """Tests for LLMProxyProvider._call_llm_proxy."""

    def _make_provider(self):
        with patch("app.providers.llm_proxy_provider.config") as mock_config:
            mock_config.JARVIS_APP_ID = "app"
            mock_config.JARVIS_APP_KEY = "key"
            from app.providers.llm_proxy_provider import LLMProxyVisionProvider
            provider = LLMProxyVisionProvider()
        return provider

    @pytest.mark.asyncio
    async def test_success(self):
        provider = self._make_provider()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "  extracted text  "}}]
        }

        with patch("app.providers.llm_proxy_provider.service_config") as mock_sc:
            mock_sc.get_llm_proxy_url.return_value = "http://llm:8000"
            with patch("httpx.AsyncClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.post.return_value = mock_resp
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = mock_instance

                result = await provider._call_llm_proxy([{"role": "user", "content": "test"}])

        assert result == "extracted text"

    @pytest.mark.asyncio
    async def test_no_base_url_raises(self):
        provider = self._make_provider()
        with patch("app.providers.llm_proxy_provider.service_config") as mock_sc:
            mock_sc.get_llm_proxy_url.return_value = ""
            with pytest.raises(RuntimeError, match="not configured"):
                await provider._call_llm_proxy([])

    @pytest.mark.asyncio
    async def test_invalid_response_format(self):
        provider = self._make_provider()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"choices": []}

        with patch("app.providers.llm_proxy_provider.service_config") as mock_sc:
            mock_sc.get_llm_proxy_url.return_value = "http://llm:8000"
            with patch("httpx.AsyncClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.post.return_value = mock_resp
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = mock_instance

                with pytest.raises(RuntimeError, match="Invalid response"):
                    await provider._call_llm_proxy([{"role": "user", "content": "test"}])

    @pytest.mark.asyncio
    async def test_timeout_raises(self):
        import httpx as httpx_mod
        provider = self._make_provider()

        with patch("app.providers.llm_proxy_provider.service_config") as mock_sc:
            mock_sc.get_llm_proxy_url.return_value = "http://llm:8000"
            with patch("httpx.AsyncClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.post.side_effect = httpx_mod.TimeoutException("timeout")
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = mock_instance

                with pytest.raises(RuntimeError, match="timed out"):
                    await provider._call_llm_proxy([{"role": "user", "content": "test"}])

    @pytest.mark.asyncio
    async def test_request_error_raises(self):
        import httpx as httpx_mod
        provider = self._make_provider()

        with patch("app.providers.llm_proxy_provider.service_config") as mock_sc:
            mock_sc.get_llm_proxy_url.return_value = "http://llm:8000"
            with patch("httpx.AsyncClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.post.side_effect = httpx_mod.RequestError("connection failed")
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = mock_instance

                with pytest.raises(RuntimeError, match="Failed to reach"):
                    await provider._call_llm_proxy([{"role": "user", "content": "test"}])

    @pytest.mark.asyncio
    async def test_with_response_format(self):
        provider = self._make_provider()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": '{"text": "hello"}'}}]
        }

        with patch("app.providers.llm_proxy_provider.service_config") as mock_sc:
            mock_sc.get_llm_proxy_url.return_value = "http://llm:8000"
            with patch("httpx.AsyncClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.post.return_value = mock_resp
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = mock_instance

                result = await provider._call_llm_proxy(
                    [{"role": "user", "content": "test"}],
                    response_format={"type": "json_object"}
                )
                # Verify response_format was passed in request body
                call_kwargs = mock_instance.post.call_args
                assert "response_format" in call_kwargs.kwargs["json"]


class TestValidateOcrOutput:
    """Tests for LLMProxyProvider._validate_ocr_output."""

    def _make_provider(self):
        with patch("app.providers.llm_proxy_provider.config") as mock_config:
            mock_config.JARVIS_APP_ID = "app"
            mock_config.JARVIS_APP_KEY = "key"
            from app.providers.llm_proxy_provider import LLMProxyVisionProvider
            provider = LLMProxyVisionProvider()
        return provider

    @pytest.mark.asyncio
    async def test_empty_text_returns_false(self):
        provider = self._make_provider()
        result = await provider._validate_ocr_output("")
        assert result is False

    @pytest.mark.asyncio
    async def test_short_text_returns_false(self):
        provider = self._make_provider()
        result = await provider._validate_ocr_output("ab")
        assert result is False

    @pytest.mark.asyncio
    async def test_no_base_url_returns_true(self):
        provider = self._make_provider()
        with patch("app.providers.llm_proxy_provider.service_config") as mock_sc:
            mock_sc.get_llm_proxy_url.return_value = ""
            result = await provider._validate_ocr_output("Hello World text")
        assert result is True

    @pytest.mark.asyncio
    async def test_valid_text_from_llm(self):
        provider = self._make_provider()
        llm_response = {
            "choices": [{
                "message": {
                    "content": json.dumps({"is_valid": True, "confidence": 0.95, "reason": "clear"})
                }
            }]
        }
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = llm_response

        with patch("app.providers.llm_proxy_provider.service_config") as mock_sc:
            mock_sc.get_llm_proxy_url.return_value = "http://llm:8000"
            with patch("httpx.AsyncClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.post.return_value = mock_resp
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = mock_instance
                result = await provider._validate_ocr_output("Hello World text here")

        assert result is True

    @pytest.mark.asyncio
    async def test_invalid_text_from_llm(self):
        provider = self._make_provider()
        llm_response = {
            "choices": [{
                "message": {
                    "content": json.dumps({"is_valid": False, "confidence": 0.1, "reason": "garbled"})
                }
            }]
        }
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = llm_response

        with patch("app.providers.llm_proxy_provider.service_config") as mock_sc:
            mock_sc.get_llm_proxy_url.return_value = "http://llm:8000"
            with patch("httpx.AsyncClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.post.return_value = mock_resp
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = mock_instance
                result = await provider._validate_ocr_output("asdfghjkl random garbled")

        assert result is False

    @pytest.mark.asyncio
    async def test_no_choices_returns_true(self):
        provider = self._make_provider()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"choices": []}

        with patch("app.providers.llm_proxy_provider.service_config") as mock_sc:
            mock_sc.get_llm_proxy_url.return_value = "http://llm:8000"
            with patch("httpx.AsyncClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.post.return_value = mock_resp
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = mock_instance
                result = await provider._validate_ocr_output("Some text here")

        assert result is True

    @pytest.mark.asyncio
    async def test_exception_returns_true(self):
        provider = self._make_provider()
        with patch("app.providers.llm_proxy_provider.service_config") as mock_sc:
            mock_sc.get_llm_proxy_url.return_value = "http://llm:8000"
            with patch("httpx.AsyncClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.post.side_effect = Exception("conn error")
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = mock_instance
                result = await provider._validate_ocr_output("Some text")

        assert result is True


class TestLLMProxyProcess:
    """Tests for LLMProxyProvider.process method."""

    def _make_provider(self):
        with patch("app.providers.llm_proxy_provider.config") as mock_config:
            mock_config.JARVIS_APP_ID = "app"
            mock_config.JARVIS_APP_KEY = "key"
            from app.providers.llm_proxy_provider import LLMProxyVisionProvider
            provider = LLMProxyVisionProvider()
        return provider

    def test_process_success_json(self):
        provider = self._make_provider()
        png_bytes = _make_minimal_png()
        json_response = json.dumps({"page1": {"text": "Hello World"}})

        with patch.object(provider, '_call_llm_proxy', new_callable=AsyncMock, return_value=json_response):
            with patch.object(provider, '_validate_ocr_output', new_callable=AsyncMock, return_value=True):
                result = provider.process(png_bytes)

        assert isinstance(result, OCRResult)
        assert result.text == "Hello World"
        assert result.duration_ms > 0

    def test_process_fallback_raw_text(self):
        provider = self._make_provider()
        png_bytes = _make_minimal_png()

        with patch.object(provider, '_call_llm_proxy', new_callable=AsyncMock, return_value="not valid json"):
            with patch.object(provider, '_validate_ocr_output', new_callable=AsyncMock, return_value=True):
                result = provider.process(png_bytes)

        assert result.text == "not valid json"

    def test_process_with_boxes(self):
        provider = self._make_provider()
        png_bytes = _make_minimal_png()
        json_response = json.dumps({"page1": {"text": "Text"}})

        with patch.object(provider, '_call_llm_proxy', new_callable=AsyncMock, return_value=json_response):
            with patch.object(provider, '_validate_ocr_output', new_callable=AsyncMock, return_value=True):
                result = provider.process(png_bytes, return_boxes=True)

        assert len(result.blocks) == 1
        assert result.blocks[0].text == "Text"
        assert result.blocks[0].confidence == 0.95

    def test_process_without_boxes(self):
        provider = self._make_provider()
        png_bytes = _make_minimal_png()
        json_response = json.dumps({"page1": {"text": "Text"}})

        with patch.object(provider, '_call_llm_proxy', new_callable=AsyncMock, return_value=json_response):
            with patch.object(provider, '_validate_ocr_output', new_callable=AsyncMock, return_value=True):
                result = provider.process(png_bytes, return_boxes=False)

        assert len(result.blocks) == 0

    def test_process_with_language_hints(self):
        provider = self._make_provider()
        png_bytes = _make_minimal_png()
        json_response = json.dumps({"page1": {"text": "Bonjour"}})

        with patch.object(provider, '_call_llm_proxy', new_callable=AsyncMock, return_value=json_response) as mock_call:
            with patch.object(provider, '_validate_ocr_output', new_callable=AsyncMock, return_value=True):
                result = provider.process(png_bytes, language_hints=["fr", "en"])

        assert result.text == "Bonjour"

    def test_process_garbled_output_still_returns(self):
        """Garbled output is flagged but still returned."""
        provider = self._make_provider()
        png_bytes = _make_minimal_png()
        json_response = json.dumps({"page1": {"text": "asdfghjkl"}})

        with patch.object(provider, '_call_llm_proxy', new_callable=AsyncMock, return_value=json_response):
            with patch.object(provider, '_validate_ocr_output', new_callable=AsyncMock, return_value=False):
                result = provider.process(png_bytes)

        assert result.text == "asdfghjkl"


class TestLLMProxyVisionBatch:
    """Tests for LLMProxyVisionProvider.process_batch."""

    def _make_provider(self):
        with patch("app.providers.llm_proxy_provider.config") as mock_config:
            mock_config.JARVIS_APP_ID = "app"
            mock_config.JARVIS_APP_KEY = "key"
            from app.providers.llm_proxy_provider import LLMProxyVisionProvider
            return LLMProxyVisionProvider()

    def test_batch_processes_each_image(self):
        provider = self._make_provider()
        png_bytes = _make_minimal_png()
        images = [(png_bytes, "image/png"), (png_bytes, "image/png")]

        results = [
            OCRResult(text="A", blocks=[], duration_ms=1.0),
            OCRResult(text="B", blocks=[], duration_ms=1.0),
        ]

        with patch.object(provider, 'process', side_effect=results):
            batch_results = provider.process_batch(images)

        assert len(batch_results) == 2
        assert batch_results[0].text == "A"
        assert batch_results[1].text == "B"


class TestLLMProxyCloudBatch:
    """Tests for LLMProxyCloudProvider.process_batch."""

    def _make_provider(self):
        with patch("app.providers.llm_proxy_provider.config") as mock_config:
            mock_config.JARVIS_APP_ID = "app"
            mock_config.JARVIS_APP_KEY = "key"
            from app.providers.llm_proxy_provider import LLMProxyCloudProvider
            return LLMProxyCloudProvider()

    def test_batch_success(self):
        provider = self._make_provider()
        png_bytes = _make_minimal_png()
        images = [(png_bytes, "image/png"), (png_bytes, "image/png")]

        json_response = json.dumps({
            "page1": {"text": "First"},
            "page2": {"text": "Second"},
        })

        with patch.object(provider, '_call_llm_proxy', new_callable=AsyncMock, return_value=json_response):
            with patch.object(provider, '_validate_ocr_output', new_callable=AsyncMock, return_value=True):
                results = provider.process_batch(images)

        assert len(results) == 2
        assert results[0].text == "First"
        assert results[1].text == "Second"

    def test_batch_invalid_json_fallback(self):
        provider = self._make_provider()
        png_bytes = _make_minimal_png()
        images = [(png_bytes, "image/png")]

        with patch.object(provider, '_call_llm_proxy', new_callable=AsyncMock, return_value="not json"):
            with patch.object(provider, '_validate_ocr_output', new_callable=AsyncMock, return_value=True):
                results = provider.process_batch(images)

        assert len(results) == 1
        assert results[0].text == ""  # No page1 key in empty dict

    def test_batch_with_boxes(self):
        provider = self._make_provider()
        png_bytes = _make_minimal_png()
        images = [(png_bytes, "image/png")]

        json_response = json.dumps({"page1": {"text": "Boxed"}})

        with patch.object(provider, '_call_llm_proxy', new_callable=AsyncMock, return_value=json_response):
            with patch.object(provider, '_validate_ocr_output', new_callable=AsyncMock, return_value=True):
                results = provider.process_batch(images, return_boxes=True)

        assert len(results[0].blocks) == 1

    def test_batch_without_boxes(self):
        provider = self._make_provider()
        png_bytes = _make_minimal_png()
        images = [(png_bytes, "image/png")]

        json_response = json.dumps({"page1": {"text": "No box"}})

        with patch.object(provider, '_call_llm_proxy', new_callable=AsyncMock, return_value=json_response):
            with patch.object(provider, '_validate_ocr_output', new_callable=AsyncMock, return_value=True):
                results = provider.process_batch(images, return_boxes=False)

        assert len(results[0].blocks) == 0

    def test_batch_with_language_hints(self):
        provider = self._make_provider()
        png_bytes = _make_minimal_png()
        images = [(png_bytes, "image/png")]

        json_response = json.dumps({"page1": {"text": "Bonjour"}})

        with patch.object(provider, '_call_llm_proxy', new_callable=AsyncMock, return_value=json_response) as mock_call:
            with patch.object(provider, '_validate_ocr_output', new_callable=AsyncMock, return_value=True):
                results = provider.process_batch(images, language_hints=["fr"])

        assert results[0].text == "Bonjour"

    def test_batch_garbled_output(self):
        provider = self._make_provider()
        png_bytes = _make_minimal_png()
        images = [(png_bytes, "image/png")]

        json_response = json.dumps({"page1": {"text": "asdf"}})

        with patch.object(provider, '_call_llm_proxy', new_callable=AsyncMock, return_value=json_response):
            with patch.object(provider, '_validate_ocr_output', new_callable=AsyncMock, return_value=False):
                results = provider.process_batch(images)

        # Still returns result even if garbled
        assert results[0].text == "asdf"
