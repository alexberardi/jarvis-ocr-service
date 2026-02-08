"""Tests for the settings service and definitions.

These tests cover:
- Settings definitions
- Settings service behavior
- Helper methods
"""

import os
import time
from unittest.mock import MagicMock, patch

import pytest

from jarvis_settings_client import SettingDefinition
from jarvis_settings_client.service import SettingsService
from jarvis_settings_client.types import SettingValue

from app.services.settings_definitions import SETTINGS_DEFINITIONS
from app.services.settings_service import (
    get_settings_service,
    reset_settings_service,
)


class TestSettingsDefinitions:
    """Tests for settings definitions."""

    def test_all_definitions_have_required_fields(self):
        """Test that all definitions have required fields."""
        for definition in SETTINGS_DEFINITIONS:
            assert definition.key, f"Missing key for definition"
            assert definition.category, f"Missing category for {definition.key}"
            assert definition.value_type in ("string", "int", "float", "bool", "json"), \
                f"Invalid value_type for {definition.key}: {definition.value_type}"

    def test_no_duplicate_keys(self):
        """Test that there are no duplicate keys."""
        keys = [d.key for d in SETTINGS_DEFINITIONS]
        assert len(keys) == len(set(keys)), "Duplicate keys found in SETTINGS_DEFINITIONS"

    def test_key_format(self):
        """Test that keys follow the expected format."""
        for definition in SETTINGS_DEFINITIONS:
            # Keys should be lowercase with dots
            assert "." in definition.key, f"Key should contain dots: {definition.key}"
            assert definition.key == definition.key.lower(), \
                f"Key should be lowercase: {definition.key}"

    def test_expected_settings_exist(self):
        """Test that expected OCR settings are defined."""
        keys = [d.key for d in SETTINGS_DEFINITIONS]
        assert "ocr.enable_easyocr" in keys
        assert "ocr.enable_paddleocr" in keys
        assert "ocr.enable_apple_vision" in keys
        assert "ocr.max_text_bytes" in keys
        assert "ocr.min_valid_chars" in keys
        assert "ocr.enabled_tiers" in keys


class TestSettingsServiceCache:
    """Tests for SettingsService caching behavior."""

    @pytest.fixture
    def service(self):
        """Create a service instance for testing."""
        return SettingsService(
            definitions=SETTINGS_DEFINITIONS,
            get_db_session=lambda: None,
            setting_model=None,
        )

    def test_cache_hit(self, service):
        """Test that cached values are returned without DB query."""
        # Manually populate cache
        cache_key = service._make_cache_key("ocr.enable_easyocr")
        service._cache[cache_key] = SettingValue(
            value=True,
            value_type="bool",
            requires_reload=True,
            is_secret=False,
            env_fallback="OCR_ENABLE_EASYOCR",
            from_db=True,
            cached_at=time.time(),
        )

        # Should return cached value without DB query
        result = service.get("ocr.enable_easyocr")
        assert result is True

    def test_cache_expiry(self, service):
        """Test that expired cache entries are not used."""
        # Populate cache with expired entry
        cache_key = service._make_cache_key("ocr.max_text_bytes")
        service._cache[cache_key] = SettingValue(
            value=1000,
            value_type="int",
            requires_reload=False,
            is_secret=False,
            env_fallback="OCR_MAX_TEXT_BYTES",
            from_db=True,
            cached_at=time.time() - 120,  # 2 minutes ago (expired)
        )

        # Should fall through to env/default since cache is expired
        with patch.dict(os.environ, {"OCR_MAX_TEXT_BYTES": "99999"}):
            result = service.get("ocr.max_text_bytes")
            assert result == 99999

    def test_invalidate_all(self, service):
        """Test invalidating entire cache."""
        key1_cache = service._make_cache_key("test.key1")
        key2_cache = service._make_cache_key("test.key2")

        service._cache[key1_cache] = SettingValue(
            value="value1",
            value_type="string",
            requires_reload=False,
            is_secret=False,
            env_fallback=None,
            from_db=True,
            cached_at=time.time(),
        )
        service._cache[key2_cache] = SettingValue(
            value="value2",
            value_type="string",
            requires_reload=False,
            is_secret=False,
            env_fallback=None,
            from_db=True,
            cached_at=time.time(),
        )

        service.invalidate_cache()

        assert len(service._cache) == 0


