"""Text normalization and truncation utilities."""

import re
from typing import Tuple, Optional
from app.config import config


def normalize_text(text: str) -> str:
    """
    Normalize OCR-extracted text.
    
    - Strip nulls
    - Normalize newlines
    - Collapse extreme whitespace
    
    Args:
        text: Raw OCR text
    
    Returns:
        Normalized text
    """
    if not text:
        return ""
    
    # Strip null bytes
    text = text.replace("\x00", "")
    
    # Normalize newlines (convert all to \n)
    text = re.sub(r"\r\n|\r", "\n", text)
    
    # Collapse multiple newlines to single newline (max 2 consecutive)
    text = re.sub(r"\n{3,}", "\n\n", text)
    
    # Collapse multiple spaces to single space (but preserve newlines)
    lines = text.split("\n")
    normalized_lines = [re.sub(r" +", " ", line.strip()) for line in lines]
    text = "\n".join(normalized_lines)
    
    # Final strip
    return text.strip()


def truncate_text(text: str, max_bytes: Optional[int] = None) -> Tuple[str, bool]:
    """
    Truncate text to max bytes if needed.
    
    Args:
        text: Text to truncate
        max_bytes: Maximum bytes (defaults to OCR_MAX_TEXT_BYTES)
    
    Returns:
        Tuple of (truncated_text, was_truncated)
    """
    if max_bytes is None:
        max_bytes = config.OCR_MAX_TEXT_BYTES
    
    text_bytes = text.encode("utf-8")
    
    if len(text_bytes) <= max_bytes:
        return text, False
    
    # Truncate to max_bytes, ensuring we don't break UTF-8 sequences
    truncated_bytes = text_bytes[:max_bytes]
    
    # Try to decode, if it fails, remove last byte and try again
    while True:
        try:
            truncated_text = truncated_bytes.decode("utf-8")
            break
        except UnicodeDecodeError:
            truncated_bytes = truncated_bytes[:-1]
            if len(truncated_bytes) == 0:
                truncated_text = ""
                break
    
    return truncated_text, True

