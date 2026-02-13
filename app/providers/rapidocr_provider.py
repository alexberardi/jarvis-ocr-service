"""RapidOCR provider implementation."""

import io
import time
from typing import List, Optional

from PIL import Image

from app.providers.base import OCRProvider, OCRResult, TextBlock

# Availability is checked lazily — importing rapidocr_onnxruntime loads ONNX
# models into memory, so we defer it until the provider is actually enabled.
RAPIDOCR_AVAILABLE: bool | None = None


def _check_rapidocr_available() -> bool:
    """Check if rapidocr_onnxruntime can be imported (deferred to avoid OOM at startup)."""
    global RAPIDOCR_AVAILABLE
    if RAPIDOCR_AVAILABLE is None:
        try:
            import rapidocr_onnxruntime  # noqa: F401
            RAPIDOCR_AVAILABLE = True
        except ImportError:
            RAPIDOCR_AVAILABLE = False
    return RAPIDOCR_AVAILABLE


class RapidOCRProvider(OCRProvider):
    """RapidOCR provider implementation (ONNX Runtime-based)."""

    def __init__(self):
        self._ocr = None
        self._initialized = False

    def _ensure_initialized(self):
        """Lazy initialization of RapidOCR."""
        if not _check_rapidocr_available():
            raise RuntimeError("RapidOCR is not installed")

        if not self._initialized:
            from rapidocr_onnxruntime import RapidOCR
            self._ocr = RapidOCR()
            self._initialized = True

    @property
    def name(self) -> str:
        return "rapidocr"

    def is_available(self) -> bool:
        """Check if RapidOCR is available."""
        if not _check_rapidocr_available():
            return False
        try:
            self._ensure_initialized()
            return True
        except Exception:
            return False

    def process(
        self,
        image_bytes: bytes,
        language_hints: Optional[List[str]] = None,
        return_boxes: bool = True,
        mode: str = "document"
    ) -> OCRResult:
        """Process image with RapidOCR."""
        start = time.time()

        if not _check_rapidocr_available():
            raise RuntimeError("RapidOCR is not installed")

        self._ensure_initialized()

        # Load image
        image = Image.open(io.BytesIO(image_bytes))

        # RapidOCR expects numpy array
        import numpy as np
        image_array = np.array(image)

        # Run OCR - returns (result, elapse) where result is list of [bbox_points, text, confidence] or None
        result, _ = self._ocr(image_array)

        # Extract text and blocks
        text_parts: list[str] = []
        blocks: list[TextBlock] = []

        if result:
            for line in result:
                bbox_points, text_item, confidence = line

                # Convert bbox from 4 corner points to [x, y, width, height]
                x_coords = [p[0] for p in bbox_points]
                y_coords = [p[1] for p in bbox_points]
                x = min(x_coords)
                y = min(y_coords)
                width = max(x_coords) - x
                height = max(y_coords) - y

                text_parts.append(text_item)

                if return_boxes:
                    blocks.append(TextBlock(
                        text=text_item,
                        bbox=[float(x), float(y), float(width), float(height)],
                        confidence=float(confidence)
                    ))

        full_text = " ".join(text_parts)
        duration_ms = (time.time() - start) * 1000

        return OCRResult(
            text=full_text,
            blocks=blocks,
            duration_ms=duration_ms
        )
