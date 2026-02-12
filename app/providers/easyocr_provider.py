"""EasyOCR provider implementation."""

import io
import time
from typing import List, Optional
from PIL import Image
import numpy as np

try:
    import easyocr
    EASYOCR_AVAILABLE = True
except ImportError:
    EASYOCR_AVAILABLE = False

from app.providers.base import OCRProvider, OCRResult, TextBlock


class EasyOCRProvider(OCRProvider):
    """EasyOCR provider implementation."""
    
    def __init__(self):
        self._reader = None
        self._initialized = False
    
    def _ensure_initialized(self):
        """Lazy initialization of EasyOCR reader."""
        if not EASYOCR_AVAILABLE:
            raise RuntimeError("EasyOCR is not installed")
        
        if not self._initialized:
            # Initialize with English by default, can be extended
            self._reader = easyocr.Reader(['en'], gpu=False)
            self._initialized = True
    
    @property
    def name(self) -> str:
        return "easyocr"
    
    def is_available(self) -> bool:
        """Check if EasyOCR is available."""
        if not EASYOCR_AVAILABLE:
            return False
        try:
            self._ensure_initialized()
            return True
        except Exception as e:
            return False
    
    def process(
        self,
        image_bytes: bytes,
        language_hints: Optional[List[str]] = None,
        return_boxes: bool = True,
        mode: str = "document"
    ) -> OCRResult:
        """Process image with EasyOCR."""
        start = time.time()
        
        if not EASYOCR_AVAILABLE:
            raise RuntimeError("EasyOCR is not installed")
        
        self._ensure_initialized()
        
        # Load image
        image = Image.open(io.BytesIO(image_bytes))
        image_array = np.array(image)
        
        # EasyOCR expects specific language codes
        # For now, use English. Could be extended to support other languages
        results = self._reader.readtext(image_array)
        
        # Extract text and blocks
        text_parts = []
        blocks = []
        
        for detection in results:
            bbox_points, text_item, confidence = detection
            
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

