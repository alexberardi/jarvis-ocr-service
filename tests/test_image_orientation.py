"""EXIF orientation normalisation.

Regression guard for a silent quality bug: phone cameras record rotation as an
EXIF tag rather than rotating the pixel buffer, so a portrait-held iPhone shot
arrives as landscape pixels tagged orientation=6. Every provider hands raw
pixels to its engine, so before this was normalised centrally the recogniser
saw every such photo sideways — with no error, no log, just poor text.
"""

import io

import pytest
from PIL import Image

from app.image_resolver import _normalize_orientation

_ORIENTATION_TAG = 274


def _jpeg(size: tuple[int, int], orientation: int | None) -> bytes:
    image = Image.new("RGB", size, "white")
    buffer = io.BytesIO()
    if orientation is None:
        image.save(buffer, format="JPEG")
    else:
        exif = image.getexif()
        exif[_ORIENTATION_TAG] = orientation
        image.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


@pytest.mark.parametrize("orientation", [6, 8])
def test_rotated_photo_is_transposed(orientation: int) -> None:
    """Orientation 6/8 (portrait phone shots) swap width and height."""
    result = _normalize_orientation(_jpeg((400, 300), orientation), "image/jpeg")
    assert Image.open(io.BytesIO(result)).size == (300, 400)


def test_transposed_output_no_longer_claims_rotation() -> None:
    """The tag must be cleared, or a second pass would rotate again."""
    result = _normalize_orientation(_jpeg((400, 300), 6), "image/jpeg")
    assert Image.open(io.BytesIO(result)).getexif().get(_ORIENTATION_TAG) in (None, 0, 1)


def test_normalisation_is_idempotent() -> None:
    once = _normalize_orientation(_jpeg((400, 300), 6), "image/jpeg")
    assert _normalize_orientation(once, "image/jpeg") == once


@pytest.mark.parametrize("orientation", [None, 1])
def test_upright_image_is_returned_byte_for_byte(orientation: int | None) -> None:
    """No needless re-encode: an upright photo must not lose a JPEG generation."""
    original = _jpeg((400, 300), orientation)
    assert _normalize_orientation(original, "image/jpeg") is original


def test_undecodable_bytes_fall_through_unchanged() -> None:
    """Orientation is an enhancement, never a gate — it must not fail the job."""
    garbage = b"this is not an image"
    assert _normalize_orientation(garbage, "image/jpeg") == garbage
