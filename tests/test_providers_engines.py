"""Happy-path tests for the optional providers, with the engines mocked.

tests/test_providers_misc.py already covers the "library not installed" arms.
What was untested is the part this service actually owns: turning each engine's
result shape into an OCRResult, and the four-corner-points -> [x, y, w, h] bbox
conversion. The engines themselves are never imported here, so these run in the
default (Tesseract-only) install.
"""

import io
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from app.providers.base import OCRResult

# A rectangle whose corners are deliberately out of order, so a provider that
# assumes points[0] is the top-left instead of taking min/max would fail.
BBOX_POINTS = [[30.0, 10.0], [130.0, 12.0], [128.0, 60.0], [28.0, 58.0]]
EXPECTED_BBOX = [28.0, 10.0, 102.0, 50.0]


def _png_bytes(width: int = 100, height: int = 50) -> bytes:
    """A blank PNG big enough that normalized coordinates scale visibly."""
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, format="PNG")
    return buffer.getvalue()


class TestEasyOCRProcess:
    """EasyOCRProvider.process against a stubbed reader."""

    def _provider(self, detections: list[Any]):
        from app.providers.easyocr_provider import EasyOCRProvider

        provider = EasyOCRProvider()
        provider._reader = MagicMock()
        provider._reader.readtext.return_value = detections
        provider._initialized = True
        return provider

    def test_builds_result_from_detections(self):
        provider = self._provider([(BBOX_POINTS, "Hello", 0.91)])

        with patch("app.providers.easyocr_provider.EASYOCR_AVAILABLE", True):
            result = provider.process(_png_bytes())

        assert isinstance(result, OCRResult)
        assert result.text == "Hello"
        assert len(result.blocks) == 1
        assert result.blocks[0].bbox == EXPECTED_BBOX
        assert result.blocks[0].confidence == pytest.approx(0.91)
        assert result.duration_ms >= 0

    def test_joins_multiple_detections_with_spaces(self):
        provider = self._provider([
            (BBOX_POINTS, "Hello", 0.9),
            (BBOX_POINTS, "World", 0.8),
        ])

        with patch("app.providers.easyocr_provider.EASYOCR_AVAILABLE", True):
            result = provider.process(_png_bytes())

        assert result.text == "Hello World"
        assert len(result.blocks) == 2

    def test_return_boxes_false_still_returns_text(self):
        provider = self._provider([(BBOX_POINTS, "Hello", 0.9)])

        with patch("app.providers.easyocr_provider.EASYOCR_AVAILABLE", True):
            result = provider.process(_png_bytes(), return_boxes=False)

        assert result.text == "Hello"
        assert result.blocks == []

    def test_no_detections_yields_empty_text(self):
        provider = self._provider([])

        with patch("app.providers.easyocr_provider.EASYOCR_AVAILABLE", True):
            result = provider.process(_png_bytes())

        assert result.text == ""
        assert result.blocks == []


class TestPaddleOCRProcess:
    """PaddleOCRProvider.process against a stubbed 2.x engine.

    The nested [[ [bbox, (text, confidence)] ]] shape is 2.x-only; PaddleOCR 3.x
    returns dicts, which is why the dependency is pinned (.github/dependabot.yml).
    """

    def _provider(self, results: Any):
        from app.providers.paddleocr_provider import PaddleOCRProvider

        provider = PaddleOCRProvider()
        provider._ocr = MagicMock()
        provider._ocr.ocr.return_value = results
        provider._initialized = True
        return provider

    def test_builds_result_from_2x_shape(self):
        provider = self._provider([[[BBOX_POINTS, ("Hello", 0.88)]]])

        with patch("app.providers.paddleocr_provider.PADDLEOCR_AVAILABLE", True):
            result = provider.process(_png_bytes())

        assert result.text == "Hello"
        assert result.blocks[0].bbox == EXPECTED_BBOX
        assert result.blocks[0].confidence == pytest.approx(0.88)
        provider._ocr.ocr.assert_called_once()
        assert provider._ocr.ocr.call_args.kwargs == {"cls": True}

    def test_skips_falsy_lines(self):
        provider = self._provider([[None, [BBOX_POINTS, ("Hello", 0.5)]]])

        with patch("app.providers.paddleocr_provider.PADDLEOCR_AVAILABLE", True):
            result = provider.process(_png_bytes())

        assert result.text == "Hello"

    def test_empty_result_yields_empty_text(self):
        provider = self._provider([[]])

        with patch("app.providers.paddleocr_provider.PADDLEOCR_AVAILABLE", True):
            result = provider.process(_png_bytes())

        assert result.text == ""
        assert result.blocks == []

    def test_none_result_yields_empty_text(self):
        provider = self._provider(None)

        with patch("app.providers.paddleocr_provider.PADDLEOCR_AVAILABLE", True):
            result = provider.process(_png_bytes())

        assert result.text == ""


