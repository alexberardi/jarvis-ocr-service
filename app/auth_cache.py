"""In-memory cache for app credential validation results."""

import time
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Cache entry for auth validation."""
    result: Dict[str, Any]
    expires_at: float


class AuthCache:
    """In-memory cache for app credential validation."""
    
    def __init__(self, success_ttl: int = 60, failure_ttl: int = 10):
        """
        Initialize auth cache.
        
        Args:
            success_ttl: TTL in seconds for successful validations (default 60)
            failure_ttl: TTL in seconds for failed validations (default 10)
        """
        self.success_ttl = success_ttl
        self.failure_ttl = failure_ttl
        self._cache: Dict[str, CacheEntry] = {}
    
    def _make_key(self, app_id: str, app_key: str) -> str:
        """Create cache key from app_id and app_key."""
        # Use a hash of the key for security (don't store raw keys)
        import hashlib
        key_str = f"{app_id}:{app_key}"
        return hashlib.sha256(key_str.encode()).hexdigest()
    
    def get(self, app_id: str, app_key: str) -> Optional[Dict[str, Any]]:
        """
        Get cached validation result.
        
        Args:
            app_id: App identifier
            app_key: App secret
        
        Returns:
            Cached result if valid and not expired, None otherwise
        """
        cache_key = self._make_key(app_id, app_key)
        entry = self._cache.get(cache_key)
        
        if entry is None:
            return None
        
        # Check if expired
        if time.time() > entry.expires_at:
            # Remove expired entry
            del self._cache[cache_key]
            return None
        
        return entry.result
    
    def set(self, app_id: str, app_key: str, result: Dict[str, Any]):
        """
        Cache validation result.
        
        Args:
            app_id: App identifier
            app_key: App secret
            result: Validation result dict
        """
        cache_key = self._make_key(app_id, app_key)
        
        # Determine TTL based on success/failure
        is_success = result.get("ok") is True
        ttl = self.success_ttl if is_success else self.failure_ttl
        
        expires_at = time.time() + ttl
        
        self._cache[cache_key] = CacheEntry(
            result=result,
            expires_at=expires_at
        )
        
        logger.debug(f"Cached auth result for {app_id} (TTL: {ttl}s, success: {is_success})")
    
    def clear(self):
        """Clear all cache entries."""
        self._cache.clear()


# Global cache instance (will be initialized with config values)
_auth_cache_instance: Optional[AuthCache] = None


def get_auth_cache() -> AuthCache:
    """Get the global auth cache instance."""
    global _auth_cache_instance
    if _auth_cache_instance is None:
        # Lazy initialization with defaults (will be re-initialized in lifespan)
        from app.config import config
        _auth_cache_instance = AuthCache(
            success_ttl=config.JARVIS_APP_AUTH_CACHE_TTL_SECONDS,
            failure_ttl=10
        )
    return _auth_cache_instance


def set_auth_cache(cache: AuthCache):
    """Set the global auth cache instance."""
    global _auth_cache_instance
    _auth_cache_instance = cache

