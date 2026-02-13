"""Pydantic models for API requests and responses."""

from typing import List, Optional, Literal
from pydantic import BaseModel, Field


class ImageInput(BaseModel):
    """Image input model."""
    content_type: str = Field(..., description="MIME type of the image (e.g., image/png)")
    base64: str = Field(..., description="Base64-encoded image data")


class OCROptions(BaseModel):
    """OCR processing options."""
    language_hints: Optional[List[str]] = Field(default=None, description="Language hints for OCR")
    return_boxes: bool = Field(default=True, description="Whether to return bounding boxes")
    mode: Literal["document", "single_line", "word"] = Field(default="document", description="OCR mode")


class TextBlock(BaseModel):
    """Text block with bounding box and confidence."""
    text: str = Field(..., description="Extracted text")
    bbox: List[float] = Field(..., description="Bounding box [x, y, width, height]")
    confidence: float = Field(..., description="Confidence score (0.0-1.0)")


class OCRRequest(BaseModel):
    """Request model for OCR endpoint."""
    document_id: Optional[str] = Field(default=None, description="Optional document identifier")
    provider: Literal["auto", "tesseract", "easyocr", "paddleocr", "rapidocr", "apple_vision", "llm_proxy_vision", "llm_proxy_cloud"] = Field(
        default="auto", description="OCR provider to use"
    )
    image: ImageInput = Field(..., description="Image to process")
    options: Optional[OCROptions] = Field(default_factory=OCROptions, description="OCR processing options")


class OCRResponse(BaseModel):
    """Response model for OCR endpoint."""
    provider_used: str = Field(..., description="Provider that was used")
    text: str = Field(..., description="Full extracted text")
    blocks: List[TextBlock] = Field(default_factory=list, description="Text blocks with bounding boxes")
    meta: dict = Field(..., description="Metadata (duration, etc.)")


class OCRBatchRequest(BaseModel):
    """Request model for batch OCR endpoint."""
    document_id: Optional[str] = Field(default=None, description="Optional document identifier")
    provider: Literal["auto", "tesseract", "easyocr", "paddleocr", "rapidocr", "apple_vision", "llm_proxy_vision", "llm_proxy_cloud"] = Field(
        default="auto", description="OCR provider to use"
    )
    images: List[ImageInput] = Field(..., description="Images to process (1-100 images)", min_length=1, max_length=100)
    options: Optional[OCROptions] = Field(default_factory=OCROptions, description="OCR processing options")


class OCRBatchResponse(BaseModel):
    """Response model for batch OCR endpoint."""
    results: List[OCRResponse] = Field(..., description="OCR results, one per input image (in same order)")
    meta: dict = Field(..., description="Batch-level metadata")


class ProvidersResponse(BaseModel):
    """Response model for providers endpoint."""
    providers: dict = Field(..., description="Provider availability map")


class HealthResponse(BaseModel):
    """Response model for health endpoint."""
    status: str = Field(default="ok", description="Service status")


class OCRJobResponse(BaseModel):
    """Response model for queued OCR job."""
    job_id: str = Field(..., description="Job ID for tracking")
    status: str = Field(..., description="Job status (pending, processing, completed, failed)")
    created_at: str = Field(..., description="Job creation timestamp")


class OCRJobStatusResponse(BaseModel):
    """Response model for OCR job status."""
    job_id: str = Field(..., description="Job ID")
    status: str = Field(..., description="Job status")
    created_at: str = Field(..., description="Job creation timestamp")
    updated_at: Optional[str] = Field(default=None, description="Last update timestamp")
    result: Optional[OCRResponse] = Field(default=None, description="OCR result (if completed)")
    error: Optional[str] = Field(default=None, description="Error message (if failed)")

