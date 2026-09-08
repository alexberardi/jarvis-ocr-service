"""Apple Vision with the two provider bugs corrected, for benchmarking only.

Bug 1: `performRequests_error_` is a PyObjC out-parameter method: it returns
       (success, error). The service does `error = handler.performRequests_error_(...)`
       then `if error: raise` — a 2-tuple is always truthy, so it raises on SUCCESS.
Bug 2: recognition level is inverted. Vision's constants are
       Accurate = 0, Fast = 1; the provider sets 1 and comments it as "accurate".
       Measured on a cookbook page: level 0 -> 94 observations / 3057 chars,
       level 1 -> 1 observation / 8 chars.
"""
import io, time, sys
sys.path.insert(0, '/Users/alexanderberardi/jarvis/jarvis-ocr-service')
from PIL import Image
from Vision import VNRecognizeTextRequest, VNImageRequestHandler
from CoreFoundation import NSData
from app.providers.base import OCRProvider, OCRResult, TextBlock


class AppleVisionFixedProvider(OCRProvider):
    @property
    def name(self): return "apple_vision_fixed"

    def is_available(self): return True

    def process(self, image_bytes, language_hints=None, return_boxes=True, mode="document"):
        start = time.time()
        image = Image.open(io.BytesIO(image_bytes))
        buf = io.BytesIO(); image.save(buf, format='PNG'); data = buf.getvalue()

        handler = VNImageRequestHandler.alloc().initWithData_options_(
            NSData.dataWithBytes_length_(data, len(data)), {})
        request = VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(0)            # 0 = ACCURATE
        request.setUsesLanguageCorrection_(True)
        if language_hints:
            request.setRecognitionLanguages_(language_hints)

        success, error = handler.performRequests_error_([request], None)
        if not success or error is not None:
            raise RuntimeError(f"Apple Vision OCR failed: {error}")

        parts, blocks = [], []
        for obs in (request.results() or []):
            cands = obs.topCandidates_(1)
            if not cands:
                continue
            c = cands[0]
            parts.append(c.string())
            if return_boxes:
                bb = obs.boundingBox()
                blocks.append(TextBlock(
                    text=c.string(),
                    bbox=[bb.origin.x, bb.origin.y, bb.size.width, bb.size.height],
                    confidence=float(c.confidence()),
                ))
        return OCRResult(text="\n".join(parts), blocks=blocks,
                         duration_ms=(time.time() - start) * 1000)
