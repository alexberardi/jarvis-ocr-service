"""PaddleOCR provider implementation."""

import io
import time
from typing import List, Optional
from PIL import Image

try:
    from paddleocr import PaddleOCR
    PADDLEOCR_AVAILABLE = True
except ImportError:
    PADDLEOCR_AVAILABLE = False

from app.providers.base import OCRProvider, OCRResult, TextBlock


class PaddleOCRProvider(OCRProvider):
    """PaddleOCR provider implementation."""
    
    def __init__(self):
        self._ocr = None
        self._initialized = False
    
    def _ensure_initialized(self):
        """Lazy initialization of PaddleOCR."""
        if not PADDLEOCR_AVAILABLE:
            raise RuntimeError("PaddleOCR is not installed")
        
        if not self._initialized:
            # Initialize PaddleOCR (use_angle_cls=True for better accuracy)
            self._ocr = PaddleOCR(use_angle_cls=True, lang='en', use_gpu=False)
            self._initialized = True
    
    @property
    def name(self) -> str:
        return "paddleocr"
    
    def is_available(self) -> bool:
        """Check if PaddleOCR is available."""
        if not PADDLEOCR_AVAILABLE:
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
        """Process image with PaddleOCR."""
        start = time.time()
        
        if not PADDLEOCR_AVAILABLE:
            raise RuntimeError("PaddleOCR is not installed")
        
        self._ensure_initialized()
        
        # Load image
        image = Image.open(io.BytesIO(image_bytes))
        
        # PaddleOCR expects image path or numpy array
        import numpy as np
        image_array = np.array(image)
        
        # Run OCR
        results = self._ocr.ocr(image_array, cls=True)
        
        # Extract text and blocks
        text_parts = []
        blocks = []
        
        if results and results[0]:
            for line in results[0]:
                if line:
                    bbox_points, (text_item, confidence) = line
                    
                    # Convert bbox from points to [x, y, width, height]
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

