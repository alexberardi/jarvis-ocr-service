"""Extended tests for app/config.py and app/db/session.py."""

import os
from unittest.mock import patch, MagicMock

import pytest


class TestConfigGetEnabledTiers:
    """Tests for Config.get_enabled_tiers."""

    def test_default_tiers(self):
        from app.config import Config
        tiers = Config.get_enabled_tiers()
        assert isinstance(tiers, list)
        assert len(tiers) > 0
        assert "tesseract" in tiers

    def test_custom_tiers(self):
        from app.config import Config
        original = Config.OCR_ENABLED_TIERS
        try:
            Config.OCR_ENABLED_TIERS = "tesseract,llm_cloud"
            tiers = Config.get_enabled_tiers()
            assert tiers == ["tesseract", "llm_cloud"]
        finally:
            Config.OCR_ENABLED_TIERS = original

    def test_strips_whitespace(self):
        from app.config import Config
        original = Config.OCR_ENABLED_TIERS
        try:
            Config.OCR_ENABLED_TIERS = " tesseract , easyocr "
            tiers = Config.get_enabled_tiers()
            assert tiers == ["tesseract", "easyocr"]
        finally:
            Config.OCR_ENABLED_TIERS = original

    def test_empty_string(self):
        from app.config import Config
        original = Config.OCR_ENABLED_TIERS
        try:
            Config.OCR_ENABLED_TIERS = ""
            tiers = Config.get_enabled_tiers()
            assert tiers == []
        finally:
            Config.OCR_ENABLED_TIERS = original


class TestConfigGetProviderConfig:
    """Tests for Config.get_provider_config."""

    def test_returns_dict(self):
        from app.config import Config
        result = Config.get_provider_config()
        assert isinstance(result, dict)
        assert "tesseract" in result
        assert result["tesseract"] is True

    def test_disabled_providers(self):
        from app.config import Config
        result = Config.get_provider_config()
        # All optional providers should be False by default in test env
        assert result["easyocr"] is False
        assert result["paddleocr"] is False


class TestConfigValidate:
    """Tests for Config.validate."""

    def test_validate_no_apple_vision(self):
        from app.config import Config
        original = Config.OCR_ENABLE_APPLE_VISION
        try:
            Config.OCR_ENABLE_APPLE_VISION = False
            # Should not raise
            Config.validate()
        finally:
            Config.OCR_ENABLE_APPLE_VISION = original

    def test_validate_with_apple_vision_calls_validation(self):
        from app.config import Config
        original = Config.OCR_ENABLE_APPLE_VISION
        try:
            Config.OCR_ENABLE_APPLE_VISION = True
            with patch("app.config.validate_apple_vision_environment") as mock_validate:
                Config.validate()
                mock_validate.assert_called_once()
        finally:
            Config.OCR_ENABLE_APPLE_VISION = original


class TestDbSession:
    """Tests for app/db/session.py."""

    def test_get_session_local_returns_class(self):
        from app.db.session import get_session_local
        SessionLocal = get_session_local()
        assert SessionLocal is not None

    def test_get_db_generator(self):
        """get_db should be a generator that yields a session and closes it."""
        from app.db.session import get_db

        # Mock the SessionLocal to avoid real DB connection
        mock_session = MagicMock()
        with patch("app.db.session.SessionLocal", return_value=mock_session):
            gen = get_db()
            session = next(gen)
            assert session is mock_session
            try:
                next(gen)
            except StopIteration:
                pass
            mock_session.close.assert_called_once()
