"""Container-format tolerance at the provider boundary.

iPhone photos are not plain JPEGs. The camera writes MPO (Multi-Picture Object)
-- a JPEG container holding two frames -- and Pillow surfaces that as an
MpoImageFile. pytesseract rejects that type outright with
"TypeError: Unsupported image format/type", so tesseract, the FIRST tier in
DEFAULT_TIER_ORDER, failed on every unmodified phone photo and the request fell
through to a slower tier.

The EXIF-orientation fix in image_resolver masks this for rotated photos, because
re-encoding happens to flatten MPO to JPEG. A photo that needs no rotation
(orientation absent or 1) is returned byte-for-byte unchanged by design, so it
still reaches the provider as MPO. That is the case these tests pin down.
"""

import io

import pytest
from PIL import Image

from app.providers.base import OCRResult
from app.providers.tesseract_provider import TesseractProvider


def _mpo_bytes(width: int = 240, height: int = 80) -> bytes:
    """A genuine two-frame MPO, the shape a phone camera produces."""
    base = Image.new("RGB", (width, height), "white")
    second = Image.new("RGB", (width, height), "white")
    buffer = io.BytesIO()
    base.save(buffer, format="MPO", append_images=[second])
    return buffer.getvalue()


def test_fixture_really_is_mpo():
    """Guard the guard: if Pillow ever writes a plain JPEG here the tests below
    would pass for the wrong reason."""
    image = Image.open(io.BytesIO(_mpo_bytes()))
    assert image.format == "MPO"
    assert getattr(image, "n_frames", 1) == 2


@pytest.mark.skipif(
    not TesseractProvider().is_available(), reason="tesseract binary not installed"
)
class TestTesseractContainerFormats:
    def test_mpo_photo_does_not_raise(self):
        result = TesseractProvider().process(_mpo_bytes())
        assert isinstance(result, OCRResult)

    def test_mpo_photo_with_boxes_does_not_raise(self):
        """image_to_data is a second, separate call into pytesseract -- it needs
        the same converted image, not the original MpoImageFile."""
        result = TesseractProvider().process(_mpo_bytes(), return_boxes=True)
        assert isinstance(result, OCRResult)
        assert result.blocks == [] or all(b.text for b in result.blocks)

    def test_plain_jpeg_still_works(self):
        buffer = io.BytesIO()
        Image.new("RGB", (240, 80), "white").save(buffer, format="JPEG")
        assert isinstance(TesseractProvider().process(buffer.getvalue()), OCRResult)
