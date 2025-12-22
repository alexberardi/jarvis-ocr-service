"""Tesseract OCR provider implementation."""

import io
import time
from typing import List, Optional
from PIL import Image
import pytesseract

from app.providers.base import OCRProvider, OCRResult, TextBlock


class TesseractProvider(OCRProvider):
    """Tesseract OCR provider (mandatory, always available)."""
    
    @property
    def name(self) -> str:
        return "tesseract"
    
    def is_available(self) -> bool:
        """Tesseract is always available (mandatory provider)."""
        try:
            # Quick check if tesseract is installed
            pytesseract.get_tesseract_version()
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
        """Process image with Tesseract."""
        start = time.time()
        
        # Load image
        image = Image.open(io.BytesIO(image_bytes))
        
        # Build language string (default to eng)
        lang = "eng"
        if language_hints:
            # Tesseract uses 3-letter codes, map common ones
            lang_map = {"en": "eng", "fr": "fra", "de": "deu", "es": "spa", "it": "ita"}
            lang = "+".join([lang_map.get(h.lower(), h.lower()) for h in language_hints[:3]])
        
        # Extract text
        text = pytesseract.image_to_string(image, lang=lang)
        
        blocks = []
        if return_boxes:
            # Get detailed data with bounding boxes
            data = pytesseract.image_to_data(image, lang=lang, output_type=pytesseract.Output.DICT)
            
            for i in range(len(data["text"])):
                text_item = data["text"][i].strip()
                if text_item:  # Skip empty text
                    conf = float(data["conf"][i]) / 100.0 if data["conf"][i] != -1 else 0.0
                    blocks.append(TextBlock(
                        text=text_item,
                        bbox=[
                            float(data["left"][i]),
                            float(data["top"][i]),
                            float(data["width"][i]),
                            float(data["height"][i])
                        ],
                        confidence=conf
                    ))
        
        duration_ms = (time.time() - start) * 1000
        
        return OCRResult(
            text=text.strip(),
            blocks=blocks,
            duration_ms=duration_ms
        )

