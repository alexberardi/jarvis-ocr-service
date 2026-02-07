"""Tests for app/service_config.py - Service discovery configuration."""

import importlib
from unittest.mock import MagicMock, patch

import pytest

import app.service_config as service_config


class TestInit:
    """Tests for service_config.init()."""

    @pytest.fixture(autouse=True)
    def reset_state(self):
        """Reset module state before and after each test."""
        service_config._initialized = False
        yield
        service_config._initialized = False

    def test_returns_false_when_config_url_not_set(self):
        """Return False when JARVIS_CONFIG_URL is not set."""
        with patch.dict("os.environ", {}, clear=False):
            with patch("os.getenv", return_value=None):
                result = service_config.init()
                assert result is False

    def test_returns_false_when_config_url_empty(self):
        """Return False when JARVIS_CONFIG_URL is empty string."""
        with patch("os.getenv", return_value=""):
            result = service_config.init()
            assert result is False

    def test_does_not_set_initialized_when_no_config_url(self):
        """_initialized remains False when no config URL."""
        with patch("os.getenv", return_value=None):
            service_config.init()
            assert service_config._initialized is False

    def test_returns_true_when_config_client_succeeds(self):
        """Return True when jarvis-config-client initializes successfully."""
        mock_init_client = MagicMock(return_value=True)
        with patch("os.getenv", return_value="http://config:8013"):
            with patch.dict("sys.modules", {"jarvis_config_client": MagicMock(init=mock_init_client)}):
                # Need to reimport to pick up the mock module
                result = service_config.init()
                assert result is True

    def test_sets_initialized_when_config_client_succeeds(self):
        """_initialized set to True when config client succeeds."""
        mock_init_client = MagicMock(return_value=True)
        with patch("os.getenv", return_value="http://config:8013"):
            with patch.dict("sys.modules", {"jarvis_config_client": MagicMock(init=mock_init_client)}):
                service_config.init()
                assert service_config._initialized is True

    def test_returns_false_when_config_client_returns_false(self):
        """Return False when config client init returns False (service unavailable)."""
        mock_init_client = MagicMock(return_value=False)
        with patch("os.getenv", return_value="http://config:8013"):
            with patch.dict("sys.modules", {"jarvis_config_client": MagicMock(init=mock_init_client)}):
                result = service_config.init()
                assert result is False

    def test_does_not_set_initialized_when_config_client_fails(self):
        """_initialized remains False when config client returns False."""
        mock_init_client = MagicMock(return_value=False)
        with patch("os.getenv", return_value="http://config:8013"):
            with patch.dict("sys.modules", {"jarvis_config_client": MagicMock(init=mock_init_client)}):
                service_config.init()
                assert service_config._initialized is False

    def test_returns_false_when_config_client_not_installed(self):
        """Return False when jarvis-config-client is not installed (ImportError)."""
        with patch("os.getenv", return_value="http://config:8013"):
            # Simulate ImportError by making the import fail
            original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__
            def mock_import(name, *args, **kwargs):
                if name == "jarvis_config_client":
                    raise ImportError("No module named 'jarvis_config_client'")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                result = service_config.init()
                assert result is False

    def test_returns_false_on_unexpected_exception(self):
        """Return False when config client raises unexpected exception."""
        mock_module = MagicMock()
        mock_module.init.side_effect = RuntimeError("connection refused")
        with patch("os.getenv", return_value="http://config:8013"):
            with patch.dict("sys.modules", {"jarvis_config_client": mock_module}):
                result = service_config.init()
                assert result is False


class TestIsInitialized:
    """Tests for service_config.is_initialized()."""

    @pytest.fixture(autouse=True)
    def reset_state(self):
        """Reset module state before and after each test."""
        service_config._initialized = False
        yield
        service_config._initialized = False

    def test_returns_false_by_default(self):
        """Return False when init() has not been called."""
        assert service_config.is_initialized() is False

    def test_returns_true_after_successful_init(self):
        """Return True after successful initialization."""
        service_config._initialized = True
        assert service_config.is_initialized() is True


