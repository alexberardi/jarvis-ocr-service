"""Tests for app/service_config.py - Service discovery configuration."""

import os
from unittest.mock import MagicMock, patch

import pytest

import app.service_config as service_config


class TestInit:
    """Tests for service_config.init()."""

    @pytest.fixture(autouse=True)
    def reset_state(self):
        """Reset module state before and after each test."""
        orig = {
            "_initialized": service_config._initialized,
            "_config_url_set": service_config._config_url_set,
            "_has_config_client": service_config._has_config_client,
            "_nag_thread": service_config._nag_thread,
        }
        service_config._initialized = False
        service_config._config_url_set = False
        yield
        service_config._config_url_set = True  # Stop any nag thread
        for k, v in orig.items():
            setattr(service_config, k, v)

    def test_returns_false_when_no_config_client(self):
        """Return False and set _initialized when config client not installed."""
        service_config._has_config_client = False
        result = service_config.init()
        assert result is False
        assert service_config._initialized is True

    def test_returns_false_when_config_url_not_set(self):
        """Return False when JARVIS_CONFIG_URL is not set."""
        service_config._has_config_client = True
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("JARVIS_CONFIG_URL", None)
            with patch("app.service_config.threading.Thread"):
                result = service_config.init()
        assert result is False
        assert service_config._initialized is True

    def test_returns_false_when_config_url_empty(self):
        """Return False when JARVIS_CONFIG_URL is empty string."""
        service_config._has_config_client = True
        with patch.dict(os.environ, {"JARVIS_CONFIG_URL": ""}):
            with patch("app.service_config.threading.Thread"):
                result = service_config.init()
        assert result is False
        assert service_config._initialized is True

    def test_starts_nag_thread_when_no_config_url(self):
        """Start nag thread when config client installed but no URL."""
        service_config._has_config_client = True
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("JARVIS_CONFIG_URL", None)
            with patch("app.service_config.threading.Thread") as mock_thread:
                mock_instance = MagicMock()
                mock_thread.return_value = mock_instance
                service_config.init()
                mock_thread.assert_called_once()
                mock_instance.start.assert_called_once()

    def test_returns_true_when_config_init_succeeds(self):
        """Return True when config_init() succeeds."""
        service_config._has_config_client = True
        with patch.dict(os.environ, {"JARVIS_CONFIG_URL": "http://config:7700"}):
            with patch.object(service_config, "config_init", return_value=True):
                with patch.object(service_config, "get_all_services", return_value={}):
                    result = service_config.init()
        assert result is True
        assert service_config._initialized is True

    def test_returns_false_when_config_init_returns_false(self):
        """Return False when config_init() returns False."""
        service_config._has_config_client = True
        with patch.dict(os.environ, {"JARVIS_CONFIG_URL": "http://config:7700"}):
            with patch.object(service_config, "config_init", return_value=False):
                result = service_config.init()
        assert result is False
        assert service_config._initialized is True

    def test_passes_db_engine_to_config_init(self):
        """Pass db_engine parameter through to config_init."""
        service_config._has_config_client = True
        mock_engine = MagicMock()
        with patch.dict(os.environ, {"JARVIS_CONFIG_URL": "http://config:7700"}):
            with patch.object(service_config, "config_init", return_value=False) as mock_init:
                service_config.init(db_engine=mock_engine)
                mock_init.assert_called_once_with(
                    config_url="http://config:7700",
                    refresh_interval_seconds=300,
                    db_engine=mock_engine,
                )

    def test_sets_config_url_set_when_url_provided(self):
        """Set _config_url_set when JARVIS_CONFIG_URL is provided."""
        service_config._has_config_client = True
        with patch.dict(os.environ, {"JARVIS_CONFIG_URL": "http://config:7700"}):
            with patch.object(service_config, "config_init", return_value=False):
                service_config.init()
        assert service_config._config_url_set is True


class TestShutdown:
    """Tests for service_config.shutdown()."""

    @pytest.fixture(autouse=True)
    def reset_state(self):
        """Reset module state before and after each test."""
        orig = {
            "_initialized": service_config._initialized,
            "_config_url_set": service_config._config_url_set,
            "_has_config_client": service_config._has_config_client,
        }
        yield
        for k, v in orig.items():
            setattr(service_config, k, v)

    def test_sets_initialized_false(self):
        """Shutdown sets _initialized to False."""
        service_config._initialized = True
        service_config._has_config_client = False
        service_config.shutdown()
        assert service_config._initialized is False

    def test_stops_nag_thread(self):
        """Shutdown sets _config_url_set to stop nag thread."""
        service_config._config_url_set = False
        service_config._has_config_client = False
        service_config.shutdown()
        assert service_config._config_url_set is True

    def test_calls_config_shutdown_when_available(self):
        """Call config_shutdown when config client is available."""
        service_config._has_config_client = True
        with patch.object(service_config, "config_shutdown") as mock_sd:
            service_config.shutdown()
            mock_sd.assert_called_once()

    def test_skips_config_shutdown_when_unavailable(self):
        """Don't call config_shutdown when config client not installed."""
        service_config._has_config_client = False
        service_config.shutdown()
        assert service_config._initialized is False


