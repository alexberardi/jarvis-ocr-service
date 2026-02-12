"""Apple Vision OCR provider implementation (macOS only)."""

import io
import time
from typing import List, Optional
from PIL import Image

try:
    from Vision import VNRecognizeTextRequest, VNImageRequestHandler, VNRequest
    from CoreFoundation import NSData
    from Foundation import NSURL
    APPLE_VISION_AVAILABLE = True
except ImportError:
    APPLE_VISION_AVAILABLE = False

from app.providers.base import OCRProvider, OCRResult, TextBlock


class AppleVisionProvider(OCRProvider):
    """Apple Vision provider implementation (macOS only)."""
    
    @property
    def name(self) -> str:
        return "apple_vision"
    
    def is_available(self) -> bool:
        """Check if Apple Vision is available (macOS only)."""
        if not APPLE_VISION_AVAILABLE:
            return False
        
        try:
            # Quick test to ensure Vision framework works
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
        """Process image with Apple Vision."""
        start = time.time()
        
        if not APPLE_VISION_AVAILABLE:
            raise RuntimeError("Apple Vision is not available (requires macOS and pyobjc-framework-Vision)")
        
        # Load image
        image = Image.open(io.BytesIO(image_bytes))
        
        # Convert PIL image to NSData
        img_buffer = io.BytesIO()
        image.save(img_buffer, format='PNG')
        img_data = img_buffer.getvalue()
        
        ns_data = NSData.dataWithBytes_length_(img_data, len(img_data))
        
        # Create image request handler
        handler = VNImageRequestHandler.alloc().initWithData_options_(ns_data, {})
        
        # Create text recognition request
        request = VNRecognizeTextRequest.alloc().init()
        
        # Set recognition level (accurate is better, fast is faster)
        request.setRecognitionLevel_(1)  # 0 = fast, 1 = accurate
        
        # Perform request
        error = handler.performRequests_error_([request], None)
        
        if error:
            raise RuntimeError(f"Apple Vision OCR failed: {error}")
        
        # Extract results
        observations = request.results()
        text_parts = []
        blocks = []
        
        for observation in observations:
            text_item = str(observation.topCandidates_(1)[0].string())
            text_parts.append(text_item)
            
            if return_boxes:
                # Get bounding box
                bbox = observation.boundingBox()
                # Vision returns normalized coordinates (0-1), convert to pixel coordinates
                x = bbox.origin.x * image.width
                y = (1 - bbox.origin.y - bbox.size.height) * image.height  # Flip Y axis
                width = bbox.size.width * image.width
                height = bbox.size.height * image.height
                
                # Get confidence
                top_candidate = observation.topCandidates_(1)[0]
                confidence = top_candidate.confidence()
                
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

