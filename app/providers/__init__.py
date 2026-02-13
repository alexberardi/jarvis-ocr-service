"""OCR provider implementations."""

from app.providers.base import OCRProvider, OCRResult
from app.providers.tesseract_provider import TesseractProvider

__all__ = ["OCRProvider", "OCRResult", "TesseractProvider"]

# Optional providers will be imported conditionally
try:
    from app.providers.easyocr_provider import EasyOCRProvider
    __all__.append("EasyOCRProvider")
except ImportError:
    pass

try:
    from app.providers.paddleocr_provider import PaddleOCRProvider
    __all__.append("PaddleOCRProvider")
except ImportError:
    pass

try:
    from app.providers.rapidocr_provider import RapidOCRProvider
    __all__.append("RapidOCRProvider")
except ImportError:
    pass

try:
    from app.providers.apple_vision_provider import AppleVisionProvider
    __all__.append("AppleVisionProvider")
except ImportError:
    pass

