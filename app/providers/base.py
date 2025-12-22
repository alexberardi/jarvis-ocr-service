"""Base class for OCR providers."""

from abc import ABC, abstractmethod
from typing import List, Optional
from dataclasses import dataclass
import time


@dataclass
class TextBlock:
    """Text block with bounding box and confidence."""
    text: str
    bbox: List[float]  # [x, y, width, height]
    confidence: float


@dataclass
class OCRResult:
    """Result from OCR processing."""
    text: str
    blocks: List[TextBlock]
    duration_ms: float


class OCRProvider(ABC):
    """Base class for all OCR providers."""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name."""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if provider is available."""
        pass
    
    @abstractmethod
    def process(
        self,
        image_bytes: bytes,
        language_hints: Optional[List[str]] = None,
        return_boxes: bool = True,
        mode: str = "document"
    ) -> OCRResult:
        """
        Process image and return OCR result.
        
        Args:
            image_bytes: Raw image bytes
            language_hints: Optional language hints (e.g., ["en", "fr"])
            return_boxes: Whether to return bounding boxes
            mode: OCR mode ("document", "single_line", "word")
        
        Returns:
            OCRResult with text, blocks, and duration
        """
        pass
    
    def _time_execution(self, func, *args, **kwargs):
        """Helper to time execution of a function."""
        start = time.time()
        result = func(*args, **kwargs)
        duration_ms = (time.time() - start) * 1000
        return result, duration_ms

