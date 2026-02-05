"""Settings service for jarvis-ocr-service.

Provides runtime configuration that can be modified without restarting.
Settings are stored in the database with fallback to environment variables.
"""

import logging
from typing import Any

from jarvis_settings_client import SettingsService as BaseSettingsService

from app.services.settings_definitions import SETTINGS_DEFINITIONS

logger = logging.getLogger(__name__)


class OCRSettingsService(BaseSettingsService):
    """Settings service for OCR service with helper methods."""

    def get_provider_config(self) -> dict[str, bool]:
        """Get provider enable/disable configuration."""
        return {
            "tesseract": True,  # Always available
            "easyocr": self.get_bool("ocr.enable_easyocr", False),
            "paddleocr": self.get_bool("ocr.enable_paddleocr", False),
            "apple_vision": self.get_bool("ocr.enable_apple_vision", False),
            "llm_proxy_vision": self.get_bool("ocr.enable_llm_proxy_vision", False),
            "llm_proxy_cloud": self.get_bool("ocr.enable_llm_proxy_cloud", False),
        }

    def get_processing_config(self) -> dict[str, Any]:
        """Get processing configuration settings."""
        return {
            "max_text_bytes": self.get_int("ocr.max_text_bytes", 51200),
            "min_valid_chars": self.get_int("ocr.min_valid_chars", 3),
            "language_default": self.get_str("ocr.language_default", "en"),
            "max_attempts": self.get_int("ocr.max_attempts", 3),
            "validation_model": self.get_str("ocr.validation_model", "lightweight"),
        }

    def get_enabled_tiers(self) -> list[str]:
        """Get list of enabled OCR tiers."""
        tiers_str = self.get_str("ocr.enabled_tiers", "tesseract")
        return [tier.strip() for tier in tiers_str.split(",") if tier.strip()]


# Global singleton
_settings_service: OCRSettingsService | None = None


def get_settings_service() -> OCRSettingsService:
    """Get the global SettingsService instance."""
    global _settings_service
    if _settings_service is None:
        from app.db.models import Setting
        from app.db.session import get_session_local

        SessionLocal = get_session_local()
        _settings_service = OCRSettingsService(
            definitions=SETTINGS_DEFINITIONS,
            get_db_session=SessionLocal,
            setting_model=Setting,
        )
    return _settings_service


def reset_settings_service() -> None:
    """Reset the settings service singleton (for testing)."""
    global _settings_service
    _settings_service = None
