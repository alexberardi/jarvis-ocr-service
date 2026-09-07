"""Tesseract OCR provider implementation."""

import io
import time
from typing import List, Optional
from PIL import Image

# Guarded like every other provider. app/providers/__init__.py imports all of
# them eagerly, so a bare `import pytesseract` made this package unimportable on
# any host that does not install it -- which took down provider_manager, and with
# it the whole worker, on the Mac that runs Apple Vision alone.
try:
    import pytesseract

    PYTESSERACT_AVAILABLE = True
except ImportError:
    pytesseract = None
    PYTESSERACT_AVAILABLE = False

from app.providers.base import OCRProvider, OCRResult, TextBlock


class TesseractProvider(OCRProvider):
    """Tesseract OCR provider.

    Was described as "mandatory, always available". It is neither: the binary can
    be absent, and on a macOS host that exists only to run Apple Vision the
    Python wrapper is not installed either.
    """
    
    @property
    def name(self) -> str:
        return "tesseract"
    
    def is_available(self) -> bool:
        """True only when both the wrapper and the tesseract binary are present."""
        if not PYTESSERACT_AVAILABLE:
            return False
        try:
            # Quick check if tesseract is installed
            pytesseract.get_tesseract_version()
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
        """Process image with Tesseract."""
        if not PYTESSERACT_AVAILABLE:
            raise RuntimeError("Tesseract is not available (pytesseract is not installed)")

        start = time.time()
        
        # Load image.
        #
        # pytesseract only accepts a plain single-frame Image; it rejects
        # container types such as MpoImageFile -- which is exactly what an iPhone
        # photo decodes to -- with "Unsupported image format/type". Collapsing to
        # a single RGB frame here costs nothing and keeps tier 1 from failing on
        # the most common input this service receives.
        image = Image.open(io.BytesIO(image_bytes))
        if image.format == "MPO" or getattr(image, "n_frames", 1) > 1:
            image.seek(0)
            image = image.convert("RGB")
        
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