class TestRapidOCRProcess:
    """RapidOCRProvider.process against a stubbed callable engine."""

    def _provider(self, result: Any):
        from app.providers.rapidocr_provider import RapidOCRProvider

        provider = RapidOCRProvider()
        provider._ocr = MagicMock(return_value=(result, 0.01))
        provider._initialized = True
        return provider

    def test_builds_result_from_lines(self):
        provider = self._provider([[BBOX_POINTS, "Hello", 0.77]])

        with patch("app.providers.rapidocr_provider._check_rapidocr_available", return_value=True):
            result = provider.process(_png_bytes())

        assert result.text == "Hello"
        assert result.blocks[0].bbox == EXPECTED_BBOX
        assert result.blocks[0].confidence == pytest.approx(0.77)

    def test_none_result_yields_empty_text(self):
        """RapidOCR returns None rather than [] when it finds nothing."""
        provider = self._provider(None)

        with patch("app.providers.rapidocr_provider._check_rapidocr_available", return_value=True):
            result = provider.process(_png_bytes())

        assert result.text == ""
        assert result.blocks == []

    def test_return_boxes_false_still_returns_text(self):
        provider = self._provider([[BBOX_POINTS, "Hello", 0.77]])

        with patch("app.providers.rapidocr_provider._check_rapidocr_available", return_value=True):
            result = provider.process(_png_bytes(), return_boxes=False)

        assert result.text == "Hello"
        assert result.blocks == []

    def test_is_available_when_engine_constructs(self):
        from app.providers.rapidocr_provider import RapidOCRProvider

        provider = RapidOCRProvider()
        provider._initialized = True  # skip the real RapidOCR() construction

        with patch("app.providers.rapidocr_provider._check_rapidocr_available", return_value=True):
            assert provider.is_available() is True


def _observation(text: str, confidence: float, origin: tuple[float, float],
                 size: tuple[float, float]) -> MagicMock:
    """A stand-in for a VNRecognizedTextObservation."""
    candidate = MagicMock()
    candidate.string.return_value = text
    candidate.confidence.return_value = confidence

    observation = MagicMock()
    observation.topCandidates_.return_value = [candidate]
    observation.boundingBox.return_value = SimpleNamespace(
        origin=SimpleNamespace(x=origin[0], y=origin[1]),
        size=SimpleNamespace(width=size[0], height=size[1]),
    )
    return observation


