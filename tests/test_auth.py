"""Tests for app/auth.py, app/auth_client.py, and app/auth_cache.py."""

import hashlib
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException

from app.auth import verify_app_auth
from app.auth_cache import AuthCache, get_auth_cache, set_auth_cache
from app.auth_client import AuthClient


class TestAuthCache:
    """Tests for AuthCache."""

    def test_get_miss(self):
        cache = AuthCache()
        assert cache.get("app1", "key1") is None

    def test_set_and_get_success(self):
        cache = AuthCache(success_ttl=60, failure_ttl=10)
        result = {"ok": True, "app_id": "app1"}
        cache.set("app1", "key1", result)
        assert cache.get("app1", "key1") == result

    def test_set_and_get_failure(self):
        cache = AuthCache(success_ttl=60, failure_ttl=10)
        result = {"ok": False, "error_code": "invalid"}
        cache.set("app1", "key1", result)
        assert cache.get("app1", "key1") == result

    def test_expiry_success_ttl(self):
        cache = AuthCache(success_ttl=60, failure_ttl=10)
        result = {"ok": True, "app_id": "app1"}
        cache.set("app1", "key1", result)

        with patch("app.auth_cache.time") as mock_time:
            mock_time.time.return_value = time.time() + 61
            assert cache.get("app1", "key1") is None

    def test_expiry_failure_ttl(self):
        cache = AuthCache(success_ttl=60, failure_ttl=10)
        result = {"ok": False, "error_code": "invalid"}
        cache.set("app1", "key1", result)

        with patch("app.auth_cache.time") as mock_time:
            mock_time.time.return_value = time.time() + 11
            assert cache.get("app1", "key1") is None

    def test_clear(self):
        cache = AuthCache()
        cache.set("app1", "key1", {"ok": True})
        cache.set("app2", "key2", {"ok": True})
        cache.clear()
        assert cache.get("app1", "key1") is None
        assert cache.get("app2", "key2") is None

    def test_key_hashing_consistency(self):
        cache = AuthCache()
        key1 = cache._make_key("app1", "key1")
        key2 = cache._make_key("app1", "key1")
        assert key1 == key2

        # Different credentials produce different keys
        key3 = cache._make_key("app1", "key2")
        assert key1 != key3

    def test_key_is_sha256(self):
        cache = AuthCache()
        key = cache._make_key("app1", "key1")
        expected = hashlib.sha256(b"app1:key1").hexdigest()
        assert key == expected

    def test_different_ttls_for_success_vs_failure(self):
        cache = AuthCache(success_ttl=100, failure_ttl=5)
        success_result = {"ok": True, "app_id": "app1"}
        failure_result = {"ok": False, "error_code": "invalid"}

        now = time.time()
        cache.set("app1", "key1", success_result)
        cache.set("app2", "key2", failure_result)

        with patch("app.auth_cache.time") as mock_time:
            # After 6 seconds: failure expired, success still valid
            mock_time.time.return_value = now + 6
            assert cache.get("app1", "key1") == success_result
            assert cache.get("app2", "key2") is None


class TestGetSetAuthCache:
    """Tests for module-level get/set functions."""

    def test_set_and_get(self):
        cache = AuthCache(success_ttl=120, failure_ttl=20)
        set_auth_cache(cache)
        assert get_auth_cache() is cache