class TestSettingsServiceEnvFallback:
    """Tests for environment variable fallback."""

    @pytest.fixture
    def service(self):
        """Create a service instance for testing."""
        return SettingsService(
            definitions=SETTINGS_DEFINITIONS,
            get_db_session=lambda: None,
            setting_model=None,
        )

    def test_env_fallback_when_db_unavailable(self, service):
        """Test that env vars are used when DB is unavailable."""
        with patch.dict(os.environ, {"OCR_MAX_TEXT_BYTES": "75000"}):
            result = service.get("ocr.max_text_bytes")
            assert result == 75000

    def test_default_when_no_env(self, service):
        """Test that defaults are used when no env var is set."""
        with patch.dict(os.environ, {}, clear=True):
            result = service.get("ocr.min_valid_chars")
            # Should return definition default (3)
            assert result == 3

    def test_unknown_key_returns_none(self, service):
        """Test that unknown keys return None."""
        result = service.get("unknown.key")
        assert result is None


class TestSettingsServiceTypedGetters:
    """Tests for typed getter methods."""

    @pytest.fixture
    def service(self):
        """Create a service instance for testing."""
        return SettingsService(
            definitions=SETTINGS_DEFINITIONS,
            get_db_session=lambda: None,
            setting_model=None,
        )

    def test_get_bool(self, service):
        """Test get_bool method."""
        with patch.dict(os.environ, {"OCR_ENABLE_EASYOCR": "true"}):
            result = service.get_bool("ocr.enable_easyocr", False)
            assert result is True
            assert isinstance(result, bool)

    def test_get_int(self, service):
        """Test get_int method."""
        with patch.dict(os.environ, {"OCR_MAX_ATTEMPTS": "7"}):
            result = service.get_int("ocr.max_attempts", 0)
            assert result == 7
            assert isinstance(result, int)

    def test_get_str(self, service):
        """Test get_str method."""
        with patch.dict(os.environ, {"OCR_LANGUAGE_DEFAULT": "fr"}):
            result = service.get_str("ocr.language_default", "")
            assert result == "fr"
            assert isinstance(result, str)


class TestSettingsServiceListMethods:
    """Tests for listing methods."""

    @pytest.fixture
    def service(self):
        """Create a service instance for testing."""
        return SettingsService(
            definitions=SETTINGS_DEFINITIONS,
            get_db_session=lambda: None,
            setting_model=None,
        )

    def test_list_categories(self, service):
        """Test list_categories returns unique categories."""
        categories = service.list_categories()

        assert isinstance(categories, list)
        assert len(categories) > 0
        assert "ocr.providers" in categories
        assert "ocr.processing" in categories
        # Should be sorted
        assert categories == sorted(categories)

    def test_list_all(self, service):
        """Test list_all returns all settings."""
        settings = service.list_all()

        assert isinstance(settings, list)
        assert len(settings) == len(SETTINGS_DEFINITIONS)

        # Check structure of first setting
        first = settings[0]
        assert "key" in first
        assert "value" in first
        assert "value_type" in first
        assert "category" in first
        assert "from_db" in first

    def test_list_all_with_category_filter(self, service):
        """Test list_all with category filter."""
        settings = service.list_all(category="ocr.providers")

        assert all(s["category"] == "ocr.providers" for s in settings)
        assert len(settings) > 0


class TestSingleton:
    """Tests for singleton behavior via get_settings_service."""

    @pytest.fixture(autouse=True)
    def reset(self):
        """Reset singleton before and after each test."""
        reset_settings_service()
        yield
        reset_settings_service()

    def test_singleton_instance(self):
        """Test that get_settings_service returns same instance."""
        # Mock the db imports to avoid actual DB connection
        mock_setting = MagicMock()
        mock_session_local = MagicMock()

        with patch("app.db.session.get_session_local", return_value=mock_session_local):
            with patch("app.db.models.Setting", mock_setting):
                service1 = get_settings_service()
                service2 = get_settings_service()

                assert service1 is service2
