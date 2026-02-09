"""Configuration management from environment variables."""

import os
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

# Load .env file from project root BEFORE reading environment variables
# Try multiple locations: project root, app directory, current working directory
env_paths = [
    Path(__file__).parent.parent / ".env",  # Project root (preferred)
    Path(__file__).parent / ".env",  # app/ directory (fallback)
    Path.cwd() / ".env",  # Current working directory (fallback)
]

for env_path in env_paths:
    if env_path.exists():
        try:
            load_dotenv(env_path, override=False)
            break
        except (PermissionError, IOError):
            # If we can't read the file, continue to next location
            continue
else:
    # If no .env file found or readable, that's okay - use environment variables directly
    # Environment variables set in the shell will still work
    pass

from app.utils import is_running_in_docker, validate_apple_vision_environment


class Config:
    """Application configuration from environment variables."""
    
    # Server config
    OCR_PORT: int = int(os.getenv("OCR_PORT", "5009"))
    OCR_LOG_LEVEL: str = os.getenv("OCR_LOG_LEVEL", "info").upper()
    
    # Provider flags
    OCR_ENABLE_EASYOCR: bool = os.getenv("OCR_ENABLE_EASYOCR", "false").lower() == "true"
    OCR_ENABLE_PADDLEOCR: bool = os.getenv("OCR_ENABLE_PADDLEOCR", "false").lower() == "true"
    OCR_ENABLE_APPLE_VISION: bool = os.getenv("OCR_ENABLE_APPLE_VISION", "false").lower() == "true"
    OCR_ENABLE_LLM_PROXY_VISION: bool = os.getenv("OCR_ENABLE_LLM_PROXY_VISION", "false").lower() == "true"
    OCR_ENABLE_LLM_PROXY_CLOUD: bool = os.getenv("OCR_ENABLE_LLM_PROXY_CLOUD", "false").lower() == "true"
    
    # Auth config
    JARVIS_AUTH_BASE_URL: str = os.getenv("JARVIS_AUTH_BASE_URL", "")
    JARVIS_APP_AUTH_CACHE_TTL_SECONDS: int = int(os.getenv("JARVIS_APP_AUTH_CACHE_TTL_SECONDS", "60"))
    
    # LLM Proxy config
    JARVIS_LLM_PROXY_URL: str = os.getenv("JARVIS_LLM_PROXY_URL", "")
    JARVIS_APP_ID: str = os.getenv("JARVIS_APP_ID", "")
    JARVIS_APP_KEY: str = os.getenv("JARVIS_APP_KEY", "")
    
    # Redis config
    REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_PASSWORD: Optional[str] = os.getenv("REDIS_PASSWORD")
    
    # Queue processing config (from PRD)
    OCR_MAX_TEXT_BYTES: int = int(os.getenv("OCR_MAX_TEXT_BYTES", "51200"))  # 50 KB
    OCR_MIN_VALID_CHARS: int = int(os.getenv("OCR_MIN_VALID_CHARS", "3"))
    OCR_LANGUAGE_DEFAULT: str = os.getenv("OCR_LANGUAGE_DEFAULT", "en")
    OCR_MAX_ATTEMPTS: int = int(os.getenv("OCR_MAX_ATTEMPTS", "3"))
    OCR_VALIDATION_MODEL: str = os.getenv("OCR_VALIDATION_MODEL", "lightweight")  # LLM model for validation
    OCR_MIN_CONFIDENCE: Optional[float] = None  # Optional minimum confidence (informational only in v1)
    OCR_ENABLED_TIERS: str = os.getenv("OCR_ENABLED_TIERS", "tesseract,easyocr,paddleocr,apple_vision,llm_local,llm_cloud")
    
    # S3/MinIO configuration
    S3_ENDPOINT_URL: Optional[str] = os.getenv("S3_ENDPOINT_URL")  # Optional custom endpoint (for MinIO)
    S3_REGION: str = os.getenv("S3_REGION", "us-east-2")  # AWS region
    S3_FORCE_PATH_STYLE: bool = os.getenv("S3_FORCE_PATH_STYLE", "false").lower() == "true"  # Path-style addressing
    
    @classmethod
    def get_enabled_tiers(cls) -> List[str]:
        """Get list of enabled OCR tiers."""
        return [tier.strip() for tier in cls.OCR_ENABLED_TIERS.split(",") if tier.strip()]
    
    @classmethod
    def validate(cls) -> None:
        """Validate configuration and fail fast on invalid settings."""
        if cls.OCR_ENABLE_APPLE_VISION:
            validate_apple_vision_environment()
    
    @classmethod
    def get_provider_config(cls) -> Dict[str, bool]:
        """Get provider availability configuration."""
        return {
            "tesseract": True,  # Always available
            "easyocr": cls.OCR_ENABLE_EASYOCR,
            "paddleocr": cls.OCR_ENABLE_PADDLEOCR,
            "apple_vision": cls.OCR_ENABLE_APPLE_VISION and not is_running_in_docker(),
            "llm_proxy_vision": cls.OCR_ENABLE_LLM_PROXY_VISION,
            "llm_proxy_cloud": cls.OCR_ENABLE_LLM_PROXY_CLOUD,
        }


# Global config instance
config = Config()