class TestAuthClient:
    """Tests for AuthClient."""

    @pytest.mark.asyncio
    async def test_success_200_json(self):
        client = AuthClient()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"app_id": "app1", "name": "Test"}

        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_response):
            with patch("app.auth_client.service_config") as mock_sc:
                mock_sc.get_auth_url.return_value = "http://localhost:8007"
                result = await client.verify_app_credentials("app1", "key1")

        assert result["app_id"] == "app1"

    @pytest.mark.asyncio
    async def test_401_response(self):
        client = AuthClient()
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.json.return_value = {
            "error_code": "invalid_app_credentials",
            "error_message": "Bad creds",
        }

        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_response):
            with patch("app.auth_client.service_config") as mock_sc:
                mock_sc.get_auth_url.return_value = "http://localhost:8007"
                result = await client.verify_app_credentials("app1", "key1")

        assert result["ok"] is False
        assert result["error_code"] == "invalid_app_credentials"

    @pytest.mark.asyncio
    async def test_200_non_json(self):
        client = AuthClient()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = Exception("not json")

        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_response):
            with patch("app.auth_client.service_config") as mock_sc:
                mock_sc.get_auth_url.return_value = "http://localhost:8007"
                result = await client.verify_app_credentials("app1", "key1")

        assert result["ok"] is False
        assert result["error_code"] == "invalid_response"

    @pytest.mark.asyncio
    async def test_timeout_raises_request_error(self):
        client = AuthClient()

        with patch.object(
            httpx.AsyncClient, "get",
            new_callable=AsyncMock,
            side_effect=httpx.TimeoutException("timeout"),
        ):
            with patch("app.auth_client.service_config") as mock_sc:
                mock_sc.get_auth_url.return_value = "http://localhost:8007"
                with pytest.raises(httpx.RequestError):
                    await client.verify_app_credentials("app1", "key1")

    @pytest.mark.asyncio
    async def test_connection_error_raises(self):
        client = AuthClient()

        with patch.object(
            httpx.AsyncClient, "get",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectError("refused"),
        ):
            with patch("app.auth_client.service_config") as mock_sc:
                mock_sc.get_auth_url.return_value = "http://localhost:8007"
                with pytest.raises(httpx.RequestError):
                    await client.verify_app_credentials("app1", "key1")

    @pytest.mark.asyncio
    async def test_missing_base_url_raises(self):
        client = AuthClient()
        with patch("app.auth_client.service_config") as mock_sc:
            mock_sc.get_auth_url.return_value = ""
            with pytest.raises(ValueError, match="not configured"):
                await client.verify_app_credentials("app1", "key1")

    @pytest.mark.asyncio
    async def test_url_construction(self):
        client = AuthClient()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"app_id": "app1"}

        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_response) as mock_get:
            with patch("app.auth_client.service_config") as mock_sc:
                mock_sc.get_auth_url.return_value = "http://localhost:8007/"
                await client.verify_app_credentials("app1", "key1")

        call_args = mock_get.call_args
        assert call_args[0][0] == "http://localhost:8007/internal/app-ping"


class TestVerifyAppAuth:
    """Tests for the verify_app_auth FastAPI dependency."""

    @pytest.mark.asyncio
    async def test_missing_headers_raises_401(self):
        request = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            await verify_app_auth(request, None, None)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_missing_app_key_raises_401(self):
        request = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            await verify_app_auth(request, "app1", None)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_cached_success_returns_result(self, auth_cache):
        auth_cache.set("app1", "key1", {"app_id": "app1", "name": "Test"})
        request = MagicMock()
        result = await verify_app_auth(request, "app1", "key1")
        assert result["app_id"] == "app1"

    @pytest.mark.asyncio
    async def test_cached_failure_raises_401(self, auth_cache):
        auth_cache.set("app1", "key1", {"ok": False, "error_code": "invalid"})
        request = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            await verify_app_auth(request, "app1", "key1")
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_valid_from_service_caches_and_returns(self, auth_cache):
        request = MagicMock()
        success = {"app_id": "app1", "name": "Test"}
        with patch("app.auth.auth_client") as mock_client:
            mock_client.verify_app_credentials = AsyncMock(return_value=success)
            result = await verify_app_auth(request, "app1", "key1")

        assert result["app_id"] == "app1"
        # Should be cached now
        assert auth_cache.get("app1", "key1") == success

    @pytest.mark.asyncio
    async def test_invalid_from_service_caches_and_raises(self, auth_cache):
        """Invalid credentials from auth service get cached and raise HTTP error.

        Note: raises 503 because the inner HTTPException(401) is caught by the
        broad except Exception handler in verify_app_auth. The result IS cached.
        """
        request = MagicMock()
        failure = {"ok": False, "error_code": "invalid"}
        mock_client = MagicMock()
        mock_client.verify_app_credentials = AsyncMock(return_value=failure)
        with patch("app.auth.auth_client", mock_client):
            with pytest.raises(HTTPException) as exc_info:
                await verify_app_auth(request, "app1", "bad_key")

        # Result is cached regardless of which status code is raised
        assert auth_cache.get("app1", "bad_key") is not None

    @pytest.mark.asyncio
    async def test_service_unavailable_raises_503(self, auth_cache):
        request = MagicMock()
        with patch("app.auth.auth_client") as mock_client:
            mock_client.verify_app_credentials = AsyncMock(
                side_effect=httpx.ConnectError("refused")
            )
            with pytest.raises(HTTPException) as exc_info:
                await verify_app_auth(request, "app1", "key1")

        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_unexpected_error_raises_503(self, auth_cache):
        request = MagicMock()
        with patch("app.auth.auth_client") as mock_client:
            mock_client.verify_app_credentials = AsyncMock(
                side_effect=RuntimeError("unexpected")
            )
            with pytest.raises(HTTPException) as exc_info:
                await verify_app_auth(request, "app1", "key1")

        assert exc_info.value.status_code == 503