class TestAppleVisionProcess:
    """AppleVisionProvider.process against a stubbed Vision framework.

    The Vision symbols only exist in the module namespace on a machine with
    pyobjc installed, hence create=True on the patches.
    """

    def _patched_vision(self, observations: list[MagicMock], error: Any = None):
        """Stub Vision the way PyObjC actually behaves.

        `performRequests:error:` has an NSError** out-parameter, so PyObjC returns
        a (success, error) TUPLE -- (True, None) on success. An earlier version of
        this stub returned a bare None on success, which let the provider's
        `if error: raise` pass its tests while raising on every real call, because
        a 2-tuple is always truthy. Model the real contract here or the tests are
        worse than useless.
        """
        request = MagicMock()
        request.results.return_value = observations
        request_cls = MagicMock()
        request_cls.alloc.return_value.init.return_value = request

        handler = MagicMock()
        handler.performRequests_error_.return_value = (error is None, error)
        handler_cls = MagicMock()
        handler_cls.alloc.return_value.initWithData_options_.return_value = handler
        self._request = request

        return patch.multiple(
            "app.providers.apple_vision_provider",
            APPLE_VISION_AVAILABLE=True,
            NSData=MagicMock(),
            VNRecognizeTextRequest=request_cls,
            VNImageRequestHandler=handler_cls,
            create=True,
        )

    def test_converts_normalized_coordinates_to_pixels(self):
        from app.providers.apple_vision_provider import AppleVisionProvider

        # Bottom-left origin, normalized: x=0.1, y=0.2, w=0.5, h=0.4 on a
        # 100x50 image -> x=10, y=(1-0.2-0.4)*50=20, w=50, h=20.
        observation = _observation("Hello", 0.95, origin=(0.1, 0.2), size=(0.5, 0.4))

        with self._patched_vision([observation]):
            result = AppleVisionProvider().process(_png_bytes(100, 50))

        assert result.text == "Hello"
        assert result.blocks[0].bbox == [10.0, 20.0, 50.0, 20.0]
        assert result.blocks[0].confidence == pytest.approx(0.95)

    def test_joins_observations_with_spaces(self):
        from app.providers.apple_vision_provider import AppleVisionProvider

        observations = [
            _observation("Hello", 0.9, origin=(0.0, 0.0), size=(0.5, 0.5)),
            _observation("World", 0.8, origin=(0.5, 0.0), size=(0.5, 0.5)),
        ]

        with self._patched_vision(observations):
            result = AppleVisionProvider().process(_png_bytes())

        assert result.text == "Hello World"
        assert len(result.blocks) == 2

    def test_return_boxes_false_still_returns_text(self):
        from app.providers.apple_vision_provider import AppleVisionProvider

        observation = _observation("Hello", 0.9, origin=(0.0, 0.0), size=(1.0, 1.0))

        with self._patched_vision([observation]):
            result = AppleVisionProvider().process(_png_bytes(), return_boxes=False)

        assert result.text == "Hello"
        assert result.blocks == []

    def test_framework_error_raises(self):
        from app.providers.apple_vision_provider import AppleVisionProvider

        with self._patched_vision([], error="VisionKit exploded"):
            with pytest.raises(RuntimeError, match="Apple Vision OCR failed"):
                AppleVisionProvider().process(_png_bytes())

    def test_success_tuple_is_not_mistaken_for_an_error(self):
        """(True, None) means success. Regression guard for a total outage.

        The provider assigned the whole return value to `error` and raised if it
        was truthy, so every successful recognition raised
        "Apple Vision OCR failed: (True, None)" and the tier fell through.
        """
        from app.providers.apple_vision_provider import AppleVisionProvider

        observation = _observation("Hello", 0.9, origin=(0.0, 0.0), size=(1.0, 1.0))

        with self._patched_vision([observation]):
            result = AppleVisionProvider().process(_png_bytes())

        assert result.text == "Hello"

    def test_uses_accurate_recognition_level(self):
        """Vision's levels are Accurate=0, Fast=1 -- the provider had them backwards.

        Measured on a cookbook page: level 0 returned 94 text observations
        (3057 chars), level 1 returned 1 observation (8 chars). Getting this
        constant wrong silently reduces the provider to noise.
        """
        from app.providers.apple_vision_provider import AppleVisionProvider

        observation = _observation("Hello", 0.9, origin=(0.0, 0.0), size=(1.0, 1.0))

        with self._patched_vision([observation]):
            AppleVisionProvider().process(_png_bytes())

        self._request.setRecognitionLevel_.assert_called_once_with(0)

    def test_is_available_when_framework_present(self):
        from app.providers.apple_vision_provider import AppleVisionProvider

        with patch("app.providers.apple_vision_provider.APPLE_VISION_AVAILABLE", True):
            assert AppleVisionProvider().is_available() is True
