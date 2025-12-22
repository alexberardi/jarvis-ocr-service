"""Custom exceptions for OCR service."""


class OCRException(Exception):
    """Base exception for OCR-related errors."""
    pass


class OCRProcessingException(OCRException):
    """Exception for OCR processing failures (should return 422)."""
    pass


class ProviderUnavailableException(OCRException):
    """Exception for provider unavailability (should return 400)."""
    pass