class TestGetUrl:
    """Tests for service_config._get_url() fallback chain."""

    @pytest.fixture(autouse=True)
    def reset_state(self):
        """Reset module state before and after each test."""
        service_config._initialized = False
        yield
        service_config._initialized = False

    def test_returns_default_when_not_initialized_and_no_env(self):
        """Return default URL when not initialized and no env var set."""
        with patch.dict("os.environ", {}, clear=False):
            with patch("os.getenv", return_value=None):
                url = service_config._get_url("jarvis-auth")
                assert url == "http://localhost:8007"

    def test_returns_env_var_when_not_initialized(self):
        """Return env var URL when not initialized but env var is set."""
        with patch("os.getenv", return_value="http://custom-auth:9000"):
            url = service_config._get_url("jarvis-auth")
            assert url == "http://custom-auth:9000"

    def test_returns_config_client_url_when_initialized(self):
        """Return URL from config client when initialized."""
        service_config._initialized = True
        mock_module = MagicMock()
        mock_module.get_service_url.return_value = "http://config-auth:8007"
        with patch.dict("sys.modules", {"jarvis_config_client": mock_module}):
            url = service_config._get_url("jarvis-auth")
            assert url == "http://config-auth:8007"

    def test_falls_back_to_env_when_config_client_returns_none(self):
        """Fall back to env var when config client returns None."""
        service_config._initialized = True
        mock_module = MagicMock()
        mock_module.get_service_url.return_value = None
        with patch.dict("sys.modules", {"jarvis_config_client": mock_module}):
            with patch("os.getenv", return_value="http://env-auth:8007"):
                url = service_config._get_url("jarvis-auth")
                assert url == "http://env-auth:8007"

    def test_falls_back_to_default_when_config_client_raises(self):
        """Fall back to default when config client raises exception."""
        service_config._initialized = True
        mock_module = MagicMock()
        mock_module.get_service_url.side_effect = RuntimeError("connection lost")
        with patch.dict("sys.modules", {"jarvis_config_client": mock_module}):
            with patch("os.getenv", return_value=None):
                url = service_config._get_url("jarvis-auth")
                assert url == "http://localhost:8007"

    def test_returns_empty_string_for_unknown_service(self):
        """Return empty string for unknown service names."""
        with patch("os.getenv", return_value=None):
            url = service_config._get_url("jarvis-unknown-service")
            assert url == ""

    def test_env_var_fallback_for_llm_proxy(self):
        """Use JARVIS_LLM_PROXY_URL env var for jarvis-llm-proxy."""
        with patch("os.getenv", return_value="http://custom-llm:8000"):
            url = service_config._get_url("jarvis-llm-proxy")
            assert url == "http://custom-llm:8000"

    def test_default_for_llm_proxy(self):
        """Return default URL for jarvis-llm-proxy."""
        with patch("os.getenv", return_value=None):
            url = service_config._get_url("jarvis-llm-proxy")
            assert url == "http://localhost:8000"


class TestGetAuthUrl:
    """Tests for service_config.get_auth_url()."""

    @pytest.fixture(autouse=True)
    def reset_state(self):
        """Reset module state before and after each test."""
        service_config._initialized = False
        yield
        service_config._initialized = False

    def test_returns_auth_url(self):
        """get_auth_url() delegates to _get_url('jarvis-auth')."""
        with patch.object(service_config, "_get_url", return_value="http://auth:8007") as mock_get:
            url = service_config.get_auth_url()
            assert url == "http://auth:8007"
            mock_get.assert_called_once_with("jarvis-auth")

    def test_returns_default_auth_url(self):
        """get_auth_url() returns default when nothing is configured."""
        with patch("os.getenv", return_value=None):
            url = service_config.get_auth_url()
            assert url == "http://localhost:8007"


class TestGetLlmProxyUrl:
    """Tests for service_config.get_llm_proxy_url()."""

    @pytest.fixture(autouse=True)
    def reset_state(self):
        """Reset module state before and after each test."""
        service_config._initialized = False
        yield
        service_config._initialized = False

    def test_returns_llm_proxy_url(self):
        """get_llm_proxy_url() delegates to _get_url('jarvis-llm-proxy')."""
        with patch.object(service_config, "_get_url", return_value="http://llm:8000") as mock_get:
            url = service_config.get_llm_proxy_url()
            assert url == "http://llm:8000"
            mock_get.assert_called_once_with("jarvis-llm-proxy")

    def test_returns_default_llm_proxy_url(self):
        """get_llm_proxy_url() returns default when nothing is configured."""
        with patch("os.getenv", return_value=None):
            url = service_config.get_llm_proxy_url()
            assert url == "http://localhost:8000"


class TestDefaults:
    """Tests for module-level defaults and constants."""

    def test_defaults_contain_expected_services(self):
        """_DEFAULTS maps expected service names."""
        assert "jarvis-auth" in service_config._DEFAULTS
        assert "jarvis-llm-proxy" in service_config._DEFAULTS

    def test_env_var_fallbacks_contain_expected_services(self):
        """_ENV_VAR_FALLBACKS maps expected service names."""
        assert "jarvis-auth" in service_config._ENV_VAR_FALLBACKS
        assert "jarvis-llm-proxy" in service_config._ENV_VAR_FALLBACKS

    def test_env_var_names_are_uppercase(self):
        """Env var names follow SCREAMING_SNAKE_CASE convention."""
        for env_var in service_config._ENV_VAR_FALLBACKS.values():
            assert env_var == env_var.upper(), f"Env var should be uppercase: {env_var}"

    def test_default_urls_are_localhost(self):
        """Default URLs point to localhost."""
        for url in service_config._DEFAULTS.values():
            assert "localhost" in url, f"Default URL should be localhost: {url}"