class TestIsInitialized:
    """Tests for service_config.is_initialized()."""

    @pytest.fixture(autouse=True)
    def reset_state(self):
        """Reset module state before and after each test."""
        orig = service_config._initialized
        service_config._initialized = False
        yield
        service_config._initialized = orig

    def test_returns_false_by_default(self):
        """Return False when init() has not been called."""
        assert service_config.is_initialized() is False

    def test_returns_true_when_set(self):
        """Return True after initialization."""
        service_config._initialized = True
        assert service_config.is_initialized() is True


class TestGetUrl:
    """Tests for service_config._get_url() fallback chain."""

    @pytest.fixture(autouse=True)
    def reset_state(self):
        """Reset module state before and after each test."""
        orig = {
            "_initialized": service_config._initialized,
            "_has_config_client": service_config._has_config_client,
        }
        service_config._initialized = False
        yield
        for k, v in orig.items():
            setattr(service_config, k, v)

    def test_returns_config_service_url_when_available(self):
        """Return URL from config service when initialized."""
        service_config._initialized = True
        service_config._has_config_client = True
        with patch.object(service_config, "get_service_url", return_value="http://auth:7701"):
            url = service_config._get_url("jarvis-auth")
            assert url == "http://auth:7701"

    def test_falls_back_to_env_var_when_config_returns_none(self):
        """Fall back to env var when config service returns None."""
        service_config._initialized = True
        service_config._has_config_client = True
        with patch.object(service_config, "get_service_url", return_value=None):
            with patch.dict(os.environ, {"JARVIS_AUTH_BASE_URL": "http://env-auth:7701"}):
                url = service_config._get_url("jarvis-auth")
                assert url == "http://env-auth:7701"

    def test_falls_back_to_env_var_when_not_initialized(self):
        """Use env var directly when not initialized."""
        service_config._initialized = False
        service_config._has_config_client = True
        with patch.dict(os.environ, {"JARVIS_AUTH_BASE_URL": "http://env:7701"}):
            url = service_config._get_url("jarvis-auth")
            assert url == "http://env:7701"

    def test_raises_when_no_config_and_no_env(self):
        """Raise ValueError when no config service URL and no env var."""
        service_config._initialized = True
        service_config._has_config_client = True
        with patch.object(service_config, "get_service_url", return_value=None):
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("JARVIS_AUTH_BASE_URL", None)
                with pytest.raises(ValueError, match="Cannot discover jarvis-auth"):
                    service_config._get_url("jarvis-auth")

    def test_raises_for_unknown_service(self):
        """Raise ValueError for service with no fallback."""
        service_config._has_config_client = False
        with pytest.raises(ValueError, match="Cannot discover"):
            service_config._get_url("jarvis-unknown")

    def test_env_var_fallback_for_llm_proxy(self):
        """Use JARVIS_LLM_PROXY_API_URL for jarvis-llm-proxy-api."""
        service_config._has_config_client = False
        with patch.dict(os.environ, {"JARVIS_LLM_PROXY_API_URL": "http://llm:8000"}):
            url = service_config._get_url("jarvis-llm-proxy-api")
            assert url == "http://llm:8000"

    def test_skips_config_service_when_has_client_false(self):
        """Don't use config service when _has_config_client is False."""
        service_config._initialized = True
        service_config._has_config_client = False
        with patch.dict(os.environ, {"JARVIS_AUTH_BASE_URL": "http://env:7701"}):
            url = service_config._get_url("jarvis-auth")
            assert url == "http://env:7701"


class TestGetAuthUrl:
    """Tests for service_config.get_auth_url()."""

    def test_delegates_to_get_url(self):
        """get_auth_url() calls _get_url('jarvis-auth')."""
        with patch.object(service_config, "_get_url", return_value="http://auth:7701") as mock:
            url = service_config.get_auth_url()
            assert url == "http://auth:7701"
            mock.assert_called_once_with("jarvis-auth")


class TestGetLlmProxyUrl:
    """Tests for service_config.get_llm_proxy_url()."""

    def test_delegates_to_get_url(self):
        """get_llm_proxy_url() calls _get_url('jarvis-llm-proxy-api')."""
        with patch.object(service_config, "_get_url", return_value="http://llm:8000") as mock:
            url = service_config.get_llm_proxy_url()
            assert url == "http://llm:8000"
            mock.assert_called_once_with("jarvis-llm-proxy-api")


class TestEnvVarFallbacks:
    """Tests for module-level constants."""

    def test_contains_auth(self):
        """_ENV_VAR_FALLBACKS includes jarvis-auth."""
        assert "jarvis-auth" in service_config._ENV_VAR_FALLBACKS

    def test_contains_llm_proxy_api(self):
        """_ENV_VAR_FALLBACKS includes jarvis-llm-proxy-api."""
        assert "jarvis-llm-proxy-api" in service_config._ENV_VAR_FALLBACKS

    def test_env_var_names_are_uppercase(self):
        """Env var names follow SCREAMING_SNAKE_CASE convention."""
        for env_var in service_config._ENV_VAR_FALLBACKS.values():
            assert env_var == env_var.upper(), f"Env var should be uppercase: {env_var}"
